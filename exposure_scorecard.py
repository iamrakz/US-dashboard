from dataclasses import dataclass
from math import floor


BASE_MODE_RULES = {
    "Defensive": 0.75,
    "Normal": 1.00,
    "Margin": 1.20,
}

MARKET_HEALTH_RULES = {
    "Strong": (1.00, 1.20, "Broad participation supports full risk."),
    "Neutral": (0.75, 0.90, "Breadth is acceptable but not strong enough for maximum exposure."),
    "Weak": (0.50, 0.60, "Weak breadth limits new risk."),
    "Risk-off": (0.25, 0.30, "Risk-off breadth requires capital protection."),
}

PT_FTD_RULES = {
    "PT on / confirmed uptrend": (1.00, 1.20, "Confirmed uptrend supports full participation."),
    "Under pressure": (0.80, 0.75, "Market is under pressure, so cap exposure."),
    "PT off but market above SMA200": (0.80, 0.75, "PT is off, but long-term trend remains supportive."),
    "PT off and market below SMA200": (0.60, 0.50, "PT is off and index is below SMA200."),
    "Failed FTD": (0.30, 0.30, "Failed FTD requires a defensive cap."),
    "No FTD in downtrend": (0.10, 0.20, "No FTD in a downtrend keeps exposure very low."),
}

MARKET_TREND_RULES = {
    "Index > EMA21 and EMA21 > SMA50 and Index > SMA200": (
        "Strong uptrend",
        1.00,
        1.20,
        "Index is above EMA21, EMA21 is above SMA50, and index is above SMA200.",
    ),
    "Index < EMA21 and EMA21 > SMA50 and Index > SMA200": (
        "Healthy pullback",
        0.75,
        0.90,
        "Index is pulling back below EMA21 while EMA21 remains above SMA50 and index stays above SMA200.",
    ),
    "Index > SMA200 and EMA21 < SMA50": (
        "Weakening trend",
        0.60,
        0.60,
        "Index is above SMA200, but EMA21 is below SMA50.",
    ),
    "Index < EMA21 and Index < SMA50 and Index > SMA200": (
        "Deeper correction above SMA200",
        0.50,
        0.50,
        "Index is below EMA21 and SMA50, but still above SMA200.",
    ),
    "Index < SMA200 and FTD is true": (
        "Below SMA200 with valid FTD or mini-FTD",
        0.40,
        0.40,
        "Index is below SMA200 but a valid FTD or mini-FTD exists.",
    ),
    "Index < SMA200 and FTD is false": (
        "Below SMA200 without FTD",
        0.20,
        0.20,
        "Index is below SMA200 with no valid FTD.",
    ),
}

VOLATILITY_RULES = {
    "Normal: ATR percentile < 50": (
        "Normal",
        1.00,
        1.20,
        "ATR percentile is normal, below 50.",
    ),
    "Mildly elevated: ATR percentile 50-75": (
        "Mildly elevated",
        0.85,
        1.00,
        "ATR percentile is mildly elevated, between 50 and 75.",
    ),
    "High: ATR percentile 75-90": (
        "High",
        0.65,
        0.70,
        "ATR percentile is high, between 75 and 90.",
    ),
    "Extreme: ATR percentile 90-95": (
        "Extreme",
        0.45,
        0.50,
        "ATR percentile is extreme, between 90 and 95.",
    ),
    "Panic: ATR percentile > 95": (
        "Panic",
        0.25,
        0.30,
        "ATR percentile is in panic territory, above 95.",
    ),
}

BASE_MODE_OPTIONS = list(BASE_MODE_RULES.keys())
MARKET_HEALTH_OPTIONS = list(MARKET_HEALTH_RULES.keys())
PT_FTD_OPTIONS = list(PT_FTD_RULES.keys())
MARKET_TREND_OPTIONS = list(MARKET_TREND_RULES.keys())
VOLATILITY_OPTIONS = list(VOLATILITY_RULES.keys())


@dataclass(frozen=True)
class FactorBreakdown:
    factor: str
    selected_state: str
    multiplier: float
    cap: float
    comment: str


@dataclass(frozen=True)
class ExposureScorecardInput:
    nav: float
    ema10: float
    ema20: float
    ema50: float
    ema10_rising: bool
    market_trend_condition: str
    market_health: str
    pt_ftd: str
    volatility_condition: str
    distribution_days: int
    personal_drawdown_pct: float
    base_mode: str = "Normal"
    stalling_days: int = 0
    bad_up_days: int = 0


@dataclass(frozen=True)
class ExposureScorecardOutput:
    raw_exposure_pct: float
    final_exposure_pct: int
    unrounded_final_exposure_pct: float
    exposure_band_label: str
    risk_regime: str
    performance_regime: str
    market_trend_regime: str
    market_health_regime: str
    pt_ftd_regime: str
    volatility_regime: str
    margin_allowed: bool
    active_limiting_cap: str
    biggest_reducer: str
    explanation: str
    breakdown: list[FactorBreakdown]


