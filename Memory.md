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
- **Alpaca fee-in-base crypto exit dust** (found 2026-10-21 via a controlled test trade): a full exit
  leaves a sub-fee base-currency residual that Freqtrade cannot sell, so the trade never closes. Blocks
  AUTONOMOUS crypto EXITS on BOTH executors (fast momentum bot is PAUSED for this reason; daily baseline
  hasn't filled yet). Needs an approved fix before re-enabling exits — see Log 2026-10-21.

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
- **Bounded sizing is mandatory.** `stake_amount="unlimited"` is a preflight BLOCK, not a
  warning. The agent PROPOSES bounded settings for owner approval; it never self-authorizes
  risk (docs/Rules.md §5). **2026-10-21:** the owner gave explicit WRITTEN authorization for
  autonomous PAPER-only execution (transcribed in `risk_approval.json` rev3) — per-trade manual
  approval gates are removed for eligible pairs WITHIN the bounded policy; hard risk limits,
  broker reconciliation, data-quality checks and paper-only restriction are NEVER bypassed.
  BTC/USD remains the live baseline; live trading/leverage/shorts/futures/transfers remain
  prohibited without a new written authorization.

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
- 2026-10-21 **BOUNDED-RISK CORRECTION (owner/reviewer flag).** Prior preflight self-authorized
  `stake_amount="unlimited"` — a docs/Rules.md §5 violation. Stopped the running unlimited bot;
  config converted to BOUNDED (`stake_amount=5000`, `available_capital=100000`, `max_open_trades=1`);
  `app/configs/risk_approval.json` rewritten (revision 2) as an explicit BOUNDED PROPOSAL — paper-only
  approved / live NOT approved / FVG-OB pending. `preflight.py` upgraded UNLIMITED_STAKE WARN→**BLOCK**
  (test `test_unlimited_stake_is_blocked`). Preflight → STAKE_BOUND, TRADING READY True, exit 0.
- 2026-10-21 **FVG/OB exact-sequence strategy (RESEARCH ONLY, decision #2/#3).** Deterministic pure core
  `app/strategies_core/fvg_ob.py`: 3-candle FVG, confirmed swings, Wilder ATR, EMA bias, order blocks;
  `SetupTracker` state machine enforces bias→zone→**tap**→new-5M-FVG→**first** retest→long entry at
  close, fixed 1:2 RR, spot/long-only, per-step timestamps, no-lookahead (close-time events),
  restart-safe via `state_store.py` (intent JSON, not exec truth). 21 tests in `app/tests/test_fvg_ob.py`.
  `app/scripts/discover_assets.py` (read-only): availability from Alpaca `/v2/assets` crypto list,
  eligibility = relative-liquidity/data-quality/spread proposal → **enables nothing** (enabled=0);
  output `app/configs/asset_universe.json` (73 avail, 6 eligible incl. BTC baseline). Full spec:
  `docs/Strategy_FVG_OB.md`.
- 2026-10-21 **FVG/OB research backtest — NO edge shown.** `app/scripts/research_fvg_backtest.py`
  replays the tested core on REAL Alpaca 1H+5M candles (NOT a second engine). Free-tier 5M depth ≈8 days.
  Shipped `require_overlap=True` → 0 setups in-window; sensitivity `--no-overlap` → BTC 5(2W/2L/1TO),
  ETH 3(0W/3L), XRP 1(0W/1L), LINK 4(0W/4L): ~17% win rate (< 33% breakeven for 1:2), negative net-R
  after fees on every pair. Pessimistic tie-break (stop first). Kept research-only; activates nothing.
  Fixed a replay bug where a wedged tracker (no re-arm after invalidation/stale tap) suppressed all
  setups — evaluate now supersedes an incomplete pre-entry setup on the next bullish 1H FVG, never an
  ENTRY/POSITION.
- 2026-10-21 **Telegram DETAIL notifications.** `app/notifications/format.py` (pure, 3 tests in
  `test_notifications.py`): `format_signal_report` (baseline decision + inputs + bounded risk),
  `format_fvg_ob_setup` (per-step timestamps + 1:2 RR), `format_status`. `BtcZScore` now sets
  `enter_tag`/`exit_tag` (z-score reasoning) so Freqtrade's Telegram entry/exit messages carry *why*.
  config telegram `notification_types` expanded (entry/exit/filled/profit/protection/status/…).
  `app/scripts/test_notify.py` sends real formatted samples (no orders) — delivery verified (ok=True ×3).
- 2026-10-21 **AUTONOMOUS PAPER EXECUTION ACTIVATED (owner written authorization).** Transcribed to
  `risk_approval.json` rev3 — per-trade/per-coin manual approval REMOVED for eligible pairs WITHIN the
  bounded policy; live trading/leverage/shorts/futures/transfers still prohibited. New data layer:
  `paper_risk_policy.json` (per-pair stake caps BTC $5000 / alts $1000 & max planned loss $500;
  portfolio exposure min($10000, 10% equity); ≤5 concurrent positions, 1 per pair; circuit breakers
  daily −2% / peak-to-trough −5% → kill switch persisted, manual recovery only) +
  `strategy_registry.json` (pair→strategy: BTC ACTIVE_BASELINE, ETH/XRP/DOT/LINK EXPERIMENTAL_PAPER
  daily Z-score alt-1d-z65-v0, USDT STATUS_ONLY, FVG/OB RESEARCH_ONLY). Independent risk layer
  `app/risk/policy.py` (fail-closed sizing/validators/kill-switch/rejection log). Executor =
  `PaperAutonomous` dispatcher SUBCLASSING `BtcZScore`: BTC/USD routes to `super()` byte-identical
  (parity test); alts use registry thresholds; non-tradeable pairs emit no signals. Entry veto via
  `confirm_trade_entry` (unsupported/cap/breaker/stale-equity/duplicate/exposure → reject+log+explain);
  sizing via `custom_stake_amount`. Config: whitelist 5 pairs, `max_open_trades=5`, USDT blacklisted —
  ONE executor only. FVG/OB stays research-only: its 1H-bias/5M-entry sequence cannot run inside the
  single 1d executor without altering the BTC baseline — documented, not faked (`strategy_registry.json`
  reason_not_traded + docs/Strategy_FVG_OB.md). `crypto_status_monitor.py` = independent READ-ONLY
  notifier (Alpaca data endpoint, no ccxt): per-asset Telegram (60s poll, notify-on-change + 60-min
  heartbeat), real open positions/order state from the Freqtrade DB, maintains `equity.json`, evaluates
  breakers and persists the kill switch, `--recover-kill-switch` for manual recovery. Tests +49
  (`test_risk_policy.py`, `test_dispatcher.py`, format_asset_status) → 104 passed. Preflight TRADING
  READY. Verified live: reconcile HEALTHY (drift 0), bot RUNNING 5 pairs, Telegram per-asset delivered,
  dashboard "Autonomous Pairs" tab browser-verified (0 console errors). **Autonomous ≠ profitable:
  alts are experimental forward-test only; FVG/OB showed no edge; no profitability claimed.**
- 2026-10-21 **FAST INTRADAY EXECUTOR (owner directive "instant buy sell … carefully strategically").**
  Owner chose via explicit questions: separate fast bot / 5m timeframe / EMA-cross+volume-surge momentum.
  TWO disjoint PAPER order executors now run: "daily" = BTC-only 1d `PaperAutonomous` (unchanged baseline,
  `config.alpaca.paper.json`, `tradesv3.sqlite`, $5000 cap, max_open_trades 1) and "fast" = ETH/XRP/DOT/LINK
  5m `MomentumAlt` (`config.alpaca.paper.fast.json`, `tradesv3_fast.sqlite`, $1000/pair, max_open_trades 4,
  stoploss −0.03, intraday protections 2h/24h windows). `MomentumAlt` SUBCLASSES `PaperAutonomous` so the
  risk veto (`custom_stake_amount`+`confirm_trade_entry`) is reused verbatim (identity-tested); fresh EMA
  cross-up + volume surge required (never "already above" → no chasing/duplicate entries); BTC baseline and
  status-only pairs emit nothing from the fast bot. Safety-by-construction: disjoint whitelists +
  structural worst case 5000+4×1000=9000 ≤ 10000 exposure cap, 1+4=5 positions ≤ 5; `validate_executors`
  enforces disjoint/union/combined bounds at preflight; cross-executor ledger `app/state/open_exposure.json`
  (written each sweep by the READ-ONLY monitor) is added to the global exposure check in `confirm_trade_entry`
  and FAILS CLOSED if missing/stale (>180s). Telegram getUpdates allows only one polling bot → fast config
  `telegram.enabled=false`; owner still gets fast-trade alerts via monitor sendMessage across both DBs
  (composite "label:id" event keys). `run_paper.py --fast` launches the fast profile. Ops lesson: stale
  daily bot holding alts in memory would have double-traded → all stale PIDs stopped, daily relaunched
  BTC-only BEFORE starting fast. Tests +22 → **126 passed**; preflight TRADING READY both executors;
  reconcile **HEALTHY** aggregated across both DBs (drift 0); monitor first sweep sent 6 per-asset alerts +
  wrote the ledger; live signal reads confirm correct states (alts HOLD/FLAT without a fresh cross, BTC
  unchanged +0.812). **No profitability claimed — 5m forward-test only, fees/slippage drag expected.**
- 2026-10-21 **CONTROLLED TEST TRADE → DISCOVERED ALPACA FEE-IN-BASE EXIT DUST (fast bot paused).**
  Owner asked "buy something for testing." Temporarily enabled a localhost `api_server` + `force_entry_enable`
  on the FAST paper config (creds from .env, never committed; later reverted) and POSTed a $50 DOT/USD market
  forceentry. **BUY path fully verified**: it ran the ENTIRE `confirm_trade_entry` veto (tradeable→cap→breaker→
  fresh-equity→duplicate→global-exposure incl. cross-executor ledger), filled at the paper broker, wrote
  `open_exposure.json`, fired monitor Telegram alerts, and reconcile mirrored it. **EXIT exposed a real bug**:
  Alpaca settles crypto fees **net of position** (fee deducted from the BASE coins received: credited 42.64 DOT,
  not the 42.75 Freqtrade recorded) but its ccxt order reports the fee in QUOTE. Freqtrade's `_safe_exit_amount`
  falls back to the wallet amount, yet `recalc_trade_from_orders` recomputes balance from order fills
  (buy 42.748 − sell 42.641 = 0.107), so a sub-fee **dust residual stays permanently open** — the bot thrashes
  re-applying buy-fee and the trade never closes (would flip reconcile back to CRITICAL). No config knob fixes
  it; the only true fixes (patch the vendored engine/exchange subclass, or mutate the live bot DB out-of-band)
  both violate our thin-layer / read-only-observability rules, so NEITHER was done. DECISION (owner "pick best"):
  keep the FAST executor **PAUSED** — entries/holding are fine but autonomous crypto EXITS must not run until
  fee-in-base is solved; shipping it into a known exit-jam is not "carefully." The DAILY BTC baseline (approved,
  holding no position) is left running but shares this latent exit issue. Reverted test affordances: fast config
  `force_entry_enable=false`, api_server block removed, `run_paper.py` api injection removed. **Kept a genuine
  fix**: `reconcile.py` now treats fee-net drift as expected (tolerance scales with open amount, not absolute
  1e-6) so a correctly-held position doesn't false-CRITICAL; +2 regression tests (fee-net within tol → HEALTHY,
  real mismatch → still CRITICAL) → **128 passed**. Cleaned the isolated fast test DB (broker 0 == DB 0 open);
  baseline untouched; equity honestly 99,999.59 (−$0.41 test cost). **OPEN BLOCKER (both executors, crypto):
  Alpaca fee-in-base exit dust — must design a proper handling (engine fee-currency override via an approved
  Alpaca exchange subclass, or a safe documented operational close) before re-enabling autonomous exits.**

## How to run
- Automated tests (no creds/orders): `python -m pytest`  ·  one file: `python -m pytest app/tests/test_reconcile.py -v`
- Backtest (BTC baseline, binance proxy): `freqtrade backtesting -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --timerange 20170817-20261019 --enable-protections` (or `python app/scripts/run_backtest.py`)
- FVG/OB research (read-only, needs .env keys): `python app/scripts/discover_assets.py --top 20 --write`  ·  `python app/scripts/research_fvg_backtest.py --pair ETH/USD` (add `--no-overlap` for sensitivity)
- Telegram delivery check (sends a message, no order): `python app/scripts/test_notify.py` (`--dry` to preview)
- Preflight gate (read-only, must pass before any restart): `python app/scripts/preflight.py`  (exit 3 = BLOCKED, 4 = live/unsafe)
- Ledger: `python app/scripts/build_ledger.py`
- Dashboard: `streamlit run app/dashboard/app.py` (http://127.0.0.1:8501)
- Live dry-run: `freqtrade trade -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --dry-run`
- Alpaca gate: `python app/scripts/check_alpaca.py`
- Alpaca paper bot: `python app/scripts/run_paper.py` (injects keys from .env, dry_run=false → paper-api)
- Alpaca paper FAST bot (5m momentum alts): `python app/scripts/run_paper.py --fast` (telegram off — monitor alerts both DBs)
- Autonomous per-asset Telegram monitor (READ-ONLY, no orders): `python app/scripts/crypto_status_monitor.py --interval 60 --heartbeat-minutes 60`  ·  kill-switch manual recovery after review: add `--recover-kill-switch`
- Phase 8 HMM research (non-trading): `python app/research/hmm_regime.py` → artifacts + docs/Phase8_HMM_Report.md
- Phase 10 reconcile (read-only mirror): `python app/scripts/reconcile.py`  ·  cadence: `python app/scripts/reconcile.py --watch 900`
- Phase 10 weekly report: `python app/scripts/weekly_report.py` (optional `--days 14`) → docs/Phase10_Observation.md
