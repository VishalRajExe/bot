# UnboundBot — Architecture

**Version:** 0.2 · **Status:** Approved documentation direction; execution route unselected and Phase 0 not started.

> **Implementation addendum (2026-10-22).** This document still describes the
> *proposed contracts* (and remains accurate on those). The current **built**
> state of the system — three disjoint order executors (daily / fast / swing),
> a shared causal `families.py` library, an evidence-scaled sizing hook, an
> auto-demoting strategy gate, and a 24/7 supervisor — is documented in
> [`Audit_2026-10-22.md`](Audit_2026-10-22.md) and the top-level
> [`README.md`](../README.md). Where the two differ, the audit + README reflect
> what actually runs; this file describes the design intent it was built from.

[Phases.md](Phases.md) owns task status, evidence, and phase approvals. This document defines proposed contracts; it does not certify a working integration.

## 1. Architectural principles

1. **Reuse before rewrite.** Preserve compatible Freqtrade capabilities and use strategy/plugin/adapter seams before modifying framework internals.
2. **One execution authority.** Exactly one component submits Alpaca paper orders. Enforce ownership and detect competing workers or unexpected account activity.
3. **Deterministic trading path.** Strategy intent → allocation → independent risk → durable intent → executor. The LLM cannot participate in order authorization.
4. **Paper broker routing only.** No live broker endpoint, live credentials, borrowing, shorts, margin, or transfers. Offline research is separate from broker execution.
5. **Reproducibility.** Version data, configuration, code, model artifacts, decisions, experiments, and approvals.
6. **One authoritative owner per record.** Broker state is reconciled into the execution ledger; research records reference it rather than creating a conflicting trade history.
7. **Explicit data semantics.** Never silently splice sources, fabricate missing candles, use future information, or present unknown values as zero.
8. **Small application first.** Testable modules are not a requirement for microservices, multiple databases, or a large new package tree.

## 2. Starting layout and scope

The owner confirmed:

```text
D:\BOT\
├── docs\
└── freqtrade-stable\
```

Only documentation alignment and its requested commit/push are currently authorized. Phase 0 requires a separate go-ahead. Do not move or replace the checkout, install dependencies, run an execution worker, connect to a broker, or create `docs/Memory.md` during this step.

Do not infer that the framework directory is a clean Git checkout or a tested installation. Phase 0 records actual provenance, local modifications, dependency/runtime compatibility, and available test evidence. Repository setup used to publish documentation is not proof of the framework's upstream ancestry.

### Limited source observations already available

- `freqtrade-stable/pyproject.toml` declares Python `>=3.11`, GPLv3, CCXT, SQLAlchemy, numerical libraries, FastAPI, and optional research/testing dependencies.
- `freqtrade/exchange/exchange.py` returns locally simulated orders when `dry_run` is enabled; normal submission goes through the exchange API.
- `freqtrade/persistence/trade_model.py` uses an unleveraged spot multiplier of `1.0`. Do not force it to zero to express no borrowing.
- `freqtrade/rpc/rpc.py` conditionally initializes fiat conversion from `fiat_display_currency`; `fiat_convert.py` uses CoinGecko. The application must disable and test these paths.

These are planning observations, not a completed audit or broker compatibility result.

## 3. Freqtrade–Alpaca compatibility decision

The local README does not list Alpaca. Earlier project notes mention an upstream issue and a candidate Alpaca fork with a limit-order testing warning. Phase 0 must verify their current status and source; no adoption decision has been made.

References to inspect during the authorized audit:

- https://www.freqtrade.io/en/stable/exchanges/
- https://github.com/freqtrade/freqtrade/issues/10862
- https://github.com/aidinstinct/freqtrade-alpaca
- https://docs.alpaca.markets/us/docs/crypto-trading
- https://docs.alpaca.markets/us/docs/paper-trading

### Routes to compare

**Route A — Pinned Alpaca-enabled fork.** Compare ancestry, framework age, dependencies, adapter contracts, tests, lifecycle behavior, and maintenance cost. Preserve the existing checkout; do not copy files blindly. A separate local comparison copy needs approval during the read-only audit.

