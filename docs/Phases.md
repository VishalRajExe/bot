# UnboundBot — Master Build Checklist and Phase Gates

**Authoritative root:** `D:\BOT` · **Product:** UnboundBot · **Dashboard:** Regime Trader

This is the single progress checklist for the project. [PRD.md](PRD.md), [Architecture.md](Architecture.md), [Rules.md](Rules.md), [Design.md](Design.md), [Prompt.md](Prompt.md), and [CRYPTO_BOT_PROJECT_CONTEXT.md](CRYPTO_BOT_PROJECT_CONTEXT.md) define requirements, contracts, and source context.

## Current authorization and verified baseline

- The owner approved documentation alignment and requested a documentation commit/push to `https://github.com/VishalRajExe/bot.git` plus browser verification of what is built.
- Do not begin Phase 0, install dependencies, implement code, connect to Alpaca, start a bot, or create `docs/Memory.md` without the later phase authorization.
- All seven existing project documents, the supplied strategy note/paper/screenshots, local framework README/package metadata, and limited source paths were inspected for planning.
- This is not a completed repository audit or working installation. Framework Git provenance, installed runtime, current fork compatibility, strategy performance, and historical coverage remain unverified.
- Original video transcripts/URLs, executable strategy source, and a complete source trade export were not available for independent verification.
- Freqtrade local dry-run is distinct from Alpaca paper execution; valid unleveraged spot accounting uses a `1.0` multiplier; CoinGecko fiat conversion must be explicitly disabled/tested.
- **Status update 2026-10-21 (audit remediation):** a repository audit, a 55-test automated pytest suite (strategy/reconciliation/reporting/execution-safety, all mocked), reproducible backtests, lookahead/recursive leakage checks, and a read-only reconciliation harness ARE complete and evidenced in `docs/Audit_Remediation_2026-10-21.md`. **No paper orders have been placed by the current build and the trading process has NOT been restarted** — paper/executor lifecycle remains gated pending owner risk approval (`app/configs/risk_approval.json` absent) and an honest edge demonstration.

## Direction and checklist conventions

Build one Freqtrade-first trading application plus a separate research assistant. Reuse proven infrastructure; do not create a second executor or unnecessary microservices. HMM is optional; LSTM is deferred. Profitability remains an empirical question.

`Completed daily candle → validated features → approved strategy intent → optional approved regime policy → allocation → independent risk → durable intent → sole Alpaca paper executor → reconciliation → ledger → research review.`

Each task has one state: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `COMPLETE`, or `DEFERRED`. Unchecked tasks inherit their phase state unless explicitly annotated. Checked boxes mean complete and require evidence. Deferred work remains unchecked. Approval to plan is not approval to execute.

### Phase authorization register

| Stage | Authorization | Work state | Predecessor / gate |
|---|---|---|---|
| Documentation | Approved by owner in this session | COMPLETE (evidence in verification record) | Documentation alignment and validation done |
| Phase 0 | Owner-authorized (autonomous progression) | COMPLETE — `docs/Phase0_Audit.md` | Install + Alpaca feasibility verified |
| Phase 1 | Owner-authorized | COMPLETE — skeleton, configs, guards, Memory.md | Foundation present |
| Phase 2 | Owner-authorized | COMPLETE — Binance BTC/USDT 1d data + freshness limits | Data downloaded |
| Phase 3 | Owner-authorized | COMPLETE — `BtcZScore` strategy (candidate thresholds) | Strategy implemented |
| Phase 4 | Owner-authorized | COMPLETE + **unit-tested (2026-10-21)** — backtest + lookahead/recursive PASS | Signals deterministic, no leakage |
| Phase 5 | Owner-authorized | COMPLETE — protections in-strategy, **startup 70→400 for convergence** | Risk layer coded; **edge NOT proven** |
| Phase 6 | Wired, **NOT authorized to run** | IN PROGRESS — preflight+reconcile coded/tested; **paper lifecycle NOT exercised, trading gated** | Owner risk approval MISSING |
| Phase 7 | Owner-authorized | COMPLETE — SQLite ledger `unbound.db`, idempotent reconcile (tested) | Durable traceable records |
| Phase 8 | Not authorized; activation disabled | DEFERRED — HMM research-only, did not beat baselines | Explicit deferral recorded |
| Phase 9 | Owner-authorized | COMPLETE — Streamlit dashboard (status-aware observation tab) | Renders live |
| Phase 10 | Owner-authorized | COMPLETE + **false-OK fixed & tested (2026-10-21)** — observation harness READ-ONLY | **Accumulate weeks before judgments** |
| Future research | Outside initial build | DEFERRED | Separate request |

