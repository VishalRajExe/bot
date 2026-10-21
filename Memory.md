# Memory.md — UnboundBot build memory

Created at Phase 1 (coding has begun). This is the **coding-agent** working memory.
It is distinct from the runtime **trade ledger** (Phase 7), which records trading
decisions/outcomes. Do not conflate the two.

## Environment facts (verified 2026-10-20)
- Freqtrade **2026.9** at `D:\BOT\freqtrade-stable` (extracted archive, no `.git`).
- Runtime venv: `D:\BOT\.venv` → Python **3.12.13** (uv-managed). 3.14 is default `py`
  but is too new for the pinned native deps — do not use it.
- `uv 0.11.21`. Docker NOT installed. ta-lib 0.8.2 via binary wheel (works).
- Run Freqtrade with: `D:\BOT\.venv\Scripts\freqtrade.exe --userdir D:\BOT\app\user_data -c <config>`.
- **Authoritative strategy path: `D:\BOT\app\user_data\strategies\BtcZScore.py`** — this is the
  file Freqtrade loads via `--userdir app/user_data` (no `--strategy-path`). The old duplicate at
  `app/strategies/BtcZScore.py` was removed 2026-10-21 (audit TASK 4); see `app/strategies/README.md`.

## Decisions
- **Route B**: target Alpaca directly via CCXT on the local checkout; no fork.
- **Feature completeness by inheritance, not duplication.** We do NOT copy Freqtrade source into
  `app/` (that would be a second, drifting engine). Our app is a thin layer (strategy, configs,
  scripts, dashboard, ledger) running ON the full Freqtrade 2026.9 engine installed into `.venv`
  (`uv pip install -e freqtrade-stable`). So the app already has all Freqtrade fundamentals —
  protections, backtesting, hyperopt, lookahead/recursive analysis, dry-run semantics, restart
  reconciliation, FreqAI/telegram available — PLUS our extras (observation ledger, liveness
  reconciliation, preflight gate, status-aware dashboard). Engine checkout is gitignored.
- Research/backtest data source: **Binance BTC/USDT** public daily candles (see
  `app/configs/config.research.binance.json`). Rationale (verified 2026-10-21): Freqtrade
  2026.9 cannot load **Alpaca** markets for `backtesting` — ccxt-alpaca's `load_markets()`
  calls the *private* `traderPrivateGetV2Assets` endpoint, and the backtest exchange bootstrap
  does not authenticate it (`AuthenticationError: alpaca requires "apiKey"` even with valid
  keys injected via env or inline config). Alpaca is not a Freqtrade-native exchange. Live/paper
  trade mode DOES authenticate, so this is a backtest-only limitation. Caveat: binance data is a
  research proxy, not the Alpaca feed → not execution parity.
- Strategy `BtcZScore`: long-only spot, daily Z=(close-EMA65)/STD65. Thresholds are
  **candidate defaults** (bull=0.5, exit=0.0), NOT source-verified.

## Blockers (open)
- Second "dual signal" component of the source strategy is unavailable (protected).

## Resolved blockers
- **Alpaca paper keys now authenticate** (AUTH OK: cash 100k, crypto ACTIVE). Keys live
  only in git-ignored `D:\BOT\.env`. They were pasted in chat — rotate them.
- **"Empty candle (OHLCV) for BTC/USD" in the live paper bot** — root cause: ccxt alpaca
  returns only 1 partial bar when Freqtrade's periodic refresh calls fetch_ohlcv with
  `since=None`. Fix: `exchange._ft_has_params.ohlcv_require_since=true` forces Freqtrade
  to compute a `since` and take the historic-fetch path → full daily history.

## Safety rails (always)
- Paper only. No live keys. No leverage/margin/shorts. Preserve `1.0` spot multiplier.
- Keep `fiat_display_currency` unset → no CoinGecko runtime calls.
- AI learning loop may propose/annotate but never auto-change approved rules or place orders.

