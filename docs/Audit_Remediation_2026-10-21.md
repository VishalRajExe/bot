# Audit Remediation Report — 2026-10-21

Scope: fix the critical correctness issues raised by the latest audit before any
paper-bot restart, add a real automated test suite, verify configuration, and
report evidence. Per the owner's explicit directive, **the Freqtrade trading
process was NOT started or restarted** during this work. Nothing here places an
order; all broker interaction was read-only GETs, and all tests are mocked /
credential-free.

The project is **not complete** and is **not** claimed complete. This report
states exactly what was fixed, tested, verified, and what remains open.

---

## 0. Audit findings addressed

| # | Finding (audit) | Severity | Status now |
|---|---|---|---|
| C1 | `reconcile.py` could report `status=OK` merely because no drift was visible, even with the executor dead | CRITICAL | **Fixed** — precedence-ordered liveness/status model; cannot reach HEALTHY when offline/stale/drifted/corrupt |
| C2 | `weekly_report.py` treated `fee_open`/`fee_close` (rates) as monetary fees | CRITICAL | **Fixed** — uses `fee_open_cost`/`fee_close_cost`; counts missing/null records |
| C3 | No real automated test suite | HIGH | **Fixed** — 55 mocked pytest tests (strategy / reconciliation / reporting / execution-safety) |
| C4 | Duplicate strategy files with drift risk (`app/strategies/` vs `app/user_data/strategies/`) | HIGH | **Fixed** — authoritative path established, identical unused copy removed, README documents it |
| C5 | Lookahead / recursive analysis not actually run | HIGH | **Fixed** — both executed; `startup_candle_count` 70→400 for convergence |
| C6 | Risk settings (thresholds 0.5/0.0, stoploss -0.35, unlimited stake) assumed approved | HIGH | **Gated** — `preflight.py` keeps trading DISABLED; no approval invented |
| C7 | Phases.md and Memory.md contradicted reality | MEDIUM | **Reconciled** — both updated with evidence, acceptance kept honest |

---

## 1. Files changed

Modified:
- `app/scripts/reconcile.py` — full rewrite: liveness/status model, identity reconciliation, monetary-fee mirroring
- `app/scripts/obs_lib.py` — heartbeat/PID state file, candle-freshness helper, fee/liveness ledger columns + idempotent migrations
- `app/scripts/weekly_report.py` — `summarize_fees()` monetary + missing-count; status-aware sections; safe `.get()` on partial rows
- `app/scripts/run_paper.py` — `Popen` + heartbeat/PID writer thread (so reconcile can prove liveness)
- `app/dashboard/app.py` — Observation tab status-color map + heartbeat-age metric
- `app/user_data/strategies/BtcZScore.py` — `startup_candle_count` 70 → **400**
- `app/configs/config.research.binance.json` — clarified research-proxy comment / pricing
- `docs/Phases.md` — register, Phase 6/10 items, Final acceptance (with evidence)
- `Memory.md` — strategy path, status model, backtest numbers, remediation log
- `.gitignore` — added `app/state/`

Added:
- `app/scripts/preflight.py` — read-only config/risk gate (TASK 6)
- `app/scripts/run_backtest.py` — reproducible credential-injected offline backtest
- `app/strategies/README.md` — documents the authoritative strategy path
- `pytest.ini` — scopes the suite to `app/tests` (excludes vendored `freqtrade-stable/`)
- `app/tests/conftest.py`, `app/tests/test_strategy.py`, `app/tests/test_reconcile.py`,
  `app/tests/test_reporting.py`, `app/tests/test_execution_safety.py`

Removed:
- `app/strategies/BtcZScore.py` — byte-identical unused duplicate of the authoritative file

---

## 2. Tests — passed / failed

```
python -m pytest   →   55 passed in ~7s   (0 failed, 0 skipped)
```

