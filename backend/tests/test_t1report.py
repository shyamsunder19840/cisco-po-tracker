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
        self.assertEqual(heads[:6], [h.replace("_", " ") for h in REPORT_ORDER])   # headings use spaces, not '_'
        self.assertEqual(heads[-3:], ["SO Order Month", "BSO Line Item No", "Proactive PO Buyer Line No"])
        self.assertFalse(any("_" in h for h in heads))
        self.assertEqual(len(heads), 64)
        self.assertEqual(len(set(heads)), 64)

    def test_values_dates_numbers_and_month(self):
        ws = self.sheet([{"bsoNo": "BSO1", "bsoLineNo": 20000, "bsoOrderDate": "2026-10-01", "soDate": "2026-09-15",
                          "bsoQuantity": 3.0, "scheduledDate": "0001-01-01", "previousScheduleShipDate": "05-11-26",
                          "lineStatus": "Scheduled"}])
        h = {c.value.replace(" ", "_"): i for i, c in enumerate(ws[1])}
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
        h = {c.value.replace(" ", "_"): i for i, c in enumerate(ws[1])}
        row = [c.value for c in ws[2]]
        self.assertEqual((row[h["BSO_No"]], row[h["SO_Order_Month"]]), ("BSO9", "Dec"))

    def test_month_names_match_report(self):
        self.assertEqual(t1report.MONTHS, ["Jan", "Feb", "March", "April", "May", "June", "July",
                                           "August", "Sept", "Oct", "Nov", "Dec"])


class PurchaseLineSheetTests(unittest.TestCase):
    LN = {"documentNo": "POCSIN1-M", "lineNo": 20000, "buyersLineNo": "2", "ciscoSOLineNo": "1.2", "shipset": "1",
          "ciscoDeliveryStatus": "Scheduled", "scheduledDate": "2026-11-10", "previousScheduledDate": "01-11-26",
          "estimateDeliveryDate": "0001-01-01"}

    def book(self, *a):
        return load_workbook(io.BytesIO(t1report.build_xlsx([{"bsoNo": "B"}], *a).read()))

    def test_second_sheet_has_the_sync_fields(self):
        wb = self.book([self.LN])
        self.assertEqual(wb.sheetnames, ["T1 Report", "Purchase Lines"])
        ws = wb["Purchase Lines"]
        self.assertEqual([c.value for c in ws[1]], ["Document No", "Line No", "Buyers Line No", "CISCO SO Line No", "Shipset",
                         "CISCO Delivery Status", "Scheduled Date", "Previous Scheduled Date", "Estimate Delivery Date"])
        row = [c.value for c in ws[2]]
        self.assertEqual(row[:6], ["POCSIN1-M", 20000, "2", "1.2", "1", "Scheduled"])
        self.assertEqual(row[6].date(), date(2026, 11, 10))
        self.assertEqual((row[7], row[8]), ("01-11-26", None))        # BC's 0001-01-01 = no date

    def test_no_second_sheet_by_default_and_a_note_when_unreadable(self):
        self.assertEqual(self.book().sheetnames, ["T1 Report"])
        ws = self.book(None, "API not found")["Purchase Lines"]
        self.assertIn("API not found", ws["A1"].value)

    def test_purchase_lines_are_read_in_groups_for_the_pos_in_the_rows(self):
        seen = []
        orig = t1report.bcsync.fetch_lines
        t1report.bcsync.fetch_lines = lambda docs: seen.append(list(docs)) or [dict(self.LN, documentNo=d, lineNo=1) for d in docs]
        try:
            rows = [{"proactivePONo": f"P{i:03d}-M"} for i in range(40)] + [{"ProactivePONo": "P000-M"}, {"bsoNo": "x"}]
            out = t1report.purchase_lines(rows, chunk=15)
        finally:
            t1report.bcsync.fetch_lines = orig
        self.assertEqual(sorted(len(g) for g in seen), [10, 15, 15])   # 40 distinct documents in groups of 15
        self.assertEqual(len(out), 40)
        self.assertEqual(out[0]["documentNo"], "P000-M")


class CiscoSheetTests(unittest.TestCase):
    def test_third_sheet_has_the_app_rows_and_columns(self):
        cisco = [{"PO ID": "P1", "Quantity": 3, "Status Code": "Closed", "Extra": {"a": 1}}, {"PO ID": "P2", "Quantity": 1}]
        wb = load_workbook(io.BytesIO(t1report.build_xlsx([{"bsoNo": "B"}], [], "", cisco, ["PO ID", "Quantity", "Status Code", "Extra"]).read()))
        self.assertEqual(wb.sheetnames, ["T1 Report", "Purchase Lines", "Cisco API Data"])
        ws = wb["Cisco API Data"]
        self.assertEqual([c.value for c in ws[1]], ["PO ID", "Quantity", "Status Code", "Extra"])
        self.assertEqual([c.value for c in ws[2]], ["P1", 3, "Closed", '{"a": 1}'])
        self.assertEqual([c.value for c in ws[3]], ["P2", 1, None, None])

    def test_no_check_status_means_no_third_sheet(self):
        wb = load_workbook(io.BytesIO(t1report.build_xlsx([{"bsoNo": "B"}]).read()))
        self.assertEqual(wb.sheetnames, ["T1 Report"])


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

    def test_po_filters_without_dates(self):
        t1report.fetch_rows(None, None, customer_pos=["4500348821"], proactive_pos=["POCSIN1", "POCSIN1-M"])
        flt = self.calls[0][1]["params"]["$filter"]
        self.assertNotIn("bsoOrderDate", flt)
        self.assertIn("customerPONo eq '4500348821'", flt)
        self.assertIn("proactivePONo eq 'POCSIN1' or proactivePONo eq 'POCSIN1-M'", flt)

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
