"""Offline tests for the Business Central sync logic (no network: bcsync is replaced by a fake)."""
import os
import sys
import time
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bcsync  # noqa: E402
import jobs  # noqa: E402
import sync  # noqa: E402
import t1refresh  # noqa: E402

FMT = "%d-%m-%Y"


def row(po="POCSIN1", line="1", so="1.0", ids="1", status="Closed", final="2026-11-10"):
    return {"PO ID": po, "PO Line Number": line, "SO Line Ref": so, "Line ID Set": ids,
            "Status Code": status, "Final Scheduled Ship Date": final}


def bcline(doc="POCSIN1-M", buyers="1", **kw):
    base = {"id": f"{doc}-{buyers}", "@odata.etag": "W/1", "documentNo": doc, "buyersLineNo": buyers,
            "ciscoSOLineNo": "", "shipset": "", "ciscoDeliveryStatus": "",
            "scheduledDate": "0001-01-01", "previousScheduledDate": "", "estimateDeliveryDate": "0001-01-01"}
    base.update(kw)
    return base


class PlanTests(unittest.TestCase):
    def test_fresh_line_gets_all_fields(self):
        ch, w = sync.plan_line(row(), bcline(), date(2026, 11, 24), FMT, "Closed")
        self.assertEqual(ch, {"ciscoSOLineNo": "1.0", "shipset": "1", "ciscoDeliveryStatus": "Closed",
                              "scheduledDate": "2026-11-10", "estimateDeliveryDate": "2026-11-24"})
        self.assertEqual(w, [])

    def test_changed_date_moves_old_into_history(self):
        ln = bcline(scheduledDate="2026-10-01", ciscoSOLineNo="1.0", shipset="1", ciscoDeliveryStatus="Closed")
        ch, _ = sync.plan_line(row(), ln, None, FMT, "Closed")
        self.assertEqual(ch, {"previousScheduledDate": "01-10-2026", "scheduledDate": "2026-11-10"})

    def test_same_date_is_unchanged(self):
        ln = bcline(scheduledDate="2026-11-10", ciscoSOLineNo="1.0", shipset="1", ciscoDeliveryStatus="Closed")
        self.assertEqual(sync.plan_line(row(), ln, None, FMT, "Closed")[0], {})

    def test_blank_cisco_values_never_overwrite(self):
        ln = bcline(shipset="7", scheduledDate="2026-10-01", ciscoDeliveryStatus="Open")
        ch, _ = sync.plan_line(row(ids="", status="", final=""), ln, None, FMT, None)
        self.assertEqual(ch, {"ciscoSOLineNo": "1.0"})

    def test_too_long_value_is_skipped_with_warning(self):
        ch, w = sync.plan_line(row(ids="123456"), bcline(), None, FMT)  # Shipset is Code[5]
        self.assertNotIn("shipset", ch)
        self.assertEqual(len(w), 1)

    def test_history_dedupes_and_stays_within_50_chars(self):
        h = ""
        for d in range(1, 8):
            h = sync.add_history(h, date(2026, 10, d), FMT)
        self.assertLessEqual(len(h), 50)
        self.assertTrue(h.endswith("07-10-2026"))
        self.assertEqual(sync.add_history(h, date(2026, 10, 7), FMT), h)