Record phase approval, scope, and evidence in this register and the closeout record; do not infer approval from a completed checkbox. **Code-complete ≠ acceptance-met:** Phase 4/5 results show no proven edge over buy-and-hold, and Phase 6 paper/executor lifecycle has NOT been exercised — see `docs/Audit_Remediation_2026-10-21.md`.

## Documentation alignment

Use these IDs to track the approved documentation-only change. Evidence will be consolidated in the documentation verification record below.

- [x] DOC-01 Correct project paths to `D:\BOT`; do not move/extract existing folders.
- [x] DOC-02 Align PRD with paper-only BTC/USD and separate operational/research milestones.
- [x] DOC-03 Emphasize Freqtrade extension points; make the large package sketch optional.
- [x] DOC-04 Expand this file into stable task IDs, dependencies, gates, evidence, and approval records.
- [x] DOC-05 Make Phase 0 inspection-only; distinguish local simulation from broker paper execution.
- [x] DOC-06 Correct no-borrowing semantics without forcing the framework's spot multiplier to zero.
- [x] DOC-07 Display borrowing disabled and actual exposure in the dashboard specification.
- [x] DOC-08 Align starter prompts with current authorization, corrected root, and checklist workflow.
- [x] DOC-09 Reconcile stale context: repository present, broker/pair/timeframe selected, audit pending.
- [x] DOC-10 Preserve source claims and identify unavailable source code, videos, exports, and datasets.
- [x] DOC-11 Keep LSTM optional and record lag, reproducibility, and date/accounting concerns without adopting its returns/fees.
- [x] DOC-12 Keep `docs/Memory.md` absent until Phase 1 coding begins.
- [x] DOC-13 Validate document links, task IDs, phase ordering, safety semantics, and scope; report actual checks.

**Gate:** Documentation reflects confirmed scope without claiming audit/test/implementation completion. Phase 0 remains unauthorized.

### Documentation verification record

Actual checks performed during this documentation-only step (no application, install, broker, or bot test):

- Path correction: `docs/` search for `D:\UnboundBot` returned 0 matches across all seven documents.
- Safety semantics: search for `0.00x`, `leverage (always`, and `NO REAL ORDERS` returned 0 matches; corrected wording uses `Borrowing: disabled`, actual exposure, and valid `1.0` spot multiplier.
- `docs/Memory.md` confirmed absent (Glob returned no file).
- Internal links to PRD/Architecture/Rules/Phases/Design/Prompt/CRYPTO_BOT_PROJECT_CONTEXT resolve to existing files; `../freqtrade-stable/README.md` resolves to the present framework README.
- Seven documents updated: PRD, Architecture, Rules, Phases (master checklist), Design, Prompt, CRYPTO_BOT_PROJECT_CONTEXT.
- Not performed / not claimed: repository Git provenance audit, dependency install, framework or application tests, backtests, Alpaca connection, browser application check. These belong to later authorized phases.
- Publication: documentation commit/push to the owner's remote and rendered-markdown browser verification are handled as the separate requested handoff, tracked below.

## Phase 0 — Read-only repository audit and Alpaca decision

**Goal:** Recommend the smallest maintainable path without replacing or running the framework. Source inspection identifies a candidate, not a demonstrated broker lifecycle.

### Repository provenance and environment

- [ ] P0-01 Determine Git checkout/archive/nested repository status; do not invent missing branch/SHA metadata.
- [ ] P0-02 Record status, branch, commit, remotes, tags, and modifications where available; redact credentials in remote URLs.
- [ ] P0-03 Record framework version/dependencies and compare requirements with installed runtimes/container tooling without installing anything.
- [ ] P0-04 Inspect strategies, configs, data, tests, APIs/UI, and customizations without exposing secrets.
- [ ] P0-05 Record test commands/prerequisites; run only isolated existing checks needing no installation, credentials, or worker. Otherwise report not run.
- [ ] P0-06 Preserve attribution/licenses and define source/update tracking. Do not commit without a request.

