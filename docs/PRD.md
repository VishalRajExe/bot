# UnboundBot — Product Requirements Document (PRD)

**Status:** Approved documentation alignment; Phase 0 not started  
**Version:** 0.2  
**Prepared:** 2026-10-20  
**Project root shown by the owner:** `D:\BOT`  
**Existing local engine checkout shown by the owner:** `D:\BOT\freqtrade-stable`  
**Dashboard working name:** Regime Trader / UnboundBot

## 1. Product summary

UnboundBot is a customizable Bitcoin spot-trading system built alongside the existing Freqtrade codebase. The goal is to retain as much proven Freqtrade infrastructure as practical while adding the owner's strategy, regime analysis, risk controls, post-trade memory, controlled research loop, and a custom monitoring dashboard.

The first release is **BTC/USD spot paper trading through Alpaca**. CoinGecko is not the configured market-data or execution provider. Alpaca's own crypto market-data and trading APIs are the preferred venue interfaces, subject to verifying the requested historical data is available. If Alpaca cannot supply the full history needed for a reproducible backtest, the bot may use a separately approved historical OHLCV archive; that source must be documented and must not be silently mixed with Alpaca data.

This is a software engineering and research project, not a promise of positive trading returns.

[Phases.md](Phases.md) is the single master checklist and approval register. The current authorization covers documentation alignment and its requested commit/push only. Phase 0 requires a separate go-ahead; no bot, installation, broker connection, or coding-agent memory is started by approving this documentation.

### Delivery milestones

- **Operational foundation:** one Freqtrade-first trading authority, verified data and strategy, independent risk, durable decision/order records, and reconciled Alpaca paper execution (Phases 0–6).
- **Research assistant:** evidence-linked reviews and isolated experiments without authority over orders or active rules (Phase 7).
- **Optional regime research:** evaluate HMM independently; adoption, rejection, or explicit deferral are valid outcomes (Phase 8). This must not block the baseline dashboard once deferral is recorded.
- **Observable paper product:** a read-only dashboard and extended operational evaluation (Phases 9–10). LSTM remains outside the initial build.

These are modules of one application, not a requirement for microservices or duplicate trading engines.

## 2. Product goals

1. Preserve useful capabilities already provided by Freqtrade instead of rewriting them unnecessarily.
2. Reproduce and independently evaluate the provided BTC daily Z-score trend strategy.
3. Paper-trade BTC/USD using Alpaca before any discussion of real-money execution.
4. Keep strategy logic, regime classification, allocation, risk checks, and broker execution in testable boundaries.
5. Record every signal, decision, order, fill, fee, position change, and closed-trade outcome.
6. Build a transparent learning loop that reviews history, writes evidence-backed research notes, and proposes experiments without changing live rules by itself.
7. Deliver a dark dashboard inspired by the supplied “Regime Trader” screenshots, adapted for a 24/7 crypto market and BTC/USD.
8. Make development resumable across coding agents and chats using these documents and a `Memory.md` file created when coding begins.

## 3. Non-goals for the first release

- No live-money trading, live API credentials, or automatic switch from paper to live.
- No leverage, margin, futures, short selling, borrowing, or withdrawals.
- No multi-asset portfolio until BTC is end-to-end reliable.
- No autonomous changes to live strategy code, thresholds, sizing, or risk limits.
- No LLM-generated orders bypassing the deterministic strategy and risk manager.
- No LSTM, reinforcement-learning, or other predictive model in the initial baseline. The supplied LSTM paper is a later research reference, not a production requirement.
- No scraping/news/sentiment subsystem until the core historical-data, strategy, and paper-execution path is validated.
- No wholesale rewrite of Freqtrade's backtester, exchange handling, storage, CLI, or existing controls unless the initial compatibility audit demonstrates a concrete gap.

## 4. Target user

The initial and primary user is the project owner/developer operating the bot on a Windows development machine, inspecting source code, running backtests, reviewing strategy decisions, and observing paper trading through a dashboard. The system should be straightforward for a future coding agent to understand and maintain.

## 5. Initial operating assumptions

