"""Offline tests for the day-wise history."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import history  # noqa: E402


def job(i="j1"):
    return {"id": i, "total": 2, "rows": [1, 2, 3], "errors": [], "not_found": []}


def stat(status="done"):
    return {"status": status, "counts": {"updated": 3}, "lines": 3, "error": None, "po_errors": []}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        history.PATH = os.path.join(tempfile.mkdtemp(), "h.json")

    def test_empty_today_is_pending_and_past_days_listed(self):
        d = history.days()
        self.assertEqual(len(d), history.SHOW_DAYS)
        self.assertEqual((d[0]["date"], d[0]["state"]), (date.today().isoformat(), "pending"))
        self.assertEqual(d[1]["state"], "none")

    def test_check_then_sync_and_multiple_runs_per_day(self):
        history.record_check(job("a"), {"tab": "po", "label": "P1"})
        self.assertEqual(history.days()[0]["state"], "checked")
        history.record_sync("a", stat())
        history.record_check(job("b"), {"tab": "t1", "label": "x"})
        today = history.days()[0]
        self.assertEqual((today["state"], today["checks"], today["syncs"]), ("done", 2, 1))
        self.assertEqual(len(today["runs"][1]["syncs"]), 1)   # run "a" (older) carries its sync

    def test_failed_sync_does_not_complete_the_day(self):
        history.record_check(job("a"), {})
        history.record_sync("a", stat("failed"))
        self.assertEqual(history.days()[0]["state"], "checked")

    def test_old_activity_extends_the_list(self):
        old = (date.today() - timedelta(days=30)).isoformat()
        history._save([{"job_id": "o", "ts": old + "T10:00:00", "date": old, "tab": "", "label": "", "pos": 1,
                        "lines": 1, "errors": 0, "not_found": 0, "syncs": []}])
        d = history.days()
        self.assertEqual(len(d), 31)
        self.assertEqual(d[-1]["checks"], 1)


if __name__ == "__main__":
    unittest.main()