### Freqtrade reuse map

- [ ] P0-07 Trace strategy loading, completed-candle processing, callbacks, and entry/exit handling.
- [ ] P0-08 Trace exchange resolution, CCXT assumptions, history, metadata, precision, rate limits, and timeframes.
- [ ] P0-09 Trace submission, timeout/retry paths, partial fills, cancellation, fees, and startup reconciliation.
- [ ] P0-10 Trace wallets, trade/order persistence, custom metadata, and migrations.
- [ ] P0-11 Inspect backtesting, lookahead/recursive analysis, plotting, optimization, and benchmarks.
- [ ] P0-12 Inspect protections, exits, API/FreqUI/Telegram, and manual controls for possible risk bypasses.
- [ ] P0-13 Identify all CoinGecko initialization paths and configuration-only disablement where sufficient; distinguish unused dependencies from runtime use.
- [ ] P0-14 Produce the parity matrix: capability, local evidence, fork evidence, reuse/adapt/defer/unavailable, missing tests, maintenance risk.

### Alpaca comparison

- [ ] P0-15 Inspect current official Freqtrade/Alpaca crypto and paper docs; record URLs, dates, and constraints.
- [ ] P0-16 Inspect `https://github.com/aidinstinct/freqtrade-alpaca` remotely; request approval if a separate local comparison copy is necessary.
- [ ] P0-17 Record fork SHA, provable ancestry, age, dependencies, license, warnings, tests, and activity.
- [ ] P0-18 Compare BTC/USD, daily bars, balances, positions, market orders, time-in-force, client-ID lookup, fills, fees, and cancellations.
- [ ] P0-19 Check response normalization against this framework version's interfaces; never transplant by filename alone.
- [ ] P0-20 Document configuration mappings and isolated records for backtests, local dry-run, and Alpaca paper orders.
- [ ] P0-21 Define paper-routing proof: exact endpoints, SDK settings, paper-only authentication, and negative tests; key strings alone do not prove environment.
- [ ] P0-22 Record unproven asset availability, historical coverage, costs, lifecycle behavior, and simulated fills.

### Decision and handoff

- [ ] P0-23 Evaluate Route A: pinned Alpaca fork with original checkout preserved.
- [ ] P0-24 Evaluate Route B: minimal adapter/extensions with explicit framework divergence and maintenance cost.
- [ ] P0-25 Evaluate Route C only as an approved fallback: Freqtrade research plus one executor, shared semantics, and documented lost parity.
- [ ] P0-26 Recommend the credible route with least unsupported divergence; do not silently adopt Route C or call an untested fork working.
- [ ] P0-27 Write `docs/Phase0_Audit.md` with provenance, matrix, sources, risks, candidate route, remaining proof steps, and proposed setup.
- [ ] P0-28 Obtain route/Phase 1 approval; if no route is credible, report a blocker and bounded next experiment.

**Gate:** Audit report and candidate route approved; original checkout preserved; no coding, orders, or Memory.md. Full paper compatibility remains unverified until execution tests pass.

## Phase 1 — Minimal implementation foundation

- [ ] P1-01 Explain/install only required compatible dependencies in an isolated workspace environment after approval.
- [ ] P1-02 Create only extension structure required by the selected route; do not instantiate the whole architecture sketch.
- [ ] P1-03 Create `docs/Memory.md` now with real audit findings, route, phase, changed paths, commands/results, blockers, and next action.
- [ ] P1-04 Add typed paper-routing, BTC/USD/spot, provider, strategy-version settings; keep approval-required parameters unset.
- [ ] P1-05 Keep submission disabled until prerequisite gates pass; distinguish monitoring startup from trading readiness.
- [ ] P1-06 Validate exact paper host/SDK settings; test unsafe overrides; isolate keys from dashboard/AI.
- [ ] P1-07 Disable CoinGecko conversion and prove representative startup/reporting paths make no CoinGecko calls.
- [ ] P1-08 Reuse logging/API infrastructure; add redaction, health states, and correlation IDs.
- [ ] P1-09 Establish schema/migration ownership for provenance/custom state without duplicate authoritative trades/orders.
- [ ] P1-10 Test selected broker adapter contracts with mocks before broad work; stop if critical contracts cannot be met.
- [ ] P1-11 Establish reproducible test/lint commands and safe examples without secrets/live fields.

