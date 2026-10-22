"""Human-readable, deterministic message formatting for bot notifications.

Pure functions (no network, no exchange). The live Freqtrade Telegram RPC owns
the *transport*; this module owns the *detail payload* so a message is testable
without a bot or an internet connection. Two shapes are produced:

  * a signal/decision report for the running baseline (BTC Z-score), and
  * a setup-detail report for the FVG/OB sequence (entry/stop/TP + 1:2 RR).

Keeping formatting separate lets us assert exact strings in unit tests and reuse
the same text whether it goes to Telegram, a log line, or the dashboard.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def _fmt_ts(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    # pandas Timestamp also stringifies usefully; fall back to iso-ish head
    s = str(value)
    return s.replace("T", " ").replace("+00:00", " UTC")


def _num(value: Optional[float], nd: int = 4) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):,.{nd}f}"
    except (TypeError, ValueError):
        return str(value)


def format_signal_report(
    *,
    pair: str,
    timeframe: str,
    now: Optional[datetime],
    decision: str,
    reason: str,
    indicators: dict[str, Any],
    risk: Optional[dict[str, Any]] = None,
) -> str:
    """Baseline decision report (e.g. BTC Z-score) with the inputs shown.

    ``indicators`` is an ordered-friendly dict of the numbers behind the call
    (z-score, thresholds, ema, std, close). ``risk`` optionally carries the
    bounded sizing that will be applied if the decision leads to an order.
    """
    lines = [
        f"[signal] {pair} {timeframe} @ {_fmt_ts(now)}",
        f"decision: {decision}",
        f"reason:   {reason}",
        "inputs:",
    ]
    for k, v in indicators.items():
        lines.append(f"  - {k}: {_num(v) if isinstance(v, (int, float)) else v}")
    if risk:
        lines.append("bounded risk:")
        for k, v in risk.items():
            lines.append(f"  - {k}: {_num(v) if isinstance(v, (int, float)) else v}")
    return "\n".join(lines)


def format_fvg_ob_setup(entry: dict[str, Any]) -> str:
    """Render a completed FVG/OB sequence (the exact step-gated pipeline).

    Consumes the dict emitted by ``app.strategies_core.fvg_ob._try_enter`` —
    every step carries a timestamp, and the risk numbers enforce a fixed 1:2 RR.
    """
    direction = entry.get("direction", "long")
    entry_px = entry.get("entry_price")
    stop = entry.get("stop")
    tp = entry.get("take_profit")
    risk = entry.get("risk_per_unit")
    rr = entry.get("rr")
    zone = entry.get("htf_zone") or (None, None)
    z_lo, z_hi = zone[0], zone[1]
    lines = [
        f"[setup] {entry.get('pair', '?')} {str(direction).upper()} — FVG/OB sequence complete",
        f"  1H zone identified  @ {_fmt_ts(entry.get('htf_creation_ts'))} "
        f"(confluence {_num(z_lo)}..{_num(z_hi)})",
        f"  1H zone tapped      @ {_fmt_ts(entry.get('htf_tap_ts'))}",
        f"  5M FVG confirmed    @ {_fmt_ts(entry.get('ltf_creation_ts'))}",
        f"  entry (first retest)@ {_fmt_ts(entry.get('entry_ts'))} px {_num(entry_px)}",
        f"  stop  {_num(stop)}   take-profit {_num(tp)}   RR 1:{(_num(rr, 2) if rr else 'n/a')}",
        f"  risk/unit {_num(risk)}  (bounded sizing; spot long-only) "
        f"[{entry.get('strategy_version', '')}]",
    ]
    return "\n".join(lines)


def format_status(*, bot_name: str, state: str, detail: str = "") -> str:
    base = f"[status] {bot_name}: {state}"
    return f"{base} — {detail}" if detail else base


# ---------------- emoji trade-event alerts (owner request 2026-10-21) ----------------
# One clear, distinct message per lifecycle event. Pure text — the monitor owns
# delivery; these are unit-testable without network. Order events keep SUBMITTED
# distinct from FILLED: a signal is never presented as a confirmed fill.

def format_trade_entry(trade: dict[str, Any]) -> str:
    """🟢 BUY (SUBMITTED) — the executor opened a position request."""
    lines = [
        f"🟢 BUY SIGNAL → PAPER ORDER — {trade.get('pair', '?')}",
        f"⏱️ {_fmt_ts(trade.get('open_date'))}",
        f"🧠 strategy: {trade.get('strategy') or 'n/a'} [{trade.get('timeframe', 'n/a')}]",
    ]
    if trade.get("enter_tag"):
        lines.append(f"💡 why: {trade['enter_tag']}")
    lines.append(
        f"📝 size: {_num(trade.get('stake_amount'), 2)} USD"
        f" @ ~{_num(trade.get('open_rate'))}  →  qty {_num(trade.get('amount'), 6)}"
    )
    lines.append("🛡️ risk check: AUTO-APPROVED — within bounded paper policy (no manual approval)")
    lines.append("📡 order state: SUBMITTED — awaiting fill confirmation (next alert will say ✅)")
    return "\n".join(lines)


def format_trade_filled(trade: dict[str, Any]) -> str:
    """✅ FILLED — the paper order is a confirmed position."""
    lines = [
        f"✅ ORDER FILLED — position OPEN: {trade.get('pair', '?')}",
        f"⏱️ {_fmt_ts(trade.get('open_date'))}",
        f"📦 qty {_num(trade.get('amount'), 6)} @ {_num(trade.get('open_rate'))}"
        f"  =  {_num(trade.get('open_trade_value'), 2)} USD",
    ]
    if trade.get("fee_open_cost") is not None:
        lines.append(f"💸 entry fee: {_num(trade.get('fee_open_cost'))}")
    lines.append(f"🛑 stop: {_num(trade.get('stop_loss'))}  ·  🎯 exit: strategy signal / ROI")
    return "\n".join(lines)


def format_trade_exit(trade: dict[str, Any]) -> str:
    """🔴 EXIT (SUBMITTED) — the bot decided to close the position."""
    lines = [
        f"🔴 EXIT — closing {trade.get('pair', '?')}",
        f"⏱️ {_fmt_ts(trade.get('close_date') or trade.get('exit_hint_ts'))}",
        f"🧭 reason: {trade.get('exit_reason') or 'strategy/risk rule'}",
    ]
    if trade.get("exit_tag"):
        lines.append(f"💡 tag: {trade['exit_tag']}")
    lines.append(f"📤 exit order state: {trade.get('exit_order_status') or 'SUBMITTED'}")
    return "\n".join(lines)


def format_trade_outcome(trade: dict[str, Any]) -> str:
    """💰 PROFIT / 💸 LOSS — closed trade with the realized outcome recorded."""
    ratio = trade.get("close_profit")
    ratio = float(ratio) if ratio is not None else None
    emoji = "💰 PROFIT" if (ratio or 0) > 0 else ("💸 LOSS" if (ratio or 0) < 0 else "⚖️ BREAK-EVEN")
    lines = [
        f"{emoji} — TRADE CLOSED: {trade.get('pair', '?')}",
        f"⏱️ {_fmt_ts(trade.get('close_date'))}",
        f"🧭 exit reason: {trade.get('exit_reason') or 'n/a'}",
        f"📥 in: {_num(trade.get('open_rate'))}  →  📤 out: {_num(trade.get('close_rate'))}",
    ]
    if ratio is not None:
        lines.append(f"📊 result: {ratio * 100:+,.2f}%  ({_num(trade.get('close_profit_abs'), 2)} USD)")
    fees = (trade.get("fee_open_cost") or 0) + (trade.get("fee_close_cost") or 0)
    if fees:
        lines.append(f"💸 fees paid: {_num(fees)}")
    lines.append("🗂️ outcome recorded — reviewable in the dashboard & ledger")
    return "\n".join(lines)


def format_risk_rejection(rej: dict[str, Any]) -> str:
    """⚠️ RISK REJECTED — an eligible signal was vetoed by the policy, with why."""
    return "\n".join([
        f"⚠️ RISK REJECTED — NO TRADE: {rej.get('pair', '?')}",
        f"⏱️ {_fmt_ts(rej.get('ts'))}",
        f"🚫 code: {rej.get('code', 'n/a')}",
        f"❓ why: {rej.get('message', 'n/a')}",
        "🛡️ the bounded paper policy or a safety check blocked this entry — "
        "hard limits are never bypassed.",
    ])


def format_demote(event: dict[str, Any]) -> str:
    """⛔ STRATEGY GATE — a pair/family auto-demoted by the Phase D learner.

    Emitted when app/state/strategy_gate.json gains a new entry (n>=N_MIN closed
    trades with a non-positive after-fee expectancy). Auto-PROMOTE is intentionally
    not supported: the owner must delete the entry (after a fresh backtest) to
    re-enable a pair, so the gate cannot flap on a lucky / unlucky streak."""
    lines = [
        f"⛔ STRATEGY GATE — AUTO-DEMOTED: {event.get('pair', '?')} "
        f"[{event.get('family') or 'n/a'}]",
        f"⏱️ {_fmt_ts(event.get('since'))}",
        f"📉 expectancy_R: {_num(event.get('expectancy_R'), 4)} at n={event.get('n', 'n/a')}",
        f"💡 reason: {event.get('reason', 'non-positive after-fee expectancy')}",
        "🚫 new entries for this pair are blocked by policy.is_tradeable.",
        "🔁 NOT auto-promoted: owner must re-approve via a fresh backtest + edit the gate file.",
    ]
    return "\n".join(lines)



def format_asset_status(asset: dict[str, Any]) -> str:
    """Rich, per-crypto status snapshot. One message per asset (owner brief §9).

    Every field is derived from the actual strategy + live data; nothing is a
    placeholder. ``order_state`` keeps SUBMITTED/PROPOSED distinct from FILLED so a
    signal is never mistaken for a confirmed fill.
    """
    label = asset.get("status_label", asset.get("status", "MONITORED"))
    lines = [
        f"[{asset.get('signal', 'N/A')}] {asset.get('symbol', '?')} — {label}",
        f"  strategy:  {asset.get('strategy') or 'none'}  [{asset.get('version', 'n/a')}]",
        f"  signal ts: {_fmt_ts(asset.get('signal_ts'))}  last candle: {_fmt_ts(asset.get('candle_ts'))}",
    ]
    price = asset.get("price")
    lines.append(f"  price:     {_num(price) if isinstance(price, (int, float)) else 'n/a (no valid data)'}")
    ind = asset.get("indicators") or {}
    if ind:
        lines.append("  indicators:")
        for k, v in ind.items():
            lines.append(f"    - {k}: {_num(v) if isinstance(v, (int, float)) else v}")
    pos = asset.get("position")
    if pos:
        lines.append(
            f"  position:  qty {_num(pos.get('qty'), 6)}  entry {_num(pos.get('entry'))} "
            f"stop {_num(pos.get('stop'))} tp {_num(pos.get('tp'))}"
        )
        upnl = pos.get("upnl")
        if upnl is not None:
            lines.append(f"  unrealized P&L: {_num(upnl)}")
        rp = pos.get("realized")
        if rp is not None:
            lines.append(f"  realized P&L (this pair): {_num(rp)}")
    else:
        lines.append("  position:  none open")
    risk = asset.get("risk") or {}
    if risk:
        lines.append(f"  risk check: {risk.get('decision', 'n/a')} — {risk.get('reason', '')}")
    if asset.get("order_state"):
        lines.append(f"  order state: {asset['order_state']}")
    note = asset.get("note")
    if note:
        lines.append(f"  note: {note}")
    return "\n".join(lines)
