import importlib.util
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "us-rs-rating-dashboard-v1.4-google-login.py"
SPEC = importlib.util.spec_from_file_location("dashboard_v14_auth", APP_PATH)
dashboard_v14 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard_v14)


class GoogleAuthTests(unittest.TestCase):
    def test_parse_allowed_google_emails_accepts_lists_and_csv(self):
        self.assertEqual(
            dashboard_v14.parse_allowed_google_emails([" You@Example.com ", "me@example.com"]),
            {"you@example.com", "me@example.com"},
        )
        self.assertEqual(
            dashboard_v14.parse_allowed_google_emails("you@example.com, ME@example.com"),
            {"you@example.com", "me@example.com"},
        )

    def test_parse_allowed_google_emails_ignores_blank_values(self):
        self.assertEqual(
            dashboard_v14.parse_allowed_google_emails(["", " ", "you@example.com"]),
            {"you@example.com"},
        )


if __name__ == "__main__":
    unittest.main()
