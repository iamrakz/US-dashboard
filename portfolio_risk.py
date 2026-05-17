import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd


PORTFOLIO_RISK_INPUT_COLUMNS = ["Stock name", "Position", "Avg. cost", "Last price", "Stop", "%ATR"]
PORTFOLIO_RISK_CALCULATED_COLUMNS = ["Market value (USD)", "Exposure %", "Heat (USD)"]
PORTFOLIO_RISK_DISPLAY_COLUMNS = PORTFOLIO_RISK_INPUT_COLUMNS + PORTFOLIO_RISK_CALCULATED_COLUMNS


@dataclass
class PortfolioRiskSummary:
    total_invested: float
    total_equity: float
    total_market_value: float
    market_value_gap: float
    market_value_gap_pct: float
    portfolio_atr_pct: float
    position_atr_pct: float
    portfolio_heat_usd: float
    portfolio_heat_pct: float
    position_heat_pct: float
    heat_regime: str

    def to_dict(self):
        return asdict(self)


def _to_float(value):
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def _normalize_date(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return date.today().isoformat()
    return parsed.date().isoformat()


def classify_heat_regime(portfolio_heat_pct):
    heat = _to_float(portfolio_heat_pct)
    if heat < 2:
        return "Very defensive"
    if heat < 4:
        return "Normal risk"
    if heat < 6:
        return "Aggressive"
    if heat < 8:
        return "Very aggressive"
    if heat <= 10:
        return "High risk"
    return "Extreme risk / outside plan"


def prepare_portfolio_risk_input(rows):
    if rows is None:
        df = pd.DataFrame(columns=PORTFOLIO_RISK_INPUT_COLUMNS)
    else:
        df = pd.DataFrame(rows).copy()

    for col in PORTFOLIO_RISK_INPUT_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col == "Stock name" else 0.0

    df = df[PORTFOLIO_RISK_INPUT_COLUMNS].copy()
    df["Stock name"] = df["Stock name"].fillna("").astype(str).str.strip()
    for col in ["Position", "Avg. cost", "Last price", "Stop", "%ATR"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(lower=0.0)
    return df


def _non_empty_positions(df):
    numeric_activity = df[["Position", "Avg. cost", "Last price", "Stop", "%ATR"]].abs().sum(axis=1)
    return df[(df["Stock name"] != "") | (numeric_activity > 0)].copy()


def calculate_portfolio_risk(rows, total_invested=0.0, total_equity=0.0):
    total_invested = _to_float(total_invested)
    total_equity = _to_float(total_equity)

    df = prepare_portfolio_risk_input(rows)
    df = _non_empty_positions(df)
    if df.empty:
        df = pd.DataFrame(columns=PORTFOLIO_RISK_DISPLAY_COLUMNS)
        summary = PortfolioRiskSummary(
            total_invested=total_invested,
            total_equity=total_equity,
            total_market_value=0.0,
            market_value_gap=-total_invested,
            market_value_gap_pct=-100.0 if total_invested > 0 else 0.0,
            portfolio_atr_pct=0.0,
            position_atr_pct=0.0,
            portfolio_heat_usd=0.0,
            portfolio_heat_pct=0.0,
            position_heat_pct=0.0,
            heat_regime=classify_heat_regime(0.0),
        )
        return df, summary

    df["Market value (USD)"] = df["Position"] * df["Last price"]
    if total_invested > 0:
        df["Exposure %"] = df["Market value (USD)"] / total_invested * 100
    else:
        df["Exposure %"] = 0.0
    df["Heat (USD)"] = (df["Last price"] - df["Stop"]).clip(lower=0.0) * df["Position"]

    total_market_value = float(df["Market value (USD)"].sum())
    atr_risk_usd = float((df["Market value (USD)"] * df["%ATR"] / 100).sum())
    portfolio_heat_usd = float(df["Heat (USD)"].sum())
    market_value_gap = total_market_value - total_invested
    market_value_gap_pct = market_value_gap / total_invested * 100 if total_invested > 0 else 0.0
    portfolio_atr_pct = atr_risk_usd / total_equity * 100 if total_equity > 0 else 0.0
    position_atr_pct = atr_risk_usd / total_market_value * 100 if total_market_value > 0 else 0.0
    portfolio_heat_pct = portfolio_heat_usd / total_equity * 100 if total_equity > 0 else 0.0
    position_heat_pct = portfolio_heat_usd / total_market_value * 100 if total_market_value > 0 else 0.0

    summary = PortfolioRiskSummary(
        total_invested=total_invested,
        total_equity=total_equity,
        total_market_value=total_market_value,
        market_value_gap=market_value_gap,
        market_value_gap_pct=market_value_gap_pct,
        portfolio_atr_pct=portfolio_atr_pct,
        position_atr_pct=position_atr_pct,
        portfolio_heat_usd=portfolio_heat_usd,
        portfolio_heat_pct=portfolio_heat_pct,
        position_heat_pct=position_heat_pct,
        heat_regime=classify_heat_regime(portfolio_heat_pct),
    )
    return df[PORTFOLIO_RISK_DISPLAY_COLUMNS].copy(), summary


def portfolio_risk_payloads(rows, snapshot_date, total_invested=0.0, total_equity=0.0, notes=""):
    positions_df, summary = calculate_portfolio_risk(rows, total_invested, total_equity)
    now = datetime.now().isoformat(timespec="seconds")
    snapshot = {
        "snapshot_date": _normalize_date(snapshot_date),
        "total_invested": summary.total_invested,
        "total_equity": summary.total_equity,
        "total_market_value": summary.total_market_value,
        "market_value_gap": summary.market_value_gap,
        "market_value_gap_pct": summary.market_value_gap_pct,
        "portfolio_atr_pct": summary.portfolio_atr_pct,
        "position_atr_pct": summary.position_atr_pct,
        "portfolio_heat_usd": summary.portfolio_heat_usd,
        "portfolio_heat_pct": summary.portfolio_heat_pct,
        "position_heat_pct": summary.position_heat_pct,
        "heat_regime": summary.heat_regime,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }
    positions = []
    for _, row in positions_df.iterrows():
        positions.append(
            {
                "stock_name": row["Stock name"],
                "position": float(row["Position"]),
                "avg_cost": float(row["Avg. cost"]),
                "last_price": float(row["Last price"]),
                "stop": float(row["Stop"]),
                "atr_pct": float(row["%ATR"]),
                "market_value": float(row["Market value (USD)"]),
                "exposure_pct": float(row["Exposure %"]),
                "heat_usd": float(row["Heat (USD)"]),
                "created_at": now,
                "updated_at": now,
            }
        )
    return snapshot, positions, positions_df, summary


def init_portfolio_risk_db(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                total_invested REAL,
                total_equity REAL,
                total_market_value REAL,
                market_value_gap REAL,
                market_value_gap_pct REAL,
                portfolio_atr_pct REAL,
                position_atr_pct REAL,
                portfolio_heat_usd REAL,
                portfolio_heat_pct REAL,
                position_heat_pct REAL,
                heat_regime TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_risk_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                stock_name TEXT NOT NULL,
                position REAL,
                avg_cost REAL,
                last_price REAL,
                stop REAL,
                atr_pct REAL,
                market_value REAL,
                exposure_pct REAL,
                heat_usd REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(snapshot_id) REFERENCES portfolio_risk_snapshots(id) ON DELETE CASCADE
            )
            """
        )
        snapshot_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(portfolio_risk_snapshots)").fetchall()
        }
        snapshot_additions = {
            "total_invested": "REAL",
            "total_equity": "REAL",
            "total_market_value": "REAL",
            "market_value_gap": "REAL",
            "market_value_gap_pct": "REAL",
            "portfolio_atr_pct": "REAL",
            "position_atr_pct": "REAL",
            "portfolio_heat_usd": "REAL",
            "portfolio_heat_pct": "REAL",
            "position_heat_pct": "REAL",
            "heat_regime": "TEXT",
            "notes": "TEXT",
            "updated_at": "TEXT",
        }
        for column, column_type in snapshot_additions.items():
            if column not in snapshot_columns:
                conn.execute(f"ALTER TABLE portfolio_risk_snapshots ADD COLUMN {column} {column_type}")

        position_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(portfolio_risk_positions)").fetchall()
        }
        position_additions = {
            "market_value": "REAL",
            "exposure_pct": "REAL",
            "heat_usd": "REAL",
            "updated_at": "TEXT",
        }
        for column, column_type in position_additions.items():
            if column not in position_columns:
                conn.execute(f"ALTER TABLE portfolio_risk_positions ADD COLUMN {column} {column_type}")
        conn.commit()


def save_portfolio_risk_snapshot(rows, snapshot_date, total_invested, total_equity, db_path, notes=""):
    init_portfolio_risk_db(db_path)
    snapshot, positions, _positions_df, _summary = portfolio_risk_payloads(
        rows,
        snapshot_date,
        total_invested,
        total_equity,
        notes,
    )
    snapshot_fields = list(snapshot.keys())
    with sqlite3.connect(db_path) as conn:
        placeholders = ", ".join(["?"] * len(snapshot_fields))
        cursor = conn.execute(
            f"INSERT INTO portfolio_risk_snapshots ({', '.join(snapshot_fields)}) VALUES ({placeholders})",
            [snapshot[field] for field in snapshot_fields],
        )
        snapshot_id = cursor.lastrowid
        if positions:
            position_fields = ["snapshot_id"] + list(positions[0].keys())
            position_placeholders = ", ".join(["?"] * len(position_fields))
            conn.executemany(
                f"INSERT INTO portfolio_risk_positions ({', '.join(position_fields)}) VALUES ({position_placeholders})",
                [[snapshot_id] + [position[field] for field in positions[0].keys()] for position in positions],
            )
        conn.commit()
    return snapshot_id


def _records_to_positions_df(records):
    if not records:
        return pd.DataFrame(columns=PORTFOLIO_RISK_INPUT_COLUMNS)
    df = pd.DataFrame(records)
    if "heat_usd" not in df.columns and "heat_thb" in df.columns:
        df["heat_usd"] = df["heat_thb"]
    rename_map = {
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
    return df.rename(columns=rename_map)


def load_latest_portfolio_risk_snapshot(db_path):
    init_portfolio_risk_db(db_path)
    with sqlite3.connect(db_path) as conn:
        snapshots = pd.read_sql_query(
            "SELECT * FROM portfolio_risk_snapshots ORDER BY snapshot_date DESC, id DESC LIMIT 1",
            conn,
        )
        if snapshots.empty:
            return pd.DataFrame(columns=PORTFOLIO_RISK_INPUT_COLUMNS), {}
        snapshot = snapshots.iloc[0].to_dict()
        positions = pd.read_sql_query(
            "SELECT * FROM portfolio_risk_positions WHERE snapshot_id = ? ORDER BY id",
            conn,
            params=[snapshot["id"]],
        )
    return _records_to_positions_df(positions.to_dict("records")), snapshot


def load_portfolio_risk_history(db_path, limit=None):
    init_portfolio_risk_db(db_path)
    query = "SELECT * FROM portfolio_risk_snapshots ORDER BY snapshot_date DESC, id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn)