## Log
- 2026-10-20 Phase 0 complete → docs/Phase0_Audit.md. Install verified. Alpaca creds 401.
- 2026-10-20 Phase 1: skeleton, configs, BtcZScore strategy, .env/.gitignore, Memory.md.
- 2026-10-20 Phase 2: downloaded Binance BTC/USDT 1d (3351 candles, 2017-08→2026-10).
  Kraken OHLCV history too short (freqtrade refuses; --dl-trades needed).
- 2026-10-20 Phase 3/4: backtest ran. Candidate thresholds (bull .5/exit 0):
  47 trades, +482.6%, CAGR 22.16%, maxDD 22.88%, win 38.3%. Buy-hold 512.4% →
  strategy did NOT clearly beat hold. Claimed 65.92%/26.79% NOT reproduced. Unverified.
- 2026-10-20 Phase 5: protections (Cooldown, MaxDrawdown 25%/90, StoplossGuard) moved
  into strategy (config-level deprecated in 2026.9). Protected backtest: 45 trades,
  +599.3%, CAGR 24.73%, maxDD 22.88%.
- 2026-10-20 Phase 7: SQLite ledger app/ledger/unbound.db (trades/metrics/equity/ai_notes)
  via app/scripts/build_ledger.py. 6 evidence notes (FACT/HYPOTHESIS/GUARDRAIL).
- 2026-10-20 Phase 9: Streamlit dark dashboard app/dashboard/app.py renders OK
  (verified in browser). Fixed CAGR *100 bug. Live BTC tile via public Kraken (no CoinGecko).
- 2026-10-20 Runtime: `freqtrade trade --dry-run` RUNNING (heartbeat state=RUNNING),
  polls Binance, protections armed, waits for new daily candle.
- 2026-10-20 Phase 6: config.alpaca.paper.json + app/scripts/check_alpaca.py wired.
  Gate returns exit 2 (AUTH BLOCKED). NOT exercised until valid keys.
- 2026-10-20 Phase 6 (unblocked): valid paper keys → check_alpaca AUTH OK. Freqtrade does
  NOT support %ENV% config; app/scripts/run_paper.py injects FREQTRADE__EXCHANGE__KEY/SECRET.
  Fixed "Empty candle" via ohlcv_require_since (see Resolved blockers). Paper bot now RUNNING,
  fetches full daily history, populates enter/exit signals (enter=False today, no position).
- 2026-10-20 Phase 6b: dashboard "Alpaca Paper (live)" tab (read-only) shows Cash/Equity/
  Buying power/Portfolio + positions + crypto_status, live; footer reports PAPER bot ONLINE.
- 2026-10-21 Phase 8 (HMM regime, RESEARCH ONLY): app/research/hmm_regime.py — self-contained
  NumPy Gaussian HMM (Baum-Welch EM + causal forward filtering), walk-forward OOS, no ML deps.
  Causality test max|Δ|=0 (passes). BIC picked K=2. OOS 2024-10→2026-10: HMM-filter +6.2%
  (DD 51%, 100 changes) vs buy-hold +18.7% vs Z-proxy +24.9% → did NOT beat baselines.
  Decision: DEFERRED for trading activation (per plan; not wired to strategy/executor).
  Artifacts app/research/artifacts/, report docs/Phase8_HMM_Report.md, ledger regime_states.
- 2026-10-21 Phase 10 (observation harness, READ-ONLY): app/scripts/obs_lib.py + reconcile.py +
  weekly_report.py. reconcile.py mirrors the Freqtrade paper DB (D:/BOT/tradesv3.sqlite, now pinned
  via config db_url) + Alpaca PAPER account/positions/orders into NEW ledger tables kept SEPARATE
  from research (paper_trades / reconcile_log / account_equity / reports): never overwrites backtest
  rows, never places orders, never prints keys. Detects qty drift / unmatched broker orders /
  protection locks → status OK|REVIEW|BROKER_UNREACHABLE. weekly_report.py → docs/Phase10_Observation.md
  (signals/fills/costs/reconcile/risk/exposure+drawdown, honest "insufficient sample" for daily bot).
  Dashboard "Observation" tab renders live (verified): OK, $100k equity, drift 0, 0 trades. `--watch` loop
  or a scheduled task establishes the observation cadence. Time-based phase — accumulate weeks before judgments.
