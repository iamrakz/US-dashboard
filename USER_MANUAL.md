# US Trading Dashboard User Manual

This manual explains how to use the current app:

```text
us-rs-rating-dashboard-v1.4-google-login.py
```

The app is designed for a pre-execution trading workflow. It helps you review
your equity curve, decide portfolio exposure, calculate position sizing, and
screen US stocks by relative strength. It does not place trades and should not
be treated as financial advice.

## Main Workflow

Use the app in this order:

1. Update your portfolio log through Google Form or Google Sheet.
2. Open the `Equity Curve` tab and check NAV trend, drawdown, and current
   exposure.
3. Open `Exposure and Position sizing`.
4. Review the Exposure Scorecard and decide expected exposure.
5. Review position size and risk amount tables.
6. Review `Current Portfolio Risk` and update stops / ATR% for open positions.
7. Write pre-trading notes.
8. Save the pre-trading snapshot and, when useful, the portfolio risk snapshot.
9. Upload the daily US RS screening CSV in `RS Screener`.
10. Filter for liquid, high-RS stocks.
11. Export TradingView watchlists and do chart-by-chart review manually.

The app is built to support decision making before execution, not to automate
buy/sell decisions.

## Login On A Public Deployment

If the app is deployed at a public Streamlit URL, enable Google login in
Streamlit Secrets and allow only your own Google account. When login is enabled,
the dashboard stays hidden until an authorized account signs in.

Required secrets:

```toml
require_google_login = true
allowed_google_emails = ["you@example.com"]

[auth]
redirect_uri = "https://<your-app-subdomain>.streamlit.app/oauth2callback"
cookie_secret = "<strong-random-cookie-secret>"
client_id = "<google-oauth-client-id>"
client_secret = "<google-oauth-client-secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

For local testing on port `8505`, use
`http://localhost:8505/oauth2callback` as the redirect URI instead.

## Tab 1: Equity Curve

The `Equity Curve` tab reads portfolio data from your Google Sheet or Google
Form response sheet.

### What It Shows

- Latest date
- Total equity
- Total Equity NAV
- Unrealized gain
- US market value
- Cash
- US exposure
- Non-US exposure
- Total exposure
- Expected exposure, if a pre-trading snapshot exists
- Exposure status
- Equity drawdown
- Number of records
- Risk Behavior score and 20/50/100-record correlations

### Main Calculations

```text
Default sheet Total Equity = Column H + Cash
Generic mapped sheet Total Equity = mapped Total Equity, or US Market Value + Cash
```

```text
US Exposure % = US Exposure Value / Total Equity
Non-US Exposure % = Non-US Exposure Value / Total Equity
Total Exposure % = US Exposure % + Non-US Exposure %
```

```text
Equity Drawdown % = (Current NAV / Running NAV High - 1) * 100
```

Risk Behavior uses positive drawdown values and portfolio equity including cash:

```text
Risk Exposure % = Total exposure value / Total Equity
Risk Unrealized Gain % = Unrealized P/L / Total Equity
Risk Drawdown % = ABS(Equity Drawdown %)
Unrealized Gain on Exposure % = Unrealized P/L / Total exposure value
```

The chart plots:

- Total Equity NAV as the main line
- NAV EMA10
- NAV EMA20
- NAV EMA50
- Total exposure as the background bar series

The `Risk Behavior` section compares Exposure, Unrealized Gain, and Drawdown
over the latest 20, 50, and 100 portfolio records. A healthy pattern means
exposure rises with unrealized gain while staying low or defensive versus
drawdown.

### How To Read It

- NAV above EMA10/20/50 in order means your personal performance is strong.
- NAV below EMA20 means your own trading performance is weakening.
- Drawdown tells you how far your NAV is below its recent high.
- Current exposure tells you whether you are already heavily invested before
  planning new trades.

## Tab 2: Exposure and Position Sizing

The `Exposure and Position sizing` tab is the daily pre-trading decision page.

### Inputs

The app auto-fills these from the latest Equity Curve data when available:

