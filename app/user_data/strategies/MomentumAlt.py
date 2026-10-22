"""UnboundBot — experimental intraday executor for the LIVE-STRICT alt pairs (fast bot).

Owner directive 2026-10-21: the experimental alts should buy/sell *fast* and
*strategically* on a SEPARATE, DISJOINT order process from the BTC daily baseline, so
decisions form up to every 5 minutes instead of once per day. BTC's baseline stays
untouched on the 1d daily executor.

As of the multi-strategy expansion this class is a thin 5m binding of the shared
``FamilyDispatcher``: it inherits the independent, fail-closed risk layer verbatim from
PaperAutonomous (``custom_stake_amount`` + ``confirm_trade_entry``) and routes EACH pair
to its assigned ``strategy_family`` (momentum_ema_vol by default; a pair may be assigned
link_trend, rsi_divergence, or bb_squeeze in app/configs/strategy_registry.json). The
signal math lives in app/indicators/families.py; nothing here changes BTC.

Default family signal (documented as EXPERIMENTAL, not profit-proven):
  * BUY  on a *fresh* cross of the fast EMA above the slow EMA, confirmed by a volume
          surge (current volume above its rolling mean) on a completed 5m candle.
  * EXIT on a fresh cross of the fast EMA back below the slow EMA, or the -3% stop.

Fresh-cross (not "already above") prevents duplicate/chasing entries the same way the
daily baseline does. Spot, long-only, unleveraged, PAPER ONLY.
"""
from __future__ import annotations

from FamilyDispatcher import FamilyDispatcher  # noqa: E402


class MomentumAlt(FamilyDispatcher):
    INTERFACE_VERSION = 3
    timeframe = "5m"               # intraday cadence; BTC's daily bot is a separate process
    can_short = False              # spot, long-only
    RISK_EXECUTOR = "fast"         # account for the daily/swing executors' stake in the global cap
    DEFAULT_FAMILY = "momentum_ema_vol"

    # Tight intraday stop; combined with the bounded per-alt stake this keeps the planned
    # loss well under the per-pair max_planned_loss_usd cap. Per-pair stoploss overrides
    # live in the registry and are enforced by the sizing layer (max_loss / stop).
    stoploss = -0.03
    trailing_stop = False
    minimal_roi = {"0": 1.0}       # disabled; exits are signal/stop driven
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    # ~16h of 5m history — converges EMA21 + vol-MA20 (and the 55/100-window families)
    # well within warm-up.
    startup_candle_count = 200

    @property
    def protections(self):
        """Intraday-appropriate protection windows (candles are 5m here, not 1d)."""
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},          # 10 min
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 288,                                 # 24h
                "trade_limit": 5,
                "stop_duration_candles": 12,                                    # 1h
                "max_allowed_drawdown": 0.10,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,                                  # 4h
                "trade_limit": 2,
                "stop_duration_candles": 24,                                    # 2h
                "only_per_pair": True,
            },
        ]