**Gate:** Credential-free tests pass; unsafe configs fail; no-CoinGecko paths and adapter contracts are tested; Memory.md accurately records coding commencement.

## Phase 2 — Verified data and time semantics

- [ ] P2-01 Implement selected Alpaca data access and validate BTC/USD identity without orders.
- [ ] P2-02 Measure earliest/latest history, pagination, feed identity, retrieval time, missing bars, and quality.
- [ ] P2-03 If coverage is insufficient, seek approval for a named non-CoinGecko archive; never silently substitute BTC/USDT.
- [ ] P2-04 Preserve raw and normalized datasets with provenance/hashes and identifiable source revisions.
- [ ] P2-05 Specify UTC candle boundaries/timestamp meaning and compare with original source before claiming reproduction.
- [ ] P2-06 Separate incomplete/current from completed candles; no signals from unfinished bars.
- [ ] P2-07 Validate finite prices, OHLC, volume, ordering, gaps, duplicates; do not silently interpolate candles.
- [ ] P2-08 Define separate freshness limits for daily history, executable quotes, accounts, and reconciliation.
- [ ] P2-09 Test clock skew, rollover, delayed/missing bars, pagination, and reload reproducibility.
- [ ] P2-10 Document actual coverage/limitations; do not assume a May 2014 start.

**Gate:** Data provenance and closed-bar/freshness semantics are tested; invalid/missing data prevents actionable signals.

## Phase 3 — Exact Z-score baseline and decision records

- [ ] P3-01 Follow the provided source lead and authorized original materials for thresholds/settings/exports; do not bypass protected code.
- [ ] P3-02 If unavailable, obtain approval for a new candidate specification labeled adaptation, not reproduction.
- [ ] P3-03 Resolve thresholds, ordering, equality, neutral behavior, and initial state; leave unresolved values unset.
- [ ] P3-04 Resolve EMA initialization, standard deviation convention, missing data, zero denominator, and warm-up convergence.
- [ ] P3-05 Implement `Z = (close - EMA65) / STDDEV65` with existing numerical tools and pure tests.
- [ ] P3-06 Implement deterministic long/cash transitions on completed daily candles with explanations.
- [ ] P3-07 Define neutral behavior after restart/risk exits/manual changes; no reentry from stale prior intent.
- [ ] P3-08 Audit inherited ROI, stoploss, trailing, position adjustment, and force-entry defaults against the approved strategy.
- [ ] P3-09 Persist as-of inputs, candle identity, indicators, versions, state transition, and reason before execution exists.
- [ ] P3-10 Test thresholds, invalid/zero variance, warm-up, repeat candles, replay, and future-data perturbation.
- [ ] P3-11 Define causal signal/fill timing; no assumed execution at an already-observed candle close.

**Gate:** Source or adapted semantics approved; deterministic tests pass; missing parameters block entries; decision records are durable.

## Phase 4 — Reproducible research and honest performance

- [ ] P4-01 Reuse Freqtrade backtesting/reporting; document missing adapters rather than build a second general backtester.
- [ ] P4-02 Save hashes, code/config, periods, capital, compounding, fills, exposure, and run IDs.
- [ ] P4-03 Define fees/spread/slippage/rounding and separate reported versus modeled costs; unknown costs are not zero.
- [ ] P4-04 Validate fee currency/base-asset deductions; avoid double counting and overstating spendable holdings.
- [ ] P4-05 Predeclare chronological research windows and untouched holdout; handle overlapping labels/trades when relevant.
- [ ] P4-06 Benchmark cash, BTC buy-and-hold, and a documented simple trend baseline with matching periods/costs.
- [ ] P4-07 Report return, CAGR, drawdown/recovery, trades, exposure, costs, and defined risk/trade metrics where meaningful.
- [ ] P4-08 Check equity/drawdown independently with hand-checkable accounting fixtures.
- [ ] P4-09 Run applicable lookahead/recursive analysis and timestamp/feature leakage tests; document limitations.
- [ ] P4-10 Stress costs, delayed/missed execution, source differences, and dependence on exceptional trades including the claimed +373% outlier.
- [ ] P4-11 Treat 65.92% CAGR, 26.79% drawdown, 53 trades, and other source figures as claims; investigate consistency rather than tune to match.
- [ ] P4-12 Produce reproducible results distinguishing reproduction, adaptation, and unresolved discrepancies.