| Item | Initial requirement |
|---|---|
| Asset | Bitcoin only |
| Alpaca symbol | `BTC/USD` (verify current active/tradable asset metadata at startup) |
| Market | Spot only, long-only |
| Strategy timeframe | Daily candles for the first Z-score baseline |
| Broker/execution | Alpaca paper-trading API |
| Preferred market data | Alpaca crypto market-data API where available |
| Alternative historical data | Only after explicit selection and documented source/version/date coverage |
| Execution mode | Alpaca paper only for broker orders; offline backtests and Freqtrade-local simulation are separate non-live workflows |
| Leverage | No borrowing, margin, or shorts; preserve Freqtrade's valid unleveraged `1.0` spot multiplier and enforce approved exposure limits |
| Strategy research | Historical backtests and out-of-sample/walk-forward evaluation before promotion |
| Persistence | Reuse Freqtrade's persistence if compatible; otherwise SQLite for custom state, with one source of truth for each record type |
| Dashboard | Custom dark “Regime Trader” dashboard; keep Freqtrade's own interface/features where useful |

Do not infer that Alpaca's available historical crypto candles reach back to May 2014 simply because the strategy notes use a 2014 start date. Query and record the actual date coverage before reporting a long-history backtest.

## 6. Strategy candidate supplied by the owner

The first strategy candidate is a daily Bitcoin spot trend system referred to in the notes as **Dual Signal Trend Sentinel**. The provided `strategy.txt` states the following logic:

- Baseline: 65-period EMA of closing price.
- Volatility measure: 65-period standard deviation of closing price.
- Score: `(close - EMA65) / STDDEV65`.
- If score is greater than a bullish threshold, the state is bullish and the strategy is long.
- If score is below a bearish threshold, the state is bearish and the strategy exits to cash.
- Between thresholds, the state is neutral; the source says to maintain the existing position or remain in cash.
- Calculations should use confirmed/closed bars, with no future information.

**Important missing input:** The supplied notes do not specify the numeric bull and bear thresholds or complete executable code. The agent must not invent these values or describe them as verified. It must locate them in the owner's source material if available, otherwise ask the owner to approve explicit candidate values before using the strategy for actionable paper orders. Unit tests and research experiments may use clearly labelled temporary parameters, but those parameters must not silently become approved production configuration.

Neutral-state behaviour must be made deterministic and documented (e.g. carry forward the existing position state, while never opening a new position solely because the state is neutral). The exact behaviour must match the source strategy once the missing details are resolved.

The notes report results including 65.92% CAGR, 26.79% maximum drawdown, 47.2% win rate, profit factor 3.26, 53 trades, and a 2014–January 2026 test period. These are **claims in the supplied notes, not accepted results for this implementation**. Reproduce them only if the exact thresholds, trading rules, history, accounting, fees, and assumptions are available. Otherwise label the reproduction as incomplete and report our own measured results separately.

## 7. Functional requirements

### FR-01 — Freqtrade reuse and parity

Audit the checked-out version and preserve existing capabilities where possible: strategy lifecycle, historical data tools, backtesting, dry-run, database persistence, stop/exit mechanisms, exchange abstraction, CLI, monitoring APIs/UI, notifications, and parameter optimization. Produce a feature-parity matrix that identifies what we reuse, adapt, defer, or cannot use with the selected Alpaca integration.

The local README does not list Alpaca. Existing project notes identify an upstream Alpaca-support issue and a candidate fork (`aidinstinct/freqtrade-alpaca`) with a reported limit-order testing warning. Their current status and exact code must be reverified in Phase 0; they are not proof of compatibility. Compare the candidate with the local checkout without replacing existing files. See [Architecture.md](Architecture.md) for the route decision.

Freqtrade's `dry_run` simulates orders locally; it is not Alpaca paper execution. The audit must document the selected integration's transport/configuration mapping, and keep local simulation and broker-paper databases and dashboard metrics distinct. Safety is enforced by validated paper routing and credentials, not by assuming a framework flag or enum proves the broker environment.

The checkout includes CoinGecko fiat-conversion support. Keep it inactive in the approved application workflow, including notifications and reporting; test that no CoinGecko requests occur. An upstream dependency may remain installed without being used, avoiding unnecessary framework surgery.

### FR-02 — Market data

- Retrieve BTC/USD candles and any required latest quotes from the selected Alpaca endpoints.
- Validate timestamps, duplicate/missing candles, OHLC consistency, volume, and timezone.
- Persist the data-source identity, retrieval time, timeframe, and range.
- Do not use incomplete daily candles to produce end-of-day strategy signals.
- Block strategy execution when data is stale, malformed, or missing beyond configured tolerances.
- Record historical data limits; never fill gaps or splice providers invisibly.

### FR-03 — Baseline strategy