def _safe_float(value, fallback=0.0):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if numeric != numeric:
        return fallback
    return numeric


def _safe_int(value, fallback=0):
    return int(round(_safe_float(value, fallback)))


def _ratio_to_pct(value):
    return value * 100


def _round_down_to_nearest_5(value):
    return int(max(0, min(120, floor((value + 1e-9) / 5) * 5)))


def _performance_rule(nav, ema10, ema20, ema50, ema10_rising):
    peak = nav > ema10 > ema20 > ema50
    recovery = nav > ema10 and ema10_rising and ema20 < ema50
    matches = []
    if peak:
        return ("Peak performance", 1.00, 1.20, "NAV is above EMA10/20/50 in proper order.")
    if recovery:
        return ("Recovery", 0.40, 0.40, "NAV is reclaiming EMA10 while longer EMAs are still damaged.")
    if nav > ema20 and ema20 > ema50:
        matches.append(("Healthy", 0.75, 0.90, "NAV is above EMA20 and EMA20 is above EMA50."))
    if nav < ema10 and nav > ema20:
        matches.append(("Slow down", 0.50, 0.50, "NAV is below EMA10 but still above EMA20."))
    if nav < ema20 and ema20 > ema50:
        matches.append(("Caution", 0.35, 0.35, "NAV is below EMA20 while EMA20 remains above EMA50."))
    if nav < ema20 and ema20 < ema50:
        matches.append(("Stay low", 0.20, 0.20, "NAV is below EMA20 and EMA20 is below EMA50."))
    if matches:
        return min(matches, key=lambda item: item[2])
    return ("Caution", 0.35, 0.35, "Performance inputs are mixed, so defaulting to caution.")


def _distribution_day_cap(distribution_days, failed_ftd):
    if failed_ftd:
        return 0.30, "Failed FTD cap"
    if distribution_days >= 5:
        return 0.50, "Distribution days >= 5"
    if distribution_days >= 3:
        return 0.75, "Distribution days 3-4"
    return 1.20, "Distribution days 0-2"


def _drawdown_cap(drawdown_pct):
    if drawdown_pct < 2:
        return 1.20, "Drawdown < 2%"
    if drawdown_pct <= 5:
        return 0.80, "Drawdown 2-5%"
    if drawdown_pct <= 8:
        return 0.50, "Drawdown 5-8%"
    if drawdown_pct <= 10:
        return 0.30, "Drawdown 8-10%"
    return 0.20, "Drawdown > 10%"


def _band_label(final_pct):
    if final_pct <= 10:
        return "Mostly cash / review mistakes"
    if final_pct <= 25:
        return "Pilot only"
    if final_pct <= 40:
        return "Selective trading"
    if final_pct <= 60:
        return "Normal but cautious"
    if final_pct <= 80:
        return "Constructive exposure"
    if final_pct <= 100:
        return "Aggressive but no margin"
    return "Margin allowed only in ideal condition"


def _risk_regime(final_pct):
    if final_pct <= 25:
        return "Defensive"
    if final_pct <= 60:
        return "Cautious"
    if final_pct <= 100:
        return "Constructive / aggressive"
    return "Margin risk-on"


def _margin_allowed(inputs, performance_regime):
    return all(
        [
            performance_regime == "Peak performance",
            inputs.market_trend_condition == "Index > EMA21 and EMA21 > SMA50 and Index > SMA200",
            inputs.market_health == "Strong",
            inputs.volatility_condition
            in {
                "Normal: ATR percentile < 50",
                "Mildly elevated: ATR percentile 50-75",
            },
            inputs.distribution_days < 3,
            inputs.personal_drawdown_pct < 3,
            inputs.pt_ftd == "PT on / confirmed uptrend",
        ]
    )