**Gate:** Accounting/leakage checks pass and results are reproducible. Unprofitable results are valid findings; candidate changes or experimental paper progression require a recorded decision.

## Phase 5 — Independent risk, allocation, and ownership

- [ ] P5-01 Approve paper capital, exposure/order caps, loss/drawdown limits, reserves, freshness tolerances, and emergency actions.
- [ ] P5-02 Size against eligible cash/holdings, not margin buying power; validate decimals and increments.
- [ ] P5-03 Reject borrowing, shorts, unsupported assets, and unsafe settings while preserving valid spot accounting.
- [ ] P5-04 Persist equity, UTC daily baselines, peaks, and cash-flow/reset events; distinguish strategy/account metrics.
- [ ] P5-05 Monitor risk from fresh accounts/prices independently of daily signal cadence.
- [ ] P5-06 Implement exposure, duplicate-intent, stale-data, ambiguous-account, API-failure, and storage gates.
- [ ] P5-07 Separate entry blocks from validated risk-reducing actions; never blindly liquidate unknown positions.
- [ ] P5-08 Persist critical stops; require manual reset after reconciliation, never AI reset.
- [ ] P5-09 Enforce one executor with tested process/account ownership; detect external/manual activity.
- [ ] P5-10 Cover framework exits, retries, recovery, and retained RPC controls with the same safety boundary.
- [ ] P5-11 Test arithmetic boundaries, exceptions, stale inputs, kill-switch restart, and competing workers.
- [ ] P5-12 Re-backtest integrated sizing/stops/risk policies separately from the original-strategy reproduction.

**Gate:** Approved policies are versioned and negative tests pass; new entries fail closed; risk-reducing actions remain bounded; integrated risk changes are evaluated.

## Phase 6 — Alpaca paper execution and reconciliation

- [x] P6-01 Configure paper credentials locally; verify official paper routing/account/asset capability without exposing secrets. **EVIDENCE:** `app/scripts/check_alpaca.py` AUTH OK (paper account, crypto ACTIVE, BTC/USD tradable); keys only in git-ignored `.env`.
- [x] P6-02 Preflight mode, asset, freshness, versions, reconciliation, and executor ownership. **EVIDENCE (harness-level, tested):** `app/scripts/preflight.py` gates endpoint/dry-run/spot/leverage/sizing/protections + owner-approval; `reconcile.py` verifies process liveness (PID+heartbeat), candle freshness, broker reachability, DB, portfolio, identity. Not yet exercised against a live paper lifecycle (trading gated).
- [ ] P6-03 Use validated market orders/time-in-force; defer limit orders until separately tested.
- [ ] P6-04 Persist intent/client identity before submission; never blindly retry an ambiguous write.
- [ ] P6-05 Track accepted/new/partial/filled/canceled/rejected/expired/unknown states and duplicate/out-of-order events.
- [x] P6-06 Query by identity and reconcile after ambiguity before any safe resubmission decision. **EVIDENCE (tested):** `reconcile_order_identity()` set-differences broker vs Freqtrade order IDs; `test_reconcile.py`/`test_execution_safety.py` prove count-equal-but-ID-different still flags and unresolved orders are never silently accepted.
- [ ] P6-07 Record fills, fees, quantities, cash changes, and outcomes authoritatively; acceptance is not fill. **PARTIAL:** monetary fee model + submit≠fill (ft_unresolved→REVIEW) coded/tested; actual live fills not recorded (no orders placed).
- [x] P6-08 Use bounded read retries and periodic authoritative reconciliation, not streams alone. **EVIDENCE:** read-only GETs + `reconcile.py --watch` cadence; no streaming dependency.
- [ ] P6-09 Test restart before submit, after submit before response persistence, during partial fills, and after fills.
- [x] P6-10 Complete credential-free mocked/fault-injection tests before account-mutating tests. **EVIDENCE:** 55 mocked pytest tests (tmp DBs, monkeypatched broker/heartbeat) pass; no account-mutating tests exist yet.
- [ ] P6-11 Approve a bounded test budget/account; run a finite paper lifecycle and reconcile residual orders/positions.
- [ ] P6-12 Prove local simulated orders/balances are not shown as Alpaca paper records.
- [x] P6-13 Record actual compatibility evidence and update the audit matrix; unsupported behavior stays visible. **EVIDENCE:** `docs/Audit_Remediation_2026-10-21.md` records the Alpaca-backtest market-load failure and that Alpaca is not Freqtrade-native.