- Implement the documented EMA65/STDDEV65 score with a configurable, explicit threshold pair.
- Keep calculation and state-transition tests independent from trading execution.
- Use completed candles only.
- Produce a structured signal and a human-readable decision explanation.
- Keep strategy parameters versioned and exportable.
- Compare strategy results with BTC buy-and-hold and at least one clearly documented baseline.

### FR-04 — Regime classifier (later than baseline)

- Add HMM regime detection as an independent, optional research component.
- Candidate states may include crash, bear, neutral, bull, and euphoria, but HMM state numbers do not intrinsically have these meanings; mappings must be based on documented training-period characteristics.
- Report probabilities, state mapping version, stability/persistence, training window, and model version. A state posterior is not a probability of a profitable trade.
- Use causal filtering for decision-time regimes, not future-aware full-sequence smoothing. Appending future data must not rewrite earlier decision-time predictions for a fixed model.
- Do not permit HMM output to bypass the strategy or risk controls. Approve any regime-to-exposure mapping independently; do not force five meaningful labels if unsupported.
- Compare the same strategy with and without the HMM filter on identical data and costs before considering it an approved filter.

### FR-05 — Allocation and position sizing

- Calculate permitted order size from account balance/equity, existing positions, strategy target, and risk settings.
- Use decimal-safe financial arithmetic where possible.
- Enforce maximum order notional, available balance, asset increments, and portfolio exposure.
- Start with unleveraged spot; no shorts.
- Never use example allocation/leverage settings copied from a video as defaults without explicit approval.

### FR-06 — Independent risk controls

- Risk checks run independently of the HMM and AI review layer.
- Include daily-loss and peak-drawdown thresholds, maximum position/exposure limits, stale-data block, duplicate-order guard, API failure handling, and persistent kill switch.
- When a critical risk dependency is unavailable or state is ambiguous, fail closed: no new entries.
- A critical stop requires deliberate manual reactivation after reconciliation and review.
- Define whether drawdown is based on realized P&L, unrealized P&L, or equity; display the chosen calculation clearly. Persist UTC daily baselines and equity peaks, and account for cash flows/account resets.
- Monitor risk on fresh account/price updates independently of daily signal cadence. Define separate freshness limits for candles, quotes, account state, and reconciliation.
- Specify entry blocking separately from approved risk-reducing actions; do not blindly liquidate when positions or quantities are unknown.
- Cover every submission path, including framework exits, retries, recovery, and retained RPC controls. Test single-executor ownership.
- Re-backtest the integrated strategy after adding sizing, stops, or circuit policies; those changes alter the strategy being evaluated.

### FR-07 — Alpaca paper execution

- Use Alpaca for paper account, orders, fills, positions, and supported crypto market data.
- Use the official paper endpoint and paper-only API credentials. Startup must display `PAPER` clearly and refuse live broker routing. Validate endpoint/SDK configuration and successful paper-account authentication; do not claim credential environment can be inferred from the key string alone. Never fall back to live authentication.
- Validate the current asset metadata and precision constraints at runtime.
- Track every order through its confirmed lifecycle; a successful request response is not assumed to mean the order filled.
- After timeout/ambiguous response, reconcile orders and positions before retrying to avoid duplicate execution.
- Start with a simple documented order-type policy (market orders for the initial low-frequency paper baseline; limit orders require separate validation).

### FR-08 — Trade ledger and post-trade review

Store a durable ledger containing, at minimum: trade/order ID, timestamp, asset, strategy and model versions, signal inputs, regime output, decision reason, intended size, order request, fills, fees, realized/unrealized P&L, exit reason, and reconciliation state. Use the framework database/API where suitable and avoid creating conflicting duplicate sources of truth.

Create schema ownership in Phase 1, persist decisions in Phase 3, and persist intent before submission plus complete order/fill history in Phase 6. Phase 7 adds structured reviews and experiment records; it must not be the first time trades are recorded. Separate actual broker fees from modeled cost assumptions, with unknown values labeled as unknown.

After a trade closes, create a structured review. The LLM may summarize and propose hypotheses, but a single loss does not automatically justify a new rule. Every proposed change needs evidence, sample-size context, a backtest, out-of-sample validation, a versioned change record, and human approval. The reviewer has no broker credentials, order tools, or active-configuration write access. Approve its provider, data-sharing policy, and budget before any external LLM connection. Research failure must not interrupt core risk monitoring.

### FR-09 — Two kinds of memory