- 2026-10-21 **AUDIT REMEDIATION — corrected the false-OK Phase 10 model above.** The prior
  `OK|REVIEW|BROKER_UNREACHABLE` model could report `OK` merely because there was no apparent drift,
  even with the executor dead. It is replaced by a defined, precedence-ordered status model
  `CRITICAL > OFFLINE > BROKER_UNREACHABLE > STALE > REVIEW > HEALTHY` (the literal `OK` is retired):
  reconcile now proves process liveness (PID + heartbeat age), market-data freshness (candle age),
  broker reachability, DB readability, portfolio qty match, and order reconciliation **by identity**
  (ID set-difference, not count). It can NEVER report HEALTHY while offline/stale/drifted/corrupt.
  Live evidence on first re-run: reconcile returned **CRITICAL — broker holds 0.06024 BTC that the
  Freqtrade DB does not account for (drift 0.0602)** — a real unreconciled paper position the old
  `OK` would have hidden. Weekly fees now use monetary `fee_open_cost`+`fee_close_cost` (not the
  `fee_open`/`fee_close` rates) and count missing records as a lower bound. `app/scripts/preflight.py`
  gates any restart; `docs/Audit_Remediation_2026-10-21.md` is the full evidence report.
- 2026-10-21 **TASK 3 — first real automated test suite.** `pytest` installed (9.1.1) into the
  venv via `uv pip install`. Root `pytest.ini` scopes collection to `app/tests` (never the vendored
  `freqtrade-stable/` suite). 55 tests, all passing, fully mocked/credential-free (no orders, no
  network, no bot start): `test_strategy.py` (10 — warm-up NaN, zero-variance, determinism, bull/bear
  transitions, volume-gated entry, **no-lookahead append-invariance**, NaN-close safety),
  `test_reconcile.py` (25 — classify_status precedence + snapshot() proving offline/stale/corrupt-DB/
  drift can never yield HEALTHY, identity set-diff), `test_reporting.py` (6 — monetary fees, missing/
  empty/incomplete), `test_execution_safety.py` (14 — preflight fail-closed BLOCKs, submit≠filled
  never-healthy, idempotent replay). Run: `python -m pytest` from repo root.
- 2026-10-21 **TASK 5/7 — startup warm-up + reproducible backtest.** startup_candle_count raised
  70→**400** (recursive-analysis: z-score ~22% off at 70, <0.01% at 400). Backtest (binance research
  proxy, `--enable-protections`, timerange 20170817-20261019 → effective 2018-09-21→2026-10-19 after
  400-candle warm-up): **41 trades, +1326%, CAGR 38.93%, maxDD 22.88% (wallet 35.79%), win 41.5%**.
  Same-window buy-and-hold = +1112%, CAGR 36.20% → strategy is only **marginally** above holding on a
  41-trade sample and still does **NOT reproduce the source's 65.92%/26.79% claim. No edge is proven.**

## How to run
- Automated tests (no creds/orders): `python -m pytest`  ·  one file: `python -m pytest app/tests/test_reconcile.py -v`
- Backtest: `freqtrade backtesting -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --timerange 20170817-20261019 --enable-protections` (or `python app/scripts/run_backtest.py`)
- Preflight gate (read-only, must pass before any restart): `python app/scripts/preflight.py`  (exit 3 = BLOCKED, 4 = live/unsafe)
- Ledger: `python app/scripts/build_ledger.py`
- Dashboard: `streamlit run app/dashboard/app.py` (http://127.0.0.1:8501)
- Live dry-run: `freqtrade trade -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --dry-run`
- Alpaca gate: `python app/scripts/check_alpaca.py`
- Alpaca paper bot: `python app/scripts/run_paper.py` (injects keys from .env, dry_run=false → paper-api)
- Phase 8 HMM research (non-trading): `python app/research/hmm_regime.py` → artifacts + docs/Phase8_HMM_Report.md
- Phase 10 reconcile (read-only mirror): `python app/scripts/reconcile.py`  ·  cadence: `python app/scripts/reconcile.py --watch 900`
- Phase 10 weekly report: `python app/scripts/weekly_report.py` (optional `--days 14`) → docs/Phase10_Observation.md
