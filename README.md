# US RS Rating Dashboard

Streamlit dashboard for a US stock pre-execution routine. The app combines
equity curve tracking, rule-based exposure planning, and a US relative-strength
stock screener.

The current active version is:

```text
us-rs-rating-dashboard-v1.4-google-login.py
```

This US v1.4 app keeps the v1.3 EMA50 risk-behavior workflow and adds Google login for public deployments.

## Current Status

- Active app: `us-rs-rating-dashboard-v1.4-google-login.py`
- Previous fallback app: `us-rs-rating-dashboard-v1.3-ema50-risk-behavior.py`
- Main logic module: `exposure_scorecard.py`
- Portfolio risk module: `portfolio_risk.py`
- Full operating manual: `USER_MANUAL.md`
- Visible tabs: `Equity Curve`, `Exposure and Position sizing`, `RS Screener`
- Data source for equity curve: Google Form response sheet / Google Sheet CSV
- RS screener input: daily uploaded CSV export
- Local database: `data/trading_journal.sqlite3` for pre-trading snapshots and portfolio risk snapshots
- Online-ready: mostly yes, with Streamlit secrets for private Google links
  and optional Supabase storage for pre-trading and portfolio risk snapshots

This app is decision support for your own process. It is not financial advice and
does not place trades.

## Key Features

### Equity Curve

The `Equity Curve` tab reads your Google Sheet portfolio log and shows the latest
portfolio status.

It calculates:

- default sheet: `Total Equity = Column H + Cash`
- generic mapped sheets: `Total Equity = explicit Total Equity`, or `US Market Value + Cash` when no total equity column is mapped
- `US Exposure % = US Exposure Value / Total Equity`
- `Non-US Exposure % = Non-US Exposure Value / Total Equity`
- `Total Exposure % = US Exposure % + Non-US Exposure %`
- `Total Equity NAV`
- EMA 10 / 20 / 50 of NAV
- equity drawdown from the running NAV high
- exposure status versus expected exposure when expected exposure exists
- Risk Behavior correlations over 20, 50, and 100 portfolio records

The chart uses NAV as the main line and total exposure as the background bar
series.

### Exposure and Position Sizing

The `Exposure and Position sizing` tab is the daily decision page before execution.

It includes:

- auto-filled NAV, EMA10, EMA20, EMA50, and worst 20-record drawdown from the latest equity curve
- editable override inputs
- rule-based Exposure Scorecard
- recommended exposure
- raw exposure before caps
- final exposure after caps
- margin allowed / not allowed
- active limiting cap
- biggest reducer
- position size planning
- exposure gap in USD
- risk amount table at 0.10%, 0.15%, 0.25%, and 0.35% of total equity
- current portfolio risk table using `Stock name`, `Position`, `Avg. cost`, `Last price`, `Stop`, and `%ATR`
- portfolio ATR and heat against Total Equity, with reconciliation against Total Invested
- saved pre-trading snapshot history, either local SQLite or Supabase

### RS Screener

The `RS Screener` tab accepts your daily US stock screening CSV.

It includes:

- liquidity filter using average 60-day turnover
- minimum RS rating filter
- market cap size filter
- momentum quality filter
- screening priority filter
- ATR range filter: Slow and Pokey, Sweet Spot, Hot, or Super high octane
- EMA20 distance filter when available
- momentum quadrant chart
- momentum quality distribution
- sector leadership table and chart when sector data exists
- ranked stock table
- TradingView watchlist export

Default RS filters are Mid/Large/Mega market cap, price at least 10 USD,
ATR Range `Sweet Spot` and `Hot`, max EMA20 distance 25% when EMA20 data exists,
and minimum average 60-day turnover of 20,000,000 USD.

## Exposure Scorecard Logic

The scorecard calculates exposure from:

- base mode: `Defensive`, `Normal`, or `Margin`
- personal performance regime from NAV vs EMA10 / EMA20 / EMA50
- market trend condition
- market health / breadth
- PT / FTD condition
- ATR volatility condition
- distribution day count
- personal drawdown
- margin eligibility gate

Main formula:

```text
Raw Exposure =
Base Max Exposure
* Performance Multiplier
* Market Trend Multiplier
* Market Health Multiplier
* PT/FTD Multiplier
* Market Volatility Multiplier
```

```text
Final Exposure =
MIN(
Raw Exposure,
Performance Cap,
Market Trend Cap,
PT/FTD Cap,
Volatility Cap,
Distribution Day Cap,
Personal Drawdown Cap,
Margin Gate Cap
)
```

The final value is rounded down to the nearest 5%.

Margin above 100% is allowed only when the margin gate is true. If the margin
gate is false, exposure is capped at 100% even if raw exposure is higher.

## Portfolio Sheet Columns

Recommended Google Form / Sheet columns:

- `Timestamp` or `Date`
- `US Market Value (USD)`
- `Cash (USD)`
- `Unrealized gain % (US)`
- `US Exposure`
- `Non-US Exposure`

