"""Hermetic tests for the Alpaca fee-in-base exit correction (a4).

No network, no orders, no bot process. Uses the EXACT numbers captured live on
2026-10-21 from the paper account:
  * DOT/USD MARKET_BUY filled 42.74856151, wallet credited 42.641690106
    -> real base fee 0.106871404 (~0.25%) -> residual that jams the exit.

Guarantees under test:
  * derive_base_fee turns the wallet shortfall into the base fee Freqtrade needs.
  * It is strictly gated (alpaca + spot + entry side + closed order) and fail-closed
    (never enlarges, rejects implausible rates, defers to a genuinely reported fee).
  * install() patches FreqtradeBot.get_real_amount idempotently and delegates the
    reported-fee case back to the original unchanged.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from exchange_ext import alpaca_fees as AF

# Real captured fixture values.
FILLED = 42.74856151
CREDITED = 42.641690106
REAL_FEE = 0.106871404


# ---- pure decision core -----------------------------------------------------
def test_captured_dot_fill_yields_the_real_base_fee():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=FILLED, wallet_held=CREDITED,
    )
    assert fee == pytest.approx(REAL_FEE, abs=1e-8)
    assert reason.startswith("base-fee-rate-")


@pytest.mark.parametrize("rate", [0.0015, 0.0025, 0.02])
def test_plausible_fee_rates_are_applied(rate):
    filled = 100.0
    fee, _ = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=filled, wallet_held=filled * (1 - rate),
    )
    assert fee == pytest.approx(filled * rate, abs=1e-8)


def test_non_alpaca_spot_is_never_touched():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=False, is_entry_side=True, order_open=False,
        filled=FILLED, wallet_held=CREDITED,
    )
    assert fee is None and reason == "not-alpaca-spot"


def test_exit_side_is_never_touched():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=False, order_open=False,
        filled=FILLED, wallet_held=CREDITED,
    )
    assert fee is None and reason == "not-entry-side"


def test_open_order_is_skipped():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=True,
        filled=FILLED, wallet_held=CREDITED,
    )
    assert fee is None and reason == "order-still-open"


def test_wallet_covering_the_fill_never_enlarges_position():
    # If the wallet holds >= the recorded fill there is no base fee; must return None.
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=40.0, wallet_held=42.0,
    )
    assert fee is None and reason == "wallet-covers-fill"


def test_wallet_exactly_equal_to_fill_is_noop():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=42.0, wallet_held=42.0,
    )
    assert fee is None and reason == "wallet-covers-fill"


def test_zero_filled_fails_closed():
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=0.0, wallet_held=0.0,
    )
    assert fee is None and reason == "no-filled-amount"


def test_implausible_fee_rate_fails_closed():
    # 5% shortfall is not a trade fee -> leave the trade untouched (stock behavior).
    fee, reason = AF.derive_base_fee(
        alpaca_spot=True, is_entry_side=True, order_open=False,
        filled=100.0, wallet_held=95.0,
    )
    assert fee is None and reason.startswith("implausible-fee-rate-")


# ---- config gate ------------------------------------------------------------
def test_gate_accepts_alpaca_spot():
    assert AF._is_alpaca_spot({"exchange": {"name": "alpaca"}, "trading_mode": "spot"})
    assert AF._is_alpaca_spot({"exchange": {"name": "Alpaca"}})  # spot is default


@pytest.mark.parametrize("cfg", [
    {"exchange": {"name": "binance"}, "trading_mode": "spot"},
    {"exchange": {"name": "alpaca"}, "trading_mode": "futures"},
    {"exchange": {}},
    None,
    "not-a-dict",
])
def test_gate_rejects_everything_else(cfg):
    assert AF._is_alpaca_spot(cfg) is False


# ---- install() integration (patched method behaves, restores cleanly) --------
@pytest.fixture
def patched_bot_class():
    from freqtrade.freqtradebot import FreqtradeBot
    saved_method = FreqtradeBot.get_real_amount
    saved_marker = getattr(FreqtradeBot, AF._PATCHED_ATTR, False)
    if hasattr(FreqtradeBot, AF._PATCHED_ATTR):
        delattr(FreqtradeBot, AF._PATCHED_ATTR)
    yield FreqtradeBot
    FreqtradeBot.get_real_amount = saved_method
    if saved_marker:
        setattr(FreqtradeBot, AF._PATCHED_ATTR, True)
    elif hasattr(FreqtradeBot, AF._PATCHED_ATTR):
        delattr(FreqtradeBot, AF._PATCHED_ATTR)


def _alpaca_self():
    wallets = SimpleNamespace(
        update=lambda: None,
        get_free=lambda cur: CREDITED,
        get_used=lambda cur: 0.0,
    )
    exchange = SimpleNamespace(get_pair_base_currency=lambda pair: "DOT")
    return SimpleNamespace(
        # FreqtradeBot stores config on `self.config` (the real attribute name).
        config={"exchange": {"name": "alpaca"}, "trading_mode": "spot"},
        wallets=wallets,
        exchange=exchange,
    )


def _buy_ctx():
    trade = SimpleNamespace(pair="DOT/USD", entry_side="buy")
    order_obj = SimpleNamespace(ft_order_side="buy", safe_filled=FILLED)
    order = {"status": "closed"}
    return trade, order, order_obj


def test_install_is_idempotent_and_flagged(patched_bot_class):
    AF.install()
    assert getattr(patched_bot_class, AF._PATCHED_ATTR) is True
    fn = patched_bot_class.get_real_amount
    AF.install()  # second call must not double-wrap
    assert patched_bot_class.get_real_amount is fn


def test_patched_method_derives_fee_when_none_reported(patched_bot_class):
    # Simulate stock Freqtrade finding NO reported fee (Alpaca's real behavior).
    patched_bot_class.get_real_amount = lambda self, trade, order, order_obj: None
    AF.install()
    trade, order, order_obj = _buy_ctx()
    fee = patched_bot_class.get_real_amount(_alpaca_self(), trade, order, order_obj)
    assert fee == pytest.approx(REAL_FEE, abs=1e-8)


def test_patched_method_defers_to_a_genuinely_reported_fee(patched_bot_class):
    # If the engine DID find a fee, the patch must return it unchanged.
    patched_bot_class.get_real_amount = lambda self, trade, order, order_obj: 0.5
    AF.install()
    trade, order, order_obj = _buy_ctx()
    fee = patched_bot_class.get_real_amount(_alpaca_self(), trade, order, order_obj)
    assert fee == 0.5


def test_patched_method_is_inert_for_non_alpaca(patched_bot_class):
    patched_bot_class.get_real_amount = lambda self, trade, order, order_obj: None
    AF.install()
    trade, order, order_obj = _buy_ctx()
    binance_self = _alpaca_self()
    binance_self.config = {"exchange": {"name": "binance"}, "trading_mode": "spot"}
    fee = patched_bot_class.get_real_amount(binance_self, trade, order, order_obj)
    assert fee is None