**Gate:** Bounded paper lifecycles reconcile; crash/retry tests prevent duplicates; no live endpoint is reachable through the approved workflow. Prove deduplication/reconciliation, not exactly-once network delivery.

## Phase 7 — Persistent trade reviews and controlled AI research

- [ ] P7-01 Extend existing ledger with review/hypothesis/experiment/approval records; keep execution records authoritative.
- [ ] P7-02 Review closed trades and cohorts, not unfinished outcomes; insufficient samples can mean no conclusion.
- [ ] P7-03 Generate deterministic facts before AI explanations.
- [ ] P7-04 Separate facts, interpretations, hypotheses, validation, and approved rules in schema/UI.
- [ ] P7-05 Require evidence IDs, sample size, counterexamples, limitations, tests/status, and versions.
- [ ] P7-06 Retrieve relevant sanitized records; preserve rejected/contradictory evidence.
- [ ] P7-07 Approve LLM provider, data sharing, and spending before connection; begin with schemas/fixtures.
- [ ] P7-08 Isolate reviewer from keys, orders, active config, and executable patch application; treat retrieved text as untrusted.
- [ ] P7-09 Validate research schemas; isolate/review/test any experiment code before it runs.
- [ ] P7-10 Pre-register experiment objectives/criteria, preserve holdout integrity, and record all attempted variants.
- [ ] P7-11 Promote only after tests/backtests/out-of-sample evidence, owner approval, versioned release, and rollback target.
- [ ] P7-12 Test idempotent scheduling, invalid evidence, restart, prompt injection, and reviewer failure without disabling risk.

**Gate:** Notes are durable and evidence-linked; AI cannot trade or change approved behavior. Learning means measured evidence/improvement, not note volume.

## Phase 8 — Optional HMM regime experiment

**Activation:** Disabled. Record an explicit deferral decision to proceed to the baseline dashboard without implementing HMM; do not check deferred tasks as complete.

- [ ] P8-01 Recover video originals if available; distinguish inspiration from the tested model.
- [ ] P8-02 Predeclare features, windows, state-count candidates, seeds, retraining cadence, and objectives.
- [ ] P8-03 Begin with daily observations; justify/test any multi-timeframe design separately.
- [ ] P8-04 Fit transforms/HMM on training only and save artifacts/provenance.
- [ ] P8-05 Use causal inference and future-append invariance tests; full-sequence smoothing cannot drive historical decisions.
- [ ] P8-06 Map IDs from training statistics, version labels, and do not force five meaningful states.
- [ ] P8-07 Define probability, persistence, volatility rank, and uncertainty; posterior probability is not win probability.
- [ ] P8-08 Test retraining label alignment, degeneracy, instability, insufficient history, and model age.
- [ ] P8-09 Compare baseline, HMM filter, and HMM allocation separately on identical data/costs.
- [ ] P8-10 Keep risk authoritative; approve regime-to-exposure policy before activation.
- [ ] P8-11 Record adoption, rejection, or deferral based on out-of-sample performance, drawdown, turnover, stability, and complexity.

**Gate:** Inference is causal/reproducible; activation needs evidence and approval. Rejection/deferral does not invalidate a working baseline.

## Phase 9 — Regime Trader dashboard and hardening

**Default:** Local read-only Streamlit view backed by compatible Freqtrade services/APIs. Retain useful FreqUI features behind tested controls. A framework change needs an explicit decision.