- NAV
- EMA10
- EMA20
- EMA50
- EMA10 rising
- personal drawdown, defaulted from the worst drawdown in the latest 20 portfolio log records
- current exposure
- total equity

You still can edit the values manually.

Manual daily inputs:

- Base mode: `Defensive`, `Normal`, or `Margin`
- Market trend condition
- Market health
- PT / FTD condition
- Volatility / ATR condition
- Distribution day count
- Stalling days
- Bad up days
- Expected exposure
- Risk per trade
- Stop loss %
- Pre-trading notes
- Current portfolio risk rows: `Stock name`, `Position`, `Avg. cost`, `Last price`, `Stop`, `%ATR`

### Exposure Scorecard Formula

```text
Raw Exposure =
Base Max Exposure
* Performance Multiplier
* Market Trend Multiplier
* Market Health Multiplier
* PT/FTD Multiplier
* Volatility Multiplier
```

```text
Final Exposure =
MIN(
Raw Exposure,
Performance Cap,
Market Trend Cap,
Market Health Cap,
PT/FTD Cap,
Volatility Cap,
Distribution Day Cap,
Personal Drawdown Cap,
Margin Gate Cap
)
```

The final exposure is rounded down to the nearest 5%.

### Base Mode

- `Defensive`: base max 75%
- `Normal`: base max 100%
- `Margin`: base max 120%

### Performance Regime

The app checks your NAV versus EMA10, EMA20, and EMA50.

| Regime | Condition | Multiplier | Cap |
|---|---:|---:|---:|
| Peak performance | NAV > EMA10 > EMA20 > EMA50 | 1.00 | 120% |
| Healthy | NAV > EMA20 and EMA20 > EMA50 | 0.75 | 90% |
| Slow down | NAV < EMA10 and NAV > EMA20 | 0.50 | 50% |
| Caution | NAV < EMA20 and EMA20 > EMA50 | 0.35 | 35% |
| Stay low | NAV < EMA20 and EMA20 < EMA50 | 0.20 | 20% |
| Recovery | NAV > EMA10, EMA10 rising, EMA20 < EMA50 | 0.40 | 40% |

If conditions overlap, the app uses the more defensive valid regime unless
Recovery is clearly true.

### Market Trend Rules

| Condition | Regime | Multiplier | Cap |
|---|---:|---:|---:|
| Index > EMA21 and EMA21 > SMA50 and Index > SMA200 | Strong uptrend | 1.00 | 120% |
| Index < EMA21 and EMA21 > SMA50 and Index > SMA200 | Healthy pullback | 0.75 | 90% |
| Index > SMA200 and EMA21 < SMA50 | Weakening trend | 0.60 | 60% |
| Index < EMA21 and Index < SMA50 and Index > SMA200 | Deeper correction above SMA200 | 0.50 | 50% |
| Index < SMA200 and FTD is true | Below SMA200 with valid FTD or mini-FTD | 0.40 | 40% |
| Index < SMA200 and FTD is false | Below SMA200 without FTD | 0.20 | 20% |

### Market Health Rules

| Market Health | Multiplier | Cap |
|---|---:|---:|
| Strong | 1.00 | 120% |
| Neutral | 0.75 | 90% |
| Weak | 0.50 | 60% |
| Risk-off | 0.25 | 30% |

### PT / FTD Rules

| PT / FTD | Multiplier | Cap |
|---|---:|---:|
| PT on / confirmed uptrend | 1.00 | 120% |
| Under pressure | 0.80 | 75% |
| PT off but market above SMA200 | 0.80 | 75% |
| PT off and market below SMA200 | 0.60 | 50% |
| Failed FTD | 0.30 | 30% |
| No FTD in downtrend | 0.10 | 20% |

### Volatility / ATR Rules

| ATR Condition | Regime | Multiplier | Cap |
|---|---:|---:|---:|
| Normal: ATR percentile < 50 | Normal | 1.00 | 120% |
| Mildly elevated: ATR percentile 50-75 | Mildly elevated | 0.85 | 100% |
| High: ATR percentile 75-90 | High | 0.65 | 70% |
| Extreme: ATR percentile 90-95 | Extreme | 0.45 | 50% |
| Panic: ATR percentile > 95 | Panic | 0.25 | 30% |

