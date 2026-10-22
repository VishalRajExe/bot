"""UnboundBot shared indicator/strategy-family library.

This package holds the *pure, causal* signal math for every strategy family the
executors can route a pair to (see app/configs/strategy_registry.json ->
``strategy_family``). Freqtrade runs ONE strategy class per process, so a single
timeframe executor (fast 5m / swing 1h) dispatches each pair to its assigned
family here rather than spawning a process per strategy. Keeping the math in pure
functions makes it unit-testable on synthetic frames without a bot or network.

Hard rules for every function in this package:
  * CAUSAL / forward-only: only ``shift(+n)`` (past) and backward-looking
    ``rolling`` windows are allowed. No ``center=True``, no negative shifts, no
    future references. Divergence/breakout signals are confirmed on the NEXT bar
    after the pattern completes so the trigger uses only closed-candle data.
  * No side effects: functions take a DataFrame + a plain params dict and return
    a DataFrame (indicators) or a boolean Series (masks). No IO, no policy reads.
  * NaN-safe: warm-up NaNs never evaluate to a signal (masks are ``fillna(False)``
    and cast to bool).

Everything here is EXPERIMENTAL and not profit-proven; a family is only enabled
for live paper trading after a backtest (Phase C) and owner approval.
"""
from __future__ import annotations

from .families import (  # noqa: F401
    FAMILIES,
    add_indicators,
    entry_mask,
    exit_mask,
    params_for,
    tags,
)

__all__ = ["FAMILIES", "add_indicators", "entry_mask", "exit_mask", "params_for", "tags"]