| File | Tests | Covers |
|---|---|---|
| `test_strategy.py` | 10 | EMA/STD warm-up NaN, zero-variance, determinism, bullish→entry / bearish→exit transitions, volume-gated entry, **no-lookahead append-invariance**, NaN-close safety, startup==400 |
| `test_reconcile.py` | 25 | `classify_status` precedence incl. offline / stale-heartbeat / stale-data / broker-unreachable / drift / corrupt-DB / live-endpoint / external-orders / locks / unresolved — **none of these can produce HEALTHY**; identity set-difference; `snapshot()` integration proving offline→OFFLINE and drift→CRITICAL end-to-end on a temp DB |
| `test_reporting.py` | 6 | monetary fee totals (not rates), missing/empty/incomplete fee records, fee-missing warning + offline-unverified in rendered report |
| `test_execution_safety.py` | 14 | preflight fail-closed BLOCKs (live endpoint, inline secrets, short/leverage, no protections/stoploss, unset threshold, **missing approval**), unlimited-stake WARN, safe+approval READY; **submit ≠ filled** (FT-open order absent at broker → REVIEW, never HEALTHY); idempotent replay (no duplicate ledger rows) |

No test sends an order, opens a real network socket, or starts the bot.

---

## 3. Commands actually executed (and results)

Environment: Freqtrade 2026.9, Python 3.12.13 (`D:\BOT\.venv`), pytest 9.1.1.

- `python -m pytest` → **55 passed**.
- `python app/scripts/preflight.py` → strategy_meta `{can_short: False, leverage: 1.0, stoploss: -0.35, bull_threshold: 0.5, exit_threshold: 0.0, protections_count: 3, timeframe: 1d, startup_candle_count: 400}`; findings incl. `BLOCK RISK_APPROVAL_MISSING`, `WARN UNLIMITED_STAKE`; **TRADING READY: False**, **exit 3**.
- `python app/scripts/reconcile.py` (bot down) → **status=CRITICAL** — broker qty **0.06024** vs Freqtrade open amount **0** (drift 0.0602); heartbeat None. (Also observed `process_alive=None`, `candle_age_h=31.0`.) Correctly never reports OK.
- `python app/scripts/weekly_report.py --days 14` → wrote `docs/Phase10_Observation.md`; status_mix across snapshots `{'OK': 2 (legacy), 'OFFLINE': 1, 'CRITICAL': 1}`; max_drift 0.0602.
- `python app/scripts/check_alpaca.py` → **AUTH OK** paper account: cash 94,998.50, equity 99,978.73, buying_power 379,994, crypto ACTIVE, BTC/USD tradable (read-only GETs; no orders).
- `freqtrade lookahead-analysis -c <research cfg> --userdir app/user_data --strategy BtcZScore --timerange 20170801-/20200101-` → **has_bias: No** (20 signals).
- `freqtrade recursive-analysis -c <research cfg> --userdir app/user_data --strategy BtcZScore --timerange 20180101-20261019` → **No lookahead bias detected**; z-score converged at startup 400 (−0.003% vs 22.3% at 70).
- `freqtrade backtesting -c app/configs/config.research.binance.json --userdir app/user_data --strategy BtcZScore --timerange 20170817-20261019 --enable-protections --cache none` → **exit 0**; effective 2018-09-21→2026-10-19; **41 trades, +1326.00%, CAGR 38.93%, max DD 22.88% (wallet 35.79%), win 41.5% (17W/24L), profit factor 2.88**.
- `freqtrade backtesting -c app/configs/config.alpaca.paper.json ...` → **FAILED**: `AuthenticationError: alpaca requires "apiKey"` at ccxt `traderPrivateGetV2Assets`. Reproduced with keys injected via env **and** inline in a temp config. Root cause: ccxt-Alpaca `load_markets()` uses a private, authenticated endpoint the Freqtrade backtest bootstrap does not authenticate; Alpaca is not a Freqtrade-native exchange. Worked around by backtesting on public binance data. **Live/paper `trade` mode DOES authenticate** (check_alpaca + markets load), so this is backtest-only.
- Same-window buy-and-hold (computed on the binance candles): **+1112.28%, CAGR 36.20%** — the strategy is only marginally above holding on a 41-trade sample and does **NOT** reproduce the source's claimed 65.92% CAGR / 26.79% max-DD.

