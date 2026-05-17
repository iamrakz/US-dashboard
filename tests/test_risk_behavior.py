import importlib.util
import unittest
from pathlib import Path

import pandas as pd


APP_PATH = Path(__file__).resolve().parents[1] / "us-rs-rating-dashboard-v1.3-ema50-risk-behavior.py"
SPEC = importlib.util.spec_from_file_location("dashboard_v13_risk_behavior", APP_PATH)
dashboard_v13 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard_v13)


def make_default_sheet(rows):
    data = []
    for row in rows:
        values = [None] * 23
        values[1] = row["date"]
        values[7] = row["total_market_value"]
        values[8] = row["cash"]
        values[9] = row["unrealized_pl"]
        values[10] = row["us_market_value"]
        values[11] = row["non_us_market_value"]
        values[22] = row["nav"]
        data.append(values)
    return pd.DataFrame(data, columns=[f"col_{idx}" for idx in range(23)])


class RiskBehaviorTests(unittest.TestCase):
    def test_default_sheet_unrealized_pl_uses_total_equity_denominator(self):
        raw = make_default_sheet(
            [
                {
                    "date": "2026-05-01",
                    "total_market_value": 100_000,
                    "cash": 20_000,
                    "unrealized_pl": 6_000,
                    "us_market_value": 70_000,
                    "non_us_market_value": 10_000,
                    "nav": 100,
                }
            ]
        )

        portfolio_df = dashboard_v13.prepare_default_portfolio_log(raw)

        self.assertAlmostEqual(portfolio_df.loc[0, "Risk Unrealized Gain %"], 5.0)
        self.assertAlmostEqual(portfolio_df.loc[0, "Unrealized Gain"], 5.0)

    def test_unrealized_gain_on_exposure_uses_total_exposure_value(self):
        raw = make_default_sheet(
            [
                {
                    "date": "2026-05-01",
                    "total_market_value": 100_000,
                    "cash": 20_000,
                    "unrealized_pl": 6_000,
                    "us_market_value": 70_000,
                    "non_us_market_value": 10_000,
                    "nav": 100,
                }
            ]
        )

        portfolio_df = dashboard_v13.prepare_default_portfolio_log(raw)

        self.assertAlmostEqual(portfolio_df.loc[0, "Risk Exposure %"], 80_000 / 120_000 * 100)
        self.assertAlmostEqual(portfolio_df.loc[0, "Unrealized Gain on Exposure %"], 7.5)

    def test_risk_drawdown_converts_negative_legacy_drawdown_to_positive(self):
        raw = make_default_sheet(
            [
                {
                    "date": "2026-05-01",
                    "total_market_value": 100_000,
                    "cash": 0,
                    "unrealized_pl": 0,
                    "us_market_value": 70_000,
                    "non_us_market_value": 0,
                    "nav": 100,
                },
                {
                    "date": "2026-05-02",
                    "total_market_value": 90_000,
                    "cash": 0,
                    "unrealized_pl": -2_000,
                    "us_market_value": 60_000,
                    "non_us_market_value": 0,
                    "nav": 90,
                },
            ]
        )

        portfolio_df = dashboard_v13.prepare_default_portfolio_log(raw)

        self.assertAlmostEqual(portfolio_df.loc[1, "Equity Drawdown %"], -10.0)
        self.assertAlmostEqual(portfolio_df.loc[1, "Risk Drawdown %"], 10.0)

    def test_rolling_correlations_use_latest_window_only(self):
        rows = []
        for idx in range(25):
            if idx < 5:
                exposure = idx + 1
                drawdown = idx + 1
            else:
                exposure = idx - 4
                drawdown = 26 - idx
            rows.append(
                {
                    "Date": f"2026-05-{idx + 1:02d}",
                    "Risk Exposure %": exposure,
                    "Risk Unrealized Gain %": exposure * 2,
                    "Risk Drawdown %": drawdown,
                }
            )

        result = dashboard_v13.calculate_risk_behavior_windows(pd.DataFrame(rows), windows=(20,))

        self.assertEqual(result.loc[0, "Records"], 20)
        self.assertLess(result.loc[0, "Corr(Exposure, Drawdown)"], -0.99)
        self.assertEqual(result.loc[0, "Exposure Drawdown Signal"], "Defensive")

    def test_exposure_drawdown_thresholds_classify_warning_states(self):
        self.assertEqual(dashboard_v13.classify_exposure_drawdown_corr(0.51), "Strong warning")
        self.assertEqual(dashboard_v13.classify_exposure_drawdown_corr(0.31), "Warning")
        self.assertEqual(dashboard_v13.classify_exposure_drawdown_corr(-0.31), "Defensive")

    def test_insufficient_data_returns_neutral_result_without_crashing(self):
        df = pd.DataFrame(
            {
                "Risk Exposure %": [50],
                "Risk Unrealized Gain %": [2],
                "Risk Drawdown %": [1],
            }
        )

        result = dashboard_v13.calculate_risk_behavior_windows(df, windows=(20,))

        self.assertEqual(result.loc[0, "Corr(Exposure, Drawdown)"], None)
        self.assertEqual(result.loc[0, "Risk Behavior Score"], "Insufficient data")

    def test_portfolio_preparation_creates_ema50_not_ema40(self):
        raw = make_default_sheet(
            [
                {
                    "date": "2026-05-01",
                    "total_market_value": 100_000,
                    "cash": 20_000,
                    "unrealized_pl": 6_000,
                    "us_market_value": 70_000,
                    "non_us_market_value": 10_000,
                    "nav": 100,
                }
            ]
        )

        portfolio_df = dashboard_v13.prepare_default_portfolio_log(raw)

        self.assertIn("Total Equity NAV EMA50", portfolio_df.columns)
        self.assertNotIn("Total Equity NAV EMA40", portfolio_df.columns)

    def test_risk_behavior_largest_drawdown_uses_latest_20_records(self):
        rows = []
        for day in range(1, 31):
            drawdown = -1.0
            if day == 5:
                drawdown = -15.0
            if day == 20:
                drawdown = -7.0
            rows.append({"Date": f"2026-05-{day:02d}", "Equity Drawdown %": drawdown})

        result = dashboard_v13.calculate_risk_behavior_largest_drawdown_pct(pd.DataFrame(rows))

        self.assertAlmostEqual(result, 7.0)

    def test_risk_behavior_column_config_includes_correlation_tooltips(self):
        config = dashboard_v13.risk_behavior_column_config()

        self.assertIn("Corr(Exposure, Unrealized Gain)", config)
        self.assertIn("Corr(Exposure, Drawdown)", config)
        self.assertIn("Corr(Unrealized Gain, Drawdown)", config)


if __name__ == "__main__":
    unittest.main()
