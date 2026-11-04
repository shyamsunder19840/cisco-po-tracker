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
WORKERS = 8          # POs processed at the same time
PATCH_WORKERS = 4    # purchase lines of one PO updated at the same time
CHUNK = 8            # POs whose lines are read from Business Central with one request
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


def _patch_all(todo):
    """PATCH the planned lines in parallel (they are separate records). todo: [(rec, line, changes)]."""
    def one(item):
        rec, ln, changes = item
        try:
            bcsync.patch_line(ln, changes)
            rec["status"] = "updated"
        except Exception as e:  # noqa: BLE001 - reported per line
            rec["status"] = "error"
            rec["error"] = str(e)

    if len(todo) <= 1:
        for item in todo:
            one(item)
    else:
        with ThreadPoolExecutor(min(PATCH_WORKERS, len(todo))) as ex:
            list(ex.map(one, todo))


def _sync_po(po, rows, dry_run, days, fmt, lines=None, t1=None, t1_note=""):
    """lines / t1: already read from Business Central for a group of POs (see prefetch); read here when missing."""
    dates = [d for d in (_to_date(r.get("Final Scheduled Ship Date")) for r in rows) if d]
    est = roll_to_monday(max(dates) + timedelta(days=days)) if dates else None
    by_line = {}
    for ln in (lines if lines is not None else bcsync.fetch_lines([po + "-M", po + "-S"])):
        by_line.setdefault(str(ln.get("buyersLineNo", "")).strip(), []).append(ln)
    if t1 is None and not t1_note and any(str(r.get("Status Code", "")).strip().lower() in ("closed", "booked") for r in rows):
        try:
            t1 = t1_by_line([po + "-M", po + "-S"])
        except Exception as e:  # noqa: BLE001 - T1 data is optional; affects Closed / Booked lines only
            t1_note = f"T1 Process data unavailable ({str(e)[:120]})"
    out, todo = [], []
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
                todo.append((rec, ln, changes))
            out.append(rec)
    _patch_all(todo)
    return out


def prefetch(pos, rows_by_po):
    """Read the purchase lines (and the T1 rows needed for Closed / Booked lines) of a group of POs in ONE request each,
    both requests at the same time. Returns ({po: [lines]}, {(doc, line): t1 row}, note)."""
    docs = [d for po in pos for d in (po + "-M", po + "-S")]
    need_t1 = any(str(r.get("Status Code", "")).strip().lower() in ("closed", "booked")
                  for po in pos for r in rows_by_po[po])
    with ThreadPoolExecutor(2) as ex:
        f_lines = ex.submit(bcsync.fetch_lines, docs)
        f_t1 = ex.submit(t1_by_line, docs) if need_t1 else None
        lines = f_lines.result()  # a failure here is handled by the caller (the POs fall back to one-by-one reads)
        t1, note = ({}, "")
        if f_t1:
            try:
                t1 = f_t1.result()
            except Exception as e:  # noqa: BLE001
                t1, note = None, f"T1 Process data unavailable ({str(e)[:120]})"
    by_po = {po: [] for po in pos}
    for ln in lines:
        doc = str(ln.get("documentNo", ""))
        if doc[-2:].upper() in ("-M", "-S") and doc[:-2] in by_po:
            by_po[doc[:-2]].append(ln)
    return by_po, t1, note


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
          "activity": "Starting…", "lines_done": 0, "cancel": False,
          "t1": {"docs": 0, "rows": None, "would": 0, "errors": 0, "skipped": None}}
    SYNCS[sid] = st
    lock = threading.Lock()
    pre = {}  # po -> (lines, t1 map, note) read ahead for groups of POs

    def read_ahead(pos):
        if st["cancel"]:
            return
        st["activity"] = "Reading purchase lines from Business Central…"
        try:
            lines_by_po, t1, note = prefetch(pos, by_po)
        except Exception:  # noqa: BLE001 - these POs are read one by one later instead
            return
        for po in pos:
            pre[po] = (lines_by_po[po], t1, note)

    def process(po, rows):
        """Step 1: update the purchase lines of one PO."""
        if st["cancel"]:  # cancelled: POs not started yet are skipped, the one in progress finishes
            return [], []
        st["activity"] = f"Updating purchase lines — {po}"
        lines, t1, note = pre.get(po, (None, None, ""))
        res = _sync_po(po, rows, dry_run, days, fmt, lines, t1, note)
        with lock:
            st["lines_done"] += 1
        return res, sorted({r["doc"] for r in res if r["doc"] and r["status"] == ("would_update" if dry_run else "updated")})

    def refresh_t1(po, docs, res):
        """Step 2: rebuild the T1 Process Data lines of the updated orders. Runs on ONE thread, one PO after the other
        (new T1 entry numbers are taken from the last entry), while step 1 carries on with the next POs."""
        if st["cancel"]:
            return
        st["activity"] = f"Updating T1 Process Data — {po}"
        try:
            t1 = t1refresh.refresh(docs)
        except Exception as e:  # noqa: BLE001 - the purchase lines are already saved
            with lock:
                st["t1"]["errors"] += 1
                for rec in res:
                    if rec["doc"] in docs:
                        rec["warnings"].append(f"T1 Process Data not updated: {str(e)[:200]}")
                        break
            return
        with lock:
            st["t1"]["docs"] += t1["docs"]
            if t1["rows"] is not None:
                st["t1"]["rows"] = (st["t1"]["rows"] or 0) + t1["rows"]

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
        pos = list(by_po)
        with ThreadPoolExecutor(WORKERS) as ex:  # read ahead: one request per group of POs instead of one per PO
            list(ex.map(read_ahead, [pos[i:i + CHUNK] for i in range(0, len(pos), CHUNK)]))
        with ThreadPoolExecutor(WORKERS) as ex, ThreadPoolExecutor(1) as t1_ex:
            t1_futs = []
            futs = {ex.submit(process, po, rows): po for po, rows in by_po.items()}
            for fut in as_completed(futs):
                po = futs[fut]
                try:
                    res, docs = fut.result()
                except Exception as e:  # noqa: BLE001
                    with lock:
                        st["po_errors"].append({"po": po, "error": str(e)})
                        st["counts"]["error"] += len(by_po[po])
                        st["done"] += 1
                    continue
                if docs and dry_run:
                    st["t1"]["would"] += len(docs)
                elif docs and st["t1"]["skipped"] is None:
                    t1_futs.append(t1_ex.submit(refresh_t1, po, docs, res))
                with lock:
                    for rec in res:
                        st["counts"][rec["status"]] += 1
                        if (rec["status"] != "unchanged" or rec["warnings"]) and len(st["details"]) < MAX_DETAILS:
                            st["details"].append(rec)
                    st["done"] += 1
            for f in t1_futs:  # wait for the T1 step to finish the last POs
                f.result()
        st["activity"] = "Cancelled" if st["cancel"] else "Finished"
        st["status"] = "cancelled" if st["cancel"] else "done"

    def finish():
        work()
        if not dry_run:
            try:
                history.record_sync(job_id, st)
            except Exception:  # noqa: BLE001 - history must never break a sync
                pass

    threading.Thread(target=finish, daemon=True).start()
    return sid


def cancel(sid):
    """Stop a running sync after the PO that is being processed right now. Returns False if there is none."""
    st = SYNCS.get(sid)
    if not st or st["status"] != "running":
        return False
    st["cancel"] = True
    st["activity"] = "Cancelling — finishing the current PO…"
    return True


def get(sid):
    return SYNCS.get(sid)
