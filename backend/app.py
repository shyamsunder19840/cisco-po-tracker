import io
import os
import re
from datetime import date

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

load_dotenv()
import bc  # noqa: E402
import cisco  # noqa: E402
import history  # noqa: E402
import jobs  # noqa: E402
import settings  # noqa: E402
import sync  # noqa: E402
import t1report  # noqa: E402

DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
app = Flask(__name__, static_folder=None)
CORS(app)
ALL_COLUMNS = cisco.COLUMNS + ["PO Order Date", "BC PO No."]
PO_RE = re.compile(r"^[A-Za-z0-9]+$")


def _parse_po_list(text):
    seen, out = set(), []
    for tok in re.split(r"[\s,;]+", text or ""):
        tok = bc.strip_suffix(tok)
        if tok and tok.upper() not in seen:
            seen.add(tok.upper())
            out.append(tok)
    return out


def _short(items, n=3):
    """'A, B, C' or 'A, B, C +4 more' for the history label."""
    return ", ".join(items[:n]) + (f" +{len(items) - n} more" if len(items) > n else "")


def _columns_for(rows):
    """Known columns first (in order), then any extra raw-path fields Cisco returned."""
    present = {k for r in rows for k in r}
    return [c for c in ALL_COLUMNS if c in present] + sorted(present - set(ALL_COLUMNS))


@app.get("/api/settings")
def get_settings():
    return jsonify(settings.public_view())


@app.post("/api/settings")
def save_settings():
    updates = (request.get_json(silent=True) or {}).get("values", {})
    errors = settings.validate({k: v for k, v in updates.items()
                                if not (settings.BY_KEY.get(k, (0, 0, 0, False))[3] and not str(v).strip())})
    if errors:
        return jsonify(error="Please fix the highlighted fields.", fields=errors), 400
    changed = settings.save(updates)
    cisco.reset()
    bc.reset()
    return jsonify(saved=changed, settings=settings.public_view())


@app.post("/api/settings/test")
def test_settings():
    """Fetch a token from each service using the current settings."""
    results = {}
    for name, mod in (("cisco", cisco), ("bc", bc)):
        try:
            mod.get_token(force=True)
            results[name] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            results[name] = {"ok": False, "error": str(e)[:200]}
    return jsonify(results)


@app.post("/api/sync")
def start_sync():
    body = request.get_json(silent=True) or {}
    try:
        sid = sync.start(body.get("job_id", ""), bool(body.get("dry_run")))
    except KeyError as e:
        return jsonify(error=str(e.args[0])), 404
    except ValueError as e:
        return jsonify(error=str(e)), 409
    st = sync.get(sid)
    return jsonify(sync_id=sid, total=st["total"], lines=st["lines"], dry_run=st["dry_run"])


@app.post("/api/sync/<sid>/cancel")
def sync_cancel(sid):
    return (jsonify(ok=True), 200) if sync.cancel(sid) else (jsonify(error="Unknown or finished sync"), 404)


@app.get("/api/sync/<sid>")
def sync_progress(sid):
    st = sync.get(sid)
    if not st:
        return jsonify(error="Unknown sync"), 404
    out = {k: st[k] for k in ("id", "status", "dry_run", "total", "done", "lines", "counts", "error", "po_errors",
                              "activity", "lines_done", "t1", "cancel")}
    out["details"] = [] if request.args.get("details") == "0" else list(st["details"])
    return jsonify(out)