**Route B — Minimal integration on the current framework.** Use existing extension points. Identify unavoidable exchange/CCXT changes and ongoing maintenance explicitly; prove mocked contracts before broad implementation.

**Route C — Separate research and execution duties.** Consider only as an explicitly approved fallback. Freqtrade can own research while one Alpaca worker owns all orders; shared strategy semantics and parity limitations must be documented. Never run two active trading loops against the same account.

Select the credible route with the least unsupported core divergence. A route recommendation is provisional: Phase 1 contract tests and Phase 6 bounded paper lifecycle tests establish actual behavior. If no route is credible, stop with a bounded next experiment, not a claim of support.

### Required parity matrix

For strategy lifecycle, historical data, backtesting, local dry-run, wallets, orders/fills, persistence, stop/exit handling, protections, CLI, API/FreqUI, notifications, plotting, and optimization, record:

`Capability | local evidence | fork evidence | reuse/adapt/defer/unavailable | missing tests | maintenance risk`.

Write the audit findings to `docs/Phase0_Audit.md` only during authorized Phase 0. No coding/order spike belongs in the read-only audit.

## 4. Execution environments and paper safety

| Workflow | Order authority | Data/account presentation |
|---|---|---|
| Historical backtest | No broker submission | Historical simulation with explicit assumptions |
| Freqtrade-local dry-run | Framework's local simulator | Local synthetic balances/orders; never label as Alpaca account facts |
| Alpaca paper execution | Sole validated Alpaca integration | Reconciled broker-paper account, orders, and fills |
| Real-money trading | Not supported by this build | No live controls or fallback |

Keep databases, run identifiers, and UI labels separate. Do not equate the framework's `dry_run` flag or a `LIVE` transport enum with the broker's paper/live environment. The selected route must document and test its mapping. Do not toggle transport settings until paper endpoint enforcement is proven.

Paper safety uses exact endpoint/SDK configuration validation, separate paper credentials, successful authentication against the paper endpoint, and negative tests against overrides. Key strings alone do not prove account environment. Never try a live endpoint if paper authentication fails.

Examples of proposed environment fields, subject to the selected adapter contract:

```dotenv
TRADING_MODE=paper
ALPACA_PAPER_API_KEY=
ALPACA_PAPER_API_SECRET=
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
```

Do not create this configuration during documentation work. Keep actual secrets out of Git, markdown, logs, browser payloads, and AI prompts. No live fields are needed.

## 5. Data and decision flow

```text
Alpaca crypto data / explicitly approved historical archive
    → canonical candles + provenance + quality checks
    → completed daily candle
    → EMA65 / STDDEV65 / approved Z-score state machine
    → optional approved causal HMM context
    → versioned decision snapshot
    → allocation from eligible cash and confirmed holdings
    → independent risk authorization
    → durable intent + stable client identity
    → sole Alpaca paper executor
    → order/fill/account reconciliation
    → authoritative ledger
        → read-only dashboard
        → sanitized research evidence → notes → isolated experiments
            → out-of-sample evidence → human approval → versioned release
```

Account/quote monitoring and risk evaluation run independently of the daily signal cadence. UI refresh does not trigger signals, trades, or model fitting.

## 6. Module contracts and reuse boundaries

### Market data

- Prefer Alpaca's current documented crypto API or the selected validated adapter. No CoinGecko calls, including incidental fiat conversion.
- Canonical candles include UTC timestamp, boundary semantics, OHLCV, symbol, timeframe, provider/feed, retrieval time, source version, and completeness.
- Retain raw inputs and reproducible normalized artifacts; record pagination, gaps, duplicates, revisions, and coverage.
- Measure actual history; do not assume coverage begins in May 2014. Any alternative archive or source mixing needs approval and explicit provenance.
- Keep daily-bar freshness, executable-quote freshness, account freshness, and reconciliation freshness separate.

### Strategy and research

