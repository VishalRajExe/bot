"""UnboundBot — 1h SWING executor for the PAPER-RELAXED, wide-spread alt names.

Owner directive 2026-10-22 (approved plan): LTC/AVAX/DOGE fail the strict cost/liquidity
gate (spread > 0.5% and/or thin), so they are NOT run on the fast 5m executor where a
~1.1%+ round-trip cost would swamp the edge. Instead they trade on a THIRD, DISJOINT 1h
swing process whose strategies target larger moves that can clear the higher cost. This
is an owner-approved relaxation of the eligibility gate for PAPER only — it never enables
live-money trading.

Like the fast executor this is a thin binding of the shared ``FamilyDispatcher``: it
inherits the fail-closed veto + bounded sizing from PaperAutonomous verbatim and routes
each pair to its registry ``strategy_family`` (rsi_divergence or bb_squeeze for swings).
The global exposure cap still counts the daily and fast executors' open stake via the
cross-executor ledger (RISK_EXECUTOR = "swing"). Spot, long-only, unleveraged, PAPER ONLY.
"""
from __future__ import annotations

from FamilyDispatcher import FamilyDispatcher  # noqa: E402


class SwingAlt(FamilyDispatcher):
    INTERFACE_VERSION = 3
    timeframe = "1h"               # swing cadence; wide-spread names need bigger moves
    can_short = False              # spot, long-only
    RISK_EXECUTOR = "swing"        # third disjoint order process in the global exposure ledger
    DEFAULT_FAMILY = "bb_squeeze"  # per-pair override comes from the registry

    # Cost-aware stop: a wide-spread swing pair pays ~1.1-1.3% round trip, so the stop is
    # set well beyond cost (6%) and the families target multi-% moves. Per-pair stoploss
    # overrides live in the registry and are enforced by the sizing layer (max_loss / stop).
    stoploss = -0.06
    trailing_stop = False
    minimal_roi = {"0": 1.0}       # disabled; exits are signal/stop driven
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    # ~16 days of 1h history — converges BB(20) + the 100-bar squeeze quantile and EMA55/ADX.
    startup_candle_count = 400

    @property
    def protections(self):
        """Swing-appropriate protection windows (candles are 1h here)."""
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},           # 4h
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 168,                                  # 1 week
                "trade_limit": 5,
                "stop_duration_candles": 12,                                     # 12h
                "max_allowed_drawdown": 0.12,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,                                   # 2 days
                "trade_limit": 2,
                "stop_duration_candles": 24,                                     # 1 day
                "only_per_pair": True,
            },
        ]
