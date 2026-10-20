# UnboundBot — Dashboard and Visual Design

**Dashboard name:** Regime Trader  
**Product:** UnboundBot  
**Design status:** Approved documentation direction; no dashboard implemented. Based on the user's three Regime Trader screenshots, adapted for BTC/USD crypto spot trading. Progress and acceptance evidence belong in [Phases.md](Phases.md) (`P9-01` through `P9-15`), not a separate UI progress list.

## 1. Visual direction

Use a dark, technical, data-dense trading dashboard similar in tone to the provided reference screenshots: nearly black canvas, charcoal left sidebar, bright readable labels, thin separators, minimal card borders, and restrained state colours. The UI should feel like a serious monitoring console rather than a marketing website.

The screenshot currently displays `SPY`, equities-market `CLOSED`, a $99,999.61 example account value, regime confidence, stability bars, volatility rank, drawdown/peak-drawdown limits, regime history and a regime-profile table. These are visual examples only, not account facts or approved model outputs. Our dashboard must use actual BTC/USD/Alpaca paper account data and must not hardcode the example balances or regimes.

## 2. Theme tokens

Use CSS/theme variables instead of scattering hex values through UI components.

| Token | Initial value | Use |
|---|---|---|
| `bg` | `#0B0E13` | Main application background |
| `sidebar` | `#24262F` | Left navigation/settings sidebar |
| `panel` | `#121720` | Cards and chart/table surface |
| `panel-raised` | `#191E28` | Selected rows, menus, secondary panel |
| `border` | `#2C323D` | Dividers and subtle outlines |
| `text` | `#F4F6FA` | Primary text/numbers |
| `muted` | `#A0A8B5` | Labels, timestamps, help text |
| `accent` | `#F0525F` | Primary action/highlight, sliders and selected controls |
| `positive` | `#4ADE80` | Positive P&L, healthy status |
| `bull` | `#22C55E` | Bull regime |
| `bear` | `#F97316` | Bear regime |
| `crash` | `#EF4444` | Crash regime / critical loss state |
| `neutral` | `#94A3B8` | Neutral regime |
| `euphoria` | `#C084FC` | Euphoria regime |
| `warning` | `#FBBF24` | Warning / awaiting confirmation |
| `danger-surface` | `#3A171B` | Critical alert panel |
| `success-surface` | `#123323` | All risk checks clear |

All colours must remain distinguishable against the dark background. State meaning must also be conveyed in text/icons, not by colour alone.

## 3. Typography and spacing

- Preferred font: `Inter`, with `system-ui`, `Segoe UI`, and sans-serif fallbacks.
- Headings: bold/semibold; compact but not cramped.
- Primary account metrics: large (approximately 28–36 px on desktop).
- Section headings: approximately 22–28 px.
- Body/table labels: approximately 13–16 px; avoid unreadably small captions.
- Use a consistent 4/8 px spacing scale, rounded corners around 8–12 px, and subtle borders.
- Numbers should be tabular-aligned where possible; currency, percent, price precision and timestamps must be formatted consistently.

## 4. Page layout

### Left sidebar

- Product identity: `Regime Trader` with small `UnboundBot` sub-label if appropriate.
- Connection badge: Alpaca `PAPER` and connection state.
- Refresh interval control (dashboard polling only; default 10 seconds, configurable, not signal frequency).
- Fixed BTC/USD selection in MVP. Show a disabled/locked single-asset selector or one visible `BTC/USD` option; do not imply other assets are supported yet.
- Toggles for price chart, regime history, transition matrix, logs and model information.
- Last successful data refresh time, data age and broker/API health.
- Persistent `PAPER — SIMULATED ACCOUNT` label. Orders are real API requests to the paper service, not real-money trades; do not confuse them with Freqtrade-local simulation.

### Top account strip

Four primary blocks across the top:

1. **Mode:** `PAPER` badge, always prominent.
2. **Equity:** total paper account equity, with change/P&L context and timestamp.
3. **Eligible cash:** actual USD available for spot allocation after reconciled commitments/reserves. If a broker buying-power field is also displayed, label its meaning separately; never treat margin buying power as eligible spot cash.
4. **BTC/USD status:** last price and data freshness/API health. Crypto trades 24/7; do not display `MARKET CLOSED` just because a U.S. stock market is closed. Instead use `DATA LIVE`, `DELAYED`, `STALE`, `DISCONNECTED`, or `UNKNOWN` as appropriate.

### Main overview row

**Regime Detection panel** (when HMM is implemented): current mapped state, confidence/probability, state stability/persistence, volatility rank, probability gauge/bar, runner-up states and regime-profile table. Always show timestamp and model/state-map version. During the initial Z-score-only phase, label this panel `Strategy State` and show the Z-score plus bullish/bearish thresholds; do not pretend an HMM is running.