---

## 4. Remaining security & correctness issues (open)

1. **Unreconciled broker position (needs owner investigation).** The Alpaca PAPER account holds
   **~0.06024 BTC** that the Freqtrade trade DB (`D:/BOT/tradesv3.sqlite`) does not record. Reconcile
   now correctly flags this as CRITICAL. Origin unknown (likely a pre-harness manual/test order or a
   DB reset). Must be understood before any restart — do NOT auto-clear it.
2. **No owner risk approval exists.** `app/configs/risk_approval.json` is absent; thresholds
   (bull 0.5 / exit 0.0), stoploss −0.35, and `stake_amount="unlimited"` are **candidate, not approved**.
   Trading stays gated. (WARN: unlimited stake ⇒ all-in single spot position.)
3. **No edge proven.** Backtest does not clearly beat buy-and-hold and does not reproduce the source
   claim; the "dual-signal" second component of the source strategy is unavailable.
4. **Exposed credentials.** The Alpaca keys were pasted in chat earlier — rotate them (they live only
   in the git-ignored `.env`, never committed).
5. **Alpaca backtest limitation** (sec. 3) means strategy research runs on binance proxy data, not
   Alpaca execution parity; slippage/latency/quote differences are unmodeled.
6. **Freqtrade checkout has no `.git`** (extracted archive) — provenance/SHA unverified locally.

---

## 5. Acceptance criteria — per-criterion verdict

(Tracked in `docs/Phases.md` "Final acceptance".)

| Criterion | Verdict | Basis |
|---|---|---|
| ACCEPT-01 tested paper executor | **NOT MET** | harness coded/tested, but paper lifecycle not exercised (trading gated) |
| ACCEPT-02 sourced/approved rules | **NOT MET** | candidate thresholds, no owner approval |
| ACCEPT-03 traceable fills/outcomes | **PARTIAL** | durable ledger + idempotent reconcile tested; no live fills recorded |
| ACCEPT-04 provenance/benchmarks/leakage backtests | **MET** | this report + lookahead/recursive PASS + buy-hold benchmark + fee model |
| ACCEPT-05 dashboard matches sources | **PARTIAL** | status-aware tab; full broker-vs-dashboard verification pending |
| ACCEPT-06 required tests pass / honest gaps | **MET** | 55 pass; limitations stated here |
| ACCEPT-07 docs agree with reality | **MET** | Phases.md + Memory.md reconciled with evidence |
| ACCEPT-08 next action + approval boundary | **PARTIAL** | remediation defines it; per-phase closeout template still pending |

---

## 6. Documentation updates

- `docs/Phases.md`: register reflects implemented/tested vs gated reality; Phase 6 items P6-01/02/06/08/10/13 checked with evidence and the rest explicitly open; Phase 10 note documents the false-OK fix and the live CRITICAL finding; Final acceptance annotated per-criterion.
- `Memory.md`: authoritative strategy path fixed; research-data decision + Alpaca-backtest limitation recorded; reconcile status model corrected (retired `OK`); false-OK remediation, the 55-test suite, startup 400, and the reproducible backtest numbers logged; How-to-run updated (pytest / preflight / backtest).

---

## 7. Restart decision (left to owner)

Per the owner's directive, no restart was performed. To restart paper trading, the owner must:
1. Investigate/resolve the unreconciled 0.06024 BTC paper position.
2. Approve risk limits by creating `app/configs/risk_approval.json` (or move `stake_amount` to a bound).
3. Re-run `python app/scripts/preflight.py` and confirm `TRADING READY: True` (exit 0).
4. Then decide whether to start `python app/scripts/run_paper.py` and re-establish `reconcile.py --watch`.

Until those hold, `preflight.py` returns exit 3 and the system correctly refuses to report healthy.
