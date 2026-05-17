import io
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from exposure_scorecard import (
    BASE_MODE_OPTIONS,
    MARKET_HEALTH_OPTIONS,
    MARKET_TREND_OPTIONS,
    MARKET_TREND_RULES,
    PT_FTD_OPTIONS,
    VOLATILITY_OPTIONS,
    ExposureScorecardInput,
    calculate_exposure_scorecard,
)
from portfolio_risk import (
    PORTFOLIO_RISK_DISPLAY_COLUMNS,
    PORTFOLIO_RISK_INPUT_COLUMNS,
    calculate_portfolio_risk,
    load_latest_portfolio_risk_snapshot,
    load_portfolio_risk_history,
    portfolio_risk_payloads,
    prepare_portfolio_risk_input,
    save_portfolio_risk_snapshot,
)

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from supabase import create_client
except ImportError:
    create_client = None


RS_COLUMNS = [
    "Performance % 1 week",
    "Performance % 1 month",
    "Performance % 3 months",
    "Performance % 6 months",
    "Performance % 1 year",
]

REQUIRED_SCREENING_COLUMNS = [
    "Symbol",
    "Market capitalization",
    "Price",
    "Average Volume 60 days",
] + RS_COLUMNS

SCREENING_CANONICAL_COLUMNS = REQUIRED_SCREENING_COLUMNS + [
    "Price Change % 1 day",
    "Performance % Year to date",
    "Exponential Moving Average (10) 1 day",
    "Exponential Moving Average (20) 1 day",
    "Exponential Moving Average (50) 1 day",
    "Exponential Moving Average (200) 1 day",
    "High 52 weeks",
    "Low 52 weeks",
    "Volume 1 day",
    "Price * Volume (Turnover) 1 day",
    "Average True Range % 1 day",
    "Average True Range % 14 days",
    "Average True Range % (14) 1 day",
    "ATR %",
]

SECTOR_CANDIDATES = ["Sector", "sector", "Industry Group", "Industry", "Group", "Category"]

QUALITY_ORDER = [
    "Elite Momentum",
    "Strong Momentum",
    "Emerging Momentum",
    "Pullback Leader",
    "Short-term Spike",
    "Stale Leader",
    "Mixed / Neutral",
]

ATR_RANGE_ORDER = [
    "Slow and Pokey",
    "Sweet Spot",
    "Hot",
    "Super high octane",
    "Unknown",
]

MARKET_DAY_TYPES = [
    "Distribution Day",
    "Bad Up Day",
    "NH Low Volume",
    "Follow Through Day",
    "Day 1",
    "Power Up Day",
    "Up on Lower Volume",
    "Down on Lower Volume",
    "Neutral",
    "First Day",
]

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
JOURNAL_DB_PATH = DATA_DIR / "trading_journal.sqlite3"

JOURNAL_DISPLAY_COLUMNS = [
    "ID",
    "Open Date",
    "Close Date",
    "Symbol",
    "Side",
    "Sector",
    "Setup",
    "Market Regime",
    "Entry Price",
    "Stop Loss",
    "Exit Price",
    "Shares",
    "Fees",
    "Risk Amount",
    "Net P/L",
    "R Multiple",
    "Mistake Tag",
    "Notes",
    "Screenshot URL",
    "Status",
    "Created At",
    "Updated At",
]

TRADE_PLAN_DISPLAY_COLUMNS = [
    "ID",
    "Plan Date",
    "Symbol",
    "Side",
    "Sector",
    "Setup",
    "Market Regime",
    "Current Price",
    "Entry Trigger",
    "Stop Loss",
    "Target 1",
    "Target 2",
    "Alert Price",
    "Planned Risk",
    "Actual Action",
    "Position Notes",
    "Status",
    "Linked Trade ID",
    "Created At",
    "Updated At",
]

TRADE_PLAN_STATUSES = ["Watching", "Alert Set", "Triggered", "Open", "Skipped", "Expired", "Closed"]

ACTUAL_ACTION_OPTIONS = [
    "Not Yet",
    "Do as Plan",
    "Chasing",
    "Missed Trade",
    "Early Entry",
    "Late Entry",
    "No Trigger",
    "Skipped by Rule",
    "Invalidated Before Entry",
    "Position Size Error",
    "Moved Stop",
    "Took Profit Early",
    "Other",
]

PERFORMANCE_EXPOSURE = {
    "Peak Performance": 100,
    "Slow Down": 80,
    "Caution": 60,
    "Stay Low": 20,
    "Recovery": 40,
}

MA200_EXPOSURE = {
    ">SMA200d": 100,
    "<SMA200d": 80,
}

TREND_EXPOSURE = {
    ">=EMA21d>SMA50d": 100,
    "<EMA21d>SMA50d": 75,
    ">=EMA21d<SMA50d": 50,
    "<EMA21d<SMA50d": 25,
}

PT_EXPOSURE = {
    "PT on": 120,
    "PT caution": 100,
    "PT off": 80,
}

AUTO_MARKET_SYMBOLS = {
    "S&P 500": "^GSPC",
    "Nasdaq Composite": "^IXIC",
    "Russell 2000": "^RUT",
}

# Keep personal Google Form/Sheet links in .streamlit/secrets.toml before uploading to GitHub.
DEFAULT_PORTFOLIO_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfo-hKc1kHvRizS9rDd4BaRfEGTDJY3dJFHKbU4xXFYBlb1CA/viewform"
DEFAULT_PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_3vrNiIs8WKsWLDgzJLQoLImQzErXQ8Nz4MvGbH8qMY/edit?usp=sharing"
DEFAULT_PORTFOLIO_SHEET_ID = "1_3vrNiIs8WKsWLDgzJLQoLImQzErXQ8Nz4MvGbH8qMY"
DEFAULT_PORTFOLIO_USECOLS = None
DEFAULT_PORTFOLIO_POSITION_MAP = {
    "date": 1,  # B
    "total_market_value": 7,  # H
    "cash": 8,  # I
    "unrealized_amount": 9,  # J
    "us_market_value": 10,  # K
    "non_us_market_value": 11,  # L
    "nav": 22,  # W
}

PORTFOLIO_COLUMN_CANDIDATES = {
    "date": ["Date", "Timestamp", "วันที่", "Time", "Record Date"],
    "market_value": ["US Market Value (USD)", "US Market Value", "Market Value", "Holding Value"],
    "equity": [
        "US Total Equity (USD)",
        "Total Equity",
        "Equity",
        "Portfolio Value",
        "Portfolio Balance",
        "Net Asset Value",
    ],
    "exposure": ["US exposure %", "Position Exposure %", "Exposure %", "Current Exposure", "Invested %"],
    "us_exposure_value": ["US Exposure", "US Exposure Value", "US Position Value"],
    "other_exposure": ["Non-US exposure %", "Non-US Exposure %", "ETF/Other exposure %", "ETF/Other Exposure %"],
    "other_exposure_value": [
        "Non-US Exposure",
        "Non-US Exposure Value",
        "Non-US Position Value",
        "ETF/Other exposure",
        "ETF/Other Exposure Value",
        "ETF/Other Position Value",
    ],
    "unrealized": ["Unrealized gain % (US)", "Unrealized Gain", "Unrealized P/L", "Unrealized PL", "Unrealized", "Open P/L"],
    "holding_us": ["Holding US", "US Holding", "US Stock Value"],
    "holding_other": ["Holding Non-US", "Holding Other", "Non-US Holding", "ETF/Other Holding"],
    "cash": ["Cash (USD)", "Cash", "Cash Balance"],
    "nav": ["US NAV", "NAV"],
}


def clean_numeric(series: pd.Series) -> pd.Series:
    """Clean numeric-like strings such as 1,234 / 12.5% / USD10,000 / (123)."""
    return pd.to_numeric(
        series.astype(str)
        .str.strip()
        .str.replace(r"\(([^)]+)\)", r"-\1", regex=True)
        .str.replace(r"[,%฿$]", "", regex=True)
        .str.replace(",", "", regex=False)
        .replace({"": pd.NA, "-": pd.NA, "nan": pd.NA, "None": pd.NA}),
        errors="coerce",
    )


def normalize_screening_column_name(name):
    return (
        str(name)
        .strip()
        .lower()
        .replace("×", "*")
        .replace("  ", " ")
    )


def standardize_screening_columns(df):
    canonical_lookup = {normalize_screening_column_name(col): col for col in SCREENING_CANONICAL_COLUMNS}
    rename_map = {}
    for col in df.columns:
        canonical_col = canonical_lookup.get(normalize_screening_column_name(col))
        if canonical_col is not None and canonical_col not in df.columns:
            rename_map[col] = canonical_col
    return df.rename(columns=rename_map)


@st.cache_data(show_spinner=False)
def load_csv_from_bytes(file_bytes):
    return pd.read_csv(io.BytesIO(file_bytes))


def load_uploaded_csv(uploaded_file):
    if uploaded_file is None:
        return None
    return load_csv_from_bytes(uploaded_file.getvalue())


def export_filename_from_upload(uploaded_file, prefix="US"):
    if uploaded_file is not None:
        date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", uploaded_file.name)
        if date_match:
            year, month, day = date_match.groups()
            return f"{prefix} {year[2:]}{month}{day}.txt"
    return f"{prefix} {datetime.now().strftime('%y%m%d')}.txt"


def get_mcap_category(mcap):
    if pd.isna(mcap):
        return "Unknown"
    if mcap < 50_000_000:
        return "1. Nano"
    if mcap < 300_000_000:
        return "2. Micro"
    if mcap < 2_000_000_000:
        return "3. Small"
    if mcap < 10_000_000_000:
        return "4. Mid"
    if mcap < 200_000_000_000:
        return "5. Large"
    return "6. Mega"


def classify_momentum_quality(row):
    rs = row["RS Composite Rating"]
    r1w = row["Performance % 1 week Rank"]
    r1m = row["Performance % 1 month Rank"]
    r3m = row["Performance % 3 months Rank"]
    r6m = row["Performance % 6 months Rank"]
    r1y = row["Performance % 1 year Rank"]
    accel = row["Acceleration Score"]
    consistency = row["Momentum Consistency"]

    if rs >= 90 and r1m >= 80 and r3m >= 80 and consistency >= 3:
        return "Elite Momentum"
    if rs >= 80 and r1m >= 70 and r3m >= 70 and consistency >= 2:
        return "Strong Momentum"
    if r1m >= 75 and accel >= 10:
        return "Emerging Momentum"
    if r1w >= 90 and r3m < 50:
        return "Short-term Spike"
    if r1y >= 85 and r1m < 50 and r3m < 60:
        return "Stale Leader"
    if r6m >= 75 and accel < -10:
        return "Pullback Leader"
    return "Mixed / Neutral"


def classify_setup_location(row):
    rs = row.get("RS Composite Rating", pd.NA)
    dist_high = row.get("Distance from 52W High %", pd.NA)
    dist_ema20 = row.get("Distance from EMA20 %", pd.NA)
    dist_ema50 = row.get("Distance from EMA50 %", pd.NA)
    accel = row.get("Acceleration Score", pd.NA)

    if pd.notna(dist_ema20) and dist_ema20 > 20:
        return "Extended above EMA20"
    if pd.notna(dist_ema50) and dist_ema50 > 35:
        return "Extended above EMA50"
    if pd.notna(dist_high) and dist_high < -35:
        return "Deep below 52W high"
    if pd.notna(dist_ema20) and -5 <= dist_ema20 <= 5 and rs >= 80:
        return "Pullback near EMA20"
    if pd.notna(dist_ema50) and -7 <= dist_ema50 <= 7 and rs >= 80:
        return "Pullback near EMA50"
    if pd.notna(dist_high) and -10 <= dist_high <= 0:
        return "Near 52W high"
    if pd.notna(accel) and accel >= 10:
        return "Accelerating"
    return "Needs chart review"


def classify_screening_priority(row):
    rs = row.get("RS Composite Rating", pd.NA)
    turnover = row.get("Avg 60D Turnover (USD)", pd.NA)
    quality = row.get("Momentum Quality", "")
    location = row.get("Setup Location", "")
    dist_high = row.get("Distance from 52W High %", pd.NA)
    enough_liquidity = pd.notna(turnover) and turnover >= 20_000_000
    not_too_deep = pd.isna(dist_high) or dist_high >= -30
    not_extended = "Extended" not in str(location)

    if rs >= 90 and enough_liquidity and quality in ["Elite Momentum", "Strong Momentum"] and not_too_deep and not_extended:
        return "A - Prime Watch"
    if rs >= 80 and enough_liquidity and quality in ["Emerging Momentum", "Pullback Leader", "Strong Momentum"]:
        return "B - Watch"
    if rs >= 80 and enough_liquidity:
        return "C - RS 80+"
    return "D - Lower Priority"


def classify_atr_range(atr):
    if pd.isna(atr):
        return "Unknown"
    if atr < 2.5:
        return "Slow and Pokey"
    if atr <= 4:
        return "Sweet Spot"
    if atr <= 8:
        return "Hot"
    return "Super high octane"


def get_rs_color(val):
    if pd.isna(val):
        return ""
    if val >= 95:
        return "background-color: #00FF00; color: black;"
    if val >= 90:
        return "background-color: #32CD32; color: black;"
    if val >= 85:
        return "background-color: #228B22; color: white;"
    if val >= 80:
        return "background-color: #006400; color: white;"
    if val >= 20:
        return "background-color: #FFFF00; color: black;"
    return "background-color: #FF4136; color: white;"


def prepare_screening_data(raw_df):
    df = raw_df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    df = standardize_screening_columns(df)

    missing_cols = [col for col in REQUIRED_SCREENING_COLUMNS if col not in df.columns]
    if missing_cols:
        return None, missing_cols, None, []

    sector_col = next((col for col in SECTOR_CANDIDATES if col in df.columns), None)
    if sector_col is not None:
        df[sector_col] = df[sector_col].fillna("Unknown Sector").astype(str).str.strip()

    optional_numeric_cols = [
        "Price Change % 1 day",
        "Performance % Year to date",
        "Exponential Moving Average (10) 1 day",
        "Exponential Moving Average (20) 1 day",
        "Exponential Moving Average (50) 1 day",
        "Exponential Moving Average (200) 1 day",
        "High 52 weeks",
        "Low 52 weeks",
        "Volume 1 day",
        "Price * Volume (Turnover) 1 day",
        "Average True Range % 1 day",
        "Average True Range % 14 days",
        "Average True Range % (14) 1 day",
        "ATR %",
    ]
    numeric_cols = ["Market capitalization", "Price", "Average Volume 60 days"] + RS_COLUMNS
    numeric_cols += [col for col in optional_numeric_cols if col in df.columns]
    for col in numeric_cols:
        df[col] = clean_numeric(df[col])

    df["Market Cap Size"] = df["Market capitalization"].apply(get_mcap_category)
    df["Avg 60D Turnover (USD)"] = df["Price"] * df["Average Volume 60 days"]

    rank_columns = []
    for col in RS_COLUMNS:
        rank_col_name = f"{col} Rank"
        df[rank_col_name] = df[col].rank(pct=True, na_option="bottom") * 100
        rank_columns.append(rank_col_name)

    df["Raw RS Score"] = (
        (2 * df["Performance % 3 months"])
        + df["Performance % 6 months"]
        + df["Performance % 1 year"]
    )
    df["RS Composite Rating"] = df["Raw RS Score"].rank(pct=True, na_option="bottom") * 100

    df["RS Composite Raw v2"] = (
        0.10 * df["Performance % 1 week Rank"]
        + 0.25 * df["Performance % 1 month Rank"]
        + 0.35 * df["Performance % 3 months Rank"]
        + 0.20 * df["Performance % 6 months Rank"]
        + 0.10 * df["Performance % 1 year Rank"]
    )
    df["RS Composite Rating v2"] = df["RS Composite Raw v2"].rank(pct=True, na_option="bottom") * 100

    df["Acceleration Score"] = df["Performance % 1 month Rank"] - df["Performance % 3 months Rank"]
    df["Momentum Consistency"] = (
        (df["Performance % 1 month Rank"] >= 70).astype(int)
        + (df["Performance % 3 months Rank"] >= 70).astype(int)
        + (df["Performance % 6 months Rank"] >= 70).astype(int)
    )
    df["Momentum Quality"] = df.apply(classify_momentum_quality, axis=1)

    if "High 52 weeks" in df.columns:
        df["Distance from 52W High %"] = ((df["Price"] / df["High 52 weeks"]) - 1) * 100
    if "Low 52 weeks" in df.columns:
        df["Distance from 52W Low %"] = ((df["Price"] / df["Low 52 weeks"]) - 1) * 100

    ema_map = {
        "Exponential Moving Average (10) 1 day": "Distance from EMA10 %",
        "Exponential Moving Average (20) 1 day": "Distance from EMA20 %",
        "Exponential Moving Average (50) 1 day": "Distance from EMA50 %",
        "Exponential Moving Average (200) 1 day": "Distance from EMA200 %",
    }
    for source_col, target_col in ema_map.items():
        if source_col in df.columns:
            df[target_col] = ((df["Price"] / df[source_col]) - 1) * 100

    if "Volume 1 day" in df.columns:
        df["Volume vs 60D Avg"] = df["Volume 1 day"] / df["Average Volume 60 days"]
    if "Price * Volume (Turnover) 1 day" in df.columns:
        df["Turnover 1D vs 60D Avg"] = df["Price * Volume (Turnover) 1 day"] / df["Avg 60D Turnover (USD)"]

    atr_col = next(
        (
            col
            for col in [
                "ATR %",
                "Average True Range % (14) 1 day",
                "Average True Range % 1 day",
                "Average True Range % 14 days",
            ]
            if col in df.columns
        ),
        None,
    )
    if atr_col is not None and atr_col != "ATR %":
        df["ATR %"] = df[atr_col]
    if "ATR %" in df.columns:
        df["ATR Range"] = df["ATR %"].apply(classify_atr_range)

    df["Setup Location"] = df.apply(classify_setup_location, axis=1)
    df["Screening Priority"] = df.apply(classify_screening_priority, axis=1)

    return df, [], sector_col, rank_columns


@st.cache_data(show_spinner=False)
def prepare_screening_data_from_bytes(file_bytes):
    return prepare_screening_data(load_csv_from_bytes(file_bytes))


def symbols_to_tv(symbols, exchanges=None):
    symbol_values = list(symbols)
    exchange_values = list(exchanges) if exchanges is not None else [None] * len(symbol_values)
    clean_symbols = []
    for symbol, exchange in zip(symbol_values, exchange_values):
        if pd.isna(symbol):
            continue
        text = str(symbol).strip()
        if not text:
            continue
        exchange_text = "" if pd.isna(exchange) else str(exchange).strip().upper()
        tv_symbol = f"{exchange_text}:{text}" if exchange_text else text
        if tv_symbol not in clean_symbols:
            clean_symbols.append(tv_symbol)
    return ",".join(clean_symbols)


def generate_bucket_watchlist(dataframe, score_col="RS Composite Rating"):
    lines = []
    buckets = [
        ("RS 95-100", 95, 100.1),
        ("RS 90-94.99", 90, 95),
        ("RS 85-89.99", 85, 90),
        ("RS 80-84.99", 80, 85),
    ]
    for name, min_val, max_val in buckets:
        bucket_df = dataframe[(dataframe[score_col] >= min_val) & (dataframe[score_col] < max_val)]
        if not bucket_df.empty:
            lines.append(f"### {name}")
            exchanges = bucket_df["Exchange"].tolist() if "Exchange" in bucket_df.columns else None
            lines.append(symbols_to_tv(bucket_df["Symbol"].tolist(), exchanges))
            lines.append("")
    return "\n".join(lines)


def build_trade_plan_export(dataframe, sector_col):
    cols = ["Symbol"]
    if "Exchange" in dataframe.columns:
        cols.append("Exchange")
    if sector_col is not None:
        cols.append(sector_col)
    for col in [
        "Price",
        "RS Composite Rating",
        "RS Composite Rating v2",
        "Momentum Quality",
        "Setup Location",
        "Screening Priority",
        "Avg 60D Turnover (USD)",
        "Distance from 52W High %",
        "Distance from EMA20 %",
        "ATR %",
        "ATR Range",
    ]:
        if col in dataframe.columns:
            cols.append(col)
    plan_df = dataframe.loc[:, cols].copy()
    for col in ["Entry Trigger", "Stop Loss", "Target 1", "Target 2", "Alert Price", "Actual Action", "Position Notes"]:
        plan_df[col] = ""
    return plan_df.to_csv(index=False)