- [ ] P9-01 Apply Design.md theme tokens, sidebar, typography, state colors, and responsive layout.
- [ ] P9-02 Show persistent Alpaca `PAPER — simulated account`, fixed BTC/USD, and no live toggle.
- [ ] P9-03 Show actual equity, eligible cash, BTC holdings, price, and status with separate source timestamps.
- [ ] P9-04 Show daily chart, EMA65, Z-score, approved thresholds, signals/fills; use `Strategy State` before HMM exists.
- [ ] P9-05 Show regime history/table/transitions/version/probabilities only from recorded model outputs.
- [ ] P9-06 Show exposure, borrowing disabled, defined drawdowns/limits, circuit status, and last risk evaluation.
- [ ] P9-07 Show reconciled positions/orders/partial fills/fees/P&L, decisions, and rejection reasons.
- [ ] P9-08 Separate paper analytics, historical backtests, and modeled costs; explain discrepancies without rewriting broker facts.
- [ ] P9-09 Show research notes with evidence, validation/approval, and `Research only — not active` labels.
- [ ] P9-10 Show redacted diagnostics/logs; unknown risk is never “all clear.”
- [ ] P9-11 Show unavailable/stale/disconnected reasons and last-known timestamps; refresh cannot make old data fresh.
- [ ] P9-12 Bind locally by default; authenticate exposed APIs and keep secrets out of browser payloads.
- [ ] P9-13 Verify browser rendering/interactions, keyboard access, contrast, narrow layouts, empty/stale states, and reconciled values.
- [ ] P9-14 Test disk/DB/API failure, rollover, locks, restart/shutdown/recovery; alerts remain independent of dashboard availability.
- [ ] P9-15 Verify backup/restore and actual Windows install/run/test/backtest/recovery commands.

**Gate:** Values reconcile, failure states are visible, UI is read-only, and clean-start/recovery procedures are reproduced. Screenshots are inspiration, never account data.

## Phase 10 — Extended paper evaluation

> **Observation harness is built** (2026-10-21): `app/scripts/reconcile.py` mirrors the Freqtrade
> paper DB + Alpaca PAPER account/positions/orders into separate ledger tables (`paper_trades`,
> `reconcile_log`, `account_equity`, `reports`) and flags drift/external activity; `app/scripts/weekly_report.py`
> generates `docs/Phase10_Observation.md`. Read-only, idempotent, never trades. Run on a cadence
> (`--watch`) or scheduled task. The remaining items below are **time-based** — they require the bot
> to actually accumulate observation over weeks before acceptance judgments can be made.
>
> **False-OK corrected (2026-10-21 audit):** reconcile no longer infers health from "no drift." It
> uses a precedence-ordered liveness/status model `CRITICAL > OFFLINE > BROKER_UNREACHABLE > STALE >
> REVIEW > HEALTHY`, verifying process liveness (PID + heartbeat age), candle freshness, broker
> reachability, DB readability, portfolio qty match, and order identity. HEALTHY is unreachable while
> offline/stale/drifted/corrupt — and the first re-run correctly returned **CRITICAL** (broker holds
> 0.06024 BTC the Freqtrade DB does not know about). Covered by `app/tests/test_reconcile.py` (25 tests).

- [ ] P10-01 Approve dedicated account/isolation and observation budget; no competing executor.
- [ ] P10-02 Pin strategy/risk/data/model versions for each evaluation interval.
- [ ] P10-03 Observe an approved interval; a month is an operational starting point, not proof of daily-strategy edge.
- [x] P10-04 Report weekly signals/skips/orders/fills/costs/discrepancies/outages/risk/exposure/drawdown. (generator: `app/scripts/weekly_report.py` → `docs/Phase10_Observation.md`)
- [ ] P10-05 Compare paper behavior with backtest/cost assumptions and explicit simulator limitations.
- [ ] P10-06 Exercise bounded recovery drills without artificial trading to inflate sample size.
- [ ] P10-07 Review AI evidence quality and false conclusions, especially with few closed trades.
- [ ] P10-08 Evaluate operational/research acceptance separately; preserve negative results and gaps.
- [ ] P10-09 Close with owner-reviewed paper report and next priorities; no automatic live promotion.

**Gate:** Review operational behavior and evidence against predeclared criteria. Paper success is not live readiness or a return guarantee.

## Later research backlog — outside the initial build

- [ ] FUT-01 Consider LSTM only with separate approval, reproducible data, training-only transforms, aligned forecasts, and naive baselines. **DEFERRED.**
- [ ] FUT-02 Require incremental out-of-sample economic value after costs, not visual forecast fit or training error. **DEFERRED.**
- [ ] FUT-03 Keep RL, news/sentiment, extra assets, complex portfolio sizing, cloud deployment, and live execution outside scope. **DEFERRED.**
- [ ] FUT-04 Any live-readiness review needs a new request and separate design; no live switch in this build. **DEFERRED.**

