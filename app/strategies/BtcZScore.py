"""UnboundBot — BTC daily Z-score trend strategy.

Derived from `strategy.txt` "Dual Signal Trend Sentinel" (public description):
    Z = (close - EMA65) / STDDEV65   over daily BTC candles.

IMPORTANT (see docs/Phase0_Audit.md sec.6):
  * The source did NOT publish the bull/bear thresholds. The values below are
    clearly-labeled CANDIDATE defaults, NOT source-verified. They are exposed as
    strategy parameters so they can be tuned by backtest and approved by the owner.
  * The "dual signal" second component is unavailable (protected source); only the
    documented Z-score signal is implemented here.
  * Long-only, spot, unleveraged. No shorts, no borrowing.
"""
from datetime import datetime

import talib
from freqtrade.strategy import IStrategy
import pandas as pd  # noqa: F401  (used by freqtrade typing)


class BtcZScore(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False  # spot, long-only

    # Candidate thresholds — NOT source-verified. Plain floats so they are usable
    # directly in vectorized comparisons. Tuned via backtest, owner-approved.
    bull_threshold: float = 0.5
    exit_threshold: float = 0.0

    zscore_period = 65

    # Risk: simple trailing stop as a floor; primary exit is signal-driven.
    stoploss = -0.35
    trailing_stop = False

    minimal_roi = {"0": 1.0}  # effectively disabled; exits are signal-driven
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    process_only_new_candles = True
    startup_candle_count = zscore_period + 5

    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    @property
    def protections(self):
        """Phase 5 independent risk layer (candidate limits, owner-approved).
        Config-level protections are deprecated in Freqtrade 2026.9, so they live here.
        """
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 90,
                "trade_limit": 5,
                "stop_duration_candles": 7,
                "max_allowed_drawdown": 0.25,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 30,
                "trade_limit": 3,
                "stop_duration_candles": 14,
                "only_per_pair": True,
            },
        ]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        ema = talib.EMA(dataframe["close"], timeperiod=self.zscore_period)
        std = dataframe["close"].rolling(window=self.zscore_period).std(ddof=0)
        # Guard against divide-by-zero / warmup NaN.
        std = std.replace(0.0, pd.NA)
        dataframe["ema65"] = ema
        dataframe["std65"] = std
        dataframe["zscore"] = (dataframe["close"] - ema) / std
        prev_z = dataframe["zscore"].shift(1)
        dataframe["z_cross_up"] = (dataframe["zscore"] >= self.bull_threshold) & (prev_z < self.bull_threshold)
        dataframe["z_cross_dn"] = (dataframe["zscore"] <= self.exit_threshold) & (prev_z > self.exit_threshold)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["z_cross_up"] == 1) & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["z_cross_dn"] == 1),
            "exit_long",
        ] = 1
        return dataframe