def build_sector_summary(dataframe, sector_col):
    if sector_col is None or dataframe.empty:
        return pd.DataFrame()

    summary = (
        dataframe.groupby(sector_col)
        .agg(
            Sector_RS_Average=("RS Composite Rating", "mean"),
            Sector_RS_Average_v2=("RS Composite Rating v2", "mean"),
            RS_80_Stocks=("RS Composite Rating", lambda s: (s >= 80).sum()),
            RS_90_Stocks=("RS Composite Rating", lambda s: (s >= 90).sum()),
            Stock_Count=("Symbol", "count"),
            Median_Turnover=("Avg 60D Turnover (USD)", "median"),
            Elite_Strong_Stocks=("Momentum Quality", lambda s: s.isin(["Elite Momentum", "Strong Momentum"]).sum()),
        )
        .reset_index()
    )
    summary["RS_80_Pct"] = (summary["RS_80_Stocks"] / summary["Stock_Count"]) * 100

    summary["Leadership Score"] = (
        0.35 * summary["Sector_RS_Average"].rank(pct=True)
        + 0.25 * summary["RS_80_Pct"].rank(pct=True)
        + 0.20 * summary["RS_90_Stocks"].rank(pct=True)
        + 0.20 * summary["Elite_Strong_Stocks"].rank(pct=True)
    ) * 100

    return summary.sort_values(
        by=["Leadership Score", "Sector_RS_Average", "RS_90_Stocks", "Stock_Count"],
        ascending=[False, False, False, False],
    )


def classify_market_day(row):
    change = row.get("Index Change %", pd.NA)
    volume_change = row.get("Volume Change %", pd.NA)
    close = row.get("Close", pd.NA)
    high_20 = row.get("20D High", pd.NA)

    if pd.isna(change) or pd.isna(volume_change):
        return "First Day"
    if change <= -0.2 and volume_change > 0:
        return "Distribution Day"
    if change > 1.2 and volume_change > 0:
        return "Power Up Day"
    if change > 0 and volume_change > 0 and change < 0.5:
        return "Bad Up Day"
    if pd.notna(close) and pd.notna(high_20) and close >= high_20 * 0.995 and volume_change < 0:
        return "NH Low Volume"
    if change > 0 and volume_change < 0:
        return "Up on Lower Volume"
    if change < 0 and volume_change < 0:
        return "Down on Lower Volume"
    return "Neutral"


def prepare_market_data(raw_df):
    df = raw_df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    required_cols = ["Date", "Index", "Close", "Volume"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        return None, missing_cols

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume", "Close MA10", "Close MA21", "Close MA50", "Close MA200", "Volume MA50"]:
        if col in df.columns:
            df[col] = clean_numeric(df[col])

    df = df.dropna(subset=["Date", "Index", "Close"]).sort_values(["Index", "Date"]).copy()
    grouped = df.groupby("Index", group_keys=False)
    df["Previous Close"] = grouped["Close"].shift(1)
    df["Previous Volume"] = grouped["Volume"].shift(1)
    df["Index Change %"] = ((df["Close"] / df["Previous Close"]) - 1) * 100
    df["Volume Change %"] = ((df["Volume"] / df["Previous Volume"]) - 1) * 100

    for window in [10, 21, 50, 200]:
        col = f"Close MA{window}"
        if col not in df.columns:
            min_periods = min(5, window)
            df[col] = grouped["Close"].transform(lambda s, w=window, m=min_periods: s.rolling(w, min_periods=m).mean())

    if "Volume MA50" not in df.columns:
        df["Volume MA50"] = grouped["Volume"].transform(lambda s: s.rolling(50, min_periods=5).mean())

    df["Volume vs 50D Avg"] = df["Volume"] / df["Volume MA50"]
    df["20D High"] = grouped["Close"].transform(lambda s: s.rolling(20, min_periods=5).max())
    df["Above MA50"] = df["Close"] > df["Close MA50"]
    df["Above MA200"] = df["Close"] > df["Close MA200"]

    if "Day Type" not in df.columns:
        df["Day Type"] = ""
    df["Day Type"] = df["Day Type"].fillna("").astype(str).str.strip()
    df["Computed Day Type"] = df.apply(classify_market_day, axis=1)
    df["Action Tag"] = df["Day Type"].where(df["Day Type"] != "", df["Computed Day Type"])

    return df, []


def latest_rows_by_index(market_df):
    return (
        market_df.sort_values("Date")
        .groupby("Index", as_index=False)
        .tail(1)
        .sort_values("Index")
    )


def get_equity_status(journal_metrics):
    if not journal_metrics:
        return "No journal data"
    return journal_metrics.get("equity_status", "No journal data")


@st.cache_data(ttl=1800)
def fetch_yfinance_chart(symbol, period="1y", interval="1d"):
    if yf is None:
        raise ImportError("yfinance is not installed")

    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise ValueError(f"No yfinance data for {symbol}")

    if isinstance(data.columns, pd.MultiIndex):
        data = data.copy()
        data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]

    data = data.reset_index()
    date_col = "Date" if "Date" in data.columns else data.columns[0]
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        raise ValueError(f"yfinance result missing columns: {', '.join(missing_cols)}")

    df = data[[date_col] + required_cols].rename(columns={date_col: "Date"}).copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    df = df.dropna(subset=["Date", "Close", "Volume"]).copy()
    if df.empty:
        raise ValueError(f"No usable yfinance OHLCV data for {symbol}")
    return df


@st.cache_data(ttl=1800)
def fetch_yahoo_chart(symbol, period="1y", interval="1d"):
    encoded_symbol = quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?range={period}&interval={interval}&events=history"
    )
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise ValueError(error.get("description", f"Yahoo Finance error for {symbol}"))

    results = chart.get("result") or []
    if not results:
        raise ValueError(f"No chart result for {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
    if not timestamps or not quote_data:
        raise ValueError(f"No historical data for {symbol}")

    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(timestamps, unit="s").date,
            "Open": quote_data.get("open"),
            "High": quote_data.get("high"),
            "Low": quote_data.get("low"),
            "Close": quote_data.get("close"),
            "Volume": quote_data.get("volume"),
        }
    )
    df = df.dropna(subset=["Date", "Close", "Volume"]).copy()
    return df


def parse_symbol_map(text):
    symbol_map = {}
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            name, symbol = stripped.split("=", 1)
        elif "," in stripped:
            name, symbol = stripped.split(",", 1)
        else:
            continue
        name = name.strip()
        symbol = symbol.strip()
        if name and symbol:
            symbol_map[name] = symbol
    return symbol_map


def fetch_auto_market_data(symbol_map, period):
    frames = []
    errors = []
    for index_name, symbol in symbol_map.items():
        frame = None
        source = None
        fetch_errors = []
        fetchers = []
        if yf is not None:
            fetchers.append(("yfinance", fetch_yfinance_chart))
        fetchers.append(("direct Yahoo", fetch_yahoo_chart))

        for source_name, fetcher in fetchers:
            try:
                frame = fetcher(symbol, period=period)
                source = source_name
                break
            except (HTTPError, URLError, TimeoutError, ValueError, ImportError, json.JSONDecodeError) as exc:
                fetch_errors.append(f"{source_name}: {exc}")

        if frame is not None:
            frame["Index"] = index_name
            frame["Source Symbol"] = symbol
            frame["Data Source"] = source
            frames.append(frame)
        else:
            errors.append(f"{index_name} ({symbol}): {'; '.join(fetch_errors)}")
    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames, ignore_index=True), errors


def derive_exposure(regime, equity_status):
    equity_good = "Above" in equity_status
    equity_weak = "Below" in equity_status or "Drawdown" in equity_status

    if regime == "Confirmed Uptrend" and equity_good:
        return "Normal to aggressive"
    if regime == "Confirmed Uptrend":
        return "Normal, but wait for clean setups"
    if regime == "Uptrend Under Pressure" and equity_good:
        return "Moderate"
    if regime == "Uptrend Under Pressure":
        return "Light to moderate"
    if regime == "Rally Attempt":
        return "Pilot positions only"
    if equity_weak:
        return "Very defensive"
    return "Defensive / cash heavy"


def build_market_regime(market_df, equity_status):
    latest = latest_rows_by_index(market_df)
    latest_names = latest["Index"].astype(str).tolist()
    primary_name = "S&P 500" if "S&P 500" in latest_names else latest.iloc[0]["Index"]
    primary = market_df[market_df["Index"].astype(str) == str(primary_name)].sort_values("Date")
    recent25 = primary.tail(25)
    recent10 = primary.tail(10)
    latest_primary = primary.tail(1).iloc[0]

    distribution_count = int(recent25["Action Tag"].str.contains("Distribution", case=False, na=False).sum())
    bad_up_count = int(recent25["Action Tag"].str.contains("Bad Up", case=False, na=False).sum())
    ftd_recent = bool(recent10["Action Tag"].str.contains("Follow Through", case=False, na=False).any())

    score = 0
    if bool(latest_primary.get("Above MA50", False)):
        score += 2
    else:
        score -= 2
    if bool(latest_primary.get("Above MA200", False)):
        score += 1
    else:
        score -= 1
    if latest_primary.get("Index Change %", 0) > 0:
        score += 1
    if latest_primary.get("Volume vs 50D Avg", 0) >= 1.2 and latest_primary.get("Index Change %", 0) > 0:
        score += 1
    if ftd_recent:
        score += 2
    if distribution_count >= 4:
        score -= 3
    elif distribution_count >= 2:
        score -= 1
    if "Distribution" in str(latest_primary.get("Action Tag", "")):
        score -= 1
    if "Below" in equity_status:
        score -= 1
    if "Drawdown" in equity_status:
        score -= 1
    if "Above" in equity_status:
        score += 1

    if score >= 4:
        regime = "Confirmed Uptrend"
    elif score >= 2:
        regime = "Uptrend Under Pressure"
    elif score >= 0:
        regime = "Rally Attempt"
    else:
        regime = "Correction"

    return {
        "primary_index": primary_name,
        "regime": regime,
        "score": score,
        "exposure": derive_exposure(regime, equity_status),
        "distribution_count": distribution_count,
        "bad_up_count": bad_up_count,
        "ftd_recent": ftd_recent,
        "latest_primary": latest_primary,
        "latest_rows": latest,
    }


def first_existing_col(columns, candidates):
    return next((col for col in candidates if col in columns), None)


def init_journal_db(db_path=JOURNAL_DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                open_date TEXT,
                close_date TEXT,
                symbol TEXT NOT NULL,
                side TEXT,
                sector TEXT,
                setup TEXT,
                market_regime TEXT,
                entry_price REAL,
                stop_loss REAL,
                exit_price REAL,
                shares REAL,
                fees REAL,
                risk_amount REAL,
                net_pl REAL,
                r_multiple REAL,
                mistake_tag TEXT,
                notes TEXT,
                screenshot_url TEXT,
                status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_date TEXT,
                symbol TEXT NOT NULL,
                side TEXT,
                sector TEXT,
                setup TEXT,
                market_regime TEXT,
                current_price REAL,
                entry_trigger REAL,
                stop_loss REAL,
                target_1 REAL,
                target_2 REAL,
                alert_price REAL,
                planned_risk REAL,
                actual_action TEXT,
                position_notes TEXT,
                status TEXT,
                linked_trade_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        trade_plan_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(trade_plans)").fetchall()
        }
        if "actual_action" not in trade_plan_columns:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN actual_action TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pretrade_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                holding_us REAL,
                holding_other REAL,
                cash REAL,
                total_equity REAL,
                expected_exposure REAL,
                current_exposure REAL,
                today_plan TEXT,
                risk_per_trade REAL,
                stop_loss_pct REAL,
                position_cost REAL,
                performance_condition TEXT,
                ma200_condition TEXT,
                trend_condition TEXT,
                pt_condition TEXT,
                distribution_days INTEGER,
                scorecard_exposure REAL,
                capped_exposure REAL,
                personal_drawdown_pct REAL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        pretrade_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pretrade_snapshots)").fetchall()
        }
        if "total_equity" not in pretrade_columns:
            conn.execute("ALTER TABLE pretrade_snapshots ADD COLUMN total_equity REAL")
        if "personal_drawdown_pct" not in pretrade_columns:
            conn.execute("ALTER TABLE pretrade_snapshots ADD COLUMN personal_drawdown_pct REAL")
        conn.commit()


def normalize_blank(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def normalize_date_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def normalize_float_value(value):
    if value is None or value == "":
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def save_trade_to_db(trade, db_path=JOURNAL_DB_PATH, trade_id=None):
    init_journal_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    fields = [
        "open_date",
        "close_date",
        "symbol",
        "side",
        "sector",
        "setup",
        "market_regime",
        "entry_price",
        "stop_loss",
        "exit_price",
        "shares",
        "fees",
        "risk_amount",
        "net_pl",
        "r_multiple",
        "mistake_tag",
        "notes",
        "screenshot_url",
        "status",
    ]
    payload = {field: normalize_blank(trade.get(field)) for field in fields}
    payload["updated_at"] = now

    with sqlite3.connect(db_path) as conn:
        if trade_id:
            assignments = ", ".join([f"{field} = ?" for field in fields] + ["updated_at = ?"])
            values = [payload[field] for field in fields] + [payload["updated_at"], trade_id]
            conn.execute(f"UPDATE trades SET {assignments} WHERE id = ?", values)
            saved_trade_id = trade_id
        else:
            payload["created_at"] = now
            columns = fields + ["created_at", "updated_at"]
            placeholders = ", ".join(["?"] * len(columns))
            cursor = conn.execute(
                f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
                [payload[col] for col in columns],
            )
            saved_trade_id = cursor.lastrowid
        conn.commit()
    return saved_trade_id


def update_trade_close_in_db(trade_id, updates, db_path=JOURNAL_DB_PATH):
    init_journal_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    allowed_fields = [
        "close_date",
        "exit_price",
        "fees",
        "risk_amount",
        "net_pl",
        "r_multiple",
        "mistake_tag",
        "notes",
        "screenshot_url",
        "status",
    ]
    payload = {field: normalize_blank(updates.get(field)) for field in allowed_fields if field in updates}
    payload["updated_at"] = now
    assignments = ", ".join([f"{field} = ?" for field in payload])
    values = list(payload.values()) + [trade_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"UPDATE trades SET {assignments} WHERE id = ?", values)
        conn.commit()


def load_journal_db(db_path=JOURNAL_DB_PATH):
    init_journal_db(db_path)
    with sqlite3.connect(db_path) as conn:
        db_df = pd.read_sql_query("SELECT * FROM trades ORDER BY COALESCE(close_date, open_date), id", conn)
    if db_df.empty:
        return pd.DataFrame(columns=JOURNAL_DISPLAY_COLUMNS)

    rename_map = {
        "id": "ID",
        "open_date": "Open Date",
        "close_date": "Close Date",
        "symbol": "Symbol",
        "side": "Side",
        "sector": "Sector",
        "setup": "Setup",
        "market_regime": "Market Regime",
        "entry_price": "Entry Price",
        "stop_loss": "Stop Loss",
        "exit_price": "Exit Price",
        "shares": "Shares",
        "fees": "Fees",
        "risk_amount": "Risk Amount",
        "net_pl": "Net P/L",
        "r_multiple": "R Multiple",
        "mistake_tag": "Mistake Tag",
        "notes": "Notes",
        "screenshot_url": "Screenshot URL",
        "status": "Status",
        "created_at": "Created At",
        "updated_at": "Updated At",
    }
    journal_df = db_df.rename(columns=rename_map)
    return journal_df[[col for col in JOURNAL_DISPLAY_COLUMNS if col in journal_df.columns]]


def trade_row_to_db_payload(row):
    return {
        "open_date": normalize_date_value(row.get("Open Date") or row.get("Entry Date") or row.get("Buy Date") or row.get("Date")),
        "close_date": normalize_date_value(row.get("Close Date") or row.get("Exit Date") or row.get("Sell Date")),
        "symbol": normalize_blank(row.get("Symbol") or row.get("Ticker")),
        "side": normalize_blank(row.get("Side") or row.get("Direction") or "Long"),
        "sector": normalize_blank(row.get("Sector")),
        "setup": normalize_blank(row.get("Setup") or row.get("Setup Type") or row.get("Pattern")),
        "market_regime": normalize_blank(row.get("Market Regime") or row.get("Market Structure")),
        "entry_price": normalize_float_value(row.get("Entry Price") or row.get("Buy Price") or row.get("Entry")),
        "stop_loss": normalize_float_value(row.get("Stop Loss") or row.get("Initial Stop") or row.get("SL")),
        "exit_price": normalize_float_value(row.get("Exit Price") or row.get("Sell Price") or row.get("Exit")),
        "shares": normalize_float_value(row.get("Shares") or row.get("Quantity") or row.get("Qty") or row.get("Position Size")),
        "fees": normalize_float_value(row.get("Fees") or row.get("Commission")),
        "risk_amount": normalize_float_value(row.get("Risk Amount") or row.get("Initial Risk Amount")),
        "net_pl": normalize_float_value(row.get("Net P/L") or row.get("Net P&L") or row.get("Profit Loss") or row.get("P/L")),
        "r_multiple": normalize_float_value(row.get("R Multiple") or row.get("R") or row.get("R-Multiple")),
        "mistake_tag": normalize_blank(row.get("Mistake Tag") or row.get("Mistake") or row.get("Mistakes")),
        "notes": normalize_blank(row.get("Notes")),
        "screenshot_url": normalize_blank(row.get("Screenshot URL")),
        "status": normalize_blank(row.get("Status") or "Imported"),
    }


def import_journal_csv_to_db(raw_df, db_path=JOURNAL_DB_PATH):
    imported = 0
    skipped = 0
    for _, row in raw_df.iterrows():
        trade = trade_row_to_db_payload(row)
        if trade["symbol"]:
            save_trade_to_db(trade, db_path=db_path)
            imported += 1
        else:
            skipped += 1
    return imported, skipped


def save_trade_plan_to_db(plan, db_path=JOURNAL_DB_PATH, plan_id=None):
    init_journal_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    fields = [
        "plan_date",
        "symbol",
        "side",
        "sector",
        "setup",
        "market_regime",
        "current_price",
        "entry_trigger",
        "stop_loss",
        "target_1",
        "target_2",
        "alert_price",
        "planned_risk",
        "actual_action",
        "position_notes",
        "status",
        "linked_trade_id",
    ]
    payload = {field: normalize_blank(plan.get(field)) for field in fields}
    payload["updated_at"] = now

    with sqlite3.connect(db_path) as conn:
        if plan_id:
            assignments = ", ".join([f"{field} = ?" for field in fields] + ["updated_at = ?"])
            values = [payload[field] for field in fields] + [payload["updated_at"], plan_id]
            conn.execute(f"UPDATE trade_plans SET {assignments} WHERE id = ?", values)
            saved_plan_id = plan_id
        else:
            payload["created_at"] = now
            columns = fields + ["created_at", "updated_at"]
            placeholders = ", ".join(["?"] * len(columns))
            cursor = conn.execute(
                f"INSERT INTO trade_plans ({', '.join(columns)}) VALUES ({placeholders})",
                [payload[col] for col in columns],
            )
            saved_plan_id = cursor.lastrowid
        conn.commit()
    return saved_plan_id


def load_trade_plans_db(db_path=JOURNAL_DB_PATH):
    init_journal_db(db_path)
    with sqlite3.connect(db_path) as conn:
        db_df = pd.read_sql_query("SELECT * FROM trade_plans ORDER BY plan_date DESC, id DESC", conn)
    if db_df.empty:
        return pd.DataFrame(columns=TRADE_PLAN_DISPLAY_COLUMNS)

    rename_map = {
        "id": "ID",
        "plan_date": "Plan Date",
        "symbol": "Symbol",
        "side": "Side",
        "sector": "Sector",
        "setup": "Setup",
        "market_regime": "Market Regime",
        "current_price": "Current Price",
        "entry_trigger": "Entry Trigger",
        "stop_loss": "Stop Loss",
        "target_1": "Target 1",
        "target_2": "Target 2",
        "alert_price": "Alert Price",
        "planned_risk": "Planned Risk",
        "actual_action": "Actual Action",
        "position_notes": "Position Notes",
        "status": "Status",
        "linked_trade_id": "Linked Trade ID",
        "created_at": "Created At",
        "updated_at": "Updated At",
    }
    plan_df = db_df.rename(columns=rename_map)
    return plan_df[[col for col in TRADE_PLAN_DISPLAY_COLUMNS if col in plan_df.columns]]


def get_trade_plan_by_id(plan_id, db_path=JOURNAL_DB_PATH):
    init_journal_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = pd.read_sql_query("SELECT * FROM trade_plans WHERE id = ?", conn, params=(plan_id,))
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def update_trade_plan_status(plan_id, status, db_path=JOURNAL_DB_PATH, linked_trade_id=None, actual_action=None):
    init_journal_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        if linked_trade_id is None and actual_action is None:
            conn.execute(
                "UPDATE trade_plans SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, plan_id),
            )
        elif linked_trade_id is None:
            conn.execute(
                "UPDATE trade_plans SET status = ?, actual_action = ?, updated_at = ? WHERE id = ?",
                (status, actual_action, now, plan_id),
            )
        elif actual_action is None:
            conn.execute(
                "UPDATE trade_plans SET status = ?, linked_trade_id = ?, updated_at = ? WHERE id = ?",
                (status, linked_trade_id, now, plan_id),
            )
        else:
            conn.execute(
                "UPDATE trade_plans SET status = ?, linked_trade_id = ?, actual_action = ?, updated_at = ? WHERE id = ?",
                (status, linked_trade_id, actual_action, now, plan_id),
            )
        conn.commit()


def convert_plan_to_trade(plan_id, db_path=JOURNAL_DB_PATH):
    plan = get_trade_plan_by_id(plan_id, db_path)
    if not plan:
        return None

    trade_id = save_trade_to_db(
        {
            "open_date": date.today().isoformat(),
            "close_date": None,
            "symbol": plan.get("symbol"),
            "side": plan.get("side") or "Long",
            "sector": plan.get("sector"),
            "setup": plan.get("setup"),
            "market_regime": plan.get("market_regime"),
            "entry_price": plan.get("entry_trigger"),
            "stop_loss": plan.get("stop_loss"),
            "exit_price": None,
            "shares": None,
            "fees": 0,
            "risk_amount": plan.get("planned_risk"),
            "net_pl": None,
            "r_multiple": None,
            "mistake_tag": None,
            "notes": plan.get("position_notes"),
            "screenshot_url": None,
            "status": "Open",
        },
        db_path=db_path,
    )
    actual_action = plan.get("actual_action")
    if actual_action in [None, "", "Not Yet"]:
        actual_action = "Do as Plan"
    update_trade_plan_status(plan_id, "Open", db_path=db_path, linked_trade_id=trade_id, actual_action=actual_action)
    return trade_id


def get_prefill_plan_from_screening(screening_df, sector_col, symbol):
    if screening_df is None or screening_df.empty or not symbol:
        return {}
    rows = screening_df[screening_df["Symbol"].astype(str).str.upper() == symbol.upper()]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "sector": row.get(sector_col, "") if sector_col else "",
        "current_price": row.get("Price", 0.0),
        "setup": row.get("Setup Location", ""),
        "position_notes": f"{row.get('Momentum Quality', '')}; {row.get('Screening Priority', '')}".strip("; "),
    }


