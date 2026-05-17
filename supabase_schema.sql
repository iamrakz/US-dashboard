create table if not exists pretrade_snapshots (
  id bigint generated always as identity primary key,
  snapshot_date date,
  holding_us numeric,
  holding_other numeric,
  cash numeric,
  total_equity numeric,
  expected_exposure numeric,
  current_exposure numeric,
  today_plan text,
  risk_per_trade numeric,
  stop_loss_pct numeric,
  position_cost numeric,
  performance_condition text,
  ma200_condition text,
  trend_condition text,
  pt_condition text,
  distribution_days integer,
  scorecard_exposure numeric,
  capped_exposure numeric,
  personal_drawdown_pct numeric,
  notes text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

alter table pretrade_snapshots
  add column if not exists personal_drawdown_pct numeric;

alter table pretrade_snapshots enable row level security;

create table if not exists portfolio_risk_snapshots (
  id bigint generated always as identity primary key,
  snapshot_date date,
  total_invested numeric,
  total_equity numeric,
  total_market_value numeric,
  market_value_gap numeric,
  market_value_gap_pct numeric,
  portfolio_atr_pct numeric,
  position_atr_pct numeric,
  portfolio_heat_usd numeric,
  portfolio_heat_pct numeric,
  position_heat_pct numeric,
  heat_regime text,
  notes text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

create table if not exists portfolio_risk_positions (
  id bigint generated always as identity primary key,
  snapshot_id bigint references portfolio_risk_snapshots(id) on delete cascade,
  stock_name text,
  position numeric,
  avg_cost numeric,
  last_price numeric,
  stop numeric,
  atr_pct numeric,
  market_value numeric,
  exposure_pct numeric,
  heat_usd numeric,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

alter table portfolio_risk_snapshots enable row level security;
alter table portfolio_risk_positions enable row level security;
