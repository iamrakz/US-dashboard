import unittest

from exposure_scorecard import ExposureScorecardInput, calculate_exposure_scorecard


def make_input(**overrides):
    data = {
        "nav": 110,
        "ema10": 105,
        "ema20": 100,
        "ema50": 95,
        "ema10_rising": True,
        "market_trend_condition": "Index > EMA21 and EMA21 > SMA50 and Index > SMA200",
        "market_health": "Strong",
        "pt_ftd": "PT on / confirmed uptrend",
        "volatility_condition": "Normal: ATR percentile < 50",
        "distribution_days": 1,
        "personal_drawdown_pct": 1,
        "base_mode": "Margin",
    }
    data.update(overrides)
    return ExposureScorecardInput(**data)


class ExposureScorecardTests(unittest.TestCase):
    def test_peak_performance_strong_market_allows_120(self):
        result = calculate_exposure_scorecard(make_input())
        self.assertTrue(result.margin_allowed)
        self.assertEqual(result.performance_regime, "Peak performance")
        self.assertEqual(result.final_exposure_pct, 120)

    def test_stay_low_weak_market_keeps_exposure_low(self):
        result = calculate_exposure_scorecard(
            make_input(
                nav=88,
                ema10=92,
                ema20=95,
                ema50=100,
                market_health="Weak",
                pt_ftd="No FTD in downtrend",
                market_trend_condition="Index < SMA200 and FTD is false",
                base_mode="Normal",
            )
        )
        self.assertEqual(result.performance_regime, "Stay low")
        self.assertLessEqual(result.final_exposure_pct, 5)

    def test_healthy_but_high_volatility_reduces_exposure(self):
        result = calculate_exposure_scorecard(
            make_input(
                nav=102,
                ema10=98,
                ema20=100,
                ema50=95,
                volatility_condition="High: ATR percentile 75-90",
                base_mode="Normal",
            )
        )
        self.assertEqual(result.performance_regime, "Healthy")
        self.assertEqual(result.volatility_regime, "High")
        self.assertLessEqual(result.final_exposure_pct, 50)

    def test_recovery_reexpands_gradually_only(self):
        result = calculate_exposure_scorecard(
            make_input(
                nav=101,
                ema10=100,
                ema20=96,
                ema50=98,
                ema10_rising=True,
                base_mode="Margin",
            )
        )
        self.assertEqual(result.performance_regime, "Recovery")
        self.assertLessEqual(result.final_exposure_pct, 40)

    def test_margin_conditions_not_met_caps_at_100(self):
        result = calculate_exposure_scorecard(
            make_input(
                market_health="Neutral",
                base_mode="Margin",
            )
        )
        self.assertFalse(result.margin_allowed)
        self.assertLessEqual(result.final_exposure_pct, 100)

    def test_market_trend_condition_maps_to_regime(self):
        result = calculate_exposure_scorecard(
            make_input(market_trend_condition="Index > SMA200 and EMA21 < SMA50")
        )
        self.assertEqual(result.market_trend_regime, "Weakening trend")

    def test_healthy_pullback_condition_maps_to_regime(self):
        result = calculate_exposure_scorecard(
            make_input(market_trend_condition="Index < EMA21 and EMA21 > SMA50 and Index > SMA200")
        )
        self.assertEqual(result.market_trend_regime, "Healthy pullback")
        self.assertEqual(result.final_exposure_pct, 90)

    def test_deeper_correction_above_sma200_maps_to_regime(self):
        result = calculate_exposure_scorecard(
            make_input(market_trend_condition="Index < EMA21 and Index < SMA50 and Index > SMA200")
        )
        self.assertEqual(result.market_trend_regime, "Deeper correction above SMA200")
        self.assertLessEqual(result.final_exposure_pct, 50)

    def test_atr_volatility_condition_maps_to_regime(self):
        result = calculate_exposure_scorecard(
            make_input(volatility_condition="Extreme: ATR percentile 90-95")
        )
        self.assertEqual(result.volatility_regime, "Extreme")


if __name__ == "__main__":
    unittest.main()