### Distribution Day Cap

- 0-2 distribution days: cap 120%
- 3-4 distribution days: cap 75%
- 5 or more distribution days: cap 50%
- Failed FTD: cap 30%

### Personal Drawdown Cap

- Drawdown < 2%: cap 120%
- Drawdown 2-5%: cap 80%
- Drawdown 5-8%: cap 50%
- Drawdown 8-10%: cap 30%
- Drawdown > 10%: cap 20%

### Margin Gate

Exposure above 100% is allowed only when all of these are true:

- Performance regime is `Peak performance`
- Market trend is `Index > EMA21 and EMA21 > SMA50 and Index > SMA200`
- Market health is `Strong`
- Volatility is `Normal` or `Mildly elevated`
- Distribution day count is less than 3
- Personal drawdown is less than 3%
- PT / FTD is `PT on / confirmed uptrend`

If any condition fails, exposure is capped at 100%.

### Position Size Planning

The app compares:

```text
Expected Exposure % - Current Exposure %
```

It labels the plan:

- `Increase` if the gap is more than +5%
- `Reduce` if the gap is less than -5%
- `Hold` if the gap is within +/-5%

It also converts the exposure gap to USD:

```text
Exposure Gap USD = Total Equity * Exposure Gap % / 100
```

The risk amount table shows 0.10%, 0.15%, 0.25%, and 0.35% of Total Equity.

### Risk Per Trade

```text
Position Cost = Risk Per Trade / (Stop Loss % / 100)
```

Example:

```text
Risk per trade = 1,700 USD
Stop loss = 3%
Position cost = 56,667 USD
```

### Current Portfolio Risk

The portfolio risk table is for open positions. Enter:

- `Stock name`
- `Position`
- `Avg. cost`
- `Last price`
- `Stop`
- `%ATR`

The app calculates:

```text
Market value (USD) = Position * Last price
Exposure % = Market value (USD) / Total Invested
Heat (USD) = MAX(Last price - Stop, 0) * Position
```

`Total Invested` means US market value plus Non-US exposure value when the
Equity Curve tab has both values. Portfolio ATR% and Portfolio Heat% are still
reported against Total Equity, so you can see open-position risk relative to the
whole account.

Heat regime labels:

| Portfolio Heat % | Regime |
|---:|---|
| Less than 2% | Very defensive |
| 2% to less than 4% | Normal risk |
| 4% to less than 6% | Aggressive |
| 6% to less than 8% | Very aggressive |
| 8% to 10% | High risk |
| More than 10% | Extreme risk / outside plan |

## Saving Pre-Trading Notes

The `Pre-trading Notes` field is saved when you click:

```text
Save Pre-Trading Snapshot
```

The portfolio risk table is saved separately when you click:

```text
Save Portfolio Risk Snapshot
```

If Supabase is configured in Streamlit Secrets, notes are saved online in:

```text
pretrade_snapshots
portfolio_risk_snapshots
portfolio_risk_positions
```

If Supabase is not configured, notes and risk snapshots are saved locally in:

```text
data/trading_journal.sqlite3
```

Use Supabase if you want your notes/history to sync across Mac, work computer,
and phone.

## Tab 3: RS Screener

The `RS Screener` tab screens US stocks from your daily CSV export.

The app focuses on:

- relative strength
- momentum quality
- liquidity
- ATR range
- setup location
- sector leadership
- TradingView watchlist export

The app does not replace manual chart review. It creates a better watchlist so
you can spend your chart time on the most relevant stocks.

## RS Screening CSV Requirements

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

Optional but useful columns:

- `Sector`
- `Industry`
- `High 52 weeks`
- `Low 52 weeks`
- `Exponential Moving Average (10) 1 day`
- `Exponential Moving Average (20) 1 day`
- `Exponential Moving Average (50) 1 day`
- `Exponential Moving Average (200) 1 day`
- `Volume 1 day`
- `Price * Volume (Turnover) 1 day`
- `Average True Range % 1 day`
- `Average True Range % 14 days`
- `Average True Range % (14) 1 day`
- `ATR %`

