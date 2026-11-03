"""In-memory job runner: one worker pool, results handled as each PO completes."""
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import cisco
import history

JOBS = {}


def _lookup(po):
    try:
        return po, cisco.parse_response(cisco.check_order_status(po)), None
    except Exception as e:  # noqa: BLE001 - surfaced per-PO to the UI
        return po, [], str(e)


def _status_filter():
    """Return a lower-cased set of allowed Status Codes, or None when the filter is off."""
    if os.environ.get("STATUS_FILTER_ENABLED", "false").lower() != "true":
        return None
    import settings
    return {v.lower() for v in settings.parse_list(os.environ.get("STATUS_FILTER_VALUES", ""))}


def start(pos, meta=None, source=None):
    """pos: PO numbers (no suffix). meta: {po: {orderDate, bc_numbers}}. source: {tab, label} for the history."""
    meta = meta or {}
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "running", "total": len(pos), "done": 0,
           "rows": [], "all_rows": [], "errors": [], "not_found": [], "filtered_out": 0,
           "filter": None, "started": time.time()}
    allowed = _status_filter()
    job["filter"] = sorted(allowed) if allowed is not None else None
    JOBS[job_id] = job
    lock = threading.Lock()

    def work():
        with ThreadPoolExecutor(int(os.environ.get("CISCO_WORKERS", 10))) as ex:
            for fut in as_completed([ex.submit(_lookup, po) for po in pos]):
                po, rows, err = fut.result()
                m = meta.get(po, {})
                for r in rows:
                    r["PO Order Date"] = m.get("orderDate", "")
                    r["BC PO No."] = ", ".join(m.get("bc_numbers", [])) or po
                everything = rows
                if allowed is not None and rows:
                    rows = [r for r in rows if str(r.get("Status Code", "")).strip().lower() in allowed]
                dropped = len(everything) - len(rows)
                with lock:
                    job["rows"] += rows
                    if allowed is not None:
                        job["all_rows"] += everything
                    job["filtered_out"] += dropped
                    if err:
                        job["errors"].append({"po": po, "error": err})
                    elif not rows and not dropped:
                        job["not_found"].append(po)
                    job["done"] += 1
        job["status"] = "done"
        try:
            history.record_check(job, source)
        except Exception:  # noqa: BLE001 - history must never break a fetch
            pass

    threading.Thread(target=work, daemon=True).start()
    return job_id


def get(job_id):
    return JOBS.get(job_id)
