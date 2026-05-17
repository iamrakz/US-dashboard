import tempfile
import unittest
from pathlib import Path

from portfolio_risk import (
    calculate_portfolio_risk,
    classify_heat_regime,
    load_latest_portfolio_risk_snapshot,
    load_portfolio_risk_history,
    save_portfolio_risk_snapshot,
)


class PortfolioRiskTests(unittest.TestCase):
    def test_calculates_market_value_exposure_atr_and_heat(self):
        rows = [
            {"Stock name": "AAA", "Position": 1000, "Avg. cost": 8, "Last price": 10, "Stop": 9, "%ATR": 5},
            {"Stock name": "BBB", "Position": 500, "Avg. cost": 18, "Last price": 20, "Stop": 18, "%ATR": 4},
        ]

        positions, summary = calculate_portfolio_risk(rows, total_invested=100_000, total_equity=150_000)

        self.assertEqual(len(positions), 2)
        self.assertAlmostEqual(positions.loc[0, "Market value (USD)"], 10_000)
        self.assertAlmostEqual(positions.loc[0, "Exposure %"], 10)
        self.assertAlmostEqual(positions.loc[0, "Heat (USD)"], 1_000)
        self.assertAlmostEqual(summary.portfolio_atr_pct, 900 / 150_000 * 100)
        self.assertAlmostEqual(summary.position_atr_pct, 900 / 20_000 * 100)
        self.assertAlmostEqual(summary.portfolio_heat_usd, 2_000)
        self.assertAlmostEqual(summary.portfolio_heat_pct, 2_000 / 150_000 * 100)
        self.assertAlmostEqual(summary.position_heat_pct, 2_000 / 20_000 * 100)

    def test_stop_above_last_price_floors_heat_at_zero(self):
        rows = [{"Stock name": "AAA", "Position": 1000, "Last price": 10, "Stop": 12, "%ATR": 5}]

        positions, summary = calculate_portfolio_risk(rows, total_invested=10_000, total_equity=20_000)

        self.assertAlmostEqual(positions.loc[0, "Heat (USD)"], 0)
        self.assertAlmostEqual(summary.portfolio_heat_pct, 0)

    def test_zero_denominators_are_safe(self):
        rows = [{"Stock name": "AAA", "Position": 1000, "Last price": 10, "Stop": 9, "%ATR": 5}]

        positions, summary = calculate_portfolio_risk(rows, total_invested=0, total_equity=0)

        self.assertAlmostEqual(positions.loc[0, "Exposure %"], 0)
        self.assertAlmostEqual(summary.portfolio_atr_pct, 0)
        self.assertAlmostEqual(summary.position_atr_pct, 5)
        self.assertAlmostEqual(summary.portfolio_heat_pct, 0)
        self.assertAlmostEqual(summary.position_heat_pct, 10)

    def test_heat_regime_boundaries(self):
        cases = [
            (1.99, "Very defensive"),
            (2.0, "Normal risk"),
            (4.0, "Aggressive"),
            (6.0, "Very aggressive"),
            (8.0, "High risk"),
            (10.0, "High risk"),
            (10.1, "Extreme risk / outside plan"),
        ]

        for heat, expected in cases:
            with self.subTest(heat=heat):
                self.assertEqual(classify_heat_regime(heat), expected)

    def test_latest_saved_snapshot_loads_back_to_editable_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk.sqlite3"
            save_portfolio_risk_snapshot(
                [{"Stock name": "OLD", "Position": 100, "Last price": 10, "Stop": 9, "%ATR": 5}],
                "2026-05-01",
                10_000,
                20_000,
                db_path,
            )
            save_portfolio_risk_snapshot(
                [{"Stock name": "NEW", "Position": 200, "Last price": 15, "Stop": 14, "%ATR": 4}],
                "2026-05-02",
                20_000,
                30_000,
                db_path,
            )

            positions, snapshot = load_latest_portfolio_risk_snapshot(db_path)

            self.assertEqual(snapshot["snapshot_date"], "2026-05-02")
            self.assertEqual(positions.loc[0, "Stock name"], "NEW")
            self.assertAlmostEqual(positions.loc[0, "Position"], 200)

    def test_history_limit_loads_recent_rows_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk.sqlite3"
            for day in [1, 2, 3]:
                save_portfolio_risk_snapshot(
                    [{"Stock name": f"AAA{day}", "Position": 100, "Last price": 10, "Stop": 9, "%ATR": 5}],
                    f"2026-05-0{day}",
                    10_000,
                    20_000,
                    db_path,
                )

            history = load_portfolio_risk_history(db_path, limit=2)

            self.assertEqual(len(history), 2)
            self.assertEqual(history.iloc[0]["snapshot_date"], "2026-05-03")
            self.assertEqual(history.iloc[1]["snapshot_date"], "2026-05-02")


if __name__ == "__main__":
    unittest.main()
