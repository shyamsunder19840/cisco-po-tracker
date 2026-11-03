"""Day-wise history of the work done in the app: every completed "Check status" and every real (non-preview) sync.

Stored in backend/data/history.json so it survives restarts. A day can have any number of runs.
"""
import json
import os
import threading
from datetime import date, datetime, timedelta

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.json")
SHOW_DAYS = 14   # days always listed (even with no activity); older days appear only if they have runs
MAX_DAYS = 90
_lock = threading.Lock()


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(runs):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def _now():
    return datetime.now().replace(microsecond=0)


def record_check(job, source):
    """Call when a Check status job has finished."""
    ts = _now()
    run = {"job_id": job["id"], "ts": ts.isoformat(), "date": ts.date().isoformat(),
           "tab": (source or {}).get("tab", ""), "label": (source or {}).get("label", ""),
           "pos": job["total"], "lines": len(job["rows"]), "errors": len(job["errors"]),
           "not_found": len(job["not_found"]), "syncs": []}
    with _lock:
        runs = _load()
        runs.append(run)
        _save(runs)


def record_sync(job_id, st):
    """Call when a real sync has finished; attaches the result to the Check status run it belongs to."""
    entry = {"ts": _now().isoformat(), "status": st["status"], "counts": dict(st["counts"]),
             "lines": st["lines"], "error": st.get("error"), "po_errors": len(st.get("po_errors", []))}
    with _lock:
        runs = _load()
        for run in reversed(runs):
            if run["job_id"] == job_id:
                run["syncs"].append(entry)
                break
        else:  # the check run is unknown (e.g. history file was cleared): keep the sync on its own
            ts = _now()
            runs.append({"job_id": job_id, "ts": ts.isoformat(), "date": ts.date().isoformat(), "tab": "", "label": "",
                         "pos": st["total"], "lines": st["lines"], "errors": 0, "not_found": 0, "syncs": [entry]})
        _save(runs)


def days(today=None):
    """Newest day first: [{date, state, checks, syncs, runs}]. state: done | checked | pending (today) | none (past)."""
    today = today or date.today()
    with _lock:
        runs = _load()
    by_day = {}
    for r in runs:
        by_day.setdefault(r["date"], []).append(r)
    first = min([today - timedelta(days=SHOW_DAYS - 1)] + [date.fromisoformat(d) for d in by_day])
    first = max(first, today - timedelta(days=MAX_DAYS - 1))
    out, d = [], today
    while d >= first:
        rs = by_day.get(d.isoformat(), [])[::-1]  # the file is chronological, show newest first
        ok_syncs = sum(1 for r in rs for s in r["syncs"] if s["status"] == "done")
        state = "done" if ok_syncs else "checked" if rs else "pending" if d == today else "none"
        out.append({"date": d.isoformat(), "state": state, "checks": len(rs), "syncs": ok_syncs, "runs": rs})
        d -= timedelta(days=1)
    return out
