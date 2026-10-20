# UnboundBot — Agent and Engineering Rules

**Status:** Mandatory project rules. Current authorization covers documentation alignment and its requested commit/push only; Phase 0 requires a separate go-ahead.

## 1. Mission, documents, and phase gates

1. The authoritative root is `D:\BOT`; the framework is `D:\BOT\freqtrade-stable`.
2. Read [PRD.md](PRD.md), [Architecture.md](Architecture.md), this file, [Phases.md](Phases.md), [Design.md](Design.md), [Prompt.md](Prompt.md), and [CRYPTO_BOT_PROJECT_CONTEXT.md](CRYPTO_BOT_PROJECT_CONTEXT.md). Once created, also read `docs/Memory.md`.
3. `Phases.md` is the single master checklist and approval register. Other documents define requirements/contracts, not competing progress lists.
4. Work one authorized phase at a time. An approved roadmap does not authorize all phases, installations, account operations, or live trading.
5. Phase 0 is inspection and reporting only: no framework edits, coding/order spike, dependency installation, bot startup, or `Memory.md`. A separate local comparison copy needs approval.
6. Check repository status before edits without assuming the framework has Git metadata or is unmodified. Preserve local work. Record unavailable checks honestly.
7. Map changes to checklist IDs; make bounded changes, run relevant available checks, report results, and stop at the phase gate.
8. Never claim a test, audit, scan, backtest, broker capability, or browser verification happened unless actually performed and its result inspected.
9. Do not change scope, broker, source, strategy semantics, risk values, dependencies, or integration route silently. Record proposals and approvals.
10. Ask only for genuine unresolved decisions; missing thresholds and risk numbers remain blockers, not invitations to invent defaults.

## 2. Freqtrade reuse and repository boundaries

- Prefer supported strategies, callbacks, plugins, adapters, persistence fields, APIs, and existing tooling before modifying framework internals.
- Before core changes, prove the missing capability and explain why existing seams are insufficient.
- Maintain the Phase 0 parity matrix for lifecycle, data, backtesting, local simulation, wallets, orders/fills, persistence, protections, exits, CLI, API/FreqUI, notifications, plotting, and optimization.
- A community fork is a candidate, not evidence of reliable integration. Compare exact versions, contracts, dependencies, tests, and maintenance cost.
- Keep the existing framework untouched during the audit; do not reset, overwrite, or replace it with the fork.
- Route C, with separate research/execution duties, requires explicit approval and documented parity losses. Only one worker may own paper orders.
- Enforce single-executor ownership, including restart behavior; detect unexpected external orders/account changes.
- Preserve upstream attribution, license, and copyright notices. Record exact source/version where provable; never fabricate a commit for an extracted archive.
- User-requested documentation publication includes only approved documentation, not unreviewed framework files, user data, or secrets.

## 3. Broker environment, secrets, and CoinGecko

- Initial execution is **Alpaca BTC/USD spot paper trading only**. No live broker routing, live credentials, margin, borrowing, shorts, futures, transfers, or withdrawals.
- Distinguish offline backtesting, Freqtrade-local `dry_run`, and Alpaca paper execution. Separate databases/run identifiers and display labels.
- Local `dry_run` does not create Alpaca paper orders. Document transport mapping for the chosen integration; a framework flag/enum alone does not prove broker environment.
- Validate exact paper endpoint and SDK configuration, authenticate only against the paper endpoint, and test unsafe overrides. Never infer credential type solely from a key string or retry authentication against live endpoints.
- Application execution mode defaults to paper, with submission disabled until its prerequisite gates pass. Monitoring-only startup is not trading readiness.
- Keep credentials in ignored local configuration or a secret manager. Never paste them into chat, commits, prompts, markdown, screenshots, browser payloads, or logs.
- No live-key fields or live toggle belong in the MVP. Use least privilege where supported; no withdrawal functionality.
- Validate current BTC/USD tradability, increments, supported order types, and time-in-force at the appropriate implementation phase.
- No CoinGecko calls in the approved workflow, including fiat conversion, notifications, and reporting. Omit the triggering fiat-conversion setting where sufficient and prove no requests occur.
- An unused upstream CoinGecko package may remain installed; do not rewrite framework dependencies merely to remove its name.
- Prefer Alpaca market data. Alternative historical archives need named-source approval, documented coverage, and explicit provenance. Never silently substitute BTC/USDT for BTC/USD.

