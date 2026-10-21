"""UnboundBot — single-executor, pair-aware autonomous PAPER dispatcher.

One authoritative strategy for all whitelisted pairs so there is exactly one order
executor (no duplicate competing processes):

  * BTC/USD  -> the *unchanged* BtcZScore baseline (this class subclasses it and
                delegates the BTC branch to ``super()``, so EMA65/STD65/Z-score,
                thresholds, daily timeframe, startup candles, protections, version
                and entry/exit transitions are byte-for-byte the baseline).
  * ETH/XRP/DOT/LINK -> an EXPERIMENTAL daily Z-score paper strategy. Its thresholds
                come from app/configs/strategy_registry.json (NOT silently reused from
                BTC as proof of profitability); it exists to gather forward-test data.
  * anything else (USDT/USD, unsupported, non-whitelisted) -> NO signals, and any
                proposed order is vetoed by ``confirm_trade_entry`` with a reason.

The independent risk layer (app/risk/policy.py) bounds every order: per-pair stake,
per-pair max planned loss, one-position-per-pair, portfolio exposure cap, a persisted
circuit-breaker kill switch, and fail-closed on stale/unknown data. Autonomous !=
unrestricted: valid entries within the policy go through WITHOUT per-trade approval,
but unsafe entries are rejected and explained. PAPER ONLY \u2014 spot, long-only, no
leverage. This class never changes BTC's approved rules and never places live orders.
"""
from __future__ import annotations

import sys
from datetime import datetime  # noqa: F401
from pathlib import Path

import pandas as pd  # noqa: F401  (used by freqtrade typing)

# Make the app-level risk layer importable regardless of Freqtrade's cwd/userdir.
_APP = Path(__file__).resolve().parents[2]          # D:\BOT\app
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
from risk import policy  # noqa: E402

from BtcZScore import BtcZScore  # noqa: E402  (same strategies dir)


