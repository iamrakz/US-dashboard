import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


APP_PATH = Path(__file__).resolve().parents[1] / "us-rs-rating-dashboard-v1.3-ema50-risk-behavior.py"
SPEC = importlib.util.spec_from_file_location("dashboard_v13_pretrade", APP_PATH)
dashboard_v13 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard_v13)


class PretradeDrawdownTests(unittest.TestCase):
    def test_recent_max_drawdown_uses_latest_20_records_only(self):
        rows = []
        for day in range(1, 31):
            drawdown = -1.0
            if day == 10:
                drawdown = -20.0
            if day == 21:
                drawdown = -9.0
            rows.append({"Date": f"2026-05-{day:02d}", "Equity Drawdown %": drawdown})

        result = dashboard_v13.calculate_recent_max_drawdown_pct(pd.DataFrame(rows))

        self.assertAlmostEqual(result, 9.0)

    def test_recent_max_drawdown_uses_worst_available_when_less_than_window(self):
        df = pd.DataFrame(
            {
                "Date": ["2026-05-01", "2026-05-02", "2026-05-03"],
                "Equity Drawdown %": [-1.0, -5.0, -2.0],
            }
        )

        result = dashboard_v13.calculate_recent_max_drawdown_pct(df)

        self.assertAlmostEqual(result, 5.0)

    def test_recent_max_drawdown_handles_missing_data(self):
        self.assertEqual(dashboard_v13.calculate_recent_max_drawdown_pct(pd.DataFrame()), 0.0)
        self.assertEqual(
            dashboard_v13.calculate_recent_max_drawdown_pct(pd.DataFrame({"Date": ["2026-05-01"]})),
            0.0,
        )

    def test_pretrade_snapshot_persists_personal_drawdown_pct_locally(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "journal.sqlite3"
            original_is_supabase_enabled = dashboard_v13.is_supabase_pretrade_enabled
            dashboard_v13.is_supabase_pretrade_enabled = lambda: False
            try:
                dashboard_v13.save_pretrade_snapshot(
                    {
                        "snapshot_date": "2026-05-11",
                        "total_equity": 100_000,
                        "expected_exposure": 80,
                        "current_exposure": 50,
                        "personal_drawdown_pct": 4.25,
                    },
                    db_path=db_path,
                )
                history = dashboard_v13.load_pretrade_snapshots(db_path=db_path)
            finally:
                dashboard_v13.is_supabase_pretrade_enabled = original_is_supabase_enabled

        self.assertIn("Personal Drawdown %", history.columns)
        self.assertAlmostEqual(history.iloc[0]["Personal Drawdown %"], 4.25)


if __name__ == "__main__":
    unittest.main()