def calculate_exposure_scorecard(inputs: ExposureScorecardInput) -> ExposureScorecardOutput:
    nav = _safe_float(inputs.nav)
    ema10 = _safe_float(inputs.ema10)
    ema20 = _safe_float(inputs.ema20)
    ema50 = _safe_float(inputs.ema50)
    distribution_days = max(0, _safe_int(inputs.distribution_days))
    drawdown = abs(_safe_float(inputs.personal_drawdown_pct))
    base_mode = inputs.base_mode if inputs.base_mode in BASE_MODE_RULES else "Normal"
    market_trend_condition = (
        inputs.market_trend_condition
        if inputs.market_trend_condition in MARKET_TREND_RULES
        else "Index < SMA200 and FTD is false"
    )
    market_health = inputs.market_health if inputs.market_health in MARKET_HEALTH_RULES else "Neutral"
    pt_ftd = inputs.pt_ftd if inputs.pt_ftd in PT_FTD_RULES else "Under pressure"
    volatility_condition = (
        inputs.volatility_condition
        if inputs.volatility_condition in VOLATILITY_RULES
        else "High: ATR percentile 75-90"
    )

    perf_state, perf_mult, perf_cap, perf_comment = _performance_rule(nav, ema10, ema20, ema50, inputs.ema10_rising)
    trend_state, trend_mult, trend_cap, trend_comment = MARKET_TREND_RULES[market_trend_condition]
    health_mult, health_cap, health_comment = MARKET_HEALTH_RULES[market_health]
    pt_mult, pt_cap, pt_comment = PT_FTD_RULES[pt_ftd]
    vol_state, vol_mult, vol_cap, vol_comment = VOLATILITY_RULES[volatility_condition]
    dd_cap, dd_comment = _distribution_day_cap(distribution_days, pt_ftd == "Failed FTD")
    drawdown_cap, drawdown_comment = _drawdown_cap(drawdown)
    base_max = BASE_MODE_RULES[base_mode]

    margin_allowed = _margin_allowed(
        ExposureScorecardInput(
            nav=nav,
            ema10=ema10,
            ema20=ema20,
            ema50=ema50,
            ema10_rising=inputs.ema10_rising,
            market_trend_condition=market_trend_condition,
            market_health=market_health,
            pt_ftd=pt_ftd,
            volatility_condition=volatility_condition,
            distribution_days=distribution_days,
            personal_drawdown_pct=drawdown,
            base_mode=base_mode,
            stalling_days=max(0, _safe_int(inputs.stalling_days)),
            bad_up_days=max(0, _safe_int(inputs.bad_up_days)),
        ),
        perf_state,
    )
    margin_gate_cap = 1.20 if margin_allowed else 1.00

    raw_ratio = base_max * perf_mult * trend_mult * health_mult * pt_mult * vol_mult
    caps = [
        ("Performance cap", perf_cap),
        ("Market trend cap", trend_cap),
        ("Market health cap", health_cap),
        ("PT/FTD cap", pt_cap),
        ("Volatility cap", vol_cap),
        ("Distribution day cap", dd_cap),
        ("Personal drawdown cap", drawdown_cap),
        ("Margin gate cap", margin_gate_cap),
    ]
    limiting_name, limiting_cap = min(caps, key=lambda item: item[1])
    unrounded_final_pct = _ratio_to_pct(min(raw_ratio, limiting_cap))
    final_pct = _round_down_to_nearest_5(unrounded_final_pct)

    reductions = [(name, cap) for name, cap in caps if cap < raw_ratio]
    if reductions:
        biggest_reducer = min(reductions, key=lambda item: item[1])[0]
    else:
        multiplier_reducers = [
            ("Performance multiplier", perf_mult),
            ("Market trend multiplier", trend_mult),
            ("Market health multiplier", health_mult),
            ("PT/FTD multiplier", pt_mult),
            ("Volatility multiplier", vol_mult),
        ]
        biggest_reducer = min(multiplier_reducers, key=lambda item: item[1])[0]

    breakdown = [
        FactorBreakdown("Base mode", base_mode, base_max, base_max, f"Base max exposure is {_ratio_to_pct(base_max):.0f}%."),
        FactorBreakdown("Performance", perf_state, perf_mult, perf_cap, perf_comment),
        FactorBreakdown("Market trend", trend_state, trend_mult, trend_cap, f"{market_trend_condition}. {trend_comment}"),
        FactorBreakdown("Market health", market_health, health_mult, health_cap, health_comment),
        FactorBreakdown("PT / FTD", pt_ftd, pt_mult, pt_cap, pt_comment),
        FactorBreakdown("Volatility", vol_state, vol_mult, vol_cap, vol_comment),
        FactorBreakdown("Distribution days", dd_comment, 1.00, dd_cap, f"{distribution_days} distribution days in the last 25 trading days."),
        FactorBreakdown("Personal drawdown", drawdown_comment, 1.00, drawdown_cap, f"Personal drawdown is {drawdown:.1f}%."),
        FactorBreakdown(
            "Margin gate",
            "Allowed" if margin_allowed else "Not allowed",
            1.00,
            margin_gate_cap,
            "Exposure above 100% is allowed." if margin_allowed else "Exposure is capped at 100%.",
        ),
    ]

    explanation = (
        f"Raw exposure is {_ratio_to_pct(raw_ratio):.1f}%. "
        f"The active limiting cap is {limiting_name} at {_ratio_to_pct(limiting_cap):.0f}%. "
        f"After rounding down to the nearest 5%, recommended exposure is {final_pct}%. "
        f"Margin is {'allowed' if margin_allowed else 'not allowed'}."
    )

    return ExposureScorecardOutput(
        raw_exposure_pct=_ratio_to_pct(raw_ratio),
        final_exposure_pct=final_pct,
        unrounded_final_exposure_pct=unrounded_final_pct,
        exposure_band_label=_band_label(final_pct),
        risk_regime=_risk_regime(final_pct),
        performance_regime=perf_state,
        market_trend_regime=trend_state,
        market_health_regime=market_health,
        pt_ftd_regime=pt_ftd,
        volatility_regime=vol_state,
        margin_allowed=margin_allowed,
        active_limiting_cap=limiting_name,
        biggest_reducer=biggest_reducer,
        explanation=explanation,
        breakdown=breakdown,
    )