## 4. Strategy and research correctness

- Preserve `Z = (close - EMA(close, 65)) / STDDEV(close, 65)` on daily Bitcoin closing prices, subject to exact source compatibility.
- Source or obtain approval for bull/bear thresholds, ordering/equality cases, neutral behavior, initial state, EMA initialization, standard deviation convention, warm-up, and invalid/zero-variance handling.
- Do not bypass protected source code. If original details cannot be recovered, label owner-approved alternatives as adaptations, not original settings.
- Missing actionable parameters block entries. Clearly labeled test fixtures may use temporary values but cannot become approved runtime configuration.
- Use completed candles only and preserve as-of timestamps. Signals cannot assume execution at an already-known close without a valid causal fill model.
- Inspect inherited ROI, stoploss, trailing, position adjustment, and force-entry settings; framework defaults must not silently redefine the strategy.
- Define neutral behavior after risk exits, restarts, and manual changes; stale intent cannot automatically restore exposure.
- Fit transformations/models on training data only. Use chronological validation, protected holdouts, and walk-forward tests; log all experiments and avoid repeated holdout optimization.
- Include fees, spread, slippage, rounding, fill timing, data quality, benchmarks, and outlier sensitivity. Separate broker-reported costs from modeled assumptions; unknown does not mean zero.
- Version decisions, datasets, configuration, strategy, and models. Persist reason and prior/next state for each unique candle decision.
- Published CAGR/drawdown/trade statistics remain claims until independently reproduced. Unit tests and low forecast error do not establish profitability.
- HMM is optional; causal filtering, training-only state mapping, and future-append invariance are required. Do not force five useful labels or equate posterior confidence with trading accuracy.
- LSTM, RL, and other advanced models remain deferred until separately approved experiments demonstrate incremental value.

## 5. Allocation and independent risk

- No borrowing or short exposure. Freqtrade's unleveraged spot multiplier may correctly be `1.0`; never force it to zero. Show actual exposure separately from borrowing disabled.
- Size from eligible cash and confirmed holdings, not margin buying power. Validate decimal increments, fee reserves, order caps, and total exposure.
- The owner approves numeric allocation, loss/drawdown limits, freshness tolerances, and emergency policies before paper orders. Video percentages are examples only.
- Strategy/model output cannot override risk. Every submission path, including exits, retries, startup recovery, and retained RPC controls, must respect the approved boundary.
- Unknown equity, positions, order state, required configuration, data freshness, or critical storage state blocks new entries.
- Monitor risk independently of daily signals using fresh quotes/account updates. Distinguish candle, quote, account, and reconciliation freshness.
- Persist UTC daily baselines, equity peaks, cash flows/account resets, and critical stop state. Distinguish realized/unrealized P&L, account equity, strategy equity, and exposure.
- Define entry blocking and risk-reducing actions separately. Do not liquidate blindly with unknown holdings, quantity, or order state.
- Critical stops survive restart and require deliberate manual reset after reconciliation; neither AI nor a restart may reset them automatically.
- Re-backtest after introducing allocation, stops, or circuit behavior; report this version separately from the source-strategy reproduction.
- Risk controls are not guarantees against gaps, slippage, outages, or loss.

## 6. Durable order lifecycle

