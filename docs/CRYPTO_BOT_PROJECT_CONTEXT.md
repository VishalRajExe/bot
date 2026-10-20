# UnboundBot — Persistent Project Context

**Purpose:** Preserve the owner's goals, source material, verified planning observations, and unresolved questions for future agents. [Phases.md](Phases.md) is the single progress/approval checklist. This context document is not coding-agent `Memory.md` and does not certify an implemented bot.

## 1. Confirmed project scope

- Product: **UnboundBot**; dashboard working name: **Regime Trader**.
- Authoritative root: `D:\BOT`; existing framework: `D:\BOT\freqtrade-stable`; documentation: `D:\BOT\docs`.
- Earlier references to a different root were mistakes, corrected by the owner. Do not migrate folders.
- Primary objective: build a reliable BTC/USD cryptocurrency trading bot by reusing Freqtrade's working infrastructure wherever compatible.
- Initial execution: **Alpaca paper account, Bitcoin spot, long/cash, no borrowing, shorts, margin, futures, transfers, or real-money orders**.
- Initial strategy timeframe: daily completed candles. Price/account/risk monitoring may run more frequently; dashboard refresh is not trading cadence.
- No CoinGecko calls, including incidental fiat-conversion/reporting paths.
- One execution authority, an independent risk layer, durable trade/decision history, an evidence-based research assistant, and a read-only dark dashboard.
- HMM is optional and experiment-gated. LSTM is later research, not initial implementation.
- The current approved step is documentation alignment and its requested commit/push, not Phase 0 or coding. No dependencies or broker activity are started by this documentation.
- The owner requested publication to `https://github.com/VishalRajExe/bot.git` and browser verification of built artifacts. Scope publication to approved work; markdown verification is not a bot runtime test.

## 2. Source inventory and confidence

| Source | Available evidence | Limitation |
|---|---|---|
| Existing Freqtrade source | Local checkout directory, README, metadata, limited inspected code | Full provenance, runtime, tests, and compatibility audit pending |
| Six project specification documents | Read directly with this context file | Requirements/proposals, not implementation evidence |
| `C:\Users\visha\Downloads\strategy.txt` | Read directly; content summarized below | Thresholds, executable code, full trade export, identified data, and costs incomplete |
| LSTM paper | Full supplied text read | No reproducible code/data supplied; returns not validated |
| Three Regime Trader screenshots | Supplied and visually inspected | Visual examples, not our account/model facts |
| First/second YouTube videos | Earlier context summaries preserved below | Original transcripts/URLs not independently available/inspected in this session |
| Alpaca-enabled fork | URL supplied | Current code, activity, and limitations require Phase 0 verification |

Historical source labels in the previous context were `Pasted markdown(20261020-112729).md` (README), `Pasted text(20261020-111648).txt` (first video), and `Pasted text (2)(1).txt` (second video). These labels do not mean those original files are present in this workspace. Filename checks did not locate the pasted transcript files here. Do not pretend to have read unavailable originals.

## 3. Freqtrade foundation and planning observations

The actual framework directory is present, so the project is no longer limited to an uploaded README. The README describes strategy execution, local dry-run, backtesting, historical-data tools, plotting, hyperparameter optimization, SQLite persistence, FreqAI, API/WebUI, Telegram, and performance reporting.

Limited source inspection established:

- `pyproject.toml` declares Python `>=3.11`, GPLv3, CCXT, SQLAlchemy, numerical dependencies, FastAPI, optional optimization/AI/testing tools, and `pycoingecko`.
- The local README does not list Alpaca. This alone is not proof that no integration can be built.
- The exchange order path uses a local simulator when `dry_run` is enabled; this does not exercise an Alpaca paper account.
- Spot trade accounting has a valid unleveraged `1.0` multiplier. No borrowing means no borrowed exposure, not zeroing this multiplier.
- RPC fiat conversion is conditionally initialized from `fiat_display_currency`; its implementation uses CoinGecko. Disable and test runtime conversion rather than unnecessarily rewriting dependencies.

These observations do not establish the framework's Git ancestry, clean state, installed runtime, passing tests, or working Alpaca support. Publication Git setup for documentation is not upstream framework provenance.

Phase 0 must compare the local source with `https://github.com/aidinstinct/freqtrade-alpaca`, evaluate current official APIs/docs, and recommend one route with a reuse/feature-parity matrix. Earlier notes mention an upstream support issue and fork limit-order warning; reverify rather than repeating them as current facts.

## 4. Strategy candidate — Dual Signal Trend Sentinel