def calculate_pretrade_exposure(performance, ma200, trend, pt, distribution_days):
    raw_exposure = (
        PERFORMANCE_EXPOSURE[performance]
        * MA200_EXPOSURE[ma200]
        * TREND_EXPOSURE[trend]
        * PT_EXPOSURE[pt]
        / (100 ** 3)
    )
    if distribution_days >= 5:
        cap = 50
    elif distribution_days >= 3:
        cap = 75
    else:
        cap = raw_exposure
    return raw_exposure, min(raw_exposure, cap), cap


def calculate_today_plan(expected_exposure, current_exposure):
    gap = expected_exposure - current_exposure
    if gap > 5:
        return "Increase"
    if gap < -5:
        return "Reduce"
    return "Hold"


def calculate_recent_max_drawdown_pct(portfolio_df, window=20):
    if portfolio_df is None or portfolio_df.empty or "Equity Drawdown %" not in portfolio_df.columns:
        return 0.0

    df = portfolio_df.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date")

    drawdowns = pd.to_numeric(df["Equity Drawdown %"], errors="coerce").dropna()
    if drawdowns.empty:
        return 0.0

    selected_drawdown = drawdowns.tail(window).min()
    return abs(float(selected_drawdown))


def calculate_risk_behavior_largest_drawdown_pct(portfolio_df, window=20):
    return calculate_recent_max_drawdown_pct(portfolio_df, window=window)


def prepare_risk_behavior_metrics(out, unrealized_is_amount=False):
    if out is None or out.empty:
        return out

    total_equity = pd.to_numeric(out.get("Total Equity"), errors="coerce").replace(0, pd.NA)
    exposure_value_cols = [col for col in ["US Exposure Value", "Non-US Exposure Value"] if col in out.columns]
    if exposure_value_cols:
        exposure_values = out[exposure_value_cols].apply(pd.to_numeric, errors="coerce")
        out["Total Exposure Value"] = exposure_values.fillna(0).sum(axis=1)
        out["Risk Exposure %"] = out["Total Exposure Value"] / total_equity * 100
    elif "Position Exposure %" in out.columns:
        out["Risk Exposure %"] = pd.to_numeric(out["Position Exposure %"], errors="coerce")
        out["Total Exposure Value"] = total_equity * out["Risk Exposure %"] / 100
    else:
        out["Risk Exposure %"] = pd.NA
        out["Total Exposure Value"] = pd.NA

    if "Unrealized Gain" in out.columns:
        raw_unrealized = pd.to_numeric(out["Unrealized Gain"], errors="coerce")
        non_missing = raw_unrealized.dropna()
        treat_as_amount = unrealized_is_amount
        if not treat_as_amount and not non_missing.empty:
            treat_as_amount = non_missing.abs().quantile(0.95) > 100

        if treat_as_amount:
            out["Unrealized P/L"] = raw_unrealized
            out["Risk Unrealized Gain %"] = out["Unrealized P/L"] / total_equity * 100
        else:
            out["Risk Unrealized Gain %"] = raw_unrealized
            out["Unrealized P/L"] = total_equity * out["Risk Unrealized Gain %"] / 100
        out["Unrealized Gain"] = out["Risk Unrealized Gain %"]
    else:
        out["Unrealized P/L"] = pd.NA
        out["Risk Unrealized Gain %"] = pd.NA

    total_exposure_value = pd.to_numeric(out["Total Exposure Value"], errors="coerce").replace(0, pd.NA)
    out["Unrealized Gain on Exposure %"] = out["Unrealized P/L"] / total_exposure_value * 100

    if "Equity Drawdown %" in out.columns:
        out["Risk Drawdown %"] = pd.to_numeric(out["Equity Drawdown %"], errors="coerce").abs()
    else:
        out["Risk Drawdown %"] = pd.NA
    return out


def safe_corr(series_a, series_b):
    pair_df = pd.DataFrame({"a": series_a, "b": series_b}).apply(pd.to_numeric, errors="coerce").dropna()
    if len(pair_df) < 3 or pair_df["a"].nunique() < 2 or pair_df["b"].nunique() < 2:
        return None
    corr = pair_df["a"].corr(pair_df["b"])
    if pd.isna(corr):
        return None
    return float(corr)


def classify_exposure_drawdown_corr(correlation):
    if correlation is None or pd.isna(correlation):
        return "Insufficient data"
    if correlation > 0.5:
        return "Strong warning"
    if correlation > 0.3:
        return "Warning"
    if correlation < -0.3:
        return "Defensive"
    if correlation < 0:
        return "Slightly defensive"
    return "Neutral"


def classify_exposure_unrealized_corr(correlation):
    if correlation is None or pd.isna(correlation):
        return "Insufficient data"
    if correlation > 0.3:
        return "Winners working"
    if correlation > 0:
        return "Slightly positive"
    if correlation < -0.3:
        return "Watch adding to weakness"
    if correlation < 0:
        return "Slightly negative"
    return "Neutral"


def classify_unrealized_drawdown_corr(correlation):
    if correlation is None or pd.isna(correlation):
        return "Insufficient data"
    if correlation < -0.3:
        return "Profit cushion"
    if correlation < 0:
        return "Slight cushion"
    if correlation > 0.3:
        return "Hidden weakness"
    if correlation > 0:
        return "Watch"
    return "Neutral"


def classify_risk_behavior_score(exposure_unrealized_corr, exposure_drawdown_corr, unrealized_drawdown_corr):
    correlations = [exposure_unrealized_corr, exposure_drawdown_corr, unrealized_drawdown_corr]
    if any(corr is None or pd.isna(corr) for corr in correlations):
        return "Insufficient data", 0
    if exposure_drawdown_corr > 0.5 or (exposure_unrealized_corr < 0 and exposure_drawdown_corr > 0):
        return "Danger", 0

    healthy_count = int(exposure_unrealized_corr > 0)
    healthy_count += int(exposure_drawdown_corr <= 0.3)
    healthy_count += int(unrealized_drawdown_corr < 0)
    if healthy_count == 3:
        return "Healthy", healthy_count
    if healthy_count == 2:
        return "Mixed", healthy_count
    if healthy_count == 1:
        return "Warning", healthy_count
    return "Danger", healthy_count


def calculate_risk_behavior_windows(portfolio_df, windows=(20, 50, 100)):
    columns = ["Risk Exposure %", "Risk Unrealized Gain %", "Risk Drawdown %"]
    if portfolio_df is None or portfolio_df.empty or any(col not in portfolio_df.columns for col in columns):
        return pd.DataFrame(
            columns=[
                "Window",
                "Records",
                "Corr(Exposure, Unrealized Gain)",
                "Corr(Exposure, Drawdown)",
                "Corr(Unrealized Gain, Drawdown)",
                "Exposure Drawdown Signal",
                "Risk Behavior Score",
                "Healthy Signals",
            ]
        )

    df = portfolio_df.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date")

    rows = []
    for window in windows:
        window_df = df.dropna(subset=columns).tail(window)
        exposure_unrealized_corr = safe_corr(window_df["Risk Exposure %"], window_df["Risk Unrealized Gain %"])
        exposure_drawdown_corr = safe_corr(window_df["Risk Exposure %"], window_df["Risk Drawdown %"])
        unrealized_drawdown_corr = safe_corr(window_df["Risk Unrealized Gain %"], window_df["Risk Drawdown %"])
        score_label, healthy_count = classify_risk_behavior_score(
            exposure_unrealized_corr,
            exposure_drawdown_corr,
            unrealized_drawdown_corr,
        )
        rows.append(
            {
                "Window": f"{window} records",
                "Records": len(window_df),
                "Corr(Exposure, Unrealized Gain)": exposure_unrealized_corr,
                "Corr(Exposure, Drawdown)": exposure_drawdown_corr,
                "Corr(Unrealized Gain, Drawdown)": unrealized_drawdown_corr,
                "Exposure Drawdown Signal": classify_exposure_drawdown_corr(exposure_drawdown_corr),
                "Risk Behavior Score": score_label,
                "Healthy Signals": healthy_count,
            }
        )
    return pd.DataFrame(rows)


def parse_percent_list(text, fallback):
    values = []
    for part in str(text).split(","):
        try:
            values.append(float(part.strip()))
        except ValueError:
            continue
    return values or fallback


def save_pretrade_snapshot(snapshot, db_path=JOURNAL_DB_PATH):
    if is_supabase_pretrade_enabled():
        save_pretrade_snapshot_to_supabase(snapshot)
        return

    init_journal_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    fields = [
        "snapshot_date",
        "holding_us",
        "holding_other",
        "cash",
        "total_equity",
        "expected_exposure",
        "current_exposure",
        "today_plan",
        "risk_per_trade",
        "stop_loss_pct",
        "position_cost",
        "performance_condition",
        "ma200_condition",
        "trend_condition",
        "pt_condition",
        "distribution_days",
        "scorecard_exposure",
        "capped_exposure",
        "personal_drawdown_pct",
        "notes",
    ]
    payload = {field: normalize_blank(snapshot.get(field)) for field in fields}
    payload["created_at"] = now
    payload["updated_at"] = now
    with sqlite3.connect(db_path) as conn:
        placeholders = ", ".join(["?"] * (len(fields) + 2))
        conn.execute(
            f"INSERT INTO pretrade_snapshots ({', '.join(fields + ['created_at', 'updated_at'])}) VALUES ({placeholders})",
            [payload[field] for field in fields] + [payload["created_at"], payload["updated_at"]],
        )
        conn.commit()


def load_pretrade_snapshots(db_path=JOURNAL_DB_PATH, limit=None):
    if is_supabase_pretrade_enabled():
        try:
            return load_pretrade_snapshots_from_supabase(limit=limit)
        except Exception as exc:
            st.warning(f"Could not load Supabase pre-trading snapshots. Showing local history instead. Error: {exc}")

    init_journal_db(db_path)
    query = "SELECT * FROM pretrade_snapshots ORDER BY snapshot_date DESC, id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return pd.DataFrame()
    rename_map = {
        "id": "ID",
        "snapshot_date": "Date",
        "holding_us": "Holding US",
        "holding_other": "Holding Non-US",
        "cash": "Cash",
        "total_equity": "Total Equity",
        "expected_exposure": "Expected Exposure",
        "current_exposure": "Current Exposure",
        "today_plan": "Today Plan",
        "risk_per_trade": "Risk per Trade",
        "stop_loss_pct": "Stop Loss %",
        "position_cost": "Position Cost",
        "performance_condition": "Performance",
        "ma200_condition": "MA200",
        "trend_condition": "Trend",
        "pt_condition": "PT",
        "distribution_days": "Distribution Days",
        "scorecard_exposure": "Scorecard Exposure",
        "capped_exposure": "Capped Exposure",
        "personal_drawdown_pct": "Personal Drawdown %",
        "notes": "Notes",
        "created_at": "Created At",
        "updated_at": "Updated At",
    }
    return df.rename(columns=rename_map)


def load_latest_pretrade_snapshot(db_path=JOURNAL_DB_PATH):
    history_df = load_pretrade_snapshots(db_path=db_path, limit=1)
    if history_df.empty:
        return {}
    return history_df.iloc[0].to_dict()


def pretrade_snapshot_fields():
    return [
        "snapshot_date",
        "holding_us",
        "holding_other",
        "cash",
        "total_equity",
        "expected_exposure",
        "current_exposure",
        "today_plan",
        "risk_per_trade",
        "stop_loss_pct",
        "position_cost",
        "performance_condition",
        "ma200_condition",
        "trend_condition",
        "pt_condition",
        "distribution_days",
        "scorecard_exposure",
        "capped_exposure",
        "personal_drawdown_pct",
        "notes",
    ]


def pretrade_display_rename_map():
    return {
        "id": "ID",
        "snapshot_date": "Date",
        "holding_us": "Holding US",
        "holding_other": "Holding Non-US",
        "cash": "Cash",
        "total_equity": "Total Equity",
        "expected_exposure": "Expected Exposure",
        "current_exposure": "Current Exposure",
        "today_plan": "Today Plan",
        "risk_per_trade": "Risk per Trade",
        "stop_loss_pct": "Stop Loss %",
        "position_cost": "Position Cost",
        "performance_condition": "Performance",
        "ma200_condition": "MA200",
        "trend_condition": "Trend",
        "pt_condition": "PT",
        "distribution_days": "Distribution Days",
        "scorecard_exposure": "Scorecard Exposure",
        "capped_exposure": "Capped Exposure",
        "personal_drawdown_pct": "Personal Drawdown %",
        "notes": "Notes",
        "created_at": "Created At",
        "updated_at": "Updated At",
    }


def is_supabase_pretrade_enabled():
    return bool(get_secret_value("supabase_url") and get_secret_value("supabase_key"))


def get_supabase_pretrade_table_name():
    return get_secret_value("supabase_pretrade_table", "pretrade_snapshots")


@st.cache_resource
def get_supabase_client(url, key):
    if create_client is None:
        raise ImportError("Install the `supabase` package first: pip install supabase")
    return create_client(url, key)


def supabase_pretrade_client():
    return get_supabase_client(get_secret_value("supabase_url"), get_secret_value("supabase_key"))


def save_pretrade_snapshot_to_supabase(snapshot):
    now = datetime.now().isoformat(timespec="seconds")
    fields = pretrade_snapshot_fields()
    payload = {field: normalize_blank(snapshot.get(field)) for field in fields}
    payload["created_at"] = now
    payload["updated_at"] = now
    supabase_pretrade_client().table(get_supabase_pretrade_table_name()).insert(payload).execute()


def format_supabase_write_error(exc):
    message = str(exc)
    if "row-level security" in message.lower() or "42501" in message:
        return (
            f"{message}\n\n"
            "Supabase blocked this write with Row Level Security. For this private Streamlit app, "
            "set `supabase_key` in `.streamlit/secrets.toml` to your Supabase `service_role` key, "
            "not the `anon` public key. The service role key must stay private and should never be committed."
        )
    return message


def load_pretrade_snapshots_from_supabase(limit=None):
    query = (
        supabase_pretrade_client()
        .table(get_supabase_pretrade_table_name())
        .select("*")
        .order("snapshot_date", desc=True)
        .order("id", desc=True)
    )
    if limit:
        query = query.limit(int(limit))
    response = query.execute()
    records = response.data or []
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).rename(columns=pretrade_display_rename_map())


def get_supabase_portfolio_risk_snapshot_table_name():
    return get_secret_value("supabase_portfolio_risk_snapshot_table", "portfolio_risk_snapshots")


def get_supabase_portfolio_risk_positions_table_name():
    return get_secret_value("supabase_portfolio_risk_positions_table", "portfolio_risk_positions")


def save_portfolio_risk_snapshot_to_supabase(rows, snapshot_date, total_invested, total_equity, notes=""):
    snapshot, positions, _positions_df, _summary = portfolio_risk_payloads(
        rows,
        snapshot_date,
        total_invested,
        total_equity,
        notes,
    )
    client = supabase_pretrade_client()
    snapshot_response = client.table(get_supabase_portfolio_risk_snapshot_table_name()).insert(snapshot).execute()
    snapshot_records = snapshot_response.data or []
    snapshot_id = snapshot_records[0].get("id") if snapshot_records else None
    if positions and snapshot_id is not None:
        position_records = [{**position, "snapshot_id": snapshot_id} for position in positions]
        try:
            client.table(get_supabase_portfolio_risk_positions_table_name()).insert(position_records).execute()
        except Exception:
            client.table(get_supabase_portfolio_risk_snapshot_table_name()).delete().eq("id", snapshot_id).execute()
            raise
    return snapshot_id


def load_latest_portfolio_risk_snapshot_from_supabase():
    snapshot_response = (
        supabase_pretrade_client()
        .table(get_supabase_portfolio_risk_snapshot_table_name())
        .select("*")
        .order("snapshot_date", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    snapshot_records = snapshot_response.data or []
    if not snapshot_records:
        return pd.DataFrame(columns=PORTFOLIO_RISK_INPUT_COLUMNS), {}

    snapshot = snapshot_records[0]
    positions_response = (
        supabase_pretrade_client()
        .table(get_supabase_portfolio_risk_positions_table_name())
        .select("*")
        .eq("snapshot_id", snapshot.get("id"))
        .order("id")
        .execute()
    )
    position_df = pd.DataFrame(positions_response.data or [])
    if position_df.empty:
        return pd.DataFrame(columns=PORTFOLIO_RISK_INPUT_COLUMNS), snapshot
    if "heat_usd" not in position_df.columns and "heat_thb" in position_df.columns:
        position_df["heat_usd"] = position_df["heat_thb"]
    position_df = position_df.rename(
        columns={
            "stock_name": "Stock name",
            "position": "Position",
            "avg_cost": "Avg. cost",
            "last_price": "Last price",
            "stop": "Stop",
            "atr_pct": "%ATR",
            "market_value": "Market value (USD)",
            "exposure_pct": "Exposure %",
            "heat_usd": "Heat (USD)",
        }
    )
    return prepare_portfolio_risk_input(position_df), snapshot


def load_portfolio_risk_history_from_supabase(limit=None):
    query = (
        supabase_pretrade_client()
        .table(get_supabase_portfolio_risk_snapshot_table_name())
        .select("*")
        .order("snapshot_date", desc=True)
        .order("id", desc=True)
    )
    if limit:
        query = query.limit(int(limit))
    response = query.execute()
    return pd.DataFrame(response.data or [])


def save_portfolio_risk_snapshot_to_storage(rows, snapshot_date, total_invested, total_equity, notes=""):
    if is_supabase_pretrade_enabled():
        return save_portfolio_risk_snapshot_to_supabase(
            rows,
            snapshot_date,
            total_invested,
            total_equity,
            notes,
        )
    return save_portfolio_risk_snapshot(
        rows,
        snapshot_date,
        total_invested,
        total_equity,
        JOURNAL_DB_PATH,
        notes,
    )


def load_latest_portfolio_risk_snapshot_from_storage():
    try:
        if is_supabase_pretrade_enabled():
            return load_latest_portfolio_risk_snapshot_from_supabase()
    except Exception as exc:
        st.warning(f"Could not load Supabase portfolio risk snapshot. Showing local rows instead. Error: {exc}")
    return load_latest_portfolio_risk_snapshot(JOURNAL_DB_PATH)


def load_portfolio_risk_history_from_storage(limit=None):
    try:
        if is_supabase_pretrade_enabled():
            return load_portfolio_risk_history_from_supabase(limit=limit)
    except Exception as exc:
        st.warning(f"Could not load Supabase portfolio risk history. Showing local history instead. Error: {exc}")
    return load_portfolio_risk_history(JOURNAL_DB_PATH, limit=limit)


def google_sheet_to_csv_url(url):
    text = str(url).strip()
    if not text:
        return ""
    if "output=csv" in text or "format=csv" in text:
        return text

    parsed = urlparse(text)
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
        return text

    sheet_id = parsed.path.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]
    query = parse_qs(parsed.query)
    fragment_query = parse_qs(parsed.fragment)
    gid = query.get("gid", fragment_query.get("gid", [""]))[0]
    if gid:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


def google_sheet_id_from_url(url):
    parsed = urlparse(str(url).strip())
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
        return ""
    return parsed.path.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]


def detect_column(columns, candidates):
    normalized = {str(col).strip().lower(): col for col in columns}
    for candidate in candidates:
        exact = normalized.get(candidate.lower())
        if exact is not None:
            return exact
    for col in columns:
        lower_col = str(col).strip().lower()
        for candidate in candidates:
            if candidate.lower() in lower_col:
                return col
    return None