1. **Coding-agent `Memory.md`:** a short current-state/context file for agents, created only when code implementation begins, as requested by the owner. It records repository findings, architecture decisions, current phase, tests, known issues, and next steps. Update it at the end of each phase.
2. **Runtime trading memory:** a persistent trade ledger plus structured learning notes/research hypotheses, backed by application storage. This is operational data and must not be confused with `Memory.md`.

### FR-10 — Custom dashboard

Provide a dark dashboard inspired by the supplied Regime Trader screenshots, adapted from SPY/equities to BTC/USD spot crypto. Include:

- Mode badge (`PAPER`), current equity, cash/available balance, and 24/7 market/data status.
- BTC/USD price chart with regime overlays and recent history.
- Current regime, confidence/probabilities, stability count, and volatility rank when those components are available.
- Daily/peak drawdown, configured limits, exposure, and circuit-breaker status.
- Current position, open orders, trade/signal feed, fills, P&L, fees, and exit reasons.
- Regime history/timeline and time spent in each mapped regime.
- Strategy/model information, recent logs, data freshness, Alpaca connectivity, and model/strategy versions.
- A persistent, highly visible paper-mode label; no live-trading button in the MVP.

### FR-11 — Testing and observability

- Unit tests for indicators, state machine, sizing, risk limits, memory schemas, and order-state transitions.
- Integration tests using mocks and paper endpoints where appropriate.
- Backtest leakage checks and reproducible run metadata.
- Structured logs with redaction of secrets.
- Health checks and clear error states in the dashboard.

## 8. Acceptance criteria for the paper MVP

The MVP is not complete until all criteria below are true:

1. The agent has audited the local `freqtrade-stable` checkout and documented the Alpaca integration choice without overwriting the existing checkout blindly.
2. The bot uses `BTC/USD`, spot-only, no leverage, paper-only configuration and has no live API credentials in its configured environment.
3. Strategy calculations reproduce deterministic test fixtures and only use confirmed daily candles.
4. The numeric strategy thresholds are sourced or explicitly approved and documented; if unresolved, actionable strategy trading remains disabled.
5. Backtesting results include fees/slippage assumptions, data source/date coverage, exact parameters, benchmark, and out-of-sample results.
6. Duplicate orders, ambiguous timeouts, stale data, missing configuration, and risk-limit breaches are tested and rejected safely.
7. Paper orders and actual simulated fills reconcile correctly with the account state.
8. The ledger preserves decision, order, fill, and outcome history across application restarts.
9. The AI produces learning notes as hypotheses and does not change production strategy/risk settings automatically.
10. The dashboard matches `Design.md`, labels paper mode, and displays data freshness/error status.
11. All automated tests pass, and a clean reproducible start/test procedure is documented.

## 9. Initial success measures

Success in the first version means correctness and observability, not profit: reproducible calculations, zero known look-ahead leakage, correct paper-order reconciliation, tested hard stops, transparent cost accounting, a useful dashboard, and a working trade-review loop. Strategy profitability remains an empirical question.

## 10. Source references

- Local [Freqtrade README](../freqtrade-stable/README.md) and source: framework references present on disk; full provenance/runtime audit pending. Relative engine links require the local checkout and may be unavailable in a documentation-only remote repository.
- `C:\Users\visha\Downloads\strategy.txt`: read directly; original strategy description and performance claims, not validated trade data. TradingView lead: “DurdenBTCs Dual Signal Trend Sentinel”; protected code and missing thresholds remain blockers.
- Supplied LSTM paper text: read as a research reference only; not part of the MVP and not a verified implementation specification.
- Two YouTube videos: only existing context-document summaries and three dashboard screenshots are available here; original transcripts/URLs have not been independently inspected. See [CRYPTO_BOT_PROJECT_CONTEXT.md](CRYPTO_BOT_PROJECT_CONTEXT.md) for source limitations.
- Official Freqtrade docs: https://www.freqtrade.io/en/stable/
- Official Alpaca crypto docs: https://docs.alpaca.markets/us/docs/crypto-trading
- Official Alpaca paper-trading docs: https://docs.alpaca.markets/us/docs/paper-trading
- Candidate Alpaca-enabled Freqtrade fork: https://github.com/aidinstinct/freqtrade-alpaca
- Upstream Alpaca-support issue: https://github.com/freqtrade/freqtrade/issues/10862

Re-verify external API and repository status during Phase 0; this document is the starting contract, not proof that a third-party integration is current or complete.
