import importlib.util
import unittest
from pathlib import Path

import pandas as pd


APP_PATH = Path(__file__).resolve().parents[1] / "us-rs-rating-dashboard-v1.3-ema50-risk-behavior.py"
SPEC = importlib.util.spec_from_file_location("dashboard_v13_screening", APP_PATH)
dashboard_v13 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard_v13)


class RSScreeningImportTests(unittest.TestCase):
    def test_accepts_case_variant_columns_and_multiply_symbol_turnover(self):
        raw = pd.DataFrame(
            {
                "Symbol": ["AAA", "BBB", "CCC"],
                "Exchange": ["NASDAQ", "NYSE", ""],
                "Market capitalization": [5_000_000_000, 20_000_000_000, 250_000_000_000],
                "Price": [10, 20, 30],
                "Average volume 60 days": [2_000_000, 1_000_000, 500_000],
                "Performance % 1 week": [1, 2, 3],
                "Performance % 1 month": [5, 10, 15],
                "Performance % 3 months": [10, 20, 30],
                "Performance % 6 months": [20, 30, 40],
                "Performance % 1 year": [30, 40, 50],
                "Exponential moving average (20) 1 day": [9, 18, 25],
                "Price × volume (turnover) 1 day": [20_000_000, 20_000_000, 15_000_000],
                "Average true range % (14) 1 day": [2.0, 3.0, 6.0],
            }
        )

        df, missing_cols, _sector_col, _rank_columns = dashboard_v13.prepare_screening_data(raw)

        self.assertEqual(missing_cols, [])
        self.assertIn("Average Volume 60 days", df.columns)
        self.assertIn("Distance from EMA20 %", df.columns)
        self.assertIn("Turnover 1D vs 60D Avg", df.columns)
        self.assertIn("ATR Range", df.columns)
        self.assertEqual(df.loc[0, "Avg 60D Turnover (USD)"], 20_000_000)
        self.assertEqual(df.loc[0, "ATR Range"], "Slow and Pokey")
        self.assertEqual(df.loc[1, "ATR Range"], "Sweet Spot")
        self.assertEqual(df.loc[2, "ATR Range"], "Hot")

    def test_tradingview_exports_plain_or_exchange_prefixed_symbols(self):
        self.assertEqual(dashboard_v13.symbols_to_tv(["AAPL", "MSFT"]), "AAPL,MSFT")
        self.assertEqual(
            dashboard_v13.symbols_to_tv(["AAPL", "XYZ"], ["NASDAQ", "nyse"]),
            "NASDAQ:AAPL,NYSE:XYZ",
        )


if __name__ == "__main__":
    unittest.main()