The bundled default sheet import also supports this fixed column layout:

- Date from column B
- Total Equity from column H + column I
- Total Equity NAV from column W
- Unrealized Gain from column J / Total Equity for risk behavior
- US Market Value from column K
- Cash from column I
- US Exposure from column K / Total Equity
- Non-US Exposure from column L / Total Equity
- `US NAV`

The app can auto-map these names. Column mapping is still available inside the
Equity Curve tab if the source sheet uses different names.

The default portfolio source is:

```text
https://docs.google.com/spreadsheets/d/1_3vrNiIs8WKsWLDgzJLQoLImQzErXQ8Nz4MvGbH8qMY/edit?usp=sharing
```

## Screening CSV Columns

Required columns:

- `Symbol`
- `Market capitalization`
- `Price`
- `Average Volume 60 days`
- `Performance % 1 week`
- `Performance % 1 month`
- `Performance % 3 months`
- `Performance % 6 months`
- `Performance % 1 year`

Optional useful columns:

- `Sector`
- `Industry`
- `Distance from EMA20 %`
- `Distance from EMA50 %`
- `Distance from 52W High %`
- `Volume vs 60D Avg`
- `ATR %`

ATR can also be imported from TradingView-style `Average True Range % (14) 1 day`.

## Local Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create local secrets:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml` with your own private Google Form and Sheet
links.

If you deploy the app publicly, add Google login secrets and allow only your own
Google account:

```toml
require_google_login = true
allowed_google_emails = ["you@example.com"]

[auth]
redirect_uri = "http://localhost:8505/oauth2callback"
cookie_secret = "<strong-random-cookie-secret>"
client_id = "<google-oauth-client-id>"
client_secret = "<google-oauth-client-secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

If you want online pre-trading notes/history, also add Supabase secrets:

```toml
supabase_url = "https://<your-project-ref>.supabase.co"
supabase_key = "<your-supabase-key>"
supabase_pretrade_table = "pretrade_snapshots"
supabase_portfolio_risk_snapshot_table = "portfolio_risk_snapshots"
supabase_portfolio_risk_positions_table = "portfolio_risk_positions"
```

Run the current app:

```bash
python3 -m streamlit run us-rs-rating-dashboard-v1.4-google-login.py
```

Run on a fixed local port:

```bash
python3 -m streamlit run us-rs-rating-dashboard-v1.4-google-login.py --server.port 8505
```

Run tests:

```bash
python3 -m unittest tests/test_exposure_scorecard.py
python3 -m unittest tests/test_portfolio_risk.py
python3 -m unittest tests/test_pretrade_drawdown.py
python3 -m unittest tests/test_rs_screening_import.py
python3 -m unittest tests/test_risk_behavior.py
python3 -m unittest tests/test_google_auth.py
```

## Files For GitHub

Recommended files to include:

- `README.md`
- `USER_MANUAL.md`
- `requirements.txt`
- `.gitignore`
- `.streamlit/secrets.toml.example`
- `supabase_schema.sql`
- `portfolio_risk.py`
- `us-rs-rating-dashboard-v1.0.py`
- `us-rs-rating-dashboard-v1.1-performance-risk.py`
- `us-rs-rating-dashboard-v1.2-risk-behavior.py`
- `us-rs-rating-dashboard-v1.3-ema50-risk-behavior.py`
- `us-rs-rating-dashboard-v1.4-google-login.py`
- `exposure_scorecard.py`
- `tests/test_exposure_scorecard.py`
- `tests/test_portfolio_risk.py`
- `tests/test_pretrade_drawdown.py`
- `tests/test_risk_behavior.py`
- `tests/test_google_auth.py`
- `tests/test_rs_screening_import.py`
- `templates/`

Do not commit:

- `.streamlit/secrets.toml`
- `data/trading_journal.sqlite3`
- personal CSV exports
- screenshots
- downloaded daily screening files

The `.gitignore` file already excludes these local/private files.

## Deploy Online

The simplest online path is Streamlit Community Cloud because this is already a
Streamlit app and the project has a `requirements.txt` file.

High-level steps:

1. Create a GitHub repository.
2. Upload the recommended files.
3. Go to Streamlit Community Cloud and create a new app.
4. Select the GitHub repository and branch.
5. Set the entrypoint file to:

```text
us-rs-rating-dashboard-v1.4-google-login.py
```

6. In advanced settings, paste your Streamlit secrets:

```toml
portfolio_form_url = "https://docs.google.com/forms/d/e/<your-form-id>/viewform"
portfolio_sheet_csv_url = "https://docs.google.com/spreadsheets/d/<your-sheet-id>/export?format=csv&gid=0"
require_google_login = true
allowed_google_emails = ["you@example.com"]
supabase_url = "https://<your-project-ref>.supabase.co"
supabase_key = "<your-supabase-key>"
supabase_pretrade_table = "pretrade_snapshots"
supabase_portfolio_risk_snapshot_table = "portfolio_risk_snapshots"
supabase_portfolio_risk_positions_table = "portfolio_risk_positions"