@st.cache_data(ttl=300)
def load_portfolio_csv_from_url(csv_url, source_sheet_id=""):
    read_kwargs = {}
    if source_sheet_id == DEFAULT_PORTFOLIO_SHEET_ID and DEFAULT_PORTFOLIO_USECOLS is not None:
        read_kwargs["usecols"] = DEFAULT_PORTFOLIO_USECOLS
    return pd.read_csv(csv_url, **read_kwargs)


def load_portfolio_source(sheet_url, uploaded_file):
    if uploaded_file is not None:
        return pd.read_csv(uploaded_file), "uploaded CSV"
    csv_url = google_sheet_to_csv_url(sheet_url)
    if csv_url:
        source_sheet_id = google_sheet_id_from_url(sheet_url)
        return load_portfolio_csv_from_url(csv_url, source_sheet_id), csv_url
    return pd.DataFrame(), ""


def format_correlation(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.2f}"


def risk_behavior_column_config():
    return {
        "Corr(Exposure, Unrealized Gain)": st.column_config.TextColumn(
            "Corr(Exposure, Unrealized Gain)",
            help=(
                "Positive: exposure tends to rise with open profits; usually healthy when winners are working.\n\n"
                "Negative: can mean adding when positions are not working or trimming winners early."
            ),
        ),
        "Corr(Exposure, Drawdown)": st.column_config.TextColumn(
            "Corr(Exposure, Drawdown)",
            help=(
                "Positive: warning signal. Above +0.3 means exposure may be high during damage; above +0.5 is a strong warning.\n\n"
                "Negative: usually defensive because exposure falls as drawdown rises."
            ),
        ),
        "Corr(Unrealized Gain, Drawdown)": st.column_config.TextColumn(
            "Corr(Unrealized Gain, Drawdown)",
            help=(
                "Positive: possible hidden weakness; open gains may be fading while equity is drawing down.\n\n"
                "Negative: usually healthy because open profits cushion drawdown."
            ),
        ),
    }


def render_risk_behavior_section(portfolio_df):
    st.markdown("#### Risk Behavior")
    st.caption(
        "Uses portfolio equity including cash as the denominator. Drawdown is shown as a positive value in this section only."
    )

    required_cols = ["Risk Exposure %", "Risk Unrealized Gain %", "Risk Drawdown %"]
    if portfolio_df is None or portfolio_df.empty or any(col not in portfolio_df.columns for col in required_cols):
        st.info("Need exposure, unrealized gain, and drawdown history to calculate Risk Behavior.")
        return

    latest = get_latest_portfolio_record(portfolio_df)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Risk Exposure", f"{number_input_value(latest.get('Risk Exposure %')):.1f}%")
    m2.metric("Unrealized Gain / Equity", f"{number_input_value(latest.get('Risk Unrealized Gain %')):.2f}%")
    m3.metric("Largest Drawdown 20d", f"{calculate_risk_behavior_largest_drawdown_pct(portfolio_df):.2f}%")
    m4.metric("Unrealized Gain / Exposure", f"{number_input_value(latest.get('Unrealized Gain on Exposure %')):.2f}%")

    behavior_df = calculate_risk_behavior_windows(portfolio_df)
    if behavior_df.empty:
        st.info("Need at least three valid history rows for correlation analysis.")
        return

    card_cols = st.columns(len(behavior_df))
    for container, row in zip(card_cols, behavior_df.to_dict("records")):
        container.metric(
            row["Window"],
            row["Risk Behavior Score"],
            row["Exposure Drawdown Signal"],
        )
        exposure_unrealized_corr = row["Corr(Exposure, Unrealized Gain)"]
        exposure_drawdown_corr = row["Corr(Exposure, Drawdown)"]
        unrealized_drawdown_corr = row["Corr(Unrealized Gain, Drawdown)"]
        container.caption(
            "Exposure / Unrealized "
            f"{format_correlation(exposure_unrealized_corr)} "
            f"({classify_exposure_unrealized_corr(exposure_unrealized_corr)})"
        )
        container.caption(
            "Exposure / Drawdown "
            f"{format_correlation(exposure_drawdown_corr)} "
            f"({classify_exposure_drawdown_corr(exposure_drawdown_corr)})"
        )
        container.caption(
            "Unrealized / Drawdown "
            f"{format_correlation(unrealized_drawdown_corr)} "
            f"({classify_unrealized_drawdown_corr(unrealized_drawdown_corr)})"
        )

    display_df = behavior_df.copy()
    for col in [
        "Corr(Exposure, Unrealized Gain)",
        "Corr(Exposure, Drawdown)",
        "Corr(Unrealized Gain, Drawdown)",
    ]:
        display_df[col] = display_df[col].apply(format_correlation)
    st.dataframe(display_df, width="stretch", hide_index=True, column_config=risk_behavior_column_config())


def prepare_default_portfolio_log(raw_df):
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    required_index = max(DEFAULT_PORTFOLIO_POSITION_MAP.values())
    if raw_df.shape[1] <= required_index:
        return pd.DataFrame()

    def source_column(key):
        return raw_df.iloc[:, DEFAULT_PORTFOLIO_POSITION_MAP[key]]

    total_market_value = clean_numeric(source_column("total_market_value"))
    cash = clean_numeric(source_column("cash"))
    us_market_value = clean_numeric(source_column("us_market_value"))
    non_us_market_value = clean_numeric(source_column("non_us_market_value"))
    unrealized_amount = clean_numeric(source_column("unrealized_amount"))

    total_equity = total_market_value.fillna(0) + cash.fillna(0)
    normalized_df = pd.DataFrame(
        {
            "Date": source_column("date"),
            "Total Equity": total_equity,
            "US Market Value": us_market_value,
            "Cash": cash,
            "Unrealized Gain": unrealized_amount,
            "US Exposure": us_market_value,
            "Non-US Exposure": non_us_market_value,
            "US NAV": clean_numeric(source_column("nav")),
        }
    )
    default_column_map = {
        "date": "Date",
        "market_value": "US Market Value",
        "equity": "Total Equity",
        "exposure": None,
        "us_exposure_value": "US Exposure",
        "other_exposure": None,
        "other_exposure_value": "Non-US Exposure",
        "unrealized": "Unrealized Gain",
        "holding_us": None,
        "holding_other": None,
        "cash": "Cash",
        "nav": "US NAV",
        "unrealized_is_amount": True,
    }
    return prepare_portfolio_log(normalized_df, default_column_map)


def prepare_portfolio_log(raw_df, column_map):
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    date_col = column_map.get("date")
    market_value_col = column_map.get("market_value")
    equity_col = column_map.get("equity")
    exposure_col = column_map.get("exposure")
    us_exposure_value_col = column_map.get("us_exposure_value")
    other_exposure_col = column_map.get("other_exposure")
    other_exposure_value_col = column_map.get("other_exposure_value")
    unrealized_col = column_map.get("unrealized")
    holding_us_col = column_map.get("holding_us")
    holding_other_col = column_map.get("holding_other")
    cash_col = column_map.get("cash")
    nav_col = column_map.get("nav")
    unrealized_is_amount = bool(column_map.get("unrealized_is_amount", False))

    has_computed_equity = market_value_col and cash_col
    if not date_col or not (equity_col or has_computed_equity):
        return pd.DataFrame()

    out = pd.DataFrame()
    out["Date"] = pd.to_datetime(df[date_col], errors="coerce")

    if market_value_col:
        out["US Market Value"] = clean_numeric(df[market_value_col])
        out["Holding US"] = out["US Market Value"]
    if cash_col:
        out["Cash"] = clean_numeric(df[cash_col])
    if equity_col:
        out["Total Equity"] = clean_numeric(df[equity_col])
    else:
        out["Total Equity"] = out["US Market Value"].fillna(0) + out["Cash"].fillna(0)

    optional_sources = {
        "Position Exposure %": exposure_col,
        "Non-US Exposure %": other_exposure_col,
        "Unrealized Gain": unrealized_col,
        "Holding US": holding_us_col if holding_us_col else None,
        "Holding Non-US": holding_other_col,
    }
    for target_col, source_col in optional_sources.items():
        if source_col:
            out[target_col] = clean_numeric(df[source_col])

    if nav_col:
        out["NAV"] = clean_numeric(df[nav_col])
    if us_exposure_value_col:
        out["US Exposure Value"] = clean_numeric(df[us_exposure_value_col])
        out["US Exposure %"] = out["US Exposure Value"] / out["Total Equity"].replace(0, pd.NA) * 100
    elif "Position Exposure %" in out.columns:
        out["US Exposure %"] = out["Position Exposure %"]
    if other_exposure_value_col:
        out["Non-US Exposure Value"] = clean_numeric(df[other_exposure_value_col])
        out["Non-US Exposure %"] = out["Non-US Exposure Value"] / out["Total Equity"].replace(0, pd.NA) * 100

    out = out.dropna(subset=["Date", "Total Equity"]).sort_values("Date").copy()
    if "US Exposure %" in out.columns:
        exposure_values = out["US Exposure %"].dropna()
        if not exposure_values.empty and exposure_values.quantile(0.95) <= 1.5:
            out["US Exposure %"] = out["US Exposure %"] * 100
    if "Non-US Exposure %" in out.columns:
        other_exposure_values = out["Non-US Exposure %"].dropna()
        if not other_exposure_values.empty and other_exposure_values.quantile(0.95) <= 1.5:
            out["Non-US Exposure %"] = out["Non-US Exposure %"] * 100
    exposure_parts = [col for col in ["US Exposure %", "Non-US Exposure %"] if col in out.columns]
    if exposure_parts:
        exposure_df = out[exposure_parts].apply(pd.to_numeric, errors="coerce")
        out["Position Exposure %"] = exposure_df.fillna(0).sum(axis=1)

    valid_equity = out["Total Equity"].replace(0, pd.NA).dropna()
    if "NAV" in out.columns and out["NAV"].notna().any():
        out["Total Equity NAV"] = out["NAV"]
    elif not valid_equity.empty:
        out["Total Equity NAV"] = out["Total Equity"] / valid_equity.iloc[0] * 100
    else:
        out["Total Equity NAV"] = pd.NA

    for span in [10, 20, 50]:
        out[f"Equity EMA{span}"] = out["Total Equity"].ewm(span=span, adjust=False, min_periods=1).mean()
        out[f"Total Equity NAV EMA{span}"] = out["Total Equity NAV"].ewm(
            span=span,
            adjust=False,
            min_periods=1,
        ).mean()
    out["Total Equity NAV EMA10 Rising"] = out["Total Equity NAV EMA10"].diff() > 0

    curve_source = out["Total Equity NAV"]
    out["Equity High"] = curve_source.cummax()
    out["Equity Drawdown %"] = ((curve_source / out["Equity High"]) - 1) * 100
    out["Equity Change"] = out["Total Equity"].diff()
    out["Equity Change %"] = out["Total Equity"].pct_change() * 100
    out = prepare_risk_behavior_metrics(out, unrealized_is_amount=unrealized_is_amount)
    return out


def get_latest_portfolio_record(portfolio_df):
    if portfolio_df is None or portfolio_df.empty:
        return {}
    latest = portfolio_df.sort_values("Date").iloc[-1].to_dict()
    return latest


def prepare_journal_data(raw_df, starting_capital, screening_df=None, sector_col=None):
    df = raw_df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    cols = df.columns.tolist()

    symbol_col = first_existing_col(cols, ["Symbol", "Ticker"])
    open_date_col = first_existing_col(cols, ["Open Date", "Entry Date", "Buy Date", "Date"])
    close_date_col = first_existing_col(cols, ["Close Date", "Exit Date", "Sell Date"])
    side_col = first_existing_col(cols, ["Side", "Direction"])
    entry_col = first_existing_col(cols, ["Entry Price", "Buy Price", "Entry"])
    stop_col = first_existing_col(cols, ["Stop Loss", "Initial Stop", "SL"])
    exit_col = first_existing_col(cols, ["Exit Price", "Sell Price", "Exit"])
    shares_col = first_existing_col(cols, ["Shares", "Quantity", "Qty", "Position Size"])
    fees_col = first_existing_col(cols, ["Fees", "Commission"])
    risk_col = first_existing_col(cols, ["Risk Amount", "Initial Risk Amount"])
    net_pl_col = first_existing_col(cols, ["Net P/L", "Net P&L", "Profit Loss", "P/L"])
    r_col = first_existing_col(cols, ["R Multiple", "R", "R-Multiple"])

    if symbol_col is None:
        return None, ["Missing Symbol column"], {}

    if sector_col and screening_df is not None and "Sector" not in df.columns:
        sector_map = screening_df[["Symbol", sector_col]].dropna().drop_duplicates("Symbol")
        df = df.merge(sector_map, how="left", left_on=symbol_col, right_on="Symbol", suffixes=("", "_Screening"))
        if sector_col != "Sector":
            df["Sector"] = df[sector_col]

    for col in [entry_col, stop_col, exit_col, shares_col, fees_col, risk_col, net_pl_col, r_col]:
        if col is not None:
            df[col] = clean_numeric(df[col])

    if open_date_col is not None:
        df["Open Date Parsed"] = pd.to_datetime(df[open_date_col], errors="coerce")
    else:
        df["Open Date Parsed"] = pd.NaT
    if close_date_col is not None:
        df["Close Date Parsed"] = pd.to_datetime(df[close_date_col], errors="coerce")
    else:
        df["Close Date Parsed"] = pd.NaT
    df["Sort Date"] = df["Close Date Parsed"].fillna(df["Open Date Parsed"])

    side = df[side_col].fillna("Long").astype(str).str.lower() if side_col is not None else pd.Series("long", index=df.index)
    entry = df[entry_col] if entry_col is not None else pd.Series(pd.NA, index=df.index)
    exit_price = df[exit_col] if exit_col is not None else pd.Series(pd.NA, index=df.index)
    shares = df[shares_col] if shares_col is not None else pd.Series(pd.NA, index=df.index)
    stop = df[stop_col] if stop_col is not None else pd.Series(pd.NA, index=df.index)
    fees = df[fees_col].fillna(0) if fees_col is not None else pd.Series(0, index=df.index)

    long_pl = (exit_price - entry) * shares
    short_pl = (entry - exit_price) * shares
    computed_pl = long_pl.where(~side.str.contains("short"), short_pl) - fees
    if net_pl_col is not None:
        df["Net P/L"] = df[net_pl_col].where(df[net_pl_col].notna(), computed_pl)
    else:
        df["Net P/L"] = computed_pl

    computed_risk = (entry - stop).abs() * shares
    if risk_col is not None:
        df["Initial Risk Amount"] = df[risk_col].where(df[risk_col].notna(), computed_risk)
    else:
        df["Initial Risk Amount"] = computed_risk

    computed_r = df["Net P/L"] / df["Initial Risk Amount"].replace(0, pd.NA)
    if r_col is not None:
        df["R Multiple"] = df[r_col].where(df[r_col].notna(), computed_r)
    else:
        df["R Multiple"] = computed_r

    df["Result"] = "Open / Unclear"
    df.loc[df["Net P/L"] > 0, "Result"] = "Win"
    df.loc[df["Net P/L"] < 0, "Result"] = "Loss"
    df.loc[df["Net P/L"] == 0, "Result"] = "Breakeven"

    closed = df[df["Net P/L"].notna() & df["Sort Date"].notna()].sort_values("Sort Date").copy()
    closed["Trade Number"] = range(1, len(closed) + 1)
    closed["Equity"] = starting_capital + closed["Net P/L"].cumsum()
    closed["Equity MA10"] = closed["Equity"].rolling(10, min_periods=1).mean()
    closed["Equity MA20"] = closed["Equity"].rolling(20, min_periods=1).mean()
    closed["Peak Equity"] = closed["Equity"].cummax()
    closed["Drawdown"] = closed["Equity"] - closed["Peak Equity"]
    closed["Drawdown %"] = (closed["Drawdown"] / closed["Peak Equity"]) * 100

    metadata = {
        "symbol_col": symbol_col,
        "setup_col": first_existing_col(cols, ["Setup", "Setup Type", "Pattern"]),
        "market_regime_col": first_existing_col(cols, ["Market Regime", "Market Structure"]),
        "mistake_col": first_existing_col(cols, ["Mistake Tag", "Mistake", "Mistakes"]),
        "sector_col": first_existing_col(closed.columns.tolist(), ["Sector", sector_col] if sector_col else ["Sector"]),
    }
    return closed, [], metadata


def compute_journal_metrics(journal_df):
    if journal_df is None or journal_df.empty:
        return {}

    wins = journal_df[journal_df["Net P/L"] > 0]["Net P/L"]
    losses = journal_df[journal_df["Net P/L"] < 0]["Net P/L"]
    total_pl = journal_df["Net P/L"].sum()
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    current_equity = journal_df["Equity"].iloc[-1]
    equity_ma20 = journal_df["Equity MA20"].iloc[-1]
    drawdown_pct = journal_df["Drawdown %"].iloc[-1]

    if current_equity >= equity_ma20 and drawdown_pct > -5:
        equity_status = "Above Equity MA20"
    elif current_equity < equity_ma20:
        equity_status = "Below Equity MA20"
    else:
        equity_status = "Drawdown Control"

    return {
        "total_trades": len(journal_df),
        "total_pl": total_pl,
        "win_rate": (journal_df["Net P/L"] > 0).mean() * 100,
        "avg_r": journal_df["R Multiple"].mean(),
        "expectancy": journal_df["Net P/L"].mean(),
        "profit_factor": profit_factor,
        "max_drawdown": journal_df["Drawdown"].min(),
        "max_drawdown_pct": journal_df["Drawdown %"].min(),
        "current_equity": current_equity,
        "equity_ma20": equity_ma20,
        "equity_status": equity_status,
    }


def render_metric(label, value):
    st.metric(label, value)


def render_market_tab(market_file, journal_metrics):
    st.subheader("Market Regime")
    market_raw = load_uploaded_csv(market_file)
    if market_raw is None:
        st.info("Upload a market regime CSV in the sidebar, or download the template from the Templates tab.")
        return

    market_df, missing_cols = prepare_market_data(market_raw)
    if missing_cols:
        st.error(f"Missing required market columns: {', '.join(missing_cols)}")
        return

    equity_status = get_equity_status(journal_metrics)
    regime = build_market_regime(market_df, equity_status)
    latest = regime["latest_rows"].copy()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Primary Index", regime["primary_index"])
    c2.metric("Regime", regime["regime"])
    c3.metric("Exposure", regime["exposure"])
    c4.metric("Distribution Days", regime["distribution_count"])
    c5.metric("Equity Status", equity_status)

    st.markdown("#### Latest Index Action")
    latest_display_cols = [
        "Date",
        "Index",
        "Close",
        "Index Change %",
        "Volume Change %",
        "Volume vs 50D Avg",
        "Above MA50",
        "Above MA200",
        "Action Tag",
    ]
    st.dataframe(latest[latest_display_cols], width="stretch", hide_index=True)

    chart_df = market_df.sort_values("Date")
    selected_indices = st.multiselect(
        "Indices to chart",
        options=sorted(chart_df["Index"].astype(str).unique().tolist()),
        default=sorted(chart_df["Index"].astype(str).unique().tolist())[:5],
    )
    if selected_indices:
        price_df = chart_df[chart_df["Index"].astype(str).isin(selected_indices)]
        fig = px.line(price_df, x="Date", y="Close", color="Index", title="Index Close")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Market Action Counts")
    action_counts = (
        market_df.tail(125)
        .groupby(["Index", "Action Tag"])
        .size()
        .reset_index(name="Count")
    )
    fig_counts = px.bar(action_counts, x="Index", y="Count", color="Action Tag", title="Recent Market Action Tags")
    st.plotly_chart(fig_counts, use_container_width=True)


