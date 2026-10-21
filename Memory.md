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
- Strategy path: `D:\BOT\app\strategies` (pass `--strategy-path` or set `strategy_path`).

## Decisions
- **Route B**: target Alpaca directly via CCXT on the local checkout; no fork.
- Research/backtest data source: **Kraken BTC/USD** (public, USD-quoted). Caveat:
  not the Alpaca feed → results are research, not execution parity.
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

## How to run
- Backtest: `freqtrade backtesting -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --timerange 20180101- --enable-protections`
- Ledger: `python app/scripts/build_ledger.py`
- Dashboard: `streamlit run app/dashboard/app.py` (http://127.0.0.1:8501)
- Live dry-run: `freqtrade trade -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --dry-run`
- Alpaca gate: `python app/scripts/check_alpaca.py`
- Alpaca paper bot: `python app/scripts/run_paper.py` (injects keys from .env, dry_run=false → paper-api)
- Phase 8 HMM research (non-trading): `python app/research/hmm_regime.py` → artifacts + docs/Phase8_HMM_Report.md
- Phase 10 reconcile (read-only mirror): `python app/scripts/reconcile.py`  ·  cadence: `python app/scripts/reconcile.py --watch 900`
- Phase 10 weekly report: `python app/scripts/weekly_report.py` (optional `--days 14`) → docs/Phase10_Observation.md