### Source description

- Bitcoin spot; daily timeframe.
- Baseline: EMA of closing price over 65 periods.
- Volatility: standard deviation of closing price over 65 periods.
- Score: `Z = (close - EMA65(close)) / STDDEV65(close)`.
- Above the bullish filter: enter/maintain long exposure.
- Below the bearish filter: exit to cash.
- Between filters: maintain prior position or remain in cash.
- Source says confirmed bars, `ta.ema()`/`ta.stdev()`, no lookahead security calls, and no repainting; verify rather than assume this proves causality.
- TradingView search lead: **DurdenBTCs Dual Signal Trend Sentinel**. The note says the code is protected. Use only authorized material; do not bypass protection.
- The note also uses the name “VAMS”; do not infer this establishes a separately verified strategy version.

### Reported figures — claims only

| Metric | Source claim |
|---|---|
| Period | May 2014–January 2026, about 11.66 years |
| Total return | 36,465% |
| CAGR | 65.92% |
| Maximum drawdown | 26.79% |
| Trades | 53 |
| Win rate | 47.2% |
| Profit factor | 3.26 |
| Average win / loss | +48.01% / -5.86% |
| Win/loss ratio | 8.19:1 |
| BTC buy-and-hold comparison | 56.18% CAGR and roughly 75% drawdown |
| Claimed relative result | 2.03× returns with 2.8× less drawdown |
| Median / mean holding period | 18 / 45 days |
| Longest reported trade | 196 days |

The source describes Trade #27 from October 8, 2020 at $10,930 to April 22, 2021 at $51,704, about +373%, and attributes about 28% of cumulative returns to it. Stress-test outlier dependence; do not adopt the attribution without a defined calculation.

Other source statements to retain as unverified:

- Peak equity around $15.5M in November 2021, trough around $12.2M in November 2022, and recovery in January 2024. Check numerical consistency against the stated drawdown and full equity series.
- A recalculated ending value of $36,568,952 versus TradingView's $36,565,336, described as a $3,616 rounding difference.
- A long entry on January 13, 2026 at $95,341. This is a historical source statement, **not a current actionable signal**.
- Parameters allegedly selected in 2014, live use since 2023, and roughly 0.5% per-trade slippage. No dated implementation or independent live ledger was supplied.
- Added RSI/MACD/volume filters, weekly timing, grid search, Kelly sizing, and volatility scaling reportedly did not help. These are author observations, not constraints on our controlled research.

### Unresolved specification

Numeric bull/bear thresholds, complete source code, exact data/feed/candle boundaries, EMA initialization, standard-deviation convention, threshold equality, neutral behavior, warm-up, entry/exit timing, initial capital, compounding, and fee methodology are incomplete or unavailable.

Do not invent original parameters or tune to reproduce attractive metrics. Recover source evidence or obtain explicit approval for a labeled adaptation. Check neutral behavior after risk exits/restarts and inherited framework ROI/stoploss/trailing/position adjustments. Actionable entries remain disabled while required settings are unresolved.

## 5. First video — HMM regime bot inspiration

Earlier context identifies “How To Actually Build a Trading Bot With Claude Code (Fully Automated)” and describes five areas: regime model, allocation, independent risk, broker/execution, and dashboard. This is a preserved secondary summary, not a newly verified transcript.

Described ideas include crash/bear/neutral/bull/euphoria labels, price/volume features, regime/volatility-aware sizing, independent drawdown/loss circuits, modular tests, and walk-forward validation. The summary mentions five-minute execution alongside daily regime history; do not copy that timing mismatch into our daily strategy without a justified specification.

For UnboundBot:

- Start with a simple daily strategy and retain HMM only if controlled out-of-sample comparisons show value.
- Hidden state IDs have no intrinsic economic labels; derive/version labels from training statistics and do not force five useful states.
- Fit preprocessing/model on training only; use causal filtering for decisions. Future-aware smoothing must not relabel historical trading decisions.
- Separate filter and allocation experiments; retain independent risk caps and explicitly approve exposure mappings.
- A model posterior is not a probability of a profitable trade. Tests passing in a video do not prove returns.

## 6. Second video — AI trade memory and learning

Earlier context identifies “how to actually build an ai trading bot (full guide).” Its summarized concept is goals/rules → observe/execute → record outcomes → review lessons → repeat. It proposes a trade ledger and learning file, evolving into database storage as history grows.

Our implementation interpretation:

- The ledger is structured, durable, and authoritative; notes are derived research records.
- Record decisions before execution and orders/fills from the first paper test. Phase 7 adds AI review to existing history.
- Separate facts, interpretations, hypotheses, validation results, and approved rules.
- Require linked trade evidence, sample size, counterexamples, limitations, proposed experiment, model/strategy version, and test/approval status.
- Review completed trades and cohorts; a single loss is not a reason to invent a rule. With only dozens of historical trades, short paper samples may support no conclusion.
- Give AI no broker credentials, order tools, or active-rule writes. Approve provider/data-sharing/cost before connecting an external LLM.
- Preserve holdouts, unsuccessful experiments, contradictory evidence, versioned approval, and rollback. Optional generated code must be isolated and reviewed before execution.
- AI unavailability must not disable the trading system's independent safety controls.

## 7. LSTM paper — later research reference

Source: “Provide Bitcoin's daily optimal trading strategy based on LSTM,” Highlights in Business, Economics and Management, Volume 5 (2023), supplied as `Provide_Bitcoins_daily_optimal_trading_strategy_b.pdf`.

The paper describes data cleaning/normalization, 956 training observations and 300 subsequent test observations, LSTM forecasting of next-period prices from prior prices, BP/RBF comparisons, BTC/gold allocation, moving-average references, and transaction-cost constraints. It reports growing $1,000 to $80,827.34 over a stated September 2016–September 2021 period.

Reasons it is a research reference, not an implementation specification:

- It acknowledges prediction peaks/lag, including output resembling prices shifted by one day.
- Training loss/RMSE near zero is not out-of-sample economic evidence.
- The result table's final displayed date is in 2019 while the narrative claims a 2021 endpoint; the relationship is not explained.
- Its initial $940 transaction amount, fee notation, holdings units, and total-asset accounting are not sufficiently clear for faithful reproduction.
- Code, reproducible source data, exact hyperparameters, and fully specified leakage-safe transformations were not supplied.

Do not copy its returns or its 1%/2% fees as Alpaca assumptions. A future experiment requires training-only transforms, correct timestamp alignment, reproducible code/data, naive forecast baselines, walk-forward evaluation, and incremental performance after realistic costs. Keep it distinct from the Z-score strategy and HMM.

## 8. Dashboard reference and adaptation

The screenshots provide dark styling, sidebar controls, equity/cash strip, regime probabilities, stability, volatility rank, risk panels, history, and model tables. They show SPY, stock-market closed status, example balances, and example leverage/drawdown settings.

Use actual BTC/USD paper records instead:

- Persistent paper badge; crypto source freshness/health rather than stock-market hours.
- Strategy State/Z-score until a real HMM exists; no invented regime confidence.
- Eligible cash, equity, holdings, orders, fills, fees, actual exposure, borrowing disabled, P&L, limits, circuit state, and reconciliation.
- Separate timestamps for market, account, orders, risk, and model; a page refresh does not make old data fresh.
- Research-only labels for unapproved hypotheses, with evidence and validation state.
- Read-only first; no order/retrain effects on refresh and no live switch.

[Design.md](Design.md) retains the visual specification. Browser tests must validate the implemented artifact, not screenshot values.

## 9. Build order and unresolved gates

Follow [Phases.md](Phases.md), not an alternate implementation list:

1. Documentation alignment, then wait for Phase 0 authorization.
2. Read-only framework/fork audit and approved integration route.
3. Minimal implementation foundation and coding-agent Memory.md.
4. Verified data, exact/approved strategy, and reproducible research.
5. Approved independent risk and one reconciled paper executor with existing durable history.
6. Structured AI reviews and controlled experiments.
7. Optional HMM experiment or explicit deferral.
8. Read-only dashboard, operational hardening, and extended paper observation.

Unresolved: framework provenance/runtime, safest Alpaca route, exact strategy semantics, data coverage/archive approval, numeric risk/exposure limits, emergency action policy, original videos/exports, AI provider/sharing/budget, and HMM promotion. LSTM remains deferred. No source claim establishes profits.

## 10. Continuity rules

- Context and Phases.md preserve pre-coding plans. `docs/Memory.md` begins only when Phase 1 code implementation starts after the audit.
- Memory.md records actual work/tests/decisions/blockers; runtime trading memory is a separate database/ledger.
- Keep source claims distinguishable from verified observations, assumptions, proposals, and approved decisions.
- At every phase, report changed files, commands/results, skipped checks, gate status, and one next authorized action.
- Do not silently advance phases, publish unrelated framework/runtime files, or enable live trading. Passing paper evaluation does not authorize live readiness work.