The app maps `Average True Range % (14) 1 day` from TradingView exports to
`ATR %`.

ATR range labels:

| ATR % | Label |
|---:|---|
| Less than 2.5 | Slow and Pokey |
| 2.5 to 4 | Sweet Spot |
| More than 4 to 8 | Hot |
| More than 8 | Super high octane |

## RS Screening Criteria In Detail

### 1. Numeric Cleaning

The app cleans numeric fields by removing:

- commas
- percent signs
- currency symbols
- parentheses for negative values

This helps values like `1,234`, `12.5%`, `$10,000`, and `(123)` become usable
numbers.

### 2. Market Cap Size

The app groups stocks by market capitalization:

| Market Cap | Category |
|---:|---|
| Less than 50M USD | 1. Nano |
| 50M to less than 300M USD | 2. Micro |
| 300M to less than 2B USD | 3. Small |
| 2B to less than 10B USD | 4. Mid |
| 10B to less than 200B USD | 5. Large |
| 200B USD or more | 6. Mega |

### 3. Liquidity

The app calculates:

```text
Avg 60D Turnover (USD) = Price * Average Volume 60 days
```

Default minimum liquidity filter:

```text
Avg 60D Turnover >= 20,000,000 USD
```

This matches your liquidity rule to reduce slippage and execution risk.

### 4. Timeframe Percentile Ranks

For each performance timeframe, the app ranks every stock from 0 to 100:

- 1 week rank
- 1 month rank
- 3 months rank
- 6 months rank
- 1 year rank

A rank of 90 means the stock is stronger than about 90% of the stocks in the CSV
for that timeframe.

### 5. Main RS Composite Rating

The app calculates a raw RS score:

```text
Raw RS Score =
(2 * Performance % 3 months)
+ Performance % 6 months
+ Performance % 1 year
```

Then it percentile-ranks that raw score into:

```text
RS Composite Rating
```

Interpretation:

- `RS >= 90`: strongest leadership group
- `RS >= 80`: watchlist quality group
- `RS < 80`: normally filtered out by default

Why 3-month performance has double weight:

- It emphasizes recent intermediate-term leadership.
- It avoids relying too much on old 1-year strength.
- It fits momentum trading better than long-only historical strength.

### 6. RS Composite Rating v2

The app also calculates a rank-based score:

```text
RS Composite Raw v2 =
0.10 * 1-week rank
+ 0.25 * 1-month rank
+ 0.35 * 3-month rank
+ 0.20 * 6-month rank
+ 0.10 * 1-year rank
```

Then it percentile-ranks that score into:

```text
RS Composite Rating v2
```

Use v2 as a smoother confirmation score. The main filter still uses
`RS Composite Rating`.

### 7. Acceleration Score

```text
Acceleration Score = 1-month rank - 3-month rank
```

Interpretation:

- Positive score: recent momentum is improving.
- Negative score: recent momentum is fading.
- `>= 10`: meaningful acceleration.
- `< -10`: meaningful slowdown or pullback.

### 8. Momentum Consistency

Momentum consistency counts how many of these ranks are at least 70:

- 1-month rank
- 3-month rank
- 6-month rank

Possible score:

```text
0 to 3
```

Interpretation:

- `3`: strong across multiple timeframes
- `2`: good consistency
- `0-1`: less reliable or more mixed

### 9. Momentum Quality Labels

The app assigns one label to each stock.

#### Elite Momentum

Conditions:

- RS Composite Rating >= 90
- 1-month rank >= 80
- 3-month rank >= 80
- Momentum Consistency >= 3

Meaning:

This is the highest-quality momentum group. These stocks are strong in both
recent and intermediate timeframes.

#### Strong Momentum

Conditions:

- RS Composite Rating >= 80
- 1-month rank >= 70
- 3-month rank >= 70
- Momentum Consistency >= 2

Meaning:

Strong enough for a serious watchlist, but not as elite as the top group.

#### Emerging Momentum

Conditions:

- 1-month rank >= 75
- Acceleration Score >= 10