## Decision register and blockers

| Decision | Current state | Unblock condition |
|---|---|---|
| ROOT | Confirmed `D:\BOT` | Documentation alignment |
| SCOPE | BTC/USD spot, Alpaca paper, no CoinGecko | Preserve at every gate |
| PROVENANCE | Framework branch/SHA/runtime unverified | Phase 0 evidence |
| ROUTE | Unselected | Phase 0 recommendation and owner approval |
| STRATEGY | Missing thresholds/incomplete semantics | Source or approved adaptation before actionable trading |
| RETURNS | Unverified claims | Independent reproducible evaluation |
| HISTORY | Long-history coverage/source unverified | Measure coverage; approve any alternate archive |
| RISK | Numeric limits/actions unapproved | Resolve before Phase 5 gate and orders |
| VIDEOS | Summaries/screenshots, originals unavailable | Obtain originals if fidelity requires them |
| AI | Provider/sharing/cost unselected | Approval before external connection |
| HMM | Disabled, optional | Experiment/promotion or explicit deferral decision |
| LSTM | Deferred | Separate research approval |
| MEMORY | Not created | Phase 1 coding after audit approval |

## Final acceptance

- [ ] ACCEPT-01 One tested paper executor; no live trading, borrowing, shorts, or CoinGecko calls in the approved workflow. **OPEN:** single Freqtrade executor + preflight enforces spot/no-short/no-lever/no-CoinGecko (tested), but the paper executor lifecycle has NOT been exercised (trading gated), so "tested paper executor" is not yet met.
- [ ] ACCEPT-02 Strategy/risk rules are sourced/approved and cannot be changed by runtime AI. **BLOCKED:** thresholds are labeled CANDIDATE, not owner-approved; `app/configs/risk_approval.json` absent. AI never mutates rules (design), but approval is missing.
- [ ] ACCEPT-03 Data, decisions, requests, fills, fees, and outcomes survive restart and remain traceable. **PARTIAL:** durable ledger + idempotent reconcile tested (replay-safe), but no real paper fills/requests recorded yet (no orders placed).
- [x] ACCEPT-04 Backtests preserve provenance, assumptions, costs, benchmarks, leakage checks, and out-of-sample evidence. **EVIDENCE:** `docs/Audit_Remediation_2026-10-21.md` — binance research proxy noted (not execution parity), buy-and-hold benchmark, fee cost model, lookahead+recursive PASS, startup-400 convergence.
- [ ] ACCEPT-05 Dashboard values, timestamps, failures, and circuit states match authoritative sources. **PARTIAL:** observation tab is now status-aware (HEALTHY/STALE/OFFLINE/…) with heartbeat age; live CRITICAL broker-drift surfaces correctly, but a full dashboard-vs-broker verification pass is pending.
- [x] ACCEPT-06 Required tests pass; unavailable/skipped checks and unresolved limitations are stated honestly. **EVIDENCE:** `python -m pytest` → 55 passed; limitations (Alpaca-backtest market-load failure, no proven edge, HMM deferred) stated.
- [x] ACCEPT-07 Checklist, source context, phase reports, and Memory.md once created agree on actual progress. **EVIDENCE:** Phases.md register + Memory.md reconciled to code/test reality on 2026-10-21 (false-OK model corrected, strategy path fixed, backtest numbers updated).
- [ ] ACCEPT-08 Each phase ends with a precise next action and explicit approval boundary. **PARTIAL:** remediation defines the next action (owner decision on paper restart + risk approval); full per-phase closeout records still use the template.

## Phase closeout record template

Use this record for each completed/blocked phase, linked to task IDs. This template does not claim any phase is complete.

- Phase, authorization, and predecessor gates:
- Task IDs completed/blocked/deferred and evidence references:
- Changed files and behavior:
- Commands actually executed, exit status, and reports:
- Tests passed/failed/skipped/not run and reasons:
- Decisions, approver, unresolved inputs, and unblock conditions:
- Acceptance gate: passed/blocked, with evidence:
- Memory.md update: applicable only after Phase 1 coding begins:
- Next bounded task and required approval:

**Next phase action after documentation closeout:** Wait for explicit authorization to perform Phase 0 inspection and report. Do not start implementation or broker activity.
