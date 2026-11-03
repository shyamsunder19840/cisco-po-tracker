"""Sync fetched Cisco rows into Business Central purchase lines (<PO>-M and <PO>-S).

Field mapping (Cisco API -> Purchase Line), following Report 60151 Export-ImportPurchaseLine:
  PO ID            + "-M" / "-S"  -> Document No.   (lines found by Document No. + Buyers Line No.)
  PO Line Number                  -> Buyers Line No. (lookup key)
  SO Line Ref                     -> CISCO SO Line No.
  Line ID Set                     -> Shipset
  Status Code + T1 Process data   -> CISCO Delivery Status (see delivery_status: GRN / Sales Invoice / Dispatch / POD / Delivery)
  Final Scheduled Ship Date       -> Scheduled_Date  (old date is appended to Previous Scheduled Date)
  latest Final Scheduled Ship Date of the PO + N days (a Saturday/Sunday result moves to Monday) -> Estimate Delivery Date
"""
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import bcsync
import history
import jobs
import t1refresh

SYNCS = {}
WORKERS = 5
PREV_MAX = 50  # Purchase Line."Previous Scheduled Date" is Text[50]
MAXLEN = {"ciscoSOLineNo": 10, "shipset": 5, "ciscoDeliveryStatus": 100}  # field lengths in BC
MAX_DETAILS = 1000


def _to_date(v):
    """'2026-11-24', '2026-11-24T00:00:00Z' -> date; blank / BC's 0001-01-01 -> None."""
    s = str(v or "").strip()
    if not s or s.startswith("0001"):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def roll_to_monday(d):
    """Saturday -> +2 days, Sunday -> +1 day, so the date lands on Monday."""
    return d + timedelta(days={5: 2, 6: 1}.get(d.weekday(), 0))


def add_history(prev, old, fmt):
    """Append `old` to the comma-separated history, keeping it within 50 chars (oldest dropped first)."""
    s = old.strftime(fmt)
    parts = [p.strip() for p in (prev or "").split(",") if p.strip()]
    if s in parts:
        return prev or ""
    parts.append(s)
    while len(", ".join(parts)) > PREV_MAX and len(parts) > 1:
        parts.pop(0)
    return ", ".join(parts)[:PREV_MAX]


T1_FIELDS = ["proactivePONo", "proactivePOLineNo", "salesInvoiceNo", "dispatchDate", "podNo",
             "customerDeliveryDate", "productReceiveDate", "lineType"]
LICENSE_TYPES = ("licenses", "attached saas")  # T1 Line Type for Item Catalog Category 'L' and 'X'
SIMPLE_STATUS = {"fulfillment in progress": "Fulfilment in progress", "fulfilment in progress": "Fulfilment in progress",
                 "scheduled": "Scheduled", "shipped": "ASIA Hold"}


def _has(v):
    s = str(v or "").strip()
    return bool(s) and not s.startswith("0001")


def delivery_status(code, t1, t1_note=""):
    """CISCO Delivery Status from the Cisco Status Code plus (for Closed / Booked) the T1 Process data of the line.

    Returns (status or None, warning or None). None = leave the field unchanged.
    """
    c = str(code or "").strip().lower()
    if not c:
        return None, None
    if c in SIMPLE_STATUS:
        return SIMPLE_STATUS[c], None
    if c not in ("closed", "booked"):
        return None, f"Status Code '{code}' has no Cisco Delivery Status rule, status not changed"
    if t1 is None:
        return None, f"Cisco Delivery Status not changed for '{code}': {t1_note or 'no T1 Process data for this line'}"
    if c == "booked":
        return ("Licenses" if str(t1.get("linetype") or "").strip().lower() in LICENSE_TYPES
                else "Scheduling Pending"), None
    si = _has(t1.get("salesinvoiceno"))
    if si:
        if _has(t1.get("customerdeliverydate")):
            return "Delivered to Customer", None
        if not _has(t1.get("dispatchdate")):
            return "Under Dispatch Planning", None
        if not _has(t1.get("podno")):
            return "Dispatched to Customer/ POD No to be updated", None
        return "Dispatched to Customer", None
    if _has(t1.get("productreceivedate")):
        return "Ready in Stock", None
    return "Intransit from CISCO Warehouse", None