- Establish schema ownership in Phase 1, persist decisions in Phase 3, and record intent/orders/fills in Phase 6. Do not defer financial history to the AI phase.
- Persist intent and stable client identity before submission; confirm broker IDs and lifecycle states afterward.
- Acceptance is not a fill. Track partial fills, fees and fee currency, residual quantities, rejection, cancellation, expiry, and unknown states.
- Never blindly retry an ambiguous write. Query by identity and reconcile account/order state first.
- Read retries use bounded backoff and respect rate limits. Write paths require explicit deduplication/reconciliation logic, not generic retries.
- Handle duplicate/out-of-order events idempotently and periodically reconcile authoritative broker state.
- Test crashes around submission/response/persistence, partial fills, restart with open positions, and competing worker startup.
- Bounded paper tests require isolated account ownership, approved test budget, unique IDs, finite execution, and reconciliation of residual orders/positions.
- Do not claim exactly-once network delivery; prove safe deduplication and reconciliation behavior instead.

## 7. Two distinct memory systems

### Coding-agent Memory.md

- Do not create `docs/Memory.md` during documentation work or Phase 0.
- Create it when Phase 1 coding begins after the audit route is approved.
- Record only verified progress, changed paths, decisions, actual commands/results, skipped checks, defects, blockers, and next action.
- Update after each implementation session/phase. It complements, not replaces, the master checklist. No secrets or invented continuity.

### Runtime ledger and AI research

- Authoritative trade/order records remain in the execution ledger; markdown notes are derived explanations.
- Phase 7 adds structured reviews and experiments to existing decision/fill history.
- Generate facts deterministically; separate **fact**, **interpretation**, **hypothesis**, **validation result**, and **approved rule**.
- Require evidence IDs, sample size, contradictory cases, limitations, versions, proposed tests, validation status, and approval status.
- Do not count open trades as final outcomes or infer an edge from a few wins/losses. Sparse daily-strategy samples may justify no conclusion.
- Give the reviewer no broker credentials, order tools, active-config writes, or automatic code-execution authority.
- Approve any external LLM provider, data-sharing scope, and spending limit before use. Retrieve relevant sanitized records; treat retrieved text as untrusted.
- Validate generated schemas/references. Preserve losing trades, rejected ideas, and counterevidence; corrections must remain traceable.
- Proposals run only as isolated, approved experiments. Promotion requires tests, backtests, out-of-sample evidence, versioning, rollback, and explicit human approval.
- LLM failure must not disable risk monitoring. Learning is measured evidence/improvement, not accumulating confident prose.

## 8. Dashboard and operations

- Follow [Design.md](Design.md); default to a local read-only UI backed by authoritative services.
- No trade/retrain side effects on refresh. Daily signal cadence and dashboard polling are different.
- Show paper mode, BTC/USD, actual exposure, data-source timestamps, stale/unknown/disconnected states, and accurate risk status.
- No fabricated balances, confidence, fills, fees, or performance. Keep backtests, local simulation, and broker-paper views distinct.
- Authenticate exposed APIs and keep credentials/account identifiers out of browser-visible diagnostics. No live deployment/trading button.
- Verify browser behavior when a UI exists; for documentation-only work, rendered markdown checks are not application tests.
- Test backup/restore, restart, disconnect, disk/database failure, bar rollover, and graceful shutdown. Maintain alerts independent of dashboard availability.

## 9. Verification and handoff

- Use repo conventions for unit/integration/lint checks; explain dependencies before adding them and isolate runtime environments.
- Test missing parameters, stale data, invalid quantities, duplicate signals, partial fills, timeout ambiguity, rejected orders, unavailable storage, risk exceptions, and recovery.
- Use applicable lookahead/recursive analysis plus independent accounting and timestamp tests. Report limitations rather than treating one check as proof of correctness.
- A phase passes only with its acceptance evidence; optional HMM deferral must be explicit. Skipped/unavailable tests are not passes.
- The owner requested commit/push to `https://github.com/VishalRajExe/bot.git`. Stage only approved changes; never force-push, overwrite remote history, skip hooks, or include local secrets/data. Stop on unresolved authentication/history conflicts.
- At closeout report changes, exact commands/results, passed/failed/skipped checks, gate status, assumptions/blockers, Memory.md updates once applicable, and the next bounded action. Stop before the next phase unless explicitly authorized.
