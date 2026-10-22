"""Strategy-family signal math (pure, causal, no side effects).

Each family is a bundle of ``add_indicators`` / ``entry`` / ``exit`` callables that
operate on a Freqtrade-shaped OHLCV DataFrame (columns: open/high/low/close/volume,
DatetimeIndex or a 'date' column) plus a plain ``params`` dict. The timeframe
dispatchers (fast 5m, swing 1h) look up a pair's family from the strategy registry
and call these; the risk veto/sizing still lives in PaperAutonomous and is inherited
verbatim.

CAUSAL CONTRACT: only backward-looking windows and ``shift(+n)`` are used. Pattern
triggers (divergence, squeeze-breakout) are evaluated on the bar AFTER the pattern
completes (``.shift(1)``), so a signal at bar t uses only data up to bar t-1 plus the
close of bar t. Masks are ``fillna(False)`` and cast to bool so warm-up NaNs never
fire. All families are EXPERIMENTAL and not profit-proven until backtested.

Families implemented:
  * momentum_ema_vol  - fast/slow EMA cross-up confirmed by a volume surge (existing alt logic).
  * rsi_divergence    - bullish price/RSI divergence at oversold, confirmed by an up-close.
  * bb_squeeze        - Bollinger bandwidth squeeze then an upside breakout on volume.
  * link_trend        - EMA trend + ADX regime + RSI pullback-continuation (improved LINK).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd
import talib

# --------------------------------------------------------------------------- helpers


def _num(params: dict, key: str, default: float) -> float:
    v = (params or {}).get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _int(params: dict, key: str, default: int) -> int:
    return int(_num(params, key, default))


def _bool(mask: pd.Series) -> pd.Series:
    """NaN-safe boolean mask (warm-up NaN -> False)."""
    return mask.fillna(False).astype(bool)


# ------------------------------------------------------------------- momentum_ema_vol


def _mom_ind(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    f, s, w = _int(p, "ema_fast", 9), _int(p, "ema_slow", 21), _int(p, "vol_window", 20)
    df["ema_fast"] = talib.EMA(df["close"], timeperiod=f)
    df["ema_slow"] = talib.EMA(df["close"], timeperiod=s)
    df["vol_ma"] = df["volume"].rolling(window=w, min_periods=w).mean()
    return df


def _mom_entry(df: pd.DataFrame, p: dict) -> pd.Series:
    f, s = df["ema_fast"], df["ema_slow"]
    vol_surge = df["volume"] > df["vol_ma"]
    cross_up = (f > s) & (f.shift(1) <= s.shift(1)) & vol_surge & (df["volume"] > 0)
    return _bool(cross_up)


def _mom_exit(df: pd.DataFrame, p: dict) -> pd.Series:
    f, s = df["ema_fast"], df["ema_slow"]
    cross_dn = (f < s) & (f.shift(1) >= s.shift(1))
    return _bool(cross_dn)


# --------------------------------------------------------------------- rsi_divergence


def _rsidiv_ind(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    period, lb = _int(p, "rsi_period", 14), _int(p, "lookback", 20)
    df["rsi"] = talib.RSI(df["close"], timeperiod=period)
    # A new `lookback`-bar low in price vs a HIGHER RSI than `lookback` bars ago is a
    # bullish divergence (sellers pushed price down but momentum did not confirm).
    prior_low = df["low"].rolling(window=lb, min_periods=lb).min().shift(1)
    df["price_new_low"] = df["low"] <= prior_low
    df["rsi_higher"] = df["rsi"] > df["rsi"].shift(lb)
    prior_high = df["high"].rolling(window=lb, min_periods=lb).max().shift(1)
    df["price_new_high"] = df["high"] >= prior_high
    df["rsi_lower"] = df["rsi"] < df["rsi"].shift(lb)
    return df


def _rsidiv_entry(df: pd.DataFrame, p: dict) -> pd.Series:
    oversold = _num(p, "rsi_oversold", 35.0)
    bull_div = df["price_new_low"] & df["rsi_higher"] & (df["rsi"] < oversold)
    # Confirm on the NEXT bar with an up-close so we do not catch a falling knife.
    confirm = df["close"] > df["close"].shift(1)
    return _bool(bull_div.shift(1) & confirm & (df["volume"] > 0))


def _rsidiv_exit(df: pd.DataFrame, p: dict) -> pd.Series:
    overbought = _num(p, "rsi_overbought", 70.0)
    bear_div = df["price_new_high"] & df["rsi_lower"] & (df["rsi"] > overbought)
    return _bool((df["rsi"] >= overbought) | bear_div.shift(1))


# ------------------------------------------------------------------------- bb_squeeze


def _bbsq_ind(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    period, std = _int(p, "bb_period", 20), _num(p, "bb_std", 2.0)
    sq_lb, sq_pct = _int(p, "squeeze_lookback", 100), _num(p, "squeeze_pct", 0.20)
    vol_w = _int(p, "vol_window", 20)
    upper, middle, lower = talib.BBANDS(df["close"], timeperiod=period, nbdevup=std, nbdevdn=std)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = upper, middle, lower
    bandwidth = (upper - lower) / middle.replace(0.0, pd.NA)
    df["bb_width"] = bandwidth
    # A squeeze = bandwidth in its lowest `squeeze_pct` quantile over `squeeze_lookback`.
    df["bb_squeeze"] = bandwidth <= bandwidth.rolling(window=sq_lb, min_periods=sq_lb).quantile(sq_pct)
    df["vol_ma"] = df["volume"].rolling(window=vol_w, min_periods=vol_w).mean()
    return df


def _bbsq_entry(df: pd.DataFrame, p: dict) -> pd.Series:
    vol_surge = df["volume"] > df["vol_ma"]
    # Prior bar was squeezed AND this bar closes above the upper band on a volume surge.
    breakout = df["bb_squeeze"].shift(1) & (df["close"] > df["bb_upper"]) & vol_surge & (df["volume"] > 0)
    return _bool(breakout)


def _bbsq_exit(df: pd.DataFrame, p: dict) -> pd.Series:
    return _bool(df["close"] < df["bb_mid"])


# -------------------------------------------------------------------------- link_trend


def _link_ind(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    f, s = _int(p, "ema_fast", 21), _int(p, "ema_slow", 55)
    rsi_p, adx_p = _int(p, "rsi_period", 14), _int(p, "adx_period", 14)
    df["ema_fast"] = talib.EMA(df["close"], timeperiod=f)
    df["ema_slow"] = talib.EMA(df["close"], timeperiod=s)
    df["rsi"] = talib.RSI(df["close"], timeperiod=rsi_p)
    df["adx"] = talib.ADX(df["high"], df["low"], df["close"], timeperiod=adx_p)
    df["atr"] = talib.ATR(df["high"], df["low"], df["close"], timeperiod=_int(p, "atr_period", 14))
    return df


def _link_entry(df: pd.DataFrame, p: dict) -> pd.Series:
    adx_min, rsi_buy = _num(p, "adx_min", 20.0), _num(p, "rsi_buy", 50.0)
    uptrend = df["ema_fast"] > df["ema_slow"]
    strong = df["adx"] > adx_min
    rsi_cross_up = (df["rsi"] >= rsi_buy) & (df["rsi"].shift(1) < rsi_buy)
    return _bool(uptrend & strong & rsi_cross_up & (df["volume"] > 0))


def _link_exit(df: pd.DataFrame, p: dict) -> pd.Series:
    rsi_exit = _num(p, "rsi_exit", 70.0)
    trend_break = df["ema_fast"] < df["ema_slow"]
    return _bool(trend_break | (df["rsi"] >= rsi_exit))


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class FamilySpec:
    """One strategy family: its indicator builder, entry/exit masks, tags, and the
    registry key its params live under (``risk[param_key]``)."""
    name: str
    param_key: str
    indicators: Callable[[pd.DataFrame, dict], pd.DataFrame]
    entry: Callable[[pd.DataFrame, dict], pd.Series]
    exit: Callable[[pd.DataFrame, dict], pd.Series]
    entry_tag: str
    exit_tag: str
    defaults: dict


FAMILIES: dict[str, FamilySpec] = {
    "momentum_ema_vol": FamilySpec(
        "momentum_ema_vol", "momentum", _mom_ind, _mom_entry, _mom_exit,
        "EXPERIMENTAL momentum ema cross-up + vol surge",
        "EXPERIMENTAL momentum ema cross-down",
        {"ema_fast": 9, "ema_slow": 21, "vol_window": 20},
    ),
    "rsi_divergence": FamilySpec(
        "rsi_divergence", "rsi_divergence", _rsidiv_ind, _rsidiv_entry, _rsidiv_exit,
        "EXPERIMENTAL rsi bullish divergence (confirmed)",
        "EXPERIMENTAL rsi overbought / bearish divergence",
        {"rsi_period": 14, "lookback": 20, "rsi_oversold": 35.0, "rsi_overbought": 70.0},
    ),
    "bb_squeeze": FamilySpec(
        "bb_squeeze", "bb_squeeze", _bbsq_ind, _bbsq_entry, _bbsq_exit,
        "EXPERIMENTAL bb squeeze breakout (vol-confirmed)",
        "EXPERIMENTAL bb close below mid",
        {"bb_period": 20, "bb_std": 2.0, "squeeze_lookback": 100, "squeeze_pct": 0.20, "vol_window": 20},
    ),
    "link_trend": FamilySpec(
        "link_trend", "link_trend", _link_ind, _link_entry, _link_exit,
        "EXPERIMENTAL link ema-trend + adx + rsi continuation",
        "EXPERIMENTAL link trend-break / rsi overbought",
        {"ema_fast": 21, "ema_slow": 55, "rsi_period": 14, "adx_period": 14,
         "atr_period": 14, "adx_min": 20.0, "rsi_buy": 50.0, "rsi_exit": 70.0},
    ),
}


def params_for(family: str, risk: dict) -> dict:
    """Merge a family's defaults with the registry-provided overrides.

    Registry params live under ``risk[param_key]`` (e.g. ``risk['momentum']`` for the
    momentum family, ``risk['bb_squeeze']`` for the squeeze family). Missing keys fall
    back to the family defaults so a partially-specified pair still runs deterministically.
    """
    spec = FAMILIES.get(family)
    if spec is None:
        return {}
    merged = dict(spec.defaults)
    override = (risk or {}).get(spec.param_key)
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _spec(family: str) -> FamilySpec | None:
    return FAMILIES.get(family)


def add_indicators(df: pd.DataFrame, family: str, params: dict) -> pd.DataFrame:
    spec = _spec(family)
    if spec is None:
        return df
    return spec.indicators(df, params or {})


def entry_mask(df: pd.DataFrame, family: str, params: dict) -> pd.Series:
    spec = _spec(family)
    if spec is None:
        return pd.Series(False, index=df.index)
    return _bool(spec.entry(df, params or {}))


def exit_mask(df: pd.DataFrame, family: str, params: dict) -> pd.Series:
    spec = _spec(family)
    if spec is None:
        return pd.Series(False, index=df.index)
    return _bool(spec.exit(df, params or {}))


def tags(family: str) -> tuple[str, str]:
    spec = _spec(family)
    if spec is None:
        return ("", "")
    return (spec.entry_tag, spec.exit_tag)