class PaperAutonomous(BtcZScore):
    INTERFACE_VERSION = 3
    timeframe = "1d"          # inherited from baseline; explicit for clarity
    can_short = False         # spot, long-only

    # Alt experimental threshold fallback if the registry omits a value (still separate
    # from the BTC baseline constants so the two are never silently coupled).
    _ALT_BULL_DEFAULT = 0.5
    _ALT_EXIT_DEFAULT = 0.0

    def _alt_thresholds(self, pair: str) -> tuple[float, float]:
        risk = policy.pair_entry(pair).get("risk", {})
        return (float(risk.get("bull_threshold", self._ALT_BULL_DEFAULT)),
                float(risk.get("exit_threshold", self._ALT_EXIT_DEFAULT)))

    def _is_baseline(self, pair: str) -> bool:
        return policy.pair_entry(pair).get("status") == "ACTIVE_BASELINE"

    # ---- signals -------------------------------------------------------------
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Baseline indicators (ema65/std65/zscore + BTC cross flags) are identical for
        # every pair; the z-score formula itself is threshold-independent.
        return super().populate_indicators(dataframe, metadata)

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if self._is_baseline(pair):
            return super().populate_entry_trend(dataframe, metadata)  # exact BTC behavior
        if not policy.is_tradeable(pair):
            dataframe["enter_long"] = 0   # status-only/unsupported: column present, no signals
            return dataframe  # no entries ever generated
        bull, _ = self._alt_thresholds(pair)
        z = dataframe["zscore"]
        prev = z.shift(1)
        cross_up = (z >= bull) & (prev < bull) & (dataframe["volume"] > 0)
        dataframe.loc[cross_up, "enter_long"] = 1
        if cross_up.any():
            dataframe.loc[cross_up, "enter_tag"] = (
                f"EXPERIMENTAL alt z_cross_up z=" + dataframe.loc[cross_up, "zscore"].round(3).astype(str)
                + f" >= {bull}"
            )
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata["pair"]
        if self._is_baseline(pair):
            return super().populate_exit_trend(dataframe, metadata)  # exact BTC behavior
        if not policy.is_tradeable(pair):
            dataframe["exit_long"] = 0   # status-only/unsupported: column present, no exits
            return dataframe
        _, exit_th = self._alt_thresholds(pair)
        z = dataframe["zscore"]
        prev = z.shift(1)
        cross_dn = (z <= exit_th) & (prev > exit_th)
        dataframe.loc[cross_dn, "exit_long"] = 1
        if cross_dn.any():
            dataframe.loc[cross_dn, "exit_tag"] = (
                f"EXPERIMENTAL alt z_cross_dn z=" + dataframe.loc[cross_dn, "zscore"].round(3).astype(str)
                + f" <= {exit_th}"
            )
        return dataframe

    # ---- independent risk sizing --------------------------------------------
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None,
                            max_stake: float, leverage: float, **kwargs) -> float:
        stake = policy.stake_for_pair(pair, proposed_stake)
        if stake is None:
            # risk cannot be computed -> make it tiny so nothing sensible is bought;
            # confirm_trade_entry still rejects + explains.
            return 0.0
        if max_stake is not None:
            stake = min(stake, max_stake)
        return float(stake)

    # ---- automatic entry veto (fail-closed) ---------------------------------
    def _reject(self, pair: str, code: str, msg: str, ctx: dict) -> bool:
        policy.log_rejection(pair, code, msg, ctx)
        return False

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs) -> bool:
        ctx = {"amount": amount, "rate": rate, "side": side, "order_type": order_type}
        # 1. spot, long-only.
        if side != "long":
            return self._reject(pair, "SHORT_NOT_ALLOWED", "spot-only system rejects non-long entries", ctx)
        # 2. pair must be tradeable per registry.
        if not policy.is_tradeable(pair):
            return self._reject(pair, "UNSUPPORTED_PAIR", "pair not enabled for trading (status-only/unknown)", ctx)
        # 3. circuit breaker / kill switch.
        blocked = policy.is_blocked()
        if blocked["blocked"]:
            return self._reject(pair, "CIRCUIT_BREAKER_ACTIVE", f"entries blocked: {blocked['reason']}", ctx)
        # 4. risk must be computable.
        cap = policy.max_stake_usd(pair)
        if cap is None:
            return self._reject(pair, "RISK_UNCALCULABLE", "no bounded stake cap for pair", ctx)
        notional = float(amount) * float(rate)
        # 5. per-position cap (defence-in-depth over custom_stake).
        if notional > cap * 1.05 + 1e-6:
            ctx["cap"] = cap
            return self._reject(pair, "PER_POSITION_CAP", f"notional {notional:.2f} > per-position cap {cap:.2f}", ctx)
        # 6. equity snapshot (fresh) required for the exposure cap -> fail-closed.
        eq = policy.get_equity()
        equity = eq.get("equity")
        if not eq or eq.get("_stale") or equity is None:
            return self._reject(pair, "STALE_OR_UNKNOWN_EQUITY", "cannot size portfolio exposure without a fresh equity snapshot", ctx)
        # 7. one position per pair + no unresolved open trade for the pair.
        from freqtrade.persistence import Trade
        opens = Trade.get_trades_proxy(is_open=True)
        if any(t.pair == pair for t in opens):
            return self._reject(pair, "DUPLICATE_OR_UNRESOLVED", "an open position/order already exists for this pair", ctx)
        open_stake = sum(float(t.stake_amount or 0) for t in opens)
        # 8. portfolio exposure cap.
        if policy.would_breach_exposure(open_stake, notional, equity):
            ctx.update({"open_stake": open_stake, "exposure_cap": policy.exposure_cap_usd(equity)})
            return self._reject(pair, "EXPOSURE_CAP", "adding this position would exceed the portfolio exposure cap", ctx)
        # all automated checks pass -> submit the paper order without manual approval
        return True
