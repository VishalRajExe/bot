# Phase 10 — Paper Observation Report

- Generated (UTC): `2026-10-21T07:00:27Z`
- Window: trailing **14 days** (2026-10-07 → 2026-10-21)
- Mode: Alpaca **PAPER** only (`dry_run=false`, paper-api endpoint). No real money.
- Freqtrade trade DB: `D:\BOT\tradesv3.sqlite`
- Source of truth: Freqtrade execution DB; this report is a read-only mirror.

## 1. Signals & entries/exits
- Trades opened in window: **0**
- Trades closed in window: **0**
- Currently open positions: **0**

> No trades in this window **and the latest reconcile status is `CRITICAL`** — treat this as UNVERIFIED, not benign. Confirm the executor is alive and data is fresh (§3) before concluding the strategy simply saw no signal.

## 2. Orders, fills & costs
- Total mirrored trades (all-time in ledger): **0**
- Cumulative monetary fees (fee_open_cost + fee_close_cost): **0.0**
- Realized P&L (closed trades): **0**

## 3. Reconciliation (Freqtrade records vs broker)
- Observation snapshots in window: **4**
- Status mix: CRITICAL=1, OFFLINE=1, OK=2
- Max absolute position qty drift: **0.06023902**
- Last snapshot: `2026-10-21T07:00:23Z` → **CRITICAL** — portfolio mismatch: broker qty 0.060239024 vs Freqtrade open amount 0 (drift 0.06023902).
  - liveness @ last snapshot: process_alive=0 heartbeat_age_s=None candle_age_h=31.006830770833336 unmatched_broker_orders=0 ft_unresolved_orders=0 active_locks=0

### ⚠ 2 snapshot(s) not HEALTHY
- `2026-10-21T06:02:59Z` **OFFLINE** — paper executor is OFFLINE (no heartbeat file); never reported healthy.
- `2026-10-21T07:00:23Z` **CRITICAL** — portfolio mismatch: broker qty 0.060239024 vs Freqtrade open amount 0 (drift 0.06023902).

## 4. Risk triggers (protections / pair locks)
- No protection/pair-lock events in window.

## 5. Account, exposure & drawdown
- Equity (start → end): **99978.73 → 99978.73**
- Peak equity in window: **99978.73**
- Max drawdown in window: **-0.021%**
- Current exposure (position/equity): **4.98%**

## 6. Paper vs backtest caveats (P10-05)
- Slippage/latency in paper differ from backtest assumptions; fills are market orders against Alpaca paper quotes.
- Daily timeframe + single pair ⇒ very low trade frequency; expect long flat stretches. Sample must accumulate over weeks, not days.
- Paper equity ≠ live-money behavior (no partial fills / rejects under real liquidity stress).

## 7. Next priorities (P10-09)
- Keep reconcile cadence (scheduled task or `--watch`) so §3/§5 gain a time series.
- Accumulate ≥ a few weeks of signals before any edge/regime judgment.
- Review HMM activation only when there is a statistically meaningful sample (see docs/Phase8_HMM_Report.md — currently DEFERRED).
- Do NOT promote to real money without explicit owner approval + a clean multi-week reconciliation with zero unresolved drift.

_Generated read-only by app/scripts/weekly_report.py. No orders placed._
