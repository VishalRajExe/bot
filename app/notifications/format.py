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