- Implement the exact source or explicitly approved adapted Z-score definition. Thresholds, standard deviation convention, EMA initialization, warm-up, equality cases, and neutral semantics remain approval/source gates.
- Strategy calculations are pure; they have no secrets or submission access.
- Persist candle identity, as-of inputs, score, version, state transition, intended action, and reason.
- Define behavior after risk exits, restarts, and manual position changes; neutral intent must not silently reopen a blocked position.
- Inspect framework ROI, stoploss, trailing, position adjustment, and manual-entry behavior so defaults do not silently change the candidate.
- Reuse Freqtrade's backtester and analysis tools where compatible. Add only missing data/cost glue and report its limitations.
- A completed-bar signal cannot assume a fill at an already-known close. Version the next eligible fill assumptions.

### Allocation and risk

- Use eligible USD cash and confirmed holdings, not margin buying power. Respect increments, fee reserves, approved order/exposure caps, and no-short rules.
- Preserve Freqtrade's valid `1.0` unleveraged multiplier. Display actual exposure and borrowing disabled; a cash-funded holding is not zero exposure.
- Approve numeric risk limits and emergency actions explicitly. Monitor equity/risk faster than the daily strategy when fresh account/price data is available.
- Persist UTC daily baselines, peaks, cash flows/account resets, and critical stop state. Distinguish account equity from strategy-attributed P&L.
- Unknown critical state blocks new entries. Risk-reducing orders require their own validated positions, quantities, and approved policy; do not blindly liquidate.
- Apply the risk boundary to every submission path, including exits, retries, recovery, and retained API/Telegram controls.
- Test single-executor ownership and unexpected account activity. Re-backtest after adding sizing/stops/risk policy.

### Execution and reconciliation

- Persist order intent and client identity before submission; store resulting broker IDs and subsequent events idempotently.
- Normalize accepted/new/partial/filled/canceled/rejected/expired/unknown states to framework contracts without assuming acceptance means fill.
- After ambiguous writes, query and reconcile before resubmitting. Use bounded retries for reads; generic write retries are unsafe.
- Reconcile duplicated/out-of-order stream events using authoritative broker reads.
- Account for actual versus modeled fees, fee currency, base-asset deductions, residual quantities, and partial exits.
- **Implemented seam — Alpaca base-asset fee deduction (`app/exchange_ext/alpaca_fees.py`).** Alpaca settles crypto
  fees by deducting the BASE asset and reports no fee on any fill read (`fetch_order` has no `commission`,
  `fetch_my_trades` has no `fee_paid`, ccxt returns a null fee), so the only authoritative signal is the broker
  wallet: credited base = filled − fee. The thin layer wraps the engine's fee-derivation call at runtime, computes
  `filled − (free + used)` of base from the wallet, and returns it so the engine reduces the trade to the net amount
  and a wallet-sized exit closes instead of jamming on dust. It is exchange/trade-mode gated (alpaca + spot),
  entry-side and closed-order gated, bounded to a plausible rate (0 < fee ≤ 2%), idempotent, and fail-closed — any
  other case or any exception returns the engine's original result and leaves the trade untouched. It edits no
  vendored engine file and mutates no database directly.
- Test process crashes before/after submission and persistence, partial fills, restart recovery, and stale account state.
- Use bounded paper tests only after strategy/risk prerequisites and a test budget/account are approved. No exactly-once network-delivery claims.

### Ledger and AI reviewer

- Phase 1 establishes schema ownership, Phase 3 records decisions, and Phase 6 records durable intent/orders/fills before any strategy paper order. Phase 7 adds reviews, not the first trade history.
- Retain authoritative framework trade/order records where accurate; add only missing provenance and research entities.
- Generate facts deterministically. Separate facts, interpretations, hypotheses, validation results, and approved rules.
- Notes require evidence IDs, cohort size, contradictory evidence, limitations, test proposal/status, versions, and approval state.
- The reviewer receives sanitized evidence only, with no broker keys, order tools, or active-configuration write access. Validate output schemas and treat retrieved text as untrusted.
- Approve external LLM provider, data-sharing policy, and budget before connection. LLM failure must not block core execution safety.
- Register experiments before testing; isolate any proposed code from the running bot. Retain negative results and protect the holdout.