class DeliveryStatusTests(unittest.TestCase):
    D = "2026-11-01"

    def st(self, code, **t1):
        return sync.delivery_status(code, {k.lower(): v for k, v in t1.items()} if t1 is not None else None)[0]

    def test_cisco_only_statuses(self):
        self.assertEqual(self.st("Fulfillment in Progress"), "Fulfilment in progress")
        self.assertEqual(self.st("Scheduled"), "Scheduled")
        self.assertEqual(self.st("Shipped"), "ASIA Hold")

    def test_booked_license_vs_scheduling_pending(self):
        self.assertEqual(self.st("Booked", lineType="Licenses"), "Licenses")
        self.assertEqual(self.st("Booked", lineType="Attached SAAS"), "Licenses")
        self.assertEqual(self.st("Booked", lineType="Products"), "Scheduling Pending")

    def test_closed_chain(self):
        self.assertEqual(self.st("Closed"), "Intransit from CISCO Warehouse")
        self.assertEqual(self.st("Closed", productReceiveDate=self.D), "Ready in Stock")
        si = {"salesInvoiceNo": "SI1", "productReceiveDate": self.D}
        self.assertEqual(self.st("Closed", **si), "Under Dispatch Planning")
        self.assertEqual(self.st("Closed", dispatchDate=self.D, **si), "Dispatched to Customer/ POD No to be updated")
        self.assertEqual(self.st("Closed", dispatchDate=self.D, podNo="P1", **si), "Dispatched to Customer")
        self.assertEqual(self.st("Closed", customerDeliveryDate=self.D, dispatchDate=self.D, podNo="P1", **si),
                         "Delivered to Customer")
        self.assertEqual(self.st("Closed", salesInvoiceNo="SI1", dispatchDate="0001-01-01"), "Under Dispatch Planning")

    def test_no_t1_row_or_unknown_code_leaves_status(self):
        self.assertEqual(sync.delivery_status("Closed", None)[0], None)
        self.assertIn("not changed", sync.delivery_status("Closed", None)[1])
        self.assertEqual(sync.delivery_status("Weird", {})[0], None)
        self.assertEqual(sync.delivery_status("", None), (None, None))


class WeekendTests(unittest.TestCase):
    def test_roll_to_monday(self):
        from datetime import timedelta
        sat, sun, mon, fri = date(2026, 11, 28), date(2026, 11, 29), date(2026, 11, 30), date(2026, 11, 27)
        self.assertEqual(sync.roll_to_monday(sat), mon)   # Saturday: +2
        self.assertEqual(sync.roll_to_monday(sun), mon)   # Sunday: +1
        self.assertEqual(sync.roll_to_monday(mon), mon)
        self.assertEqual(sync.roll_to_monday(fri), fri)
        # 14 days after Sat 14-Nov is Sat 28-Nov -> 16 days in total; after Sun 15-Nov -> 15 days in total
        self.assertEqual(sync.roll_to_monday(date(2026, 11, 14) + timedelta(days=14)) - date(2026, 11, 14), timedelta(days=16))
        self.assertEqual(sync.roll_to_monday(date(2026, 11, 15) + timedelta(days=14)) - date(2026, 11, 15), timedelta(days=15))


class RunTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import history
        history.PATH = os.path.join(tempfile.mkdtemp(), "history.json")  # never touch the real history
        self.patches = []
        self.store = {
            "POCSIN1-M": [bcline("POCSIN1-M", "1"), bcline("POCSIN1-M", "2")],
            "POCSIN1-S": [bcline("POCSIN1-S", "1")],
        }
        self.patched = []
        self.t1_calls = []
        for obj, name in ((t1refresh, "check_api"), (t1refresh, "refresh"), (sync, "t1_by_line"),
                          (bcsync, "check_api"), (bcsync, "fetch_lines"), (bcsync, "patch_line")):
            self.addCleanup(setattr, obj, name, getattr(obj, name))   # undo the fakes after each test
        t1refresh.check_api = lambda: None
        t1refresh.refresh = lambda docs: self.t1_calls.append(list(docs)) or {"docs": len(docs), "rows": 2 * len(docs)}
        sync.t1_by_line = lambda pos: {("POCSIN1-M", "10000"): {"salesinvoiceno": "SI1"}}
        bcsync.check_api = lambda: None
        bcsync.fetch_lines = lambda docs: [ln for d in docs for ln in self.store.get(d, [])]
        bcsync.patch_line = lambda ln, fields: self.patched.append((ln["id"], fields))
        sync.SYNCS.clear()
        jobs.JOBS["j1"] = {"status": "done", "rows": [
            row(line="1", final="2026-11-10"), row(line="2", final="2026-11-20"), row(line="9")]}

    def run_sync(self, dry):
        sid = sync.start("j1", dry)
        while sync.get(sid)["status"] == "running":
            time.sleep(0.05)
        return sync.get(sid)

    def test_sync_matches_both_M_and_S_and_uses_latest_date_plus_14(self):
        st = self.run_sync(False)
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["counts"]["updated"], 3)   # M1, S1 and M2
        self.assertEqual(st["counts"]["no_match"], 1)  # PO line 9 does not exist in BC
        ids = {i for i, _ in self.patched}
        self.assertEqual(ids, {"POCSIN1-M-1", "POCSIN1-S-1", "POCSIN1-M-2"})
        # latest scheduled date of the PO is 2026-11-20 -> estimate = 2026-12-04, same on every line
        self.assertTrue(all(f["estimateDeliveryDate"] == "2026-12-04" for _, f in self.patched))

    def test_dry_run_writes_nothing(self):
        st = self.run_sync(True)
        self.assertEqual(self.patched, [])
        self.assertEqual(st["counts"]["would_update"], 3)

    def test_t1_process_data_refreshed_once_for_each_updated_document(self):
        st = self.run_sync(False)
        self.assertEqual(sorted(self.t1_calls[0]), ["POCSIN1-M", "POCSIN1-S"])
        self.assertEqual(len(self.t1_calls), 1)                    # one call per PO, not per line
        self.assertEqual((st["t1"]["docs"], st["t1"]["rows"], st["t1"]["errors"]), (2, 4, 0))
        self.assertEqual((st["activity"], st["lines_done"]), ("Finished", 1))

    def test_preview_never_touches_t1(self):
        st = self.run_sync(True)
        self.assertEqual(self.t1_calls, [])
        self.assertEqual(st["t1"]["would"], 2)

    def test_t1_failure_keeps_the_purchase_line_updates(self):
        def boom(docs):
            raise RuntimeError("BC says no")
        t1refresh.refresh = boom
        st = self.run_sync(False)
        self.assertEqual(st["counts"]["updated"], 3)
        self.assertEqual(st["t1"]["errors"], 1)
        self.assertTrue(any("T1 Process Data not updated" in w for d in st["details"] for w in d["warnings"]))

    def test_missing_t1_api_skips_only_the_t1_step(self):
        def missing():
            raise t1refresh.T1RefreshApiMissing("not published")
        t1refresh.check_api = missing
        st = self.run_sync(False)
        self.assertEqual(st["counts"]["updated"], 3)
        self.assertEqual((self.t1_calls, st["t1"]["skipped"]), ([], "not published"))

    def test_cancel_stops_before_the_next_po(self):
        jobs.JOBS["j1"]["rows"] += [row(po="POCSIN2", line="1")]
        bcsync.fetch_lines = lambda docs: (time.sleep(0.3), [])[1]   # slow enough to cancel in between
        sync.WORKERS = 1
        sid = sync.start("j1", False)
        time.sleep(0.1)
        self.assertTrue(sync.cancel(sid))
        while sync.get(sid)["status"] == "running":
            time.sleep(0.05)
        st = sync.get(sid)
        self.assertEqual((st["status"], st["activity"], st["done"]), ("cancelled", "Cancelled", 2))
        self.assertFalse(sync.cancel(sid))                          # nothing left to cancel

    def test_missing_api_fails_cleanly(self):
        def boom():
            raise bcsync.SyncApiMissing("not published")
        bcsync.check_api = boom
        st = self.run_sync(False)
        self.assertEqual((st["status"], st["error"]), ("failed", "not published"))
        self.assertEqual(self.patched, [])


if __name__ == "__main__":
    unittest.main()