def render_auto_market_tab(journal_metrics):
    st.subheader("Auto Market Regime")
    source_text = "Uses yfinance first, with direct Yahoo chart JSON as fallback." if yf is not None else "yfinance is not installed; using direct Yahoo chart JSON."
    st.caption(f"Fetches index history and runs the same regime logic as the old market tab. {source_text}")

    default_symbols = "\n".join([f"{name}={symbol}" for name, symbol in AUTO_MARKET_SYMBOLS.items()])
    c1, c2 = st.columns([1, 2])
    period = c1.selectbox("History range", ["6mo", "1y", "2y", "5y"], index=1)
    symbol_text = c2.text_area("Index symbols", value=default_symbols, height=135)
    symbol_map = parse_symbol_map(symbol_text)

    if not symbol_map:
        st.warning("Add at least one index symbol in `Name=YahooSymbol` format.")
        return
    st.caption("Default Yahoo symbols cover the S&P 500, Nasdaq Composite, and Russell 2000. Use ETF symbols such as SPY, QQQ, or IWM if Yahoo index symbols are unreliable.")

    if st.button("Fetch Latest Market Data", type="primary"):
        st.session_state["auto_market_fetch_requested"] = True

    if not st.session_state.get("auto_market_fetch_requested"):
        st.info("Click Fetch Latest Market Data to update the automated market-regime comparison.")
        return

    with st.spinner("Fetching index data..."):
        raw_df, errors = fetch_auto_market_data(symbol_map, period)

    if errors:
        with st.expander("Fetch warnings", expanded=True):
            for error in errors:
                st.warning(error)

    if raw_df.empty:
        st.error("No market data was fetched. Try ETF symbols such as SPY, QQQ, or IWM, or adjust the Yahoo symbols.")
        return

    market_df, missing_cols = prepare_market_data(raw_df)
    if missing_cols:
        st.error(f"Fetched data is missing required columns: {', '.join(missing_cols)}")
        return

    equity_status = get_equity_status(journal_metrics)
    regime = build_market_regime(market_df, equity_status)
    latest = regime["latest_rows"].copy()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Primary Index", regime["primary_index"])
    c2.metric("Auto Regime", regime["regime"])
    c3.metric("Auto Exposure", regime["exposure"])
    c4.metric("Distribution Days", regime["distribution_count"])
    c5.metric("Equity Status", equity_status)

    st.markdown("#### Latest Automated Index Action")
    latest_display_cols = [
        "Date",
        "Index",
        "Data Source",
        "Close",
        "Index Change %",
        "Volume Change %",
        "Volume vs 50D Avg",
        "Above MA50",
        "Above MA200",
        "Action Tag",
    ]
    st.dataframe(latest[latest_display_cols], width="stretch", hide_index=True)

    st.markdown("#### Compare Index Trends")
    selected_indices = st.multiselect(
        "Indices to chart",
        options=sorted(market_df["Index"].astype(str).unique().tolist()),
        default=sorted(market_df["Index"].astype(str).unique().tolist())[:5],
        key="auto_market_indices",
    )
    if selected_indices:
        chart_df = market_df[market_df["Index"].astype(str).isin(selected_indices)].sort_values("Date")
        fig = px.line(chart_df, x="Date", y="Close", color="Index", title="Index Close")
        st.plotly_chart(fig, use_container_width=True)

        latest_norm = chart_df.sort_values(["Index", "Date"]).copy()
        latest_norm["Normalized_Close"] = latest_norm.groupby("Index")["Close"].transform(
            lambda series: series / series.iloc[0] * 100
        )
        fig_norm = px.line(
            latest_norm,
            x="Date",
            y="Normalized_Close",
            color="Index",
            title="Normalized Index Performance",
        )
        st.plotly_chart(fig_norm, use_container_width=True)

    st.markdown("#### Recent Action Counts")
    recent = market_df.sort_values("Date").groupby("Index", group_keys=False).tail(25)
    action_counts = recent.groupby(["Index", "Action Tag"]).size().reset_index(name="Count")
    fig_counts = px.bar(action_counts, x="Index", y="Count", color="Action Tag", title="Last 25 Rows by Index")
    st.plotly_chart(fig_counts, use_container_width=True)


