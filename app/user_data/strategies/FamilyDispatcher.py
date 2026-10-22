"""UnboundBot — timeframe executor that routes each pair to its registry strategy family.

Freqtrade runs ONE strategy class per process, so "a different best strategy per
crypto" is realized by *dispatch*, not by spawning a process per strategy. This base
class:

  * inherits the independent, fail-closed risk layer VERBATIM from PaperAutonomous
    (``custom_stake_amount`` + ``confirm_trade_entry`` are NOT overridden here, so the
    identity "MomentumAlt.confirm_trade_entry is PaperAutonomous.confirm_trade_entry"
    still holds and there is exactly one source of truth for the veto);
  * for each pair, looks up its ``strategy_family`` in app/configs/strategy_registry.json
    and delegates the indicator/entry/exit math to the pure, causal functions in
    app/indicators/families.py;
  * emits NO signals for the BTC baseline (owned by the daily executor), for
    status-only/unsupported pairs, and for any family it does not implement — the
    entry veto still rejects anything that slips through.

Subclasses pin the timeframe, the RISK_EXECUTOR ledger id, the per-executor stoploss
floor, protections, and startup warm-up. The BTC baseline math is never touched here.
"""
from __future__ import annotations

import pandas as pd  # noqa: F401  (used by freqtrade typing)

# Importing PaperAutonomous first installs the app/ path onto sys.path (it does that at
# module load), so the shared risk + indicator packages are importable here too.
from PaperAutonomous import PaperAutonomous  # noqa: E402
from risk import policy  # noqa: E402
from indicators import families  # noqa: E402


class FamilyDispatcher(PaperAutonomous):
    INTERFACE_VERSION = 3
    can_short = False                 # spot, long-only, unleveraged

    # Subclasses set the timeframe / RISK_EXECUTOR / startup warm-up / stoploss floor.
    DEFAULT_FAMILY = "momentum_ema_vol"

    # ---- per-pair family resolution -----------------------------------------
    def _family(self, pair: str) -> str | None:
        fam = policy.pair_entry(pair).get("strategy_family")
        return fam if fam in families.FAMILIES else None

    def _params(self, pair: str) -> dict:
        fam = self._family(pair)
        if fam is None:
            return {}
        return families.params_for(fam, policy.pair_entry(pair).get("risk", {}))

    def _gated_out(self, pair: str) -> bool:
        """True when this dispatcher must emit no signals for ``pair``: unsupported /
        status-only, the BTC baseline (owned by the daily executor), or an unknown family."""
        return (not policy.is_tradeable(pair)) or self._is_baseline(pair) or (self._family(pair) is None)

    # ---- signals -------------------------------------------------------------
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if self._gated_out(pair):
            return dataframe
        return families.add_indicators(dataframe, self._family(pair), self._params(pair))

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if self._gated_out(pair):
            dataframe["enter_long"] = 0
            return dataframe
        fam = self._family(pair)
        mask = families.entry_mask(dataframe, fam, self._params(pair))
        dataframe.loc[mask, "enter_long"] = 1
        if mask.any():
            dataframe.loc[mask, "enter_tag"] = families.tags(fam)[0]
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if self._gated_out(pair):
            dataframe["exit_long"] = 0
            return dataframe
        fam = self._family(pair)
        mask = families.exit_mask(dataframe, fam, self._params(pair))
        dataframe.loc[mask, "exit_long"] = 1
        if mask.any():
            dataframe.loc[mask, "exit_tag"] = families.tags(fam)[1]
        return dataframe