def t1_by_line(pos):
    """{(document no, line no): lower-cased T1Process row} for the given purchase documents (e.g. PO-M, PO-S)."""
    import t1report
    out = {}
    for r in t1report.fetch_rows(None, None, proactive_pos=pos, fields=T1_FIELDS, order_by="entryNo"):
        r = {k.lower(): v for k, v in r.items()}
        out[(str(r.get("proactivepono", "")).upper(), str(r.get("proactivepolineno", "")))] = r
    return out


def plan_line(row, line, est, fmt, status=None):
    """Return (changes, warnings) for one BC line. Blank Cisco values never overwrite BC data."""
    changes, warnings = {}, []

    def text(key, value):
        value = str(value or "").strip()
        if not value:
            return
        if len(value) > MAXLEN[key]:
            warnings.append(f"{key}: '{value}' is longer than {MAXLEN[key]} characters, skipped")
        elif value != (line.get(key) or ""):
            changes[key] = value

    text("ciscoSOLineNo", row.get("SO Line Ref"))
    text("shipset", row.get("Line ID Set"))
    text("ciscoDeliveryStatus", status)

    new = _to_date(row.get("Final Scheduled Ship Date"))
    old = _to_date(line.get("scheduledDate"))
    if new and new != old:
        if old:
            hist = add_history(line.get("previousScheduledDate"), old, fmt)
            if hist != (line.get("previousScheduledDate") or ""):
                changes["previousScheduledDate"] = hist
        changes["scheduledDate"] = new.isoformat()
    if est and est != _to_date(line.get("estimateDeliveryDate")):
        changes["estimateDeliveryDate"] = est.isoformat()
    return changes, warnings


def _sync_po(po, rows, dry_run, days, fmt):
    dates = [d for d in (_to_date(r.get("Final Scheduled Ship Date")) for r in rows) if d]
    est = roll_to_monday(max(dates) + timedelta(days=days)) if dates else None
    by_line = {}
    for ln in bcsync.fetch_lines([po + "-M", po + "-S"]):
        by_line.setdefault(str(ln.get("buyersLineNo", "")).strip(), []).append(ln)
    t1, t1_note = None, ""
    if any(str(r.get("Status Code", "")).strip().lower() in ("closed", "booked") for r in rows):
        try:
            t1 = t1_by_line([po + "-M", po + "-S"])
        except Exception as e:  # noqa: BLE001 - T1 data is optional; affects Closed / Booked lines only
            t1_note = f"T1 Process data unavailable ({str(e)[:120]})"
    out = []
    for row in rows:
        key = str(row.get("PO Line Number", "")).strip()
        base = {"po": po, "line": key}
        matches = by_line.get(key, [])
        if not matches:
            out.append({**base, "doc": "", "status": "no_match", "changes": {}, "warnings": []})
            continue
        for ln in matches:
            t1row = None if t1 is None else t1.get((str(ln.get("documentNo", "")).upper(), str(ln.get("lineNo", ""))))
            status, warn = delivery_status(row.get("Status Code"), t1row,
                                           t1_note or ("no T1 Process Report row for this line" if t1 is not None else ""))
            changes, warnings = plan_line(row, ln, est, fmt, status)
            if warn:
                warnings.append(warn)
            rec = {**base, "doc": ln.get("documentNo", ""), "changes": changes, "warnings": warnings}
            if not changes:
                rec["status"] = "unchanged"
            elif dry_run:
                rec["status"] = "would_update"
            else:
                try:
                    bcsync.patch_line(ln, changes)
                    rec["status"] = "updated"
                except Exception as e:  # noqa: BLE001 - reported per line
                    rec["status"] = "error"
                    rec["error"] = str(e)
            out.append(rec)
    return out