def get_secret_value(key, default=""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def get_auth_secret_value(key, default=""):
    try:
        auth_config = st.secrets.get("auth", {})
        return auth_config.get(key, default)
    except Exception:
        return default


def parse_allowed_google_emails(value):
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = []
    return {
        str(candidate).strip().lower()
        for candidate in candidates
        if str(candidate).strip()
    }


def is_google_auth_configured():
    required_fields = [
        "redirect_uri",
        "cookie_secret",
        "client_id",
        "client_secret",
        "server_metadata_url",
    ]
    return all(get_auth_secret_value(field) for field in required_fields)


def is_google_login_required():
    configured_value = get_secret_value("require_google_login", "")
    if isinstance(configured_value, bool):
        return configured_value
    if str(configured_value).strip():
        return str(configured_value).strip().lower() in {"1", "true", "yes", "on"}
    return is_google_auth_configured()


def current_user_email():
    try:
        return str(st.user.get("email", "")).strip().lower()
    except Exception:
        return str(getattr(st.user, "email", "")).strip().lower()


def render_google_login_gate():
    if not is_google_login_required():
        return True

    if not is_google_auth_configured():
        st.error(
            "Google login is required but `[auth]` secrets are incomplete. "
            "Add redirect URI, cookie secret, Google client ID, client secret, and server metadata URL."
        )
        return False

    allowed_emails = parse_allowed_google_emails(get_secret_value("allowed_google_emails", []))
    if not allowed_emails:
        st.error(
            "Google login is enabled, but no authorized email is configured. "
            "Add `allowed_google_emails = [\"you@example.com\"]` to Streamlit secrets."
        )
        return False

    if not st.user.is_logged_in:
        st.title("US Trading Workflow Dashboard")
        st.caption("Private dashboard. Sign in with an authorized Google account to continue.")
        st.button("Log in with Google", type="primary", on_click=st.login)
        return False

    email = current_user_email()
    if email not in allowed_emails:
        st.error(f"`{email or 'Unknown account'}` is not authorized for this dashboard.")
        st.button("Log out", on_click=st.logout)
        return False

    with st.sidebar:
        st.caption(f"Signed in as {email}")
        st.button("Log out", on_click=st.logout)
    return True


def first_valid_value(*values, default=None):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return default


def option_index(options, value, default=0):
    return options.index(value) if value in options else default


def render_exposure_gauge(final_exposure_pct):
    bands = [
        ("Defensive", 25, "#ef4444"),
        ("Cautious", 35, "#f59e0b"),
        ("Constructive", 40, "#22c55e"),
        ("Margin zone", 20, "#8b5cf6"),
    ]
    fig = go.Figure()
    start = 0
    for label, width, color in bands:
        fig.add_trace(
            go.Bar(
                x=[width],
                y=["Exposure"],
                base=[start],
                orientation="h",
                name=label,
                marker_color=color,
                opacity=0.55,
                hovertemplate=f"{label}: {start}-{start + width}%<extra></extra>",
            )
        )
        start += width
    fig.add_vline(
        x=final_exposure_pct,
        line_color="#111827",
        line_width=4,
        annotation_text=f"{final_exposure_pct:.0f}%",
        annotation_position="top",
    )
    fig.update_layout(
        title="Recommended Exposure Gauge",
        barmode="stack",
        xaxis=dict(range=[0, 120], ticksuffix="%"),
        yaxis=dict(showticklabels=False),
        height=220,
        margin=dict(l=20, r=20, t=50, b=30),
        showlegend=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_scorecard_equity_chart(portfolio_df, scorecard_input, performance_regime):
    if portfolio_df is not None and not portfolio_df.empty and "Total Equity NAV" in portfolio_df.columns:
        chart_df = portfolio_df.dropna(subset=["Total Equity NAV"]).copy()
        if chart_df.empty:
            chart_df = None
    else:
        chart_df = None

    if chart_df is None:
        chart_df = pd.DataFrame(
            {
                "Date": pd.date_range(end=date.today(), periods=4),
                "NAV": [
                    scorecard_input.ema50,
                    scorecard_input.ema20,
                    scorecard_input.ema10,
                    scorecard_input.nav,
                ],
                "EMA10": [scorecard_input.ema10] * 4,
                "EMA20": [scorecard_input.ema20] * 4,
                "EMA50": [scorecard_input.ema50] * 4,
            }
        )
        nav_col = "NAV"
        ema_cols = ["EMA10", "EMA20", "EMA50"]
        chart_df["Chart Date"] = chart_df["Date"].dt.strftime("%Y-%m-%d")
    else:
        nav_col = "Total Equity NAV"
        ema_cols = [
            col
            for col in ["Total Equity NAV EMA10", "Total Equity NAV EMA20", "Total Equity NAV EMA50"]
            if col in chart_df.columns
        ]
        chart_df["Chart Date"] = pd.to_datetime(chart_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        chart_df = chart_df.dropna(subset=["Chart Date"])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["Chart Date"],
            y=chart_df[nav_col],
            mode="lines+markers",
            name="NAV",
            line=dict(color="#60a5fa", width=3),
            marker=dict(color="#93c5fd", size=6),
            hovertemplate="%{x}<br>NAV: %{y:.2f}<extra></extra>",
        )
    )
    ema_colors = {
        "EMA10": "#facc15",
        "EMA20": "#22c55e",
        "EMA50": "#ef4444",
        "Total Equity NAV EMA10": "#facc15",
        "Total Equity NAV EMA20": "#22c55e",
        "Total Equity NAV EMA50": "#ef4444",
    }
    for col in ema_cols:
        label = col.replace("Total Equity NAV ", "NAV ")
        fig.add_trace(
            go.Scatter(
                x=chart_df["Chart Date"],
                y=chart_df[col],
                mode="lines",
                name=label,
                line=dict(color=ema_colors.get(col, "#f8fafc"), width=2.5),
                hovertemplate=f"%{{x}}<br>{label}: %{{y:.2f}}<extra></extra>",
            )
        )
    fig.update_layout(
        title=f"NAV / EMA Trend - {performance_regime}",
        xaxis_title="",
        yaxis_title="NAV",
        height=360,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#f8fafc"),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#020617", bordercolor="#64748b", font=dict(color="#f8fafc", size=14)),
        xaxis=dict(type="category", gridcolor="rgba(148, 163, 184, 0.16)"),
        yaxis=dict(title="NAV", gridcolor="rgba(148, 163, 184, 0.22)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_portfolio_log_tab():
    st.subheader("Equity Curve")
    st.caption("Connect your Google Form response sheet to track equity trend and exposure.")
    form_url = get_secret_value("portfolio_form_url", DEFAULT_PORTFOLIO_FORM_URL)
    if form_url:
        st.markdown(f"[Open daily portfolio log form]({form_url})")

    default_url = get_secret_value("portfolio_sheet_csv_url", DEFAULT_PORTFOLIO_SHEET_URL)
    source_tab, mapping_tab = st.tabs(["Dashboard", "Column Mapping Help"])

    with mapping_tab:
        st.markdown("#### Suggested Google Form Fields")
        st.write("Your Google Form response sheet can use any column names, but these names will auto-map well:")
        suggested = pd.DataFrame(
            {
                "Purpose": [
                    "Date",
                    "US market value",
                    "Cash",
                    "Unrealized gain/loss",
                    "US exposure value",
                    "Non-US exposure value",
                    "NAV",
                ],
                "Good column names": [
                    "Timestamp or Date",
                    "US Market Value (USD)",
                    "Cash (USD)",
                    "Unrealized gain % (US) or Unrealized Gain",
                    "US Exposure",
                    "Non-US Exposure",
                    "US NAV",
                ],
            }
        )
        st.dataframe(suggested, width="stretch", hide_index=True)
        st.write("For Streamlit Cloud later, put your CSV/export URL in `.streamlit/secrets.toml` as:")
        st.code('portfolio_sheet_csv_url = "https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=0"', language="toml")

    with source_tab:
        sheet_url = default_url

        if not sheet_url:
            st.info("Paste your Google Sheet URL to start.")
            return pd.DataFrame(), {}

        try:
            raw_df, _source_name = load_portfolio_source(sheet_url, None)
        except Exception as exc:
            st.error(f"Could not load portfolio log: {exc}")
            st.write("For Google Sheets, use a published CSV/export URL or a sheet that the app can access.")
            return pd.DataFrame(), {}

        if raw_df.empty:
            st.warning("Portfolio log is empty.")
            return pd.DataFrame(), {}

        columns = raw_df.columns.tolist()
        is_default_portfolio_sheet = google_sheet_id_from_url(sheet_url) == DEFAULT_PORTFOLIO_SHEET_ID

        detected = {
            key: detect_column(columns, candidates)
            for key, candidates in PORTFOLIO_COLUMN_CANDIDATES.items()
        }

        def column_selector(container, label, key):
            options = [""] + columns
            detected_col = detected.get(key) or ""
            index = options.index(detected_col) if detected_col in options else 0
            return container.selectbox(label, options=options, index=index, key=f"portfolio_map_{key}") or None

        with st.expander("Column Mapping", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            date_col = c1.selectbox(
                "Date / Timestamp",
                options=[""] + columns,
                index=([""] + columns).index(detected.get("date")) if detected.get("date") in columns else 0,
                key="portfolio_map_date",
            ) or None
            market_value_col = c2.selectbox(
                "US Market Value",
                options=[""] + columns,
                index=([""] + columns).index(detected.get("market_value")) if detected.get("market_value") in columns else 0,
                key="portfolio_map_market_value",
            ) or None
            cash_col = c3.selectbox(
                "Cash",
                options=[""] + columns,
                index=([""] + columns).index(detected.get("cash")) if detected.get("cash") in columns else 0,
                key="portfolio_map_cash",
            ) or None
            nav_col = c4.selectbox(
                "NAV",
                options=[""] + columns,
                index=([""] + columns).index(detected.get("nav")) if detected.get("nav") in columns else 0,
                key="portfolio_map_nav",
            ) or None

            c5, c6, c7, c8 = st.columns(4)
            unrealized_col = column_selector(c5, "Unrealized Gain", "unrealized")
            us_exposure_value_col = column_selector(c6, "US Exposure Value", "us_exposure_value")
            other_exposure_value_col = column_selector(c7, "Non-US Exposure Value", "other_exposure_value")
            equity_col = column_selector(c8, "Total Equity Fallback", "equity")
        exposure_col = None
        other_exposure_col = None

        column_map = {
            "date": date_col,
            "market_value": market_value_col,
            "equity": equity_col,
            "exposure": exposure_col,
            "us_exposure_value": us_exposure_value_col,
            "other_exposure": other_exposure_col,
            "other_exposure_value": other_exposure_value_col,
            "unrealized": unrealized_col,
            "holding_us": None,
            "holding_other": None,
            "cash": cash_col,
            "nav": nav_col,
        }
        if is_default_portfolio_sheet:
            default_sheet_map = {
                "date": "Date",
                "market_value": "US Market Value (USD)",
                "cash": "Cash (USD)",
                "unrealized": "Unrealized gain % (US)",
                "us_exposure_value": "US Exposure",
                "other_exposure_value": "Non-US Exposure",
                "nav": "US NAV",
                "equity": None,
                "exposure": None,
                "other_exposure": None,
                "holding_us": None,
                "holding_other": None,
            }
            column_map.update({key: value for key, value in default_sheet_map.items() if value is None or value in columns})
        portfolio_df = prepare_default_portfolio_log(raw_df) if is_default_portfolio_sheet else pd.DataFrame()
        if portfolio_df.empty:
            portfolio_df = prepare_portfolio_log(raw_df, column_map)

        if portfolio_df.empty:
            st.warning("Select at least Date/Timestamp and Total Equity columns to build the portfolio log.")
            with st.expander("Raw data preview"):
                st.dataframe(raw_df.head(20), width="stretch")
            return pd.DataFrame(), {}

        latest = get_latest_portfolio_record(portfolio_df)
        st.markdown("#### Current Portfolio Status")
        status_date = latest.get("Date")
        status_date_text = status_date.strftime("%Y-%m-%d") if hasattr(status_date, "strftime") else str(status_date)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Latest Date", status_date_text)
        m2.metric("Total Equity", f"{latest.get('Total Equity', 0):,.0f}")
        m3.metric("Total Equity NAV", f"{latest.get('Total Equity NAV', 0):,.2f}")
        m4.metric("Unrealized Gain", f"{latest.get('Unrealized Gain', 0):.2f}%")

        e1, e2, e3, e4 = st.columns(4)
        e1.metric("US Market Value", f"{latest.get('US Market Value', 0):,.0f}")
        e2.metric("Cash", f"{latest.get('Cash', 0):,.0f}")
        e3.metric("US Exposure", f"{latest.get('US Exposure %', 0):.1f}%")
        e4.metric("Non-US Exposure", f"{latest.get('Non-US Exposure %', 0):.1f}%")

        latest_pretrade = load_latest_pretrade_snapshot()
        latest_expected_exposure = pd.NA
        if latest_pretrade and "Expected Exposure" in latest_pretrade:
            latest_expected_exposure = pd.to_numeric(
                pd.Series([latest_pretrade.get("Expected Exposure")]),
                errors="coerce",
            ).iloc[0]
        current_exposure_value = number_input_value(latest.get("Position Exposure %"))
        exposure_gap = (
            current_exposure_value - float(latest_expected_exposure)
            if pd.notna(latest_expected_exposure)
            else pd.NA
        )
        if pd.isna(exposure_gap):
            exposure_status = "No plan"
            exposure_status_delta = None
        elif exposure_gap > 5:
            exposure_status = "Overexposure"
            exposure_status_delta = f"{exposure_gap:+.1f}% vs expected"
        elif exposure_gap < -5:
            exposure_status = "Underexposure"
            exposure_status_delta = f"{exposure_gap:+.1f}% vs expected"
        else:
            exposure_status = "In line"
            exposure_status_delta = f"{exposure_gap:+.1f}% vs expected"

        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("Total Exposure", f"{current_exposure_value:.1f}%")
        t2.metric(
            "Expected Exposure",
            f"{float(latest_expected_exposure):.1f}%" if pd.notna(latest_expected_exposure) else "-",
        )
        t3.metric("Exposure Status", exposure_status, exposure_status_delta)
        t4.metric("Drawdown", f"{latest.get('Equity Drawdown %', 0):.2f}%")
        t5.metric("Records", f"{len(portfolio_df):,}")

        curve_col = "Total Equity NAV"
        chart_df = portfolio_df.dropna(subset=[curve_col]).copy()
        chart_df["Chart Date"] = pd.to_datetime(chart_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        chart_df = chart_df.dropna(subset=["Chart Date"])
        equity_fig = go.Figure()
        if "Position Exposure %" in chart_df.columns:
            exposure_max = chart_df["Position Exposure %"].dropna().max()
            exposure_range = max(100, float(exposure_max) * 1.25) if pd.notna(exposure_max) else 100
            equity_fig.add_trace(
                go.Bar(
                    x=chart_df["Chart Date"],
                    y=chart_df["Position Exposure %"],
                    name="Total Exposure %",
                    marker_color="rgba(148, 163, 184, 0.35)",
                    yaxis="y2",
                )
            )
        else:
            exposure_range = 100

        equity_fig.add_trace(
            go.Scatter(
                x=chart_df["Chart Date"],
                y=chart_df[curve_col],
                mode="lines+markers",
                name="Total Equity NAV",
                line=dict(color="#60a5fa", width=3),
                marker=dict(color="#93c5fd", size=6),
                hovertemplate="%{x}<br>Total Equity NAV: %{y:.2f}<extra></extra>",
            )
        )
        ema_colors = {10: "#facc15", 20: "#22c55e", 50: "#ef4444"}
        for span in [10, 20, 50]:
            ema_col = f"Total Equity NAV EMA{span}"
            if ema_col in chart_df.columns:
                equity_fig.add_trace(
                    go.Scatter(
                        x=chart_df["Chart Date"],
                        y=chart_df[ema_col],
                        mode="lines",
                        name=f"NAV EMA{span}",
                        line=dict(color=ema_colors[span], width=2.5),
                        hovertemplate=f"%{{x}}<br>NAV EMA{span}: %{{y:.2f}}<extra></extra>",
                    )
                )
        equity_fig.update_layout(
            title="Total Equity NAV with EMA 10 / 20 / 50 and Exposure Background",
            xaxis_title="",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#f8fafc"),
            hovermode="x unified",
            hoverlabel=dict(bgcolor="#020617", bordercolor="#64748b", font=dict(color="#f8fafc", size=14)),
            yaxis=dict(title="Total Equity NAV", gridcolor="rgba(148, 163, 184, 0.22)"),
            yaxis2=dict(
                title="Total Exposure %",
                overlaying="y",
                side="right",
                range=[0, exposure_range],
                showgrid=False,
            ),
            xaxis=dict(gridcolor="rgba(148, 163, 184, 0.16)", type="category"),
            bargap=0.15,
        )
        st.plotly_chart(equity_fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            drawdown_df = portfolio_df.dropna(subset=["Date", "Equity Drawdown %"]).copy()
            drawdown_df["Date"] = pd.to_datetime(drawdown_df["Date"], errors="coerce")
            drawdown_df = drawdown_df.dropna(subset=["Date"])
            if not drawdown_df.empty:
                drawdown_df["Chart Date"] = drawdown_df["Date"].dt.strftime("%Y-%m-%d")
                drawdown_fig = go.Figure()
                drawdown_fig.add_trace(
                    go.Scatter(
                        x=drawdown_df["Chart Date"],
                        y=drawdown_df["Equity Drawdown %"],
                        mode="lines",
                        name="Equity Drawdown %",
                        line=dict(color="#38bdf8", width=2.5),
                        fill="tozeroy",
                        fillcolor="rgba(56, 189, 248, 0.20)",
                        hovertemplate="%{x}<br>Drawdown: %{y:.2f}%<extra></extra>",
                    )
                )
                drawdown_fig.add_hline(
                    y=-5,
                    line_dash="dash",
                    line_color="#f87171",
                    annotation_text="-5% DD threshold",
                    annotation_position="bottom right",
                )

                current_month = pd.Timestamp(date.today()).to_period("M")
                month_drawdown_df = drawdown_df[drawdown_df["Date"].dt.to_period("M") == current_month]
                month_note_prefix = "Largest DD this month"
                if month_drawdown_df.empty:
                    latest_month = drawdown_df["Date"].dt.to_period("M").max()
                    month_drawdown_df = drawdown_df[drawdown_df["Date"].dt.to_period("M") == latest_month]
                    month_note_prefix = "Largest DD in latest data month"
                if not month_drawdown_df.empty:
                    worst_idx = month_drawdown_df["Equity Drawdown %"].idxmin()
                    worst_dd = float(month_drawdown_df.loc[worst_idx, "Equity Drawdown %"])
                    worst_date = drawdown_df.loc[worst_idx, "Date"]
                    month_label = worst_date.strftime("%b %Y") if pd.notna(worst_date) else ""
                    drawdown_fig.add_annotation(
                        x=0.01,
                        y=0.08,
                        xref="paper",
                        yref="paper",
                        text=f"{month_note_prefix} ({month_label}): {worst_dd:.2f}% on {worst_date:%Y-%m-%d}",
                        showarrow=False,
                        align="left",
                        bgcolor="rgba(15, 23, 42, 0.88)",
                        bordercolor="#475569",
                        borderwidth=1,
                        font=dict(color="#f8fafc", size=13),
                    )

                drawdown_fig.update_layout(
                    title="Equity Drawdown %",
                    xaxis_title="",
                    yaxis_title="Drawdown %",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#f8fafc"),
                    hovermode="x unified",
                    hoverlabel=dict(bgcolor="#020617", bordercolor="#64748b", font=dict(color="#f8fafc", size=13)),
                    xaxis=dict(gridcolor="rgba(148, 163, 184, 0.16)", type="category"),
                    yaxis=dict(gridcolor="rgba(148, 163, 184, 0.22)", zerolinecolor="rgba(248, 250, 252, 0.28)"),
                    showlegend=False,
                )
                st.plotly_chart(drawdown_fig, use_container_width=True)
            else:
                st.info("Need NAV data to show equity drawdown.")
        with c2:
            exposure_cols = [
                col for col in ["US Exposure %", "Non-US Exposure %"] if col in portfolio_df.columns
            ]
            has_unrealized = "Unrealized Gain" in portfolio_df.columns
            if exposure_cols or has_unrealized:
                trend_cols = exposure_cols + (["Unrealized Gain"] if has_unrealized else [])
                trend_df = portfolio_df[["Date"] + trend_cols].copy()
                trend_df["Date"] = pd.to_datetime(trend_df["Date"], errors="coerce")
                trend_df = trend_df.dropna(subset=["Date"])
                trend_df["Chart Date"] = trend_df["Date"].dt.strftime("%Y-%m-%d")
                trend_fig = go.Figure()
                exposure_colors = {
                    "US Exposure %": "#60a5fa",
                    "Non-US Exposure %": "#a78bfa",
                }
                for col in exposure_cols:
                    trend_fig.add_trace(
                        go.Bar(
                            x=trend_df["Chart Date"],
                            y=trend_df[col],
                            name=col,
                            marker_color=exposure_colors.get(col, "#94a3b8"),
                            opacity=0.78,
                            hovertemplate=f"%{{x}}<br>{col}: %{{y:.2f}}%<extra></extra>",
                        )
                    )
                if has_unrealized:
                    trend_fig.add_trace(
                        go.Scatter(
                            x=trend_df["Chart Date"],
                            y=trend_df["Unrealized Gain"],
                            mode="lines+markers",
                            name="Unrealized Gain",
                            line=dict(color="#22c55e", width=2.8),
                            marker=dict(color="#86efac", size=5),
                            yaxis="y2",
                            hovertemplate="%{x}<br>Unrealized Gain: %{y:.2f}%<extra></extra>",
                        )
                    )
                trend_fig.update_layout(
                    title="Exposure / Unrealized Trend",
                    xaxis_title="",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#f8fafc"),
                    hovermode="x unified",
                    hoverlabel=dict(bgcolor="#020617", bordercolor="#64748b", font=dict(color="#f8fafc", size=13)),
                    yaxis=dict(title="Exposure %", gridcolor="rgba(148, 163, 184, 0.22)"),
                    yaxis2=dict(title="Unrealized %", overlaying="y", side="right", showgrid=False),
                    xaxis=dict(gridcolor="rgba(148, 163, 184, 0.16)", type="category"),
                    barmode="stack",
                    bargap=0.2,
                )
                st.plotly_chart(trend_fig, use_container_width=True)
            else:
                st.info("Map Position Exposure % or Unrealized Gain to show this trend chart.")

        render_risk_behavior_section(portfolio_df)

        st.markdown("#### Equity Curve Data Table")
        display_portfolio_df = portfolio_df.sort_values("Date", ascending=False).copy()
        if "Date" in display_portfolio_df.columns:
            display_portfolio_df["Date"] = pd.to_datetime(display_portfolio_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        st.dataframe(display_portfolio_df, width="stretch", hide_index=True, height=360)
        st.download_button(
            "Export Equity Curve CSV",
            data=portfolio_df.to_csv(index=False),
            file_name="portfolio_log_prepared.csv",
            mime="text/csv",
        )
        return portfolio_df, latest

    return pd.DataFrame(), {}


def render_pretrade_tab(latest_portfolio=None, portfolio_df=None):
    st.subheader("Exposure and position sizing")
    init_journal_db()
    if is_supabase_pretrade_enabled():
        st.caption(
            f"Daily snapshots are saved online in Supabase table `{get_supabase_pretrade_table_name()}`."
        )
    else:
        st.caption(f"Daily snapshots are saved locally in `{JOURNAL_DB_PATH}`.")

    dashboard_tab, history_tab = st.tabs(["Dashboard", "History"])
    latest = load_latest_pretrade_snapshot()
    latest_portfolio = latest_portfolio or {}

    with dashboard_tab:
        st.markdown("#### Exposure Scorecard")
        latest_nav = number_input_value(
            first_valid_value(latest_portfolio.get("Total Equity NAV"), latest_portfolio.get("NAV"), 100)
        ) or 100.0
        ema10_default = number_input_value(latest_portfolio.get("Total Equity NAV EMA10")) or latest_nav
        ema20_default = number_input_value(latest_portfolio.get("Total Equity NAV EMA20")) or latest_nav
        ema50_default = number_input_value(latest_portfolio.get("Total Equity NAV EMA50")) or latest_nav
        ema10_rising_value = latest_portfolio.get("Total Equity NAV EMA10 Rising")
        ema10_rising_default = True
        if ema10_rising_value is not None:
            try:
                if not pd.isna(ema10_rising_value):
                    ema10_rising_default = bool(ema10_rising_value)
            except (TypeError, ValueError):
                ema10_rising_default = bool(ema10_rising_value)
        drawdown_default = calculate_recent_max_drawdown_pct(portfolio_df)
        if drawdown_default <= 0:
            drawdown_default = abs(number_input_value(latest_portfolio.get("Equity Drawdown %")))

        st.markdown("##### Inputs")
        p1, p2, p3, p4, p5, p6 = st.columns([1.1, 1, 1, 1, 1, 1])
        base_mode = p1.selectbox(
            "Base mode",
            BASE_MODE_OPTIONS,
            index=option_index(BASE_MODE_OPTIONS, latest.get("Base Mode"), default=1),
        )
        nav = p2.number_input("NAV", min_value=0.0, value=latest_nav, step=0.25)
        ema10 = p3.number_input("EMA10", min_value=0.0, value=ema10_default, step=0.25)
        ema20 = p4.number_input("EMA20", min_value=0.0, value=ema20_default, step=0.25)
        ema50 = p5.number_input("EMA50", min_value=0.0, value=ema50_default, step=0.25)
        ema10_rising = p6.checkbox("EMA10 rising", value=ema10_rising_default)

        m1, m2 = st.columns([2.4, 1.2])
        market_trend_condition = m1.selectbox("Market trend condition", MARKET_TREND_OPTIONS)
        trend_regime_name = MARKET_TREND_RULES[market_trend_condition][0]
        m2.metric("Trend regime", trend_regime_name)

        r1, r2, r3 = st.columns([1.1, 1.4, 1.1])
        market_health = r1.selectbox("Market health", MARKET_HEALTH_OPTIONS)
        pt_ftd = r2.selectbox("PT / FTD", PT_FTD_OPTIONS)
        distribution_days = r3.number_input(
            "DD in 25d",
            min_value=0,
            max_value=10,
            value=int(number_input_value(latest.get("Distribution Days"))),
            step=1,
        )

        v1, v2 = st.columns([2.4, 1.1])
        volatility_condition = v1.selectbox("Volatility / ATR condition", VOLATILITY_OPTIONS)
        personal_drawdown_pct = v2.number_input(
            "Personal drawdown %",
            min_value=0.0,
            max_value=100.0,
            value=drawdown_default,
            step=0.25,
        )

        d1, d2 = st.columns(2)
        stalling_days = d1.number_input("Stalling days (optional)", min_value=0, max_value=10, value=0, step=1)
        bad_up_days = d2.number_input("Bad up days (optional)", min_value=0, max_value=10, value=0, step=1)

        scorecard_input = ExposureScorecardInput(
            nav=nav,
            ema10=ema10,
            ema20=ema20,
            ema50=ema50,
            ema10_rising=ema10_rising,
            market_trend_condition=market_trend_condition,
            market_health=market_health,
            pt_ftd=pt_ftd,
            volatility_condition=volatility_condition,
            distribution_days=distribution_days,
            personal_drawdown_pct=personal_drawdown_pct,
            base_mode=base_mode,
            stalling_days=stalling_days,
            bad_up_days=bad_up_days,
        )
        scorecard_result = calculate_exposure_scorecard(scorecard_input)
        raw_exposure = scorecard_result.raw_exposure_pct
        capped_exposure = scorecard_result.final_exposure_pct
        performance = scorecard_result.performance_regime
        ma200 = (
            ">SMA200d"
            if market_trend_condition
            in {
                "Index > EMA21 and EMA21 > SMA50 and Index > SMA200",
                "Index < EMA21 and EMA21 > SMA50 and Index > SMA200",
                "Index > SMA200 and EMA21 < SMA50",
                "Index < EMA21 and Index < SMA50 and Index > SMA200",
            }
            else "<SMA200d"
        )
        trend = scorecard_result.market_trend_regime
        pt = pt_ftd

        if min(nav, ema10, ema20, ema50) <= 0:
            st.warning("Enter NAV and EMA values above zero for reliable performance-regime detection.")

        st.markdown("##### Output")
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Recommended Exposure", f"{scorecard_result.final_exposure_pct:.0f}%")
        o2.metric("Raw Exposure", f"{scorecard_result.raw_exposure_pct:.1f}%")
        o3.metric("Final After Caps", f"{scorecard_result.unrounded_final_exposure_pct:.1f}%")
        o4.metric("Margin Allowed", "Yes" if scorecard_result.margin_allowed else "No")

        o5, o6, o7, o8 = st.columns(4)
        o5.metric("Exposure Band", scorecard_result.exposure_band_label)
        o6.metric("Risk Regime", scorecard_result.risk_regime)
        o7.metric("Active Limiting Cap", scorecard_result.active_limiting_cap)
        o8.metric("Biggest Reducer", scorecard_result.biggest_reducer)

        st.write(scorecard_result.explanation)
        render_exposure_gauge(scorecard_result.final_exposure_pct)

        breakdown_df = pd.DataFrame(
            [
                {
                    "Factor": item.factor,
                    "Selected state": item.selected_state,
                    "Multiplier": f"{item.multiplier:.2f}",
                    "Cap": f"{item.cap * 100:.0f}%",
                    "Contribution / comment": item.comment,
                }
                for item in scorecard_result.breakdown
            ]
        )
        st.markdown("##### Breakdown")
        st.dataframe(breakdown_df, width="stretch", hide_index=True)
        render_scorecard_equity_chart(portfolio_df, scorecard_input, scorecard_result.performance_regime)

        snapshot_date = date_input_value(first_valid_value(latest_portfolio.get("Date"), latest.get("Date")))
        holding_us = number_input_value(
            first_valid_value(
                latest_portfolio.get("Holding US"),
                latest_portfolio.get("US Market Value"),
                latest.get("Holding US"),
            )
        )
        holding_other = number_input_value(
            first_valid_value(
                latest_portfolio.get("Holding Non-US"),
                latest_portfolio.get("Non-US Exposure Value"),
                latest.get("Holding Non-US"),
            )
        )
        cash = number_input_value(first_valid_value(latest_portfolio.get("Cash"), latest.get("Cash")))
        component_total = holding_us + holding_other + cash
        total_equity = number_input_value(
            first_valid_value(latest_portfolio.get("Total Equity"), latest.get("Total Equity"), component_total)
        ) or component_total
        invested = holding_us + holding_other
        computed_current_exposure = (invested / total_equity * 100) if total_equity > 0 else 0

        st.markdown("#### Position Size Planning")
        c1, c2, c3, c4 = st.columns(4)
        expected_exposure = c1.number_input(
            "Expected Exposure %",
            min_value=0.0,
            max_value=150.0,
            value=number_input_value(latest.get("Expected Exposure")) or float(capped_exposure),
            step=5.0,
        )
        current_exposure_default = number_input_value(
            first_valid_value(
                latest_portfolio.get("Position Exposure %"),
                latest.get("Current Exposure"),
                computed_current_exposure,
            )
        )
        use_computed_current = c2.checkbox("Use portfolio current exposure", value=True)
        if use_computed_current:
            current_exposure = current_exposure_default
            c2.metric("Current Exposure", f"{current_exposure:.0f}%")
        else:
            current_exposure = c2.number_input(
                "Current Exposure %",
                min_value=0.0,
                max_value=150.0,
                value=current_exposure_default,
                step=1.0,
            )
        today_plan = calculate_today_plan(expected_exposure, current_exposure)
        exposure_gap_pct = expected_exposure - current_exposure
        exposure_gap_amount = total_equity * exposure_gap_pct / 100 if total_equity else 0
        c3.metric("Today Plan", today_plan, f"{exposure_gap_pct:+.0f}% gap")
        c4.metric("Exposure Gap USD", f"{exposure_gap_amount:+,.0f}")

        size_levels = [5, 8, 10, 15]
        risk_levels = [0.10, 0.15, 0.25, 0.35]

        size_df = pd.DataFrame(
            {
                "Port Size %": size_levels,
                "Amount USD": [total_equity * pct / 100 for pct in size_levels],
            }
        )
        risk_df = pd.DataFrame(
            {
                "Risk %": risk_levels,
                "Risk USD": [total_equity * pct / 100 for pct in risk_levels],
            }
        )

        t1, t2 = st.columns(2)
        with t1:
            st.markdown("##### Position Size")
            st.dataframe(
                size_df.style.format({"Port Size %": "{:.2f}%", "Amount USD": "{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )
        with t2:
            st.markdown("##### Risk Amount")
            st.dataframe(
                risk_df.style.format({"Risk %": "{:.2f}%", "Risk USD": "{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )

        st.markdown("#### Risk per Trade")
        rr1, rr2, rr3 = st.columns(3)
        risk_per_trade = rr1.number_input(
            "Risk per Trade",
            min_value=0.0,
            value=number_input_value(latest.get("Risk per Trade")),
            step=100.0,
        )
        stop_loss_pct = rr2.number_input(
            "Stop Loss %",
            min_value=0.0,
            value=number_input_value(latest.get("Stop Loss %")) or 3.0,
            step=0.25,
        )
        position_cost = risk_per_trade / (stop_loss_pct / 100) if stop_loss_pct > 0 else 0
        rr3.metric("Position Cost", f"{position_cost:,.0f}")

        notes = st.text_area("Pre-trading Notes", height=110, value=str(latest.get("Notes", "")) if latest else "")
        if st.button("Save Pre-Trading Snapshot"):
            try:
                save_pretrade_snapshot(
                    {
                        "snapshot_date": normalize_date_value(snapshot_date),
                        "holding_us": holding_us,
                        "holding_other": holding_other,
                        "cash": cash,
                        "total_equity": total_equity,
                        "expected_exposure": expected_exposure,
                        "current_exposure": current_exposure,
                        "today_plan": today_plan,
                        "risk_per_trade": risk_per_trade,
                        "stop_loss_pct": stop_loss_pct,
                        "position_cost": position_cost,
                        "performance_condition": performance,
                        "ma200_condition": ma200,
                        "trend_condition": trend,
                        "pt_condition": pt,
                        "distribution_days": distribution_days,
                        "scorecard_exposure": raw_exposure,
                        "capped_exposure": capped_exposure,
                        "personal_drawdown_pct": personal_drawdown_pct,
                        "notes": notes,
                    }
                )
                st.success("Saved today's pre-trading snapshot.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save pre-trading snapshot: {format_supabase_write_error(exc)}")

        render_portfolio_risk_section(snapshot_date, invested, total_equity)

    with history_tab:
        st.markdown("#### Saved Pre-Trading Snapshots")
        if st.button("Load / Refresh Pre-Trading History", key="load_pretrade_history"):
            st.session_state["show_pretrade_history"] = True
        if not st.session_state.get("show_pretrade_history", False):
            st.info("Click Load / Refresh Pre-Trading History to query saved pre-trading snapshots.")
        else:
            history_limit = st.number_input(
                "Rows to load",
                min_value=25,
                max_value=500,
                value=100,
                step=25,
                key="pretrade_history_limit",
            )
            history_df = load_pretrade_snapshots(limit=int(history_limit))
            if history_df.empty:
                st.info("No pre-trading snapshots saved yet.")
            else:
                st.dataframe(
                    history_df.drop(columns=["Created At", "Updated At"], errors="ignore"),
                    width="stretch",
                    hide_index=True,
                    height=420,
                )
                st.download_button(
                    "Export Pre-Trading History CSV",
                    data=history_df.to_csv(index=False),
                    file_name="pretrade_history_export.csv",
                    mime="text/csv",
                )
        st.divider()
        render_portfolio_risk_history_section()


def portfolio_risk_blank_rows(row_count=5):
    return pd.DataFrame(
        [
            {
                "Stock name": "",
                "Position": 0.0,
                "Avg. cost": 0.0,
                "Last price": 0.0,
                "Stop": 0.0,
                "%ATR": 0.0,
            }
            for _ in range(row_count)
        ],
        columns=PORTFOLIO_RISK_INPUT_COLUMNS,
    )


def format_portfolio_risk_history(history_df):
    if history_df is None or history_df.empty:
        return pd.DataFrame()
    history_df = history_df.copy()
    if "position_heat_pct" not in history_df.columns and "invested_book_heat_pct" in history_df.columns:
        history_df["position_heat_pct"] = history_df["invested_book_heat_pct"]
    if "total_invested" not in history_df.columns and "th_market_value" in history_df.columns:
        history_df["total_invested"] = history_df["th_market_value"]
    if "portfolio_heat_usd" not in history_df.columns and "portfolio_heat_thb" in history_df.columns:
        history_df["portfolio_heat_usd"] = history_df["portfolio_heat_thb"]
    rename_map = {
        "id": "ID",
        "snapshot_date": "Date",
        "total_invested": "Total Invested",
        "total_equity": "Total Equity",
        "total_market_value": "Table Market Value",
        "market_value_gap": "Market Value Gap",
        "market_value_gap_pct": "Market Value Gap %",
        "portfolio_atr_pct": "Portfolio ATR %",
        "position_atr_pct": "Exposure ATR %",
        "portfolio_heat_usd": "Portfolio Heat USD",
        "portfolio_heat_pct": "Portfolio Heat %",
        "position_heat_pct": "Exposure Heat %",
        "heat_regime": "Heat Regime",
        "notes": "Notes",
        "created_at": "Created At",
        "updated_at": "Updated At",
    }
    display_df = history_df.rename(columns=rename_map).copy()
    if "Date" in display_df.columns:
        display_df["Date"] = pd.to_datetime(display_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return display_df


def render_stat_card(container, label, value, detail=""):
    container.markdown(
        f"""
        <div style="padding: 0.25rem 0 0.75rem 0;">
            <div style="font-size: 0.95rem; font-weight: 700; color: #e5e7eb; margin-bottom: 0.35rem;">{label}</div>
            <div style="font-size: 2.35rem; line-height: 1.05; color: #f8fafc;">{value}</div>
            <div style="font-size: 0.95rem; font-weight: 650; color: #93c5fd; margin-top: 0.55rem;">{detail}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_portfolio_risk_section(snapshot_date, total_invested, total_equity):
    st.markdown("#### Current Portfolio Risk")
    storage_label = (
        f"online in Supabase tables `{get_supabase_portfolio_risk_snapshot_table_name()}` / "
        f"`{get_supabase_portfolio_risk_positions_table_name()}`"
        if is_supabase_pretrade_enabled()
        else f"locally in `{JOURNAL_DB_PATH}`"
    )
    st.caption(f"Portfolio risk snapshots are saved {storage_label}.")

    latest_positions, latest_risk_snapshot = load_latest_portfolio_risk_snapshot_from_storage()
    if latest_positions.empty:
        editor_seed = portfolio_risk_blank_rows()
    else:
        editor_seed = prepare_portfolio_risk_input(latest_positions)
        source_date = latest_risk_snapshot.get("snapshot_date")
        if source_date:
            st.caption(f"Loaded latest saved portfolio risk rows from {source_date}.")

    total_invested = number_input_value(total_invested)
    total_equity = number_input_value(total_equity)
    if total_invested <= 0 or total_equity <= 0:
        st.warning("Total Invested and Total Equity from the Equity Curve tab are needed for full risk calculations.")

    edited_rows = st.data_editor(
        editor_seed,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key="portfolio_risk_editor",
        column_config={
            "Stock name": st.column_config.TextColumn("Stock name"),
            "Position": st.column_config.NumberColumn("Position", min_value=0.0, step=100.0, format="%.0f"),
            "Avg. cost": st.column_config.NumberColumn("Avg. cost", min_value=0.0, step=0.01, format="%.2f"),
            "Last price": st.column_config.NumberColumn("Last price", min_value=0.0, step=0.01, format="%.2f"),
            "Stop": st.column_config.NumberColumn("Stop", min_value=0.0, step=0.01, format="%.2f"),
            "%ATR": st.column_config.NumberColumn("%ATR", min_value=0.0, step=0.1, format="%.2f"),
        },
    )

    risk_df, risk_summary = calculate_portfolio_risk(edited_rows, total_invested, total_equity)
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("Portfolio ATR%", f"{risk_summary.portfolio_atr_pct:.2f}%")
    r2.metric("Exposure ATR%", f"{risk_summary.position_atr_pct:.2f}%")
    r3.metric("Portfolio Heat", f"{risk_summary.portfolio_heat_pct:.2f}%")
    r4.metric("Exposure Heat", f"{risk_summary.position_heat_pct:.2f}%")
    r5.metric("Heat Regime", risk_summary.heat_regime)

    recon_delta = f"{risk_summary.market_value_gap_pct:+.1f}% vs Total Invested"

    if not risk_df.empty:
        highest_heat = risk_df.sort_values("Heat (USD)", ascending=False).iloc[0]
        largest_position = risk_df.sort_values("Exposure %", ascending=False).iloc[0]
        c1, c2, c3 = st.columns(3)
        render_stat_card(
            c1,
            "Sum Table Market Value",
            f"{risk_summary.total_market_value:,.0f}",
            recon_delta,
        )
        render_stat_card(
            c2,
            "Highest Heat Stock",
            str(highest_heat["Stock name"]),
            f"{highest_heat['Heat (USD)']:,.0f} USD",
        )
        render_stat_card(
            c3,
            "Largest Position",
            str(largest_position["Stock name"]),
            f"{largest_position['Exposure %']:.1f}% of current exposure",
        )
    else:
        render_stat_card(st, "Sum Table Market Value", f"{risk_summary.total_market_value:,.0f}", recon_delta)

    if risk_df.empty:
        st.info("Enter current holdings to calculate portfolio ATR and heat.")
    else:
        warning_notes = []
        if abs(risk_summary.market_value_gap_pct) > 5:
            warning_notes.append("table market value differs from Total Invested by more than 5%")
        missing_stop_count = int(((risk_df["Position"] > 0) & (risk_df["Stop"] <= 0)).sum())
        if missing_stop_count:
            warning_notes.append(f"{missing_stop_count} position(s) have no stop")
        missing_atr_count = int(((risk_df["Position"] > 0) & (risk_df["%ATR"] <= 0)).sum())
        if missing_atr_count:
            warning_notes.append(f"{missing_atr_count} position(s) have no ATR%")
        if risk_summary.portfolio_heat_pct > 6:
            warning_notes.append("portfolio heat is above the very-aggressive threshold")

        if warning_notes:
            st.warning("Today Risk Check: " + "; ".join(warning_notes) + ".")
        else:
            st.success("Today Risk Check: portfolio risk inputs look complete and within the defined heat bands.")

        st.dataframe(
            risk_df[PORTFOLIO_RISK_DISPLAY_COLUMNS].style.format(
                {
                    "Position": "{:,.0f}",
                    "Avg. cost": "{:,.2f}",
                    "Last price": "{:,.2f}",
                    "Stop": "{:,.2f}",
                    "%ATR": "{:.2f}",
                    "Market value (USD)": "{:,.0f}",
                    "Exposure %": "{:.2f}%",
                    "Heat (USD)": "{:,.0f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    risk_notes = st.text_input(
        "Portfolio risk notes",
        value=str(latest_risk_snapshot.get("notes", "") or "") if latest_risk_snapshot else "",
    )
    if st.button("Save Portfolio Risk Snapshot"):
        if risk_df.empty:
            st.warning("Add at least one position before saving the portfolio risk snapshot.")
        else:
            try:
                save_portfolio_risk_snapshot_to_storage(
                    edited_rows,
                    snapshot_date,
                    total_invested,
                    total_equity,
                    risk_notes,
                )
                st.success("Saved portfolio risk snapshot.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save portfolio risk snapshot: {format_supabase_write_error(exc)}")


def render_portfolio_risk_history_section():
    st.markdown("#### Portfolio Risk History")
    if st.button("Load / Refresh Portfolio Risk History", key="load_portfolio_risk_history"):
        st.session_state["show_portfolio_risk_history"] = True
    if not st.session_state.get("show_portfolio_risk_history", False):
        st.info("Click Load / Refresh Portfolio Risk History to query saved risk snapshots.")
        return

    history_df = format_portfolio_risk_history(load_portfolio_risk_history_from_storage(limit=100))
    if history_df.empty:
        st.info("No portfolio risk snapshots saved yet.")
        return

    history_cols = [
        col
        for col in [
            "Date",
            "Total Invested",
            "Total Equity",
            "Table Market Value",
            "Market Value Gap %",
            "Portfolio ATR %",
            "Exposure ATR %",
            "Portfolio Heat %",
            "Exposure Heat %",
            "Heat Regime",
            "Notes",
        ]
        if col in history_df.columns
    ]
    st.dataframe(history_df[history_cols], width="stretch", hide_index=True, height=240)
    st.download_button(
        "Export Portfolio Risk History CSV",
        data=history_df.to_csv(index=False),
        file_name="portfolio_risk_history_export.csv",
        mime="text/csv",
    )


def render_screening_tab():
    st.subheader("RS Screener")
    screening_file = st.file_uploader("Daily US RS screening CSV", type=["csv"], key="screening_file")
    if screening_file is None:
        st.info("Upload your daily US RS screening CSV here to build the RS dashboard.")
        return None, None

    df, missing_cols, sector_col, rank_columns = prepare_screening_data_from_bytes(screening_file.getvalue())
    if missing_cols:
        st.error(f"Missing required screening columns: {', '.join(missing_cols)}")
        return None, None

    export_filename = export_filename_from_upload(screening_file)

    with st.expander("Data Quality Check", expanded=False):
        numeric_cols = ["Market capitalization", "Price", "Average Volume 60 days"] + RS_COLUMNS
        if "ATR %" in df.columns:
            numeric_cols.append("ATR %")
        quality_df = pd.DataFrame(
            {
                "Column": numeric_cols,
                "Missing Values": [int(df[col].isna().sum()) for col in numeric_cols],
                "Missing %": [round(df[col].isna().mean() * 100, 2) for col in numeric_cols],
            }
        )
        st.dataframe(quality_df, width="stretch", hide_index=True)

    f1, f2, f3, f4 = st.columns(4)
    min_turnover = f1.number_input("Min Avg 60D Turnover", min_value=0, value=20_000_000, step=1_000_000)
    min_score = f2.slider("Minimum RS Rating", min_value=0.0, max_value=100.0, value=80.0)
    max_ema20 = None
    if "Distance from EMA20 %" in df.columns:
        max_ema20 = f3.number_input("Max Distance Above EMA20 %", min_value=0.0, value=25.0, step=1.0)
    else:
        f3.info("EMA20 distance unavailable")

    mcap_categories = sorted(df["Market Cap Size"].dropna().unique().tolist())
    default_mcaps = [
        category
        for category in mcap_categories
        if category.startswith(("4.", "5.", "6."))
    ]
    selected_mcaps = f4.multiselect(
        "Market Cap Size",
        options=mcap_categories,
        default=default_mcaps or [m for m in mcap_categories if m != "Unknown"] or mcap_categories,
    )

    require_min_price_10 = st.checkbox("Price >= 10 USD", value=True)

    f5, f6, f7 = st.columns(3)
    selected_quality = f5.multiselect("Momentum Quality", options=QUALITY_ORDER, default=QUALITY_ORDER)
    priority_options = sorted(df["Screening Priority"].dropna().unique().tolist())
    selected_priority = f6.multiselect("Priority", options=priority_options, default=priority_options)
    selected_atr_ranges = None
    if "ATR Range" in df.columns:
        atr_options = [label for label in ATR_RANGE_ORDER if label in df["ATR Range"].dropna().unique().tolist()]
        default_atr_ranges = [label for label in ["Sweet Spot", "Hot"] if label in atr_options]
        selected_atr_ranges = f7.multiselect(
            "ATR Range",
            options=atr_options,
            default=default_atr_ranges or atr_options,
        )
    else:
        f7.info("ATR range unavailable")

    filtered_df = df[
        (df["Avg 60D Turnover (USD)"] >= min_turnover)
        & (df["RS Composite Rating"] >= min_score)
        & (df["Market Cap Size"].isin(selected_mcaps))
        & (df["Momentum Quality"].isin(selected_quality))
        & (df["Screening Priority"].isin(selected_priority))
    ].copy()
    if require_min_price_10:
        filtered_df = filtered_df[filtered_df["Price"] >= 10].copy()
    if selected_atr_ranges is not None:
        filtered_df = filtered_df[filtered_df["ATR Range"].isin(selected_atr_ranges)].copy()

    if max_ema20 is not None:
        filtered_df = filtered_df[
            filtered_df["Distance from EMA20 %"].isna() | (filtered_df["Distance from EMA20 %"] <= max_ema20)
        ]

    if filtered_df.empty:
        st.warning("No stocks found after applying the current filters.")
        return df, sector_col

    filtered_df = filtered_df.sort_values(by=["Screening Priority", "RS Composite Rating"], ascending=[True, False])

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Stocks Shown", f"{len(filtered_df):,}")
    k2.metric("RS >= 90", f"{(filtered_df['RS Composite Rating'] >= 90).sum():,}")
    k3.metric("Prime Watch", f"{(filtered_df['Screening Priority'] == 'A - Prime Watch').sum():,}")
    k4.metric("Elite / Strong", f"{filtered_df['Momentum Quality'].isin(['Elite Momentum', 'Strong Momentum']).sum():,}")
    k5.metric("Median Turnover", f"{filtered_df['Avg 60D Turnover (USD)'].median():,.0f}")

    st.markdown("#### Momentum Quadrant")
    hover_data = {
        "RS Composite Rating": ":.1f",
        "RS Composite Rating v2": ":.1f",
        "Acceleration Score": ":.1f",
        "Momentum Quality": True,
        "Setup Location": True,
        "Screening Priority": True,
    }
    if "ATR Range" in filtered_df.columns:
        hover_data["ATR Range"] = True
        hover_data["ATR %"] = ":.1f"
    fig = px.scatter(
        filtered_df,
        x="Performance % 1 month Rank",
        y="Performance % 3 months Rank",
        hover_name="Symbol",
        color="Screening Priority",
        symbol="Momentum Quality",
        hover_data=hover_data,
        title="1-Month Rank vs 3-Month Rank",
    )
    fig.add_vline(x=80, line_width=2, line_dash="dash", line_color="gray")
    fig.add_hline(y=80, line_width=2, line_dash="dash", line_color="gray")
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        quality_summary = (
            filtered_df["Momentum Quality"]
            .value_counts()
            .reindex(QUALITY_ORDER, fill_value=0)
            .reset_index()
        )
        quality_summary.columns = ["Momentum Quality", "Count"]
        fig_quality = px.bar(quality_summary, x="Momentum Quality", y="Count", title="Momentum Quality Distribution")
        st.plotly_chart(fig_quality, use_container_width=True)

    with c2:
        priority_summary = filtered_df["Screening Priority"].value_counts().sort_index().reset_index()
        priority_summary.columns = ["Screening Priority", "Count"]
        fig_priority = px.bar(priority_summary, x="Screening Priority", y="Count", title="Screening Priority")
        st.plotly_chart(fig_priority, use_container_width=True)

    sector_summary = build_sector_summary(filtered_df, sector_col)
    if not sector_summary.empty:
        st.markdown("#### Sector Leadership")
        top_sector_cols = [
            sector_col,
            "Leadership Score",
            "Sector_RS_Average",
            "RS_80_Pct",
            "RS_90_Stocks",
            "Elite_Strong_Stocks",
            "Stock_Count",
            "Median_Turnover",
        ]
        st.dataframe(sector_summary[top_sector_cols].head(12), width="stretch", hide_index=True)

        fig_sector = px.bar(
            sector_summary.head(12),
            x=sector_col,
            y="Leadership Score",
            hover_data=["Sector_RS_Average", "RS_80_Pct", "RS_90_Stocks", "Stock_Count"],
            title="Top Sector Leadership Score",
        )
        st.plotly_chart(fig_sector, use_container_width=True)
    else:
        st.info("Sector leadership is skipped because no sector column was found.")

    st.markdown("#### Ranked Stock Table")
    table_limit = st.slider(
        "Rows to display",
        min_value=1,
        max_value=len(filtered_df),
        value=min(100, len(filtered_df)),
        step=1,
        key="rs_table_limit",
    )
    table_df = filtered_df.head(table_limit).copy()
    st.caption(f"Showing top {len(table_df):,} rows for speed. Watchlist exports still use all {len(filtered_df):,} filtered rows.")
    display_cols = ["Symbol"]
    if "Exchange" in table_df.columns:
        display_cols.append("Exchange")
    if sector_col is not None:
        display_cols.append(sector_col)
    for col in [
        "Industry",
        "Market Cap Size",
        "Price",
        "Avg 60D Turnover (USD)",
        "RS Composite Rating",
        "RS Composite Rating v2",
        "Acceleration Score",
        "Momentum Quality",
        "Setup Location",
        "Screening Priority",
        "Distance from 52W High %",
        "Distance from EMA20 %",
        "Distance from EMA50 %",
        "Volume vs 60D Avg",
        "ATR %",
        "ATR Range",
    ]:
        if col in table_df.columns and col not in display_cols:
            display_cols.append(col)
    display_cols += [col for col in rank_columns if col in table_df.columns]

    format_cols = {
        "Price": "{:,.2f}",
        "Avg 60D Turnover (USD)": "{:,.0f}",
        "RS Composite Rating": "{:.1f}",
        "RS Composite Rating v2": "{:.1f}",
        "Acceleration Score": "{:.1f}",
        "Distance from 52W High %": "{:.1f}",
        "Distance from EMA20 %": "{:.1f}",
        "Distance from EMA50 %": "{:.1f}",
        "Volume vs 60D Avg": "{:.2f}",
        "ATR %": "{:.1f}",
    }
    for col in rank_columns:
        format_cols[col] = "{:.1f}"
    rs_style_cols = ["RS Composite Rating", "RS Composite Rating v2"] + rank_columns
    rs_style_cols = [col for col in rs_style_cols if col in table_df.columns]

    try:
        styled_df = table_df[display_cols].style.map(get_rs_color, subset=rs_style_cols).format(format_cols)
    except AttributeError:
        styled_df = table_df[display_cols].style.applymap(get_rs_color, subset=rs_style_cols).format(format_cols)
    st.dataframe(styled_df, width="stretch", height=560)

    st.markdown("#### TradingView Watchlists and Trade Plan")
    w1, w2, w3, w4 = st.columns(4)
    w1.download_button(
        "RS Bucket Watchlist",
        data=generate_bucket_watchlist(filtered_df),
        file_name=export_filename,
        mime="text/plain",
    )
    prime_df = filtered_df[filtered_df["Screening Priority"] == "A - Prime Watch"]
    prime_exchanges = prime_df["Exchange"].tolist() if "Exchange" in prime_df.columns else None
    w2.download_button(
        "Prime Watch",
        data=symbols_to_tv(prime_df["Symbol"].tolist(), prime_exchanges),
        file_name=export_filename.replace(".txt", " Prime.txt"),
        mime="text/plain",
    )
    emerging_df = filtered_df[filtered_df["Momentum Quality"] == "Emerging Momentum"]
    emerging_exchanges = emerging_df["Exchange"].tolist() if "Exchange" in emerging_df.columns else None
    w3.download_button(
        "Emerging Momentum",
        data=symbols_to_tv(emerging_df["Symbol"].tolist(), emerging_exchanges),
        file_name=export_filename.replace(".txt", " Emerging.txt"),
        mime="text/plain",
    )
    w4.download_button(
        "Trade Plan CSV",
        data=build_trade_plan_export(filtered_df, sector_col),
        file_name=export_filename.replace(".txt", " trade plan.csv"),
        mime="text/csv",
    )

    return df, sector_col


def date_input_value(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return date.today()
    return parsed.date()


def number_input_value(value):
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def render_trade_plan_tab(screening_df, sector_col):
    st.subheader("Trade Plan Database")
    init_journal_db()
    st.caption(f"Saved locally at `{JOURNAL_DB_PATH}` in the `trade_plans` table.")

    new_tab, manage_tab, review_tab = st.tabs(["New Plan", "Manage Plans", "Review"])

    with new_tab:
        st.markdown("#### Create Trade Plan")
        selected_symbol = ""
        if screening_df is not None and not screening_df.empty:
            symbol_options = [""] + sorted(screening_df["Symbol"].dropna().astype(str).unique().tolist())
            selected_symbol = st.selectbox("Prefill from uploaded screener", symbol_options)
        prefill = get_prefill_plan_from_screening(screening_df, sector_col, selected_symbol)

        with st.form("new_trade_plan_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            plan_date = c1.date_input("Plan Date", value=date.today())
            symbol = c2.text_input("Symbol", value=selected_symbol).upper().strip()
            side = c3.selectbox("Side", ["Long", "Short"])
            status = c4.selectbox("Status", TRADE_PLAN_STATUSES, index=0)

            c5, c6, c7 = st.columns(3)
            sector = c5.text_input("Sector", value=str(prefill.get("sector", "")))
            setup = c6.text_input("Setup", value=str(prefill.get("setup", "")))
            market_regime = c7.selectbox(
                "Market Regime",
                ["", "Confirmed Uptrend", "Uptrend Under Pressure", "Rally Attempt", "Correction"],
            )

            c8, c9, c10, c11 = st.columns(4)
            current_price = c8.number_input(
                "Current Price",
                min_value=0.0,
                value=number_input_value(prefill.get("current_price")),
                step=0.01,
            )
            entry_trigger = c9.number_input("Entry Trigger", min_value=0.0, value=0.0, step=0.01)
            stop_loss = c10.number_input("Stop Loss", min_value=0.0, value=0.0, step=0.01)
            alert_price = c11.number_input("Alert Price", min_value=0.0, value=0.0, step=0.01)

            c12, c13, c14 = st.columns(3)
            target_1 = c12.number_input("Target 1", min_value=0.0, value=0.0, step=0.01)
            target_2 = c13.number_input("Target 2", min_value=0.0, value=0.0, step=0.01)
            planned_risk = c14.number_input("Planned Risk", min_value=0.0, value=0.0, step=100.0)

            actual_action = st.selectbox("Actual Action", ACTUAL_ACTION_OPTIONS, index=0)
            position_notes = st.text_area("Position Notes", value=str(prefill.get("position_notes", "")), height=110)

            submitted = st.form_submit_button("Save Trade Plan")
            if submitted:
                if not symbol:
                    st.error("Symbol is required.")
                else:
                    save_trade_plan_to_db(
                        {
                            "plan_date": normalize_date_value(plan_date),
                            "symbol": symbol,
                            "side": side,
                            "sector": sector,
                            "setup": setup,
                            "market_regime": market_regime,
                            "current_price": normalize_float_value(current_price),
                            "entry_trigger": normalize_float_value(entry_trigger),
                            "stop_loss": normalize_float_value(stop_loss),
                            "target_1": normalize_float_value(target_1),
                            "target_2": normalize_float_value(target_2),
                            "alert_price": normalize_float_value(alert_price),
                            "planned_risk": normalize_float_value(planned_risk),
                            "actual_action": actual_action,
                            "position_notes": position_notes,
                            "status": status,
                            "linked_trade_id": None,
                        }
                    )
                    st.success(f"Saved trade plan for {symbol}.")
                    st.rerun()

    with manage_tab:
        st.markdown("#### Manage Saved Plans")
        plans_df = load_trade_plans_db()
        if plans_df.empty:
            st.info("No trade plans saved yet.")
        else:
            status_filter = st.multiselect(
                "Status filter",
                options=TRADE_PLAN_STATUSES,
                default=["Watching", "Alert Set", "Triggered", "Open"],
            )
            visible_plans = plans_df[plans_df["Status"].isin(status_filter)] if status_filter else plans_df.copy()
            table_cols = [
                "ID",
                "Plan Date",
                "Symbol",
                "Side",
                "Sector",
                "Setup",
                "Entry Trigger",
                "Stop Loss",
                "Target 1",
                "Alert Price",
                "Planned Risk",
                "Actual Action",
                "Status",
                "Linked Trade ID",
            ]
            st.dataframe(
                visible_plans[[col for col in table_cols if col in visible_plans.columns]],
                width="stretch",
                hide_index=True,
                height=280,
            )

            plan_options = [
                f"{int(row['ID'])} | {row['Symbol']} | {row.get('Status', '')}"
                for _, row in plans_df.sort_values("ID", ascending=False).iterrows()
            ]
            selected_plan = st.selectbox("Plan to edit", plan_options)
            selected_plan_id = int(selected_plan.split("|")[0].strip())
            selected_row = plans_df[plans_df["ID"] == selected_plan_id].iloc[0]

            with st.form("edit_trade_plan_form"):
                c1, c2, c3, c4 = st.columns(4)
                plan_date = c1.date_input(
                    "Plan Date",
                    value=date_input_value(selected_row.get("Plan Date")),
                    key="edit_plan_date",
                )
                symbol = c2.text_input("Symbol", value=str(selected_row.get("Symbol", ""))).upper().strip()
                side_default = 1 if str(selected_row.get("Side", "Long")) == "Short" else 0
                side = c3.selectbox("Side", ["Long", "Short"], index=side_default, key="edit_plan_side")
                status_value = str(selected_row.get("Status", "Watching"))
                status_index = TRADE_PLAN_STATUSES.index(status_value) if status_value in TRADE_PLAN_STATUSES else 0
                status = c4.selectbox("Status", TRADE_PLAN_STATUSES, index=status_index, key="edit_plan_status")

                c5, c6, c7 = st.columns(3)
                sector = c5.text_input("Sector", value=str(selected_row.get("Sector", "")))
                setup = c6.text_input("Setup", value=str(selected_row.get("Setup", "")))
                regime_options = ["", "Confirmed Uptrend", "Uptrend Under Pressure", "Rally Attempt", "Correction"]
                regime_value = str(selected_row.get("Market Regime", ""))
                regime_index = regime_options.index(regime_value) if regime_value in regime_options else 0
                market_regime = c7.selectbox("Market Regime", regime_options, index=regime_index, key="edit_plan_regime")

                c8, c9, c10, c11 = st.columns(4)
                current_price = c8.number_input(
                    "Current Price",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Current Price")),
                    step=0.01,
                    key="edit_current",
                )
                entry_trigger = c9.number_input(
                    "Entry Trigger",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Entry Trigger")),
                    step=0.01,
                    key="edit_entry",
                )
                stop_loss = c10.number_input(
                    "Stop Loss",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Stop Loss")),
                    step=0.01,
                    key="edit_stop",
                )
                alert_price = c11.number_input(
                    "Alert Price",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Alert Price")),
                    step=0.01,
                    key="edit_alert",
                )

                c12, c13, c14 = st.columns(3)
                target_1 = c12.number_input(
                    "Target 1",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Target 1")),
                    step=0.01,
                    key="edit_target_1",
                )
                target_2 = c13.number_input(
                    "Target 2",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Target 2")),
                    step=0.01,
                    key="edit_target_2",
                )
                planned_risk = c14.number_input(
                    "Planned Risk",
                    min_value=0.0,
                    value=number_input_value(selected_row.get("Planned Risk")),
                    step=100.0,
                    key="edit_risk",
                )

                action_value = selected_row.get("Actual Action", "Not Yet")
                if pd.isna(action_value) or action_value not in ACTUAL_ACTION_OPTIONS:
                    action_value = "Not Yet"
                action_index = ACTUAL_ACTION_OPTIONS.index(action_value)
                actual_action = st.selectbox(
                    "Actual Action",
                    ACTUAL_ACTION_OPTIONS,
                    index=action_index,
                    key="edit_actual_action",
                )
                position_notes = st.text_area(
                    "Position Notes",
                    value=str(selected_row.get("Position Notes", "")),
                    height=100,
                    key="edit_plan_notes",
                )
                submitted = st.form_submit_button("Save Plan Changes")
                if submitted:
                    save_trade_plan_to_db(
                        {
                            "plan_date": normalize_date_value(plan_date),
                            "symbol": symbol,
                            "side": side,
                            "sector": sector,
                            "setup": setup,
                            "market_regime": market_regime,
                            "current_price": normalize_float_value(current_price),
                            "entry_trigger": normalize_float_value(entry_trigger),
                            "stop_loss": normalize_float_value(stop_loss),
                            "target_1": normalize_float_value(target_1),
                            "target_2": normalize_float_value(target_2),
                            "alert_price": normalize_float_value(alert_price),
                            "planned_risk": normalize_float_value(planned_risk),
                            "actual_action": actual_action,
                            "position_notes": position_notes,
                            "status": status,
                            "linked_trade_id": normalize_float_value(selected_row.get("Linked Trade ID")),
                        },
                        plan_id=selected_plan_id,
                    )
                    st.success("Trade plan updated.")
                    st.rerun()

            linked_trade = selected_row.get("Linked Trade ID")
            if pd.isna(linked_trade) or str(linked_trade).strip() == "":
                if st.button("Create Open Journal Trade From This Plan"):
                    trade_id = convert_plan_to_trade(selected_plan_id)
                    st.success(f"Created open journal trade #{trade_id} from plan #{selected_plan_id}.")
                    st.rerun()
            else:
                st.info(f"This plan is linked to journal trade #{int(float(linked_trade))}.")

    with review_tab:
        st.markdown("#### Plan Review")
        plans_df = load_trade_plans_db()
        if plans_df.empty:
            st.info("No trade plans saved yet.")
            return

        active_mask = plans_df["Status"].isin(["Watching", "Alert Set", "Triggered", "Open"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Plans", f"{len(plans_df):,}")
        c2.metric("Active Plans", f"{active_mask.sum():,}")
        c3.metric("Triggered / Open", f"{plans_df['Status'].isin(['Triggered', 'Open']).sum():,}")
        c4.metric("Planned Risk", f"{plans_df.loc[active_mask, 'Planned Risk'].fillna(0).sum():,.0f}")

        status_summary = plans_df["Status"].value_counts().reindex(TRADE_PLAN_STATUSES, fill_value=0).reset_index()
        status_summary.columns = ["Status", "Count"]
        fig_status = px.bar(status_summary, x="Status", y="Count", title="Trade Plans by Status")
        st.plotly_chart(fig_status, use_container_width=True)

        setup_summary = (
            plans_df.groupby("Setup", dropna=False)
            .agg(Plans=("ID", "count"), Planned_Risk=("Planned Risk", "sum"))
            .reset_index()
            .sort_values("Plans", ascending=False)
        )
        st.markdown("#### Plans by Setup")
        st.dataframe(setup_summary, width="stretch", hide_index=True)

        action_summary = (
            plans_df.assign(**{"Actual Action": plans_df["Actual Action"].fillna("Not Yet")})
            .groupby("Actual Action", dropna=False)
            .agg(Plans=("ID", "count"), Planned_Risk=("Planned Risk", "sum"))
            .reset_index()
        )
        action_summary["Actual Action"] = pd.Categorical(
            action_summary["Actual Action"], categories=ACTUAL_ACTION_OPTIONS, ordered=True
        )
        action_summary = action_summary.sort_values("Actual Action")
        st.markdown("#### Plans by Actual Action")
        st.dataframe(action_summary, width="stretch", hide_index=True)

        st.markdown("#### All Saved Trade Plans")
        st.dataframe(
            plans_df.drop(columns=["Created At", "Updated At"], errors="ignore"),
            width="stretch",
            hide_index=True,
            height=420,
        )
        st.download_button(
            "Export Trade Plans CSV",
            data=plans_df.to_csv(index=False),
            file_name="trade_plans_export.csv",
            mime="text/csv",
        )


def render_journal_tab(screening_df, sector_col):
    st.subheader("Trading Journal and Equity Curve")
    init_journal_db()
    st.caption(f"Saved locally at `{JOURNAL_DB_PATH}`")

    journal_db_df = load_journal_db()
    log_tab, close_tab, review_tab, import_tab = st.tabs(["Log Trade", "Close Trade", "Review", "Import / Export"])

    with log_tab:
        st.markdown("#### Add New Trade")
        with st.form("new_trade_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            open_date = c1.date_input("Open Date", value=date.today())
            symbol = c2.text_input("Symbol").upper().strip()
            side = c3.selectbox("Side", ["Long", "Short"])
            status = c4.selectbox("Status", ["Watching", "Open", "Closed", "Skipped"], index=1)

            c5, c6, c7 = st.columns(3)
            sector = c5.text_input("Sector")
            setup = c6.text_input("Setup", placeholder="Breakout, Pullback, Pocket pivot...")
            market_regime = c7.selectbox(
                "Market Regime",
                ["", "Confirmed Uptrend", "Uptrend Under Pressure", "Rally Attempt", "Correction"],
            )

            c8, c9, c10, c11 = st.columns(4)
            entry_price = c8.number_input("Entry Price", min_value=0.0, value=0.0, step=0.01)
            stop_loss = c9.number_input("Stop Loss", min_value=0.0, value=0.0, step=0.01)
            shares = c10.number_input("Shares", min_value=0.0, value=0.0, step=100.0)
            fees = c11.number_input("Fees", min_value=0.0, value=0.0, step=1.0)

            closed_trade = st.checkbox("This trade is already closed")
            close_date = None
            exit_price = None
            if closed_trade:
                c12, c13 = st.columns(2)
                close_date = c12.date_input("Close Date", value=date.today())
                exit_price = c13.number_input("Exit Price", min_value=0.0, value=0.0, step=0.01)

            use_manual_result = st.checkbox("Enter manual Net P/L or R Multiple")
            risk_amount = None
            net_pl = None
            r_multiple = None
            if use_manual_result:
                c14, c15, c16 = st.columns(3)
                risk_amount = c14.number_input("Risk Amount", value=0.0, step=100.0)
                net_pl = c15.number_input("Net P/L", value=0.0, step=100.0)
                r_multiple = c16.number_input("R Multiple", value=0.0, step=0.1)

            c17, c18 = st.columns(2)
            mistake_tag = c17.text_input("Mistake Tag")
            screenshot_url = c18.text_input("Screenshot URL")
            notes = st.text_area("Notes", height=100)

            submitted = st.form_submit_button("Save Trade")
            if submitted:
                if not symbol:
                    st.error("Symbol is required.")
                else:
                    trade = {
                        "open_date": normalize_date_value(open_date),
                        "close_date": normalize_date_value(close_date),
                        "symbol": symbol,
                        "side": side,
                        "sector": sector,
                        "setup": setup,
                        "market_regime": market_regime,
                        "entry_price": normalize_float_value(entry_price),
                        "stop_loss": normalize_float_value(stop_loss),
                        "exit_price": normalize_float_value(exit_price),
                        "shares": normalize_float_value(shares),
                        "fees": normalize_float_value(fees),
                        "risk_amount": normalize_float_value(risk_amount),
                        "net_pl": normalize_float_value(net_pl),
                        "r_multiple": normalize_float_value(r_multiple),
                        "mistake_tag": mistake_tag,
                        "notes": notes,
                        "screenshot_url": screenshot_url,
                        "status": "Closed" if closed_trade else status,
                    }
                    save_trade_to_db(trade)
                    st.success(f"Saved {symbol} to the local journal database.")
                    st.rerun()

    with close_tab:
        st.markdown("#### Close or Update an Existing Trade")
        current_journal = load_journal_db()
        open_trades = current_journal[
            current_journal["Close Date"].isna()
            | (current_journal["Close Date"].astype(str).str.strip() == "")
            | (current_journal["Status"].astype(str).str.lower().isin(["open", "watching"]))
        ].copy()

        if open_trades.empty:
            st.info("No open trades in the local database.")
        else:
            display_cols = ["ID", "Open Date", "Symbol", "Side", "Sector", "Setup", "Entry Price", "Stop Loss", "Shares", "Status"]
            st.dataframe(open_trades[[col for col in display_cols if col in open_trades.columns]], width="stretch", hide_index=True)

            trade_options = [
                f"{int(row['ID'])} | {row['Symbol']} | {row.get('Open Date', '')}"
                for _, row in open_trades.sort_values("ID").iterrows()
            ]
            selected_trade = st.selectbox("Trade to close/update", trade_options)
            selected_trade_id = int(selected_trade.split("|")[0].strip())

            with st.form("close_trade_form"):
                c1, c2, c3 = st.columns(3)
                close_date = c1.date_input("Close Date", value=date.today())
                exit_price = c2.number_input("Exit Price", min_value=0.0, value=0.0, step=0.01)
                fees = c3.number_input("Fees", min_value=0.0, value=0.0, step=1.0)

                use_manual_result = st.checkbox("Override calculated Net P/L or R Multiple")
                risk_amount = None
                net_pl = None
                r_multiple = None
                if use_manual_result:
                    c4, c5, c6 = st.columns(3)
                    risk_amount = c4.number_input("Risk Amount", value=0.0, step=100.0)
                    net_pl = c5.number_input("Net P/L", value=0.0, step=100.0)
                    r_multiple = c6.number_input("R Multiple", value=0.0, step=0.1)

                c7, c8 = st.columns(2)
                mistake_tag = c7.text_input("Mistake Tag")
                screenshot_url = c8.text_input("Screenshot URL")
                notes = st.text_area("Exit Notes", height=100)

                submitted = st.form_submit_button("Save Close / Update")
                if submitted:
                    update_trade_close_in_db(
                        selected_trade_id,
                        {
                            "close_date": normalize_date_value(close_date),
                            "exit_price": normalize_float_value(exit_price),
                            "fees": normalize_float_value(fees),
                            "risk_amount": normalize_float_value(risk_amount),
                            "net_pl": normalize_float_value(net_pl),
                            "r_multiple": normalize_float_value(r_multiple),
                            "mistake_tag": mistake_tag,
                            "notes": notes,
                            "screenshot_url": screenshot_url,
                            "status": "Closed",
                        },
                    )
                    st.success("Trade updated.")
                    st.rerun()

    with import_tab:
        st.markdown("#### Import Old Journal CSV")
        st.write("Use this once if you already have old journal data in a spreadsheet.")
        import_file = st.file_uploader("Import trading journal CSV to local database", type=["csv"], key="journal_import_file")
        if import_file is not None:
            import_raw = load_uploaded_csv(import_file)
            if st.button("Import CSV Rows"):
                imported, skipped = import_journal_csv_to_db(import_raw)
                st.success(f"Imported {imported} rows. Skipped {skipped} rows without symbols.")
                st.rerun()

        export_df = load_journal_db()
        st.download_button(
            "Export Local Journal CSV",
            data=export_df.to_csv(index=False),
            file_name="trading_journal_export.csv",
            mime="text/csv",
            disabled=export_df.empty,
        )

    with review_tab:
        st.markdown("#### Journal Review")
        current_journal = load_journal_db()
        if current_journal.empty:
            st.info("No trades saved yet. Use the Log Trade tab to add your first trade.")
            return {}

        st.markdown("##### Local Journal Records")
        st.dataframe(
            current_journal.drop(columns=["Created At", "Updated At"], errors="ignore"),
            width="stretch",
            hide_index=True,
            height=260,
        )

        starting_capital = st.number_input("Starting Capital", min_value=0.0, value=1_000_000.0, step=50_000.0)
        journal_df, issues, metadata = prepare_journal_data(current_journal, starting_capital, screening_df, sector_col)
        if issues:
            st.error(", ".join(issues))
            return {}
        if journal_df.empty:
            st.warning("No closed trades yet. Open trades are saved, but the equity curve starts after a trade has Net P/L.")
            return {}

        metrics = compute_journal_metrics(journal_df)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Closed Trades", f"{metrics['total_trades']:,}")
        m2.metric("Net P/L", f"{metrics['total_pl']:,.0f}")
        m3.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
        m4.metric("Avg R", f"{metrics['avg_r']:.2f}")
        pf_text = "inf" if metrics["profit_factor"] == float("inf") else f"{metrics['profit_factor']:.2f}"
        m5.metric("Profit Factor", pf_text)

        m6, m7, m8 = st.columns(3)
        m6.metric("Current Equity", f"{metrics['current_equity']:,.0f}")
        m7.metric("Max Drawdown", f"{metrics['max_drawdown']:,.0f}", f"{metrics['max_drawdown_pct']:.1f}%")
        m8.metric("Equity Status", metrics["equity_status"])

        equity_fig = go.Figure()
        equity_fig.add_trace(go.Scatter(x=journal_df["Sort Date"], y=journal_df["Equity"], mode="lines+markers", name="Equity"))
        equity_fig.add_trace(go.Scatter(x=journal_df["Sort Date"], y=journal_df["Equity MA10"], mode="lines", name="Equity MA10"))
        equity_fig.add_trace(go.Scatter(x=journal_df["Sort Date"], y=journal_df["Equity MA20"], mode="lines", name="Equity MA20"))
        equity_fig.update_layout(title="Equity Curve with Moving Averages", xaxis_title="", yaxis_title="Equity")
        st.plotly_chart(equity_fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            drawdown_fig = px.area(journal_df, x="Sort Date", y="Drawdown %", title="Drawdown %")
            st.plotly_chart(drawdown_fig, use_container_width=True)
        with c2:
            r_fig = px.histogram(journal_df, x="R Multiple", nbins=30, title="R Multiple Distribution")
            st.plotly_chart(r_fig, use_container_width=True)

        breakdown_cols = [
            ("Setup", metadata.get("setup_col")),
            ("Market Regime", metadata.get("market_regime_col")),
            ("Sector", metadata.get("sector_col")),
            ("Mistake Tag", metadata.get("mistake_col")),
        ]
        for label, col in breakdown_cols:
            if col and col in journal_df.columns:
                summary = (
                    journal_df.groupby(col)
                    .agg(
                        Trades=("Net P/L", "count"),
                        Net_PL=("Net P/L", "sum"),
                        Avg_R=("R Multiple", "mean"),
                        Win_Rate=("Net P/L", lambda s: (s > 0).mean() * 100),
                    )
                    .reset_index()
                    .sort_values("Net_PL", ascending=False)
                )
                st.markdown(f"#### Performance by {label}")
                st.dataframe(summary, width="stretch", hide_index=True)

        st.markdown("#### Recent Closed Trades")
        recent_cols = [metadata["symbol_col"], "Sort Date", "Net P/L", "R Multiple", "Result", "Equity", "Drawdown %"]
        recent_cols = [col for col in recent_cols if col in journal_df.columns]
        st.dataframe(
            journal_df[recent_cols].tail(30).sort_values("Sort Date", ascending=False),
            width="stretch",
            hide_index=True,
        )

        return metrics

    return {}


def render_templates_tab():
    st.subheader("Templates")
    st.write("Use these as optional backup/import templates. The main workflow stores plans and journal records locally.")

    trading_log_template = """Open Date,Close Date,Symbol,Side,Sector,Setup,Market Regime,Entry Price,Stop Loss,Exit Price,Shares,Fees,Risk Amount,Net P/L,R Multiple,Mistake Tag,Notes,Screenshot URL
2026-04-01,2026-04-05,ABC,Long,Technology,Breakout,Confirmed Uptrend,10.00,9.50,11.20,10000,100,,,,,Example closed trade,
2026-04-10,,XYZ,Long,Energy,Pullback,Uptrend Under Pressure,5.00,4.75,,20000,0,,,,,Example open trade,
"""
    plan_template = """Date,Symbol,Sector,Setup,Market Regime,Entry Trigger,Stop Loss,Target 1,Target 2,Alert Price,Planned Risk,Actual Action,Notes,Status
2026-04-25,ABC,Technology,Breakout,Confirmed Uptrend,10.50,9.90,11.50,12.50,10.45,10000,Not Yet,Example plan,Watching
"""

    c1, c2 = st.columns(2)
    c1.download_button("Trading Journal Template", trading_log_template, "trading_log_template.csv", "text/csv")
    c2.download_button("Trade Plan Template", plan_template, "trade_plan_template.csv", "text/csv")

    st.markdown("#### Trading Journal Columns")
    st.write(
        "The journal dashboard can calculate Net P/L, Initial Risk Amount, and R Multiple "
        "when entry, stop, exit, and shares are available. You can also provide those values directly."
    )


def main():
    st.set_page_config(page_title="US Trading Workflow Dashboard", layout="wide")
    if not render_google_login_gate():
        return

    st.title("US Trading Workflow Dashboard v1.4 Google Login")
    st.caption(
        "Google Sheet portfolio tracking, risk behavior analysis, rule-based exposure allocation, portfolio risk, and RS screening."
    )

    portfolio_tab, pretrade_tab, screening_tab = st.tabs(
        [
            "Equity Curve",
            "Exposure and Position sizing",
            "RS Screener",
        ]
    )

    portfolio_df_for_pretrade = pd.DataFrame()
    latest_portfolio_for_pretrade = {}

    with portfolio_tab:
        portfolio_df_for_pretrade, latest_portfolio_for_pretrade = render_portfolio_log_tab()

    with screening_tab:
        render_screening_tab()

    with pretrade_tab:
        render_pretrade_tab(latest_portfolio_for_pretrade, portfolio_df_for_pretrade)


if __name__ == "__main__":
    main()
