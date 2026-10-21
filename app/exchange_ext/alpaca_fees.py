"""Gated, fail-closed correction for a verified Alpaca PAPER accounting gap.

WHY THIS EXISTS (ground truth captured 2026-10-21 against the live paper account):
Alpaca charges crypto trading fees **net of position** — a market BUY of N base
coins credits the wallet with N minus the fee. Observed on DOT/USD: a MARKET_BUY
filled ``42.74856151`` DOT but only ``42.641690106`` DOT landed in the wallet
(~0.25% taken in base). Alpaca does **not** report this fee anywhere Freqtrade can
see it: ``fetch_order`` has no ``commission`` and ``fetch_my_trades`` returns
``fee={'cost': None, 'currency': None}`` with no ``fee_paid`` on the raw activity.

Freqtrade only shrinks a trade's recorded ``amount`` when it is *told* the fee in
base currency (``get_real_amount`` -> ``apply_fee_conditional`` -> sets the order's
``ft_fee_base``, which ``Trade.recalc_trade_from_orders`` applies via
``safe_amount_after_fee``). Because the fee is unreported, Freqtrade keeps the GROSS
filled amount (42.748). On the first full exit it sells the wallet (net) amount
(42.641), but ``recalc`` then recomputes the open balance from the *order fills*
(gross buy - net sell = 0.107 DOT), leaving a sub-fee base residual that is smaller
than the exchange minimum and can never be sold. The trade is stuck open forever and
reconciliation flips to a perpetual "falling back to wallet-amount" thrash.

WHAT THIS DOES: inject the single missing value Freqtrade needs — the base-currency
fee — derived from the broker's OWN wallet balance (the only place it is observable).
It returns that value from the existing ``get_real_amount`` seam so Freqtrade's
already-tested base-fee path records the *net credited* amount, after which a
wallet-sized exit closes the trade cleanly. No engine source is modified: this
monkeypatches the method at runtime from our thin layer; removing the import in
PaperAutonomous restores stock behavior byte-for-byte.

SAFETY (fail-closed, minimal blast radius):
  * Applies ONLY when the resolved exchange name is ``alpaca`` AND trading_mode is
    ``spot`` (gates on OUR config, not ccxt naming). Everything else is untouched.
  * Applies ONLY to entry/buy fills whose wallet reveals a *smaller* base holding
    than the recorded fill (a genuine base fee). Never enlarges a position.
  * Rejects implausible fees: the derived fee-rate must lie in ``(0, MAX_FEE_RATE]``
    (2%). Outside that band it leaves the trade untouched (stock behavior) and logs
    for reconcile/human review rather than mis-state the position.
  * Any unexpected error inside the patch returns the stock result; it never blocks
    or corrupts the normal fee path.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Beyond this, "fee taken from base" is not a plausible trade fee -> fail-closed.
MAX_FEE_RATE = 0.02

_PATCHED_ATTR = "_unboundbot_alpaca_fee_patch"
_EXCHANGE_NAME = "alpaca"


def _is_alpaca_spot(config: dict) -> bool:
    """Gate strictly on OUR configured exchange name + spot mode."""
    if not isinstance(config, dict):
        return False
    name = str((config.get("exchange") or {}).get("name", "")).lower()
    mode = str(config.get("trading_mode", "spot")).lower()
    return name == _EXCHANGE_NAME and mode == "spot"


def derive_base_fee(
    *,
    alpaca_spot: bool,
    is_entry_side: bool,
    order_open: bool,
    filled: float,
    wallet_held: float,
) -> tuple[float | None, str]:
    """Pure, hermetically testable core of the correction.

    Returns ``(fee_in_base_or_None, reason)``. ``fee_in_base`` is the amount by which
    the recorded buy fill exceeds the coins actually credited — the value Freqtrade
    needs to reduce ``trade.amount`` to the net position.

    Fail-closed to ``None`` (leave the trade as stock Freqtrade recorded it) for any
    non-applicable or implausible case.
    """
    if not alpaca_spot:
        return None, "not-alpaca-spot"
    if not is_entry_side:
        return None, "not-entry-side"
    if order_open:
        return None, "order-still-open"
    if not filled or filled <= 0:
        return None, "no-filled-amount"

    shortfall = filled - wallet_held
    if shortfall <= 0:
        # Wallet holds at least the recorded fill: no base fee to apply.
        return None, "wallet-covers-fill"

    rate = shortfall / filled
    if rate > MAX_FEE_RATE:
        return None, f"implausible-fee-rate-{round(rate, 6)}"

    return round(shortfall, 12), f"base-fee-rate-{round(rate, 6)}"


def install() -> None:
    """Register the runtime patch on FreqtradeBot.get_real_amount (idempotent).

    Imported by PaperAutonomous (and therefore the MomentumAlt fast executor that
    subclasses it), so it is active inside both PAPER order-executor processes before
    any fill is processed. Method lookup is dynamic, so patching the class method
    takes effect on the already-constructed bot/exchange instances.
    """
    from freqtrade.freqtradebot import FreqtradeBot

    if getattr(FreqtradeBot, _PATCHED_ATTR, False):
        return  # already installed

    original = FreqtradeBot.get_real_amount

    def get_real_amount(self: Any, trade: Any, order: dict, order_obj: Any) -> float | None:
        # 1) Let stock Freqtrade try first (handles exchanges that DO report the fee).
        fee_abs = original(self, trade, order, order_obj)
        if fee_abs is not None:
            return fee_abs

        # 2) Alpaca fallback: the fee is unreported, so derive it from the wallet.
        try:
            # FreqtradeBot exposes `self.config`; keep `self._config` as a defensive
            # fallback in case this is ever applied to an object that uses the other name.
            config = getattr(self, "config", None) or getattr(self, "_config", None)
            base = self.exchange.get_pair_base_currency(trade.pair)
            self.wallets.update()
            wallet_held = self.wallets.get_free(base) + self.wallets.get_used(base)
            fee, reason = derive_base_fee(
                alpaca_spot=_is_alpaca_spot(config),
                is_entry_side=order_obj.ft_order_side == trade.entry_side,
                order_open=str(order.get("status", "")) == "open",
                filled=order_obj.safe_filled,
                wallet_held=wallet_held,
            )
            if fee is None:
                if reason not in ("not-alpaca-spot", "not-entry-side",
                                  "order-still-open", "wallet-covers-fill"):
                    logger.warning(
                        "alpaca-fee patch: left %s untouched (%s).", trade, reason)
                return None
            logger.info(
                "alpaca-fee patch: derived base fee %.8f %s for %s "
                "(filled=%.8f credited=%.8f) so exits close cleanly.",
                fee, base, trade, order_obj.safe_filled, wallet_held)
            return fee
        except Exception as exc:  # noqa: BLE001 - never break the normal fee path
            logger.warning("alpaca-fee patch skipped due to error: %r", exc)
            return fee_abs

    get_real_amount.__name__ = "get_real_amount"
    FreqtradeBot.get_real_amount = get_real_amount
    setattr(FreqtradeBot, _PATCHED_ATTR, True)
    logger.info("alpaca-fee patch installed (gated: alpaca + spot, fail-closed).")