def start(job_id, dry_run=False):
    job = jobs.get(job_id)
    if not job:
        raise KeyError("Unknown fetch job - run Check status first.")
    if job["status"] != "done" or not job["rows"]:
        raise ValueError("There is no completed result to sync yet.")
    for s in SYNCS.values():
        if s["status"] == "running":
            raise ValueError("A sync is already running. Please wait for it to finish.")
    by_po = {}
    for r in job["rows"]:
        by_po.setdefault(r.get("PO ID"), []).append(r)
    days = int(os.environ.get("SYNC_ESTIMATE_DAYS", 14))
    fmt = os.environ.get("SYNC_DATE_FORMAT", "%d-%m-%y")
    sid = uuid.uuid4().hex[:12]
    st = {"id": sid, "job_id": job_id, "status": "running", "dry_run": dry_run, "total": len(by_po),
          "done": 0, "lines": len(job["rows"]), "counts": {"updated": 0, "would_update": 0, "unchanged": 0,
          "no_match": 0, "error": 0}, "details": [], "error": None, "po_errors": [], "started": time.time(),
          # live progress: what is going on right now, and the two steps run for every PO
          "activity": "Starting…", "lines_done": 0,
          "t1": {"docs": 0, "rows": None, "would": 0, "errors": 0, "skipped": None}}
    SYNCS[sid] = st
    lock = threading.Lock()
    t1_lock = threading.Lock()  # T1 entry numbers are taken from the last entry: refresh one PO at a time

    def process(po, rows):
        """Step 1: update the purchase lines. Step 2: rebuild the T1 Process Data lines of the updated orders."""
        st["activity"] = f"Updating purchase lines — {po}"
        res = _sync_po(po, rows, dry_run, days, fmt)
        with lock:
            st["lines_done"] += 1
        docs = sorted({r["doc"] for r in res if r["doc"] and r["status"] == ("would_update" if dry_run else "updated")})
        t1 = None
        if docs and dry_run:
            t1 = {"would": len(docs)}
        elif docs and st["t1"]["skipped"] is None:
            with t1_lock:
                st["activity"] = f"Updating T1 Process Data — {po}"
                try:
                    t1 = t1refresh.refresh(docs)
                except Exception as e:  # noqa: BLE001 - the purchase lines are already saved
                    t1 = {"error": str(e)}
        return res, docs, t1

    def work():
        try:
            bcsync.check_api()
        except Exception as e:  # noqa: BLE001
            st.update(status="failed", error=str(e))
            return
        if not dry_run:
            try:
                t1refresh.check_api()
            except Exception as e:  # noqa: BLE001 - purchase lines are still synced, T1 Process Data is skipped
                st["t1"]["skipped"] = str(e)
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(process, po, rows): po for po, rows in by_po.items()}
            for fut in as_completed(futs):
                po = futs[fut]
                try:
                    res, docs, t1 = fut.result()
                except Exception as e:  # noqa: BLE001
                    with lock:
                        st["po_errors"].append({"po": po, "error": str(e)})
                        st["counts"]["error"] += len(by_po[po])
                        st["done"] += 1
                    continue
                with lock:
                    if t1 and "error" in t1:
                        st["t1"]["errors"] += 1
                        for rec in res:
                            if rec["doc"] in docs:
                                rec["warnings"].append(f"T1 Process Data not updated: {t1['error'][:200]}")
                                break
                    elif t1 and "would" in t1:
                        st["t1"]["would"] += t1["would"]
                    elif t1:
                        st["t1"]["docs"] += t1["docs"]
                        if t1["rows"] is not None:
                            st["t1"]["rows"] = (st["t1"]["rows"] or 0) + t1["rows"]
                    for rec in res:
                        st["counts"][rec["status"]] += 1
                        if (rec["status"] != "unchanged" or rec["warnings"]) and len(st["details"]) < MAX_DETAILS:
                            st["details"].append(rec)
                    st["done"] += 1
        st["activity"] = "Finished"
        st["status"] = "done"

    def finish():
        work()
        if not dry_run:
            try:
                history.record_sync(job_id, st)
            except Exception:  # noqa: BLE001 - history must never break a sync
                pass

    threading.Thread(target=finish, daemon=True).start()
    return sid


def get(sid):
    return SYNCS.get(sid)
