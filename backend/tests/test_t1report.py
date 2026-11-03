"""Offline tests for the T1 Process Report export (no network)."""
import io
import os
import sys
import unittest
from datetime import date

from openpyxl import load_workbook

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bcsync  # noqa: E402
import t1report  # noqa: E402

REPORT_ORDER = [  # first / last dataset columns of Report 80000, in order
    "Account_Manager_Name", "BSO_No", "BSO_Line_No", "BSO_Order_Date", "BSO_Quantity", "Pending_Qty_to_Create_SO"]


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.ok = payload, status, status < 400
        self.text = str(payload)

    def json(self):
        return self._p


class ExportTests(unittest.TestCase):
    def sheet(self, rows):
        return load_workbook(io.BytesIO(t1report.build_xlsx(rows).read())).active

    def test_columns_follow_report_dataset_order(self):
        ws = self.sheet([{"bsoNo": "BSO1"}])
        heads = [c.value for c in ws[1]]
        self.assertEqual(heads[:6], REPORT_ORDER)
        self.assertEqual(heads[-3:], ["SO_Order_Month", "BSO_Line_Item_No", "Proactive_PO_Buyer_Line_No"])
        self.assertEqual(len(heads), 64)
        self.assertEqual(len(set(heads)), 64)

    def test_values_dates_numbers_and_month(self):
        ws = self.sheet([{"bsoNo": "BSO1", "bsoLineNo": 20000, "bsoOrderDate": "2026-10-01", "soDate": "2026-09-15",
                          "bsoQuantity": 3.0, "scheduledDate": "0001-01-01", "previousScheduleShipDate": "05-11-26",
                          "lineStatus": "Scheduled"}])
        h = {c.value: i for i, c in enumerate(ws[1])}
        row = [c.value for c in ws[2]]
        self.assertEqual(row[h["BSO_No"]], "BSO1")
        self.assertEqual(row[h["BSO_Line_No"]], 20000)
        self.assertEqual(row[h["BSO_Order_Date"]].date(), date(2026, 10, 1))
        self.assertIsNone(row[h["Scheduled_Date"]])              # BC's 0001-01-01 means "no date"
        self.assertEqual(row[h["SO_Order_Month"]], "Sept")       # same names as GetSOMonth() in the report
        self.assertEqual(row[h["Previous_Schedule_Ship_Date"]], "05-11-26")
        self.assertEqual(row[h["Line_Status"]], "Scheduled")

    def test_api_field_names_match_ignoring_case(self):
        ws = self.sheet([{"BSONo": "BSO9", "BSOOrderDate": "2026-10-01", "SODate": "2026-12-05"}])
        h = {c.value: i for i, c in enumerate(ws[1])}
        row = [c.value for c in ws[2]]
        self.assertEqual((row[h["BSO_No"]], row[h["SO_Order_Month"]]), ("BSO9", "Dec"))

    def test_month_names_match_report(self):
        self.assertEqual(t1report.MONTHS, ["Jan", "Feb", "March", "April", "May", "June", "July",
                                           "August", "Sept", "Oct", "Nov", "Dec"])


class CustomerPoTests(unittest.TestCase):
    def test_distinct_prefixed_suffix_stripped(self):
        rows = [{"proactivePONo": "pocsin262700193-M"}, {"ProactivePONo": "POCSIN262700193"},
                {"proactivePONo": "POCSIN262700200"}, {"proactivePONo": "ABC-123"}, {"proactivePONo": ""}, {}]
        self.assertEqual(t1report.customer_pos(rows, "POCSIN"), (["POCSIN262700193", "POCSIN262700200"], 1))


class FetchTests(unittest.TestCase):
    def setUp(self):
        os.environ["BC_T1_API_URL"] = "https://bc.example/t1ProcessReport"
        self.calls = []
        pages = {"https://bc.example/t1ProcessReport": {"value": [{"bsoNo": "A"}, {"bsoNo": "B"}], "@odata.nextLink": "https://bc.example/next"},
                 "https://bc.example/next": {"value": [{"bsoNo": "C"}]}}

        def fake(method, url, **kw):
            self.calls.append((url, kw))
            return FakeResp(pages[url])
        self._orig = bcsync._request
        bcsync._request = fake

    def tearDown(self):
        bcsync._request = self._orig

    def test_paging_filter_and_page_size_header(self):
        rows = t1report.fetch_rows("2026-10-01", "2026-10-30", ["BSO1", "BSO2"])
        self.assertEqual([r["bsoNo"] for r in rows], ["A", "B", "C"])
        url, kw = self.calls[0]
        self.assertIn("bsoOrderDate ge 2026-10-01 and bsoOrderDate le 2026-10-30", kw["params"]["$filter"])
        self.assertIn("bsoNo eq 'BSO1' or bsoNo eq 'BSO2'", kw["params"]["$filter"])
        self.assertEqual(kw["headers"]["Prefer"], "odata.maxpagesize=5000")
        self.assertIsNone(self.calls[1][1]["params"])            # next page: no extra params

    def test_row_limit(self):
        with self.assertRaises(OverflowError):
            t1report.fetch_rows("2026-10-01", "2026-10-30", limit=2)

    def test_rejects_unsafe_bso_number(self):
        with self.assertRaises(ValueError):
            t1report.fetch_rows("2026-10-01", "2026-10-30", ["x' or 1 eq 1 or bsoNo eq '"])

    def test_missing_api_message(self):
        bcsync._request = lambda *a, **k: FakeResp({}, 404)
        with self.assertRaises(t1report.T1ApiMissing):
            t1report.fetch_rows("2026-10-01", "2026-10-30")


if __name__ == "__main__":
    unittest.main()
