"""Offline tests for the database (Business Central environment) setting."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402

CO = "d2201f64-96ef-ec11-82f8-6045bdae852a"
URLS = {
    "BC_PO_URL": f"https://api.businesscentral.dynamics.com/v2.0/Test-Shyam/api/v2.0/companies({CO})/purchaseOrders",
    "BC_SYNC_API_URL": f"https://api.businesscentral.dynamics.com/v2.0/Test-Shyam/api/Proactive/ProactiveAPI/v1.0/companies({CO})/purchaseLineSync",
    "BC_T1_API_URL": f"https://api.businesscentral.dynamics.com/v2.0/a1492249-245b-4a8b-a6e4-ce2d20b36653/Test-Shyam/api/Proactive/ProactiveAPI/v1.0/companies({CO})/t1ProcessReport",
}


class DatabaseSettingTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._path = settings.ENV_PATH
        settings.ENV_PATH = os.path.join(tempfile.mkdtemp(), ".env")
        for k in settings.URL_KEYS:
            os.environ.pop(k, None)
        os.environ.update(URLS)

    def tearDown(self):
        settings.ENV_PATH = self._path
        os.environ.clear()
        os.environ.update(self._env)

    def test_current_database_and_choices_in_the_ui_list(self):
        self.assertEqual(settings.current_database(), "Test-Shyam")
        item = next(f for f in settings.public_view() if f["key"] == "BC_DATABASE")
        self.assertEqual((item["kind"], item["value"]), ("choice", "Test-Shyam"))
        self.assertEqual(item["options"], ["Live-Database", "Test-Shyam", "Test-Rishabh"])

    def test_changing_the_database_rewrites_every_url(self):
        changed = settings.save({"BC_DATABASE": "Live-Database", "BC_PO_URL": URLS["BC_PO_URL"]})
        self.assertIn("BC_SYNC_API_URL", changed)
        for key in URLS:
            self.assertIn("/Live-Database/", os.environ[key])
            self.assertNotIn("Test-Shyam", os.environ[key])
            self.assertIn(CO, os.environ[key])                       # the company id is kept
        self.assertIn("/a1492249-245b-4a8b-a6e4-ce2d20b36653/Live-Database/", os.environ["BC_T1_API_URL"])  # tenant form
        self.assertEqual(settings.current_database(), "Live-Database")
        self.assertIn("Live-Database", open(settings.ENV_PATH, encoding="utf-8").read())   # persisted

    def test_unknown_database_is_rejected_and_same_database_is_a_noop(self):
        self.assertIn("BC_DATABASE", settings.validate({"BC_DATABASE": "Production"}))
        self.assertEqual(settings.validate({"BC_DATABASE": "Test-Rishabh"}), {})
        settings.save({"BC_DATABASE": "Test-Shyam"})
        self.assertEqual(os.environ["BC_PO_URL"], URLS["BC_PO_URL"])


if __name__ == "__main__":
    unittest.main()