**Risk Status panel:** daily drawdown / approved limit, peak drawdown / approved limit, actual exposure (notional and percentage of equity), `Borrowing: disabled`, circuit-breaker state, and last successful risk evaluation. Alert when any required check is disabled, unknown, stale, or triggered. Freqtrade's valid unleveraged spot multiplier is `1.0`; do not force it to zero or mislabel funded holdings as zero exposure. Explain the daily UTC baseline, equity peaks, and treatment of cash flows/account resets.

### Detail sections

1. **Price and signal chart:** candlesticks for daily BTC/USD, EMA65 and strategy markers; optional regime-colour overlay after validated regime history exists. Mark the candle timestamps and signal/entry/exit times. No look-ahead/regime overlay based on future states in historical charts.
2. **Regime History:** time-line over recent bars, state counts, percentage of time per regime, transition view, mapping version. Clearly separate raw HMM state from mapped label if debugging is enabled.
3. **Current Position / Orders:** quantity, average entry, mark price, notional, unrealized P&L, order state, fees and last reconciliation status. Display `No position` when appropriate; distinguish missing data from zero position.
4. **Signal and Trade Feed:** timestamp, strategy/model version, regime/state, action, reason, proposed size, risk outcome, actual fill state, price, fees, realized P&L and exit reason. Include skipped trades/risk rejections as well as executed paper trades.
5. **Performance:** equity curve, drawdown curve, benchmark overlay, total return, CAGR only when period supports annualization, Sharpe/Sortino where properly defined, win rate, profit factor, trade count, exposure and costs. Show selected period and sample size.
6. **AI Learning Notes:** recent hypothesis, evidence/trade references, sample size, status, validation results and approval status. Show a strong label: `Research only — not active in strategy` for unapproved suggestions.
7. **System Diagnostics:** last market-data update, broker response/health, strategy loop status, DB health, last error, reconnect counters and log view with secrets redacted.

## 5. Dashboard interaction rules

- The dashboard is read-only in the first version.
- Refreshing the UI must not trigger a trade or retrain a model.
- Refresh polling is different from strategy cadence. The daily strategy acts on completed daily bars even if the UI refreshes every 10 seconds.
- If the backend disconnects, show a visible stale/disconnected banner and last known timestamp. Do not present stale values as live.
- “All circuit breakers clear” is only shown if each required risk check has a confirmed current state.
- Historical backtests, Freqtrade-local simulation, and Alpaca paper-account values must be visibly distinguished, with separate run/source identities.
- Display broker-reported fees separately from modeled slippage/cost adjustments. Unknown fees are unavailable, not zero; do not rewrite broker equity to match a modeled estimate.
- Use per-source timestamps for quotes, daily candles, accounts, orders, risk evaluation, and models. The page's last render time is not data freshness.
- A model posterior probability is not a probability of profit or a measured accuracy score. Do not hardcode 100% confidence or force five regime labels.
- Bind locally by default and authenticate exposed APIs. The UI receives no broker credentials; preserve independent alerts when the dashboard is unavailable.
- Do not place a live `Deploy` button in the MVP. Any future controls require authentication, confirmation, audit logging and risk validation.
- Avoid exposing API keys, secrets, account identifiers, local paths or sensitive config in dashboard logs.

## 6. Responsive behaviour and accessibility

Desktop is the primary development target, matching the supplied screenshots. At narrower widths, stack the top metrics and overview panels vertically; tables should scroll horizontally or collapse less-important columns rather than clipping values. Maintain keyboard focus, meaningful labels, readable contrast, and text/icons for regime and risk state in addition to colour.

## 7. Implementation guidance

Use Streamlit for the first custom dashboard if it integrates cleanly with the chosen engine, with theme tokens centralised. Retain Freqtrade's supported UI/API for its existing operations. Do not duplicate a full trading-control UI until the custom view has proven useful. Dashboard data should come from service interfaces or persisted storage, not direct exchange calls scattered in UI components.

## 8. Visual acceptance mapping

Track completion and evidence only in [Phases.md](Phases.md), using these task IDs:

| Criterion | Master checklist tasks |
|---|---|
| Dark reference direction, responsive layout, keyboard access and contrast | P9-01, P9-13 |
| Visible paper indicator and BTC/USD-only scope | P9-02 |
| Actual equity/cash/holdings and crypto freshness/health | P9-03, P9-11 |
| Strategy State before HMM; real signals and fill timestamps | P9-04 |
| Recorded regime outputs, defined probabilities, model/map versions | P9-05 |
| Approved limits, actual exposure, borrowing disabled, authoritative risk state | P9-06 |
| Reconciled positions/orders/fills/fees/P&L | P9-07, P9-13 |
| Distinct paper/backtest/modeled-cost views; no fabricated metrics | P9-08 |
| Evidence-linked hypotheses marked unapproved/inactive until promotion | P9-09 |
| Visible stale/unknown/disconnected failures and redacted diagnostics | P9-10, P9-11 |
| Read-only local default, authenticated exposure, recovery and backup tests | P9-12, P9-14, P9-15 |

When an application exists, use actual browser checks for rendering, read-only interactions, freshness/error states, and responsive behavior. During documentation-only work, a browser check verifies rendered markdown only; no app/server should be created for that purpose.
