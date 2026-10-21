# Phase 10 — Paper Observation Report

- Generated (UTC): `2026-10-21T05:30:28Z`
- Window: trailing **7 days** (2026-10-14 → 2026-10-21)
- Mode: Alpaca **PAPER** only (`dry_run=false`, paper-api endpoint). No real money.
- Freqtrade trade DB: `D:\BOT\tradesv3.sqlite`
- Source of truth: Freqtrade execution DB; this report is a read-only mirror.

## 1. Signals & entries/exits
- Trades opened in window: **0**
- Trades closed in window: **0**
- Currently open positions: **0**

> Daily-timeframe bot on a single pair (BTC/USD). Zero signals in this window is expected and is NOT evidence of a stall — it means the Z-score entry condition was not met. **Insufficient sample for statistical significance; do not extrapolate edge from this interval.**

## 2. Orders, fills & costs
- Total mirrored trades (all-time in ledger): **0**
- Cumulative fees booked in ledger: **0**
- Realized P&L (closed trades): **0**

## 3. Reconciliation (Freqtrade records vs broker)
- Observation snapshots in window: **2**
- Status mix: OK=2
- Max absolute position qty drift: **0.0**
- Last snapshot: `2026-10-21T05:25:53Z` → **OK** — Freqtrade records reconcile with broker (no external/manual activity).
- No drift / unmatched broker activity / external orders detected. ✅

## 4. Risk triggers (protections / pair locks)
- No protection/pair-lock events in window.

## 5. Account, exposure & drawdown
- Equity (start → end): **100000.0 → 100000.0**
- Peak equity in window: **100000.0**
- Max drawdown in window: **0.0%**
- Current exposure (position/equity): **0.0%**

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