@app.post("/api/t1report")
def t1_report():
    """Excel export of Report 80000 (T1 Process Batch) output for a BSO Order Date range."""
    body = request.get_json(silent=True) or {}
    f, t = body.get("from_date") or None, body.get("to_date") or None
    split = lambda key: [x for x in re.split(r"[\s,;]+", body.get(key) or "") if x]  # noqa: E731
    bsos, cpos = split("bso_nos"), split("customer_pos")
    # Proactive (Cisco) PO numbers: T1 stores them with the -M / -S suffix, so match all three spellings
    ppos = [v for p in dict.fromkeys(bc.strip_suffix(x) for x in split("proactive_pos")) for v in (p, p + "-M", p + "-S")]
    if bool(f) != bool(t):
        return jsonify(error="Enter both the Start and End date, or leave both empty."), 400
    if not (f or bsos or cpos or ppos):
        return jsonify(error="Enter a date range or at least one PO / BSO number."), 400
    try:
        if f and date.fromisoformat(f) > date.fromisoformat(t):
            return jsonify(error="Start date must be on or before End date."), 400
    except (TypeError, ValueError):
        return jsonify(error="Dates must be YYYY-MM-DD."), 400
    limit = int(os.environ.get("T1_MAX_ROWS", 100000))
    try:
        rows = t1report.fetch_rows(f, t, bsos, limit=limit, customer_pos=cpos, proactive_pos=ppos)
    except OverflowError:
        return jsonify(error=f"More than {limit} rows found. Please choose a shorter date range."), 400
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except t1report.T1ApiMissing as e:
        return jsonify(error=str(e)), 502
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Business Central request failed: {e}"), 502
    if not rows:
        return jsonify(error="No T1 Process data found for those filters."), 404
    resp = send_file(t1report.build_xlsx(rows), as_attachment=True,
                     download_name=f"T1_Report_{f}_to_{t}.xlsx" if f else f"T1_Report_{date.today()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["X-Row-Count"] = str(len(rows))
    return resp


@app.get("/api/history")
def get_history():
    return jsonify(history.days())


@app.get("/api/info")
def info():
    return jsonify(database=settings.current_database())


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/columns")
def columns():
    return jsonify(ALL_COLUMNS)


@app.post("/api/submit")
def submit():
    pos = _parse_po_list((request.get_json(silent=True) or {}).get("po_numbers", ""))
    if not pos:
        return jsonify(error="Enter at least one PO number."), 400
    bad = [p for p in pos if not PO_RE.match(p)]
    if bad:
        return jsonify(error=f"Invalid PO number(s): {', '.join(bad[:5])}"), 400
    return jsonify(job_id=jobs.start(pos, source={"tab": "po", "label": _short(pos)}), total=len(pos))


@app.post("/api/submit_by_date")
def submit_by_date():
    body = request.get_json(silent=True) or {}
    f, t = body.get("from_date"), body.get("to_date")
    try:
        if date.fromisoformat(f) > date.fromisoformat(t):
            return jsonify(error="From date must be on or before To date."), 400
    except (TypeError, ValueError):
        return jsonify(error="Dates must be YYYY-MM-DD."), 400
    try:
        pos, bc_rows = bc.list_pos_by_date(f, t)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Business Central lookup failed: {e}"), 502
    limit = int(os.environ.get("MAX_PO_PER_SEARCH", 500))
    if len(pos) > limit:
        return jsonify(error=f"{len(pos)} Cisco POs found (max {limit}). Please choose a shorter date range."), 400
    if not pos:
        return jsonify(error="No Cisco POs found in that date range."), 404
    meta = {p["po"]: p for p in pos}
    return jsonify(job_id=jobs.start([p["po"] for p in pos], meta,
                                     {"tab": "date", "label": f"PO Order Date {f} to {t}"}),
                   total=len(pos), bc_rows=len(bc_rows))


@app.post("/api/submit_by_t1")
def submit_by_t1():
    """Look up Customer PO numbers in the T1 Process Report, take their Proactive (Cisco) PO No. and check those at Cisco."""
    body = request.get_json(silent=True) or {}
    cpos = list(dict.fromkeys(x for x in re.split(r"[\s,;]+", body.get("customer_pos") or "") if x))
    if not cpos:
        return jsonify(error="Enter at least one Customer PO number."), 400
    try:
        t1_rows = t1report.fetch_rows(None, None, customer_pos=cpos, fields=["customerPONo", "proactivePONo"],
                                      order_by="customerPONo")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except t1report.T1ApiMissing as e:
        return jsonify(error=str(e)), 502
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Business Central request failed: {e}"), 502
    pos, skipped = t1report.customer_pos(t1_rows, os.environ.get("BC_PO_PREFIX", "POCSIN"))
    limit = int(os.environ.get("MAX_PO_PER_SEARCH", 500))
    if not pos:
        msg = ("No T1 Process Report rows found for Customer PO No.: " + ", ".join(cpos[:5]) if not t1_rows else
               f"{len(t1_rows)} T1 row(s) found, but none has a Cisco Proactive PO No. (prefix {os.environ.get('BC_PO_PREFIX', 'POCSIN')}).")
        return jsonify(error=msg), 404
    if len(pos) > limit:
        return jsonify(error=f"{len(pos)} Cisco POs found (max {limit}). Please choose a shorter date range."), 400
    return jsonify(job_id=jobs.start(pos, source={"tab": "t1", "label": "Customer PO " + _short(cpos)}),
                   total=len(pos), t1_rows=len(t1_rows), skipped=skipped)


@app.get("/api/progress/<job_id>")
def progress(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Unknown job"), 404
    out = {k: job[k] for k in ("id", "status", "total", "done", "errors", "not_found", "filtered_out", "filter")}
    out["row_count"] = len(job["rows"])
    out["all_count"] = len(job["all_rows"]) if job.get("filter") is not None else len(job["rows"])
    # While running, the UI polls with rows=0 so big result sets aren't re-sent every second.
    out["rows"] = [] if request.args.get("rows") == "0" else sorted(job["rows"], key=lambda r: (str(r.get("PO ID")), str(r.get("PO Line Number")).zfill(6)))
    return jsonify(out)


@app.post("/api/download")
def download():
    body = request.get_json(silent=True) or {}
    rows = body.get("rows")
    full = bool(body.get("full"))
    if rows is None and body.get("job_id"):
        job = jobs.get(body["job_id"])
        # "complete" = every line Cisco returned, ignoring the Status Code filter
        rows = (job["all_rows"] if job.get("filter") is not None else job["rows"]) if job and full else (job["rows"] if job else None)
    if not rows:
        return jsonify(error="Nothing to download."), 400
    wb = Workbook()
    ws = wb.active
    ws.title = "PO Status"
    cols = _columns_for(rows)
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    for i, name in enumerate(cols, 1):
        width = max([len(name)] + [len(str(r.get(name, ""))) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 40)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"Cisco_PO_Status_{'complete_' if full else ''}{date.today()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Serve the built React app when present (production)
@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path):
    if os.path.isdir(DIST):
        full = os.path.join(DIST, path)
        if path and os.path.isfile(full):
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, "index.html")
    return jsonify(message="API running. Start the React dev server in /frontend."), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