[auth]
redirect_uri = "https://<your-app-subdomain>.streamlit.app/oauth2callback"
cookie_secret = "<strong-random-cookie-secret>"
client_id = "<google-oauth-client-id>"
client_secret = "<google-oauth-client-secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

7. Deploy the app and open the generated `streamlit.app` URL on desktop or
mobile.

Official references:

- [Streamlit Community Cloud deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Streamlit file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- [Streamlit secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
- [Streamlit Google authentication tutorial](https://docs.streamlit.io/develop/tutorials/authentication/google)

## Mobile / Anywhere Workflow

Recommended simple workflow:

1. Use Google Form on your phone to submit daily portfolio balance, exposure, and
   unrealized gain.
2. Open the deployed Streamlit app URL on iPhone Safari or Chrome.
3. Review `Equity Curve`.
4. Use `Exposure and Position sizing` to decide expected exposure and position size.
5. Upload the RS screening CSV from desktop when doing deeper screening.

This gives you the main routine anywhere without needing this Mac to stay on.

## Important Online Limitation

The current v1.4 app reads portfolio data from Google Sheets, which is good for
multi-device use.

If Supabase is not configured, the app saves pre-trading and portfolio risk
snapshots to local SQLite. On Streamlit Community Cloud, local files should not
be treated as a permanent multi-device database.

If Supabase is configured, the app saves and loads pre-trading and portfolio
risk snapshots from Supabase tables instead. This lets notes/history sync
across phone, work computer, and Mac.

Longer-term cloud options are:

- Google Sheets write-back
- Supabase/Postgres
- Firebase
- another hosted database

For your current goal, Supabase is now the supported online database path for
pre-trading notes/history and portfolio risk snapshots.

## Google Login For Public Deployment

Use this when the Streamlit app URL must be public but the dashboard content
should stay private.

1. In Google Cloud Console, create a Google Auth Platform web application.
2. Add authorized redirect URIs for both environments you use:
   - local: `http://localhost:8505/oauth2callback`
   - deployed: `https://<your-app-subdomain>.streamlit.app/oauth2callback`
3. Copy the Google client ID and client secret.
4. Generate a strong random `cookie_secret`.
5. Add the `[auth]` block and `allowed_google_emails` values shown above to local
   `.streamlit/secrets.toml` and to Streamlit Cloud Secrets.
6. Keep `require_google_login = true`.

When login is configured, the app renders only the login screen until a Google
account in `allowed_google_emails` signs in. If login is required but the auth
secrets or allow-list are missing, the app blocks access instead of showing the
dashboard.

## Supabase Setup For Pre-Trading And Portfolio Risk

Use this only if you want `Pre-trading Notes`, saved pre-trading snapshots, and
portfolio risk snapshots to sync online.

1. Create a free Supabase account and project.
2. Open the Supabase project dashboard.
3. Go to `SQL Editor`.
4. Copy the SQL from `supabase_schema.sql`.
5. Run it to create the `pretrade_snapshots`, `portfolio_risk_snapshots`, and
   `portfolio_risk_positions` tables with RLS enabled.
6. Go to `Project Settings` > `API`.
7. Copy your `Project URL`.
8. Copy your `service_role` API key.
9. Put the values into `.streamlit/secrets.toml` locally, or Streamlit Cloud
   secrets online:

```toml
supabase_url = "https://<your-project-ref>.supabase.co"
supabase_key = "<your-service-role-key>"
supabase_pretrade_table = "pretrade_snapshots"
supabase_portfolio_risk_snapshot_table = "portfolio_risk_snapshots"
supabase_portfolio_risk_positions_table = "portfolio_risk_positions"
```

When these Supabase secrets exist, the app automatically uses Supabase for
pre-trading and portfolio risk snapshots. If they are missing, the app continues
using local SQLite.

If you see `new row violates row-level security policy`, your app is almost
always using the `anon` public key. Replace `supabase_key` with the
`service_role` key from `Project Settings` > `API`. Do not commit this key.

If Supabase warns that the new table does not have Row Level Security, choose
`Run and enable RLS`. This app is a private server-side Streamlit app, so use the
`service_role` key in Streamlit Secrets. Do not use the `anon` key for this
write-back workflow unless you later add proper user login and RLS policies.

## Privacy Notes

If the GitHub repository is public, anyone can see code and any hardcoded links.
Keep personal Google Form and Sheet links only in Streamlit secrets.

If the Google Sheet contains portfolio balances, either:

- keep the sheet private and later add Google API authentication, or
- use a sheet view/export that contains only the columns you are comfortable
  exposing to the app.

For private personal use, a private GitHub repository plus Streamlit secrets is
the cleanest starting point.
