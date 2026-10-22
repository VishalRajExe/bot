"""UnboundBot — RESEARCH-only backtest strategy (NOT wired to any live executor).

Phase C of the owner-approved multi-asset plan needs to measure the *signal quality*
of each candidate family per pair on the public Binance USDT proxy, because Freqtrade
2026.9 cannot backtest against Alpaca (its private market-metadata load fails offline)
and the production veto (``PaperAutonomous.confirm_trade_entry``) fail-closes outside
live operation (it needs a fresh broker equity snapshot + the cross-executor exposure
ledger that only the running monitor produces). A backtest must therefore exercise the
PURE family math, not the order-safety layer.

This class binds the exact same causal signal functions the live ``FamilyDispatcher``
routes to (app/indicators/families.py) but WITHOUT the registry/veto, so it runs on
``/USDT`` proxy pairs at any timeframe. It is a RESEARCH PROXY for expectancy ranking
only — it is never a trading strategy and never places orders. Which family wins per
pair is fed back into app/configs/strategy_registry.json by the Phase C report step.

Family + timeframe are chosen at import from env so one file drives the whole matrix:
  UNBOUND_RESEARCH_FAMILY   momentum_ema_vol | rsi_divergence | bb_squeeze | link_trend
  UNBOUND_RESEARCH_TF       1d | 1h | 5m      (default 1d)
  UNBOUND_RESEARCH_STOP     stoploss fraction, positive (default 0.10)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

from freqtrade.strategy import IStrategy

# Make the app-level indicator library importable regardless of Freqtrade's cwd/userdir.
_APP = Path(__file__).resolve().parents[2]              # D:\BOT\app
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
from indicators import families  # noqa: E402


class ResearchFamily(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = os.environ.get("UNBOUND_RESEARCH_TF", "1d")

    # RESEARCH family (registry-independent; uses the family's own default params).
    FAMILY = os.environ.get("UNBOUND_RESEARCH_FAMILY", "momentum_ema_vol")
    _stop = abs(float(os.environ.get("UNBOUND_RESEARCH_STOP", "0.10")))
    stoploss = -_stop
    trailing_stop = False
    minimal_roi = {"0": 1.0}          # disabled — exits are signal/stop driven
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    # Enough warm-up for the widest windows used across families (100-bar squeeze
    # quantile + EMA55 + ADX14) so signals are valid immediately after the timerange start.
    startup_candle_count = 500

    def _params(self) -> dict:
        return families.params_for(self.FAMILY, {})

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        return families.add_indicators(dataframe, self.FAMILY, self._params())

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        mask = families.entry_mask(dataframe, self.FAMILY, self._params())
        dataframe.loc[mask, "enter_long"] = 1
        if mask.any():
            dataframe.loc[mask, "enter_tag"] = families.tags(self.FAMILY)[0]
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        mask = families.exit_mask(dataframe, self.FAMILY, self._params())
        dataframe.loc[mask, "exit_long"] = 1
        if mask.any():
            dataframe.loc[mask, "exit_tag"] = families.tags(self.FAMILY)[1]
        return dataframe