### Optional HMM

- Align the initial experiment to daily data; any multi-timeframe design needs justification.
- Fit transformations/model on training windows only. Use causal filtering at decision time, not future-aware sequence smoothing.
- Test future-append invariance for historical predictions under a fixed model.
- Derive descriptive state labels from training statistics; do not force five useful states or treat posterior probability as trading accuracy.
- Version features, training windows, seeds, maps, artifacts, retraining cadence, and stability definitions.
- Compare baseline, regime filter, and regime allocation separately with identical data/costs. Approval is needed before activation. Deferral is valid.

### Dashboard and monitoring

- Default to a local, read-only Streamlit custom view backed by existing services/APIs where compatible; keep useful FreqUI capabilities behind tested controls.
- No strategy or broker access hidden in UI callbacks. Default local binding; authenticate exposed APIs.
- Each field has a named source, timestamp, freshness state, and definition. Missing values are unavailable, not fabricated zeroes.
- Show source-specific health, actual risk state, orders/fills/fees, model provenance, and research-only note status according to [Design.md](Design.md).
- Preserve independent operational alerts and recovery procedures; dashboard availability is not the safety mechanism.

## 7. Persistence, topology, and package layout

Prefer a small application with one execution worker and a separate read-only dashboard/reviewer only where useful. Database writers and migration ownership must be explicit. Avoid a second custom scheduler when Freqtrade already owns candle processing.

Reuse the Freqtrade database for authoritative trades/orders if the selected route can represent Alpaca accurately. Custom SQLite records may hold decision provenance, model registry, hypotheses, experiments, and approvals when existing extension fields are insufficient. Do not create a second financial source of truth.

Require stable IDs, UTC timestamps, migrations, transactional intent persistence, backup/restore, and replay/reconciliation tests. Ledger facts should not be rewritten to improve the appearance of past results; corrections must be traceable.

The previous broad `src/unboundbot/{data,strategy,risk,execution,...}` sketch is **optional**, not a scaffolding requirement. Actual strategy/plugin paths, custom modules, data directories, and environment boundaries are selected only after Phase 0. Do not create duplicate `user_data` trees or framework features to match a diagram.

Keep generated databases, credentials, datasets, and model artifacts out of source control as appropriate. Preserve upstream attribution and license notices when framework code is eventually published. A documentation-only push must not silently include the entire framework or local runtime data.

## 8. Dependency and delivery policy

- Use the runtime supported by the selected exact checkout; the declared minimum is not proof of the installed version.
- Install only needed, compatible dependencies into an isolated environment after the relevant phase is approved. Do not install AI/RL packages for the baseline.
- Pin the adopted framework/fork and reproducible dependencies; document upstream update strategy.
- Reuse numerical, persistence, API, test, and optimization tools already available before adding equivalents.
- Keep HMM and LSTM dependencies absent until their experiments are authorized and compatibility is checked.
- Record actual start/test/backtest/recovery commands after verification. A browser check of markdown is not an application runtime test.
- The owner requested commits and pushes to `https://github.com/VishalRajExe/bot.git`; stage only approved work, preserve remote history, and never force-push or include secrets. Report blocked authentication/history decisions instead of overwriting them.

---

## 9. Implementation addendum (2026-10-22)

Sections 1-8 remain the *proposed contracts*. The following records what was
actually built across the owner-approved multi-asset / multi-strategy /
self-learning expansion, and supersedes any "not started" reading of this
document.

### 9.1 Executor topology

Three **disjoint** order executors run as separate Freqtrade processes against
Alpaca PAPER. Disjointness is a hard invariant verified by
`app/risk/policy.validate_executors` at every preflight:

| Executor | TF | Strategy class                | Pairs                                            | Stake | max_open |
|----------|----|-------------------------------|--------------------------------------------------|-------|----------|
| daily    | 1d | PaperAutonomous → BtcZScore    | BTC/USD                                          | $15   | 1        |
| fast     | 5m | MomentumAlt → FamilyDispatcher | ETH, XRP, DOT, LINK, SOL, UNI (/USD)             | $10   | 2        |
| swing    | 1h | SwingAlt → FamilyDispatcher   | LTC, AVAX, DOGE (/USD)                            | $10   | 1        |

