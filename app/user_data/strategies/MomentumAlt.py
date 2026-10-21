"""UnboundBot â€” experimental intraday momentum strategy for the alt pairs (fast executor).

Owner directive 2026-10-21: the experimental alts (ETH/XRP/DOT/LINK) should buy/sell
*fast* and *strategically*. This runs a SECOND, DISJOINT order process on a 5-minute
candle so decisions form up to every 5 minutes instead of once per day, while the BTC
baseline stays untouched on the 1d daily executor.

It subclasses PaperAutonomous ONLY to reuse the independent, fail-closed risk layer
verbatim â€” ``custom_stake_amount`` (bounded per-alt sizing) and ``confirm_trade_entry``
(short reject, tradeable check, kill switch, per-position cap, fresh-equity gate, and
the GLOBAL exposure cap that also counts the daily executor's open stake via the
cross-executor ledger). The signal logic is fully overridden; nothing here changes BTC.

Signal (documented as EXPERIMENTAL, not profit-proven):
  * BUY  on a *fresh* cross of the fast EMA above the slow EMA, confirmed by a volume
          surge (current volume above its rolling mean) on a completed 5m candle.
  * EXIT on a fresh cross of the fast EMA back below the slow EMA, or the -3% stop.

Fresh-cross (not "already above") is deliberate: it prevents duplicate/chasing entries
the same way the daily baseline does. Spot, long-only, unleveraged, PAPER ONLY.
"""
from __future__ import annotations

from datetime import datetime  # noqa: F401

import pandas as pd  # noqa: F401
import talib

# Importing PaperAutonomous first installs the app/ path onto sys.path (it does that at
# module load), so the shared risk layer is importable here too. We reuse its veto via
# the base class; `policy` is referenced directly (module global), matching the base.
from PaperAutonomous import PaperAutonomous  # noqa: E402
from risk import policy  # noqa: E402


class MomentumAlt(PaperAutonomous):
    INTERFACE_VERSION = 3
    timeframe = "5m"               # intraday cadence; BTC's daily bot is a separate process
    can_short = False              # spot, long-only
    RISK_EXECUTOR = "fast"         # account for the daily executor's stake in the global cap

    # Momentum parameters (defaults; overridden per-pair from strategy_registry.json).
    _EMA_FAST_DEFAULT = 9
    _EMA_SLOW_DEFAULT = 21
    _VOL_WINDOW_DEFAULT = 20

    # Tighter intraday stop than the daily baseline; combined with the 1000 stake this
    # bounds planned loss to ~30 USD, well under the 500 max_planned_loss_usd cap.
    stoploss = -0.03
    trailing_stop = False
    minimal_roi = {"0": 1.0}       # disabled; exits are signal/stop driven
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    # ~16h of 5m history â€” converges EMA21 + vol-MA20 well within warm-up.
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

    def _momentum_params(self, pair: str) -> tuple[int, int, int]:
        m = policy.pair_entry(pair).get("risk", {}).get("momentum", {})
        return (int(m.get("ema_fast", self._EMA_FAST_DEFAULT)),
                int(m.get("ema_slow", self._EMA_SLOW_DEFAULT)),
                int(m.get("vol_window", self._VOL_WINDOW_DEFAULT)))

    # ---- signals -------------------------------------------------------------
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        fast_p, slow_p, vol_p = self._momentum_params(metadata["pair"])
        dataframe["ema_fast"] = talib.EMA(dataframe["close"], timeperiod=fast_p)
        dataframe["ema_slow"] = talib.EMA(dataframe["close"], timeperiod=slow_p)
        dataframe["vol_ma"] = dataframe["volume"].rolling(window=vol_p).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        # Only the fast-executor's experimental alts trade here; anything else (BTC,
        # status-only, unknown) emits NO entry â€” and confirm_trade_entry still vetoes.
        if not policy.is_tradeable(pair) or self._is_baseline(pair):
            dataframe["enter_long"] = 0
            return dataframe
        fast_p, slow_p, _ = self._momentum_params(pair)
        f, s = dataframe["ema_fast"], dataframe["ema_slow"]
        prev_f, prev_s = f.shift(1), s.shift(1)
        vol_surge = dataframe["volume"] > dataframe["vol_ma"]
        cross_up = (f > s) & (prev_f <= prev_s) & vol_surge & (dataframe["volume"] > 0)
        cross_up = cross_up.fillna(False)
        dataframe.loc[cross_up, "enter_long"] = 1
        if cross_up.any():
            dataframe.loc[cross_up, "enter_tag"] = (
                f"EXPERIMENTAL mom ema{fast_p}x{slow_p} cross-up + vol surge"
            )
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if not policy.is_tradeable(pair) or self._is_baseline(pair):
            dataframe["exit_long"] = 0
            return dataframe
        fast_p, slow_p, _ = self._momentum_params(pair)
        f, s = dataframe["ema_fast"], dataframe["ema_slow"]
        prev_f, prev_s = f.shift(1), s.shift(1)
        cross_dn = (f < s) & (prev_f >= prev_s)
        cross_dn = cross_dn.fillna(False)
        dataframe.loc[cross_dn, "exit_long"] = 1
        if cross_dn.any():
            dataframe.loc[cross_dn, "exit_tag"] = f"EXPERIMENTAL mom ema{fast_p}x{slow_p} cross-down"
        return dataframe
