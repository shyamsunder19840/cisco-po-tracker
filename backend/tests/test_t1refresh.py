"""Offline tests for the T1 Process Data refresh client (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bcsync  # noqa: E402
import t1refresh  # noqa: E402


class Resp:
    def __init__(self, payload=None, status=200):
        self._p, self.status_code, self.ok = payload or {}, status, status < 400

    def json(self):
        return self._p


class RefreshTests(unittest.TestCase):
    def setUp(self):
        os.environ["BC_SYNC_API_URL"] = "https://bc.example/api/Proactive/ProactiveAPI/v1.0/companies(1)/purchaseLineSync"
        os.environ.pop("BC_T1_REFRESH_API_URL", None)
        self.calls = []
        t1refresh._IDS.clear()
        self._orig = bcsync._request

    def tearDown(self):
        bcsync._request = self._orig

    def fake(self, headers_ok=True, post_status=200):
        def f(method, url, **kw):
            self.calls.append((method, url, kw))
            if method == "GET":
                return Resp({"value": [{"id": "a1", "documentNo": "P-M"}, {"id": "b2", "documentNo": "P-S"}]})
            return Resp({"t1Rows": 3}, post_status)
        bcsync._request = f

    def test_url_defaults_to_the_sync_api_group(self):
        self.assertTrue(t1refresh._url().endswith("/companies(1)/t1Refresh"))

    def test_finds_documents_then_runs_the_action_once_each(self):
        self.fake()
        out = t1refresh.refresh(["P-M", "P-S"])
        self.assertEqual(out, {"docs": 2, "rows": 6})
        self.assertIn("documentNo eq 'P-M' or documentNo eq 'P-S'", self.calls[0][2]["params"]["$filter"])
        self.assertEqual([c[1].rsplit("/", 1)[-1] for c in self.calls[1:]], ["Microsoft.NAV.refreshT1Data"] * 2)
        self.assertTrue(self.calls[1][1].endswith("t1Refresh(a1)/Microsoft.NAV.refreshT1Data"))

    def test_order_ids_are_looked_up_only_once(self):
        self.fake()
        t1refresh.refresh(["P-M", "P-S"])
        t1refresh.refresh(["P-M"])
        self.assertEqual([c[0] for c in self.calls], ["GET", "POST", "POST", "POST"])   # no second GET

    def test_action_failure_is_reported(self):
        self.fake(post_status=400)
        with self.assertRaises(RuntimeError):
            t1refresh.refresh(["P-M"])

    def test_missing_page_and_unsafe_number(self):
        bcsync._request = lambda *a, **k: Resp(status=404)
        with self.assertRaises(t1refresh.T1RefreshApiMissing):
            t1refresh.check_api()
        with self.assertRaises(ValueError):
            t1refresh.refresh(["x' or 1 eq 1 or documentNo eq '"])


if __name__ == "__main__":
    unittest.main()