Meaning:

Recent momentum is improving quickly. These can be early movers, but they need
careful chart confirmation.

#### Short-term Spike

Conditions:

- 1-week rank >= 90
- 3-month rank < 50

Meaning:

The stock is moving sharply now, but it does not yet have intermediate-term
leadership. This can be a news spike or short-term burst.

#### Stale Leader

Conditions:

- 1-year rank >= 85
- 1-month rank < 50
- 3-month rank < 60

Meaning:

The stock was a leader before, but current momentum has weakened.

#### Pullback Leader

Conditions:

- 6-month rank >= 75
- Acceleration Score < -10

Meaning:

The stock has longer-term strength but is currently pulling back or cooling off.
This can be useful if the pullback is orderly and near support.

#### Mixed / Neutral

Condition:

- Anything that does not match the above labels.

Meaning:

Not enough quality or clarity from the RS data alone.

### 10. Setup Location Labels

Setup location is a first-pass context label. It does not replace chart review.

#### Extended above EMA20

Condition:

```text
Distance from EMA20 % > 20
```

Meaning:

The stock may be too far from a short-term moving average. Chasing risk is
higher.

#### Extended above EMA50

Condition:

```text
Distance from EMA50 % > 35
```

Meaning:

The stock may be very stretched from intermediate support.

#### Deep below 52W high

Condition:

```text
Distance from 52W High % < -35
```

Meaning:

The stock is far from its high. It may not be a true leader yet.

#### Pullback near EMA20

Conditions:

```text
-5 <= Distance from EMA20 % <= 5
RS Composite Rating >= 80
```

Meaning:

High-RS stock pulling back near EMA20. This may be a useful chart-review zone.

#### Pullback near EMA50

Conditions:

```text
-7 <= Distance from EMA50 % <= 7
RS Composite Rating >= 80
```

Meaning:

High-RS stock near EMA50. This can be constructive if the structure is still
healthy.

#### Near 52W high

Condition:

```text
-10 <= Distance from 52W High % <= 0
```

Meaning:

The stock is near high ground, often where leaders appear.

#### Accelerating

Condition:

```text
Acceleration Score >= 10
```

Meaning:

Recent momentum is improving, but you still need to check if it is extended.

#### Needs chart review

Condition:

- Anything not covered above.

Meaning:

The data does not clearly identify location quality.

### 11. Screening Priority Labels

The app assigns a priority label after calculating RS, liquidity, momentum
quality, and setup location.

#### A - Prime Watch

Conditions:

- RS Composite Rating >= 90
- Avg 60D Turnover >= 20,000,000 USD
- Momentum Quality is `Elite Momentum` or `Strong Momentum`
- Distance from 52W high is not deeper than -30%, or that data is unavailable
- Setup Location does not contain `Extended`

Meaning:

This is the best automatic watchlist group. These should be reviewed first in
TradingView.

#### B - Watch

Conditions:

- RS Composite Rating >= 80
- Avg 60D Turnover >= 20,000,000 USD
- Momentum Quality is one of:
  - `Emerging Momentum`
  - `Pullback Leader`
  - `Strong Momentum`

Meaning:

Good candidates, but they may need more chart confirmation or better timing.

#### C - RS 80+

Conditions:

- RS Composite Rating >= 80
- Avg 60D Turnover >= 20,000,000 USD
- Does not qualify as A or B

Meaning:

Liquid and strong enough to monitor, but weaker quality or location.

#### D - Lower Priority

Condition:

- Anything that does not meet the above rules.

Meaning:

Usually not worth first-pass attention.

## Default RS Screener Filters

The default filter settings are:

- Minimum Avg 60D Turnover: 20,000,000 USD
- Minimum RS Rating: 80
- Max Distance Above EMA20: 25%, if EMA20 data exists
- Market Cap Size: Mid, Large, and Mega
- Price >= 10 USD: enabled
- ATR Range: Sweet Spot and Hot
- Momentum Quality: all labels
- Priority: all labels available after processing

If you want a tighter watchlist, a practical setting is:

- Minimum RS Rating: 80 or 85
- Liquidity: 20M USD or higher
- Priority: A and B only
- Max Distance Above EMA20: 15-25%
- ATR Range: Sweet Spot or Hot

## Momentum Quadrant

The scatter plot uses:

- X-axis: 1-month rank
- Y-axis: 3-month rank
- Color: Screening Priority
- Symbol: Momentum Quality

The app draws reference lines at 80 for both axes.

Useful interpretation:

- Upper right: strong 1-month and 3-month leadership
- High x but low y: emerging or short-term acceleration
- Low x but high y: pullback or fading leader
- Lower left: weak or mixed momentum

## Sector Leadership

If a sector column exists, the app builds sector leadership ranking.

It calculates:

- average RS Composite Rating
- average RS Composite Rating v2
- number of RS >= 80 stocks
- number of RS >= 90 stocks
- stock count
- median turnover
- number of Elite/Strong Momentum stocks
- percent of sector stocks with RS >= 80

Leadership Score:

```text
Leadership Score =
0.35 * percentile rank of Sector_RS_Average
+ 0.25 * percentile rank of RS_80_Pct
+ 0.20 * percentile rank of RS_90_Stocks
+ 0.20 * percentile rank of Elite_Strong_Stocks
```

Use this to see where leadership is clustering before selecting individual
stocks.

## TradingView Exports

The app exports plain symbols by default. If your CSV includes an `Exchange`
column, the export uses `EXCHANGE:SYMBOL` format.

Example:

```text
AAPL,MSFT,NASDAQ:NVDA,NYSE:JPM
```

RS Bucket Watchlist groups symbols into:

- RS 95-100
- RS 90-94.99
- RS 85-89.99
- RS 80-84.99

Other exports:

- `Prime Watch`: only `A - Prime Watch`
- `Emerging Momentum`: only `Emerging Momentum`
- `Trade Plan CSV`: a CSV with useful fields for review/planning

## Suggested Daily RS Review Process

1. Upload the latest CSV.
2. Keep liquidity at 20M USD minimum.
3. Start with RS >= 80.
4. Review `RS >= 90`, `Prime Watch`, and `Elite / Strong` metrics.
5. Check sector leadership.
6. Export `Prime Watch`.
7. Export RS buckets if you want a broader TradingView list.
8. Review charts manually:
   - trend
   - base pattern
   - pivot/entry
   - volume
   - ATR
   - distance from EMA20/EMA50
   - risk/reward
9. Set alerts only on stocks with clean price action and a clear plan.

## How To Interpret The Output

The RS Screener is a ranking tool, not an execution tool.

Strong automatic candidate:

- RS >= 90
- Avg 60D Turnover >= 20M USD
- Elite or Strong Momentum
- A - Prime Watch
- Not extended above EMA20/EMA50
- Near EMA20, EMA50, or 52-week high
- Sector leadership is also strong

Candidate to avoid or de-prioritize:

- Low liquidity
- RS < 80
- Extended above EMA20 or EMA50
- Deep below 52-week high
- Stale Leader
- Short-term Spike without base structure
- Weak sector leadership

## Common Problems

### The RS Screener says required columns are missing

Check that the uploaded CSV contains the exact required column names. The app
expects names such as:

```text
Performance % 3 months
Average Volume 60 days
Market capitalization
```

### EMA20 filter is missing

The uploaded CSV does not include:

```text
Exponential Moving Average (20) 1 day
```

The app can still run, but it cannot calculate distance from EMA20.

### Sector leadership is missing

The uploaded CSV does not include a sector-like column.

Accepted examples:

- `Sector`
- `Industry Group`
- `Industry`
- `Group`
- `Category`

### No stocks appear after filtering

Possible reasons:

- Minimum RS rating is too high.
- Liquidity filter is too high.
- Max distance above EMA20 is too tight.
- Market cap filter excludes too much.
- Momentum Quality or Priority filters exclude all rows.

## Practical Reminder

The app should help you narrow the market from many names to a focused watchlist.
The final trading decision should still come from your chart review, market
exposure rule, stop loss, position size, and risk/reward plan.
