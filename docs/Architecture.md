# UnboundBot — Architecture

**Version:** 0.2 · **Status:** Approved documentation direction; execution route unselected and Phase 0 not started.

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