Each process only sees its own `tradesv3*.sqlite`. Global portfolio exposure is
maintained through a cross-executor `app/state/open_exposure.json` ledger written
by the read-only monitor and consulted by every `confirm_trade_entry` — the cap
stays **global**, not per-process, and fails-closed if the ledger is stale.

### 9.2 Signal library

The `families.py` module holds the pure, causal signal math for four families:
`momentum_ema_vol`, `rsi_divergence`, `bb_squeeze`, `link_trend`. The
`FamilyDispatcher` (5m + 1h) resolves each pair's family from
`app/configs/strategy_registry.json` and delegates indicator / entry / exit
computation to those functions. **The BTC baseline (`BtcZScore`) is untouched**
— `PaperAutonomous` subclasses it and only overrides the *alt* branch.

### 9.3 Risk policy layer

Single independent authority (`app/risk/policy.py`) + one veto implementation
(`PaperAutonomous.confirm_trade_entry`, inherited verbatim by every other
strategy class). Bounds applied per entry:

- Per-pair `max_stake_usd` from the registry.
- Evidence-scaled sizing: `m = clamp(1 + 0.5·avg_R, 1.0, 2.0)`, only after
  `n ≥ N_MIN = 20` closed trades; the scaled stake is additionally clamped to
  `cap × MAX_EVIDENCE_SCALE` (defence-in-depth against a corrupt `perf.json`).
- Per-position hard ceiling: `≤ 20% × current_paper_equity` (step 6b).
- Global portfolio exposure: `min($105 fixed, 40% × equity)`.
- One position per pair + duplicate-order defense.
- Fresh broker equity + fresh cross-executor ledger (both fail-closed).
- Persisted circuit-breaker kill switch (daily loss / peak-to-trough DD).
- Strategy-gate demotion: `is_tradeable(pair)` returns False while a pair
  appears in `app/state/strategy_gate.json`.

### 9.4 Learning layer

- `app/learn/perf.py` — pure metrics (`summarize`, `by_pair_family`,
  `should_demote`, `size_multiplier`). All values fail-closed at `n=0` (never
  a fabricated 0).
- `app/learn/journal.py` — durable `trade_journal` table; one row per closed
  `paper_trades` entry with pair / family / R-multiple / PnL.
- `app/scripts/learner.py` — read-only runner that writes `perf.json` and
  appends to `strategy_gate.json`. **Auto-demote is allowed; auto-promote is
  not** — a demotion can only be reversed by an owner edit.

### 9.5 Supervisor

`app/scripts/supervise.py` runs the monitor + learner + executor children as
detached process groups. Restarts them with a `5 → 10 → 30 → 60 s` backoff
ladder. **Never** relaunches an order executor while `policy.is_blocked()` is
True — it sends a throttled Telegram alert instead, so a crash-loop cannot
silently bypass the safety layer.

### 9.6 Backtest path

Freqtrade 2026.9 cannot backtest against Alpaca (private market-metadata load
fails offline). All backtests run against the public Binance **USDT** proxy
via `config.research.binance.json`; `ResearchFamily` binds `families.py` directly
(no registry / no veto) so offline runs are not blocked by the production
fail-closed layer. This is *signal-quality ranking*, **not** execution parity
— the ranking feeds the registry, never the order path.

### 9.7 Verification snapshot

- 184 tests pass under `pytest app/tests/`.
- `python app/scripts/preflight.py` → `TRADING READY: True` across all three
  executors; disjoint pair sets; global $105 structural cap, $40 runtime cap on
  $100 equity; summed `max_open_trades = 4 = max_concurrent_positions`.

The rest of this file remains as the original proposal. Read it alongside
[`Audit_2026-10-22.md`](Audit_2026-10-22.md) for the authoritative current state.
