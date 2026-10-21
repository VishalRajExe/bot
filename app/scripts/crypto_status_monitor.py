"""Read-only per-crypto status monitor + Telegram notifier (owner brief §9, §13).

For every pair in app/configs/strategy_registry.json it evaluates the ACTUAL
daily Z-score signal (BTC baseline + experimental alts), reads the executor's real
open positions from the Freqtrade trade DB, shows each asset's order state and
P&L, and sends a SEPARATE Telegram message per crypto.

It never places, signs, or enables an order. It only:
  * reads public Alpaca daily candles (signal) and the paper account/equity,
  * reads the Freqtrade sqlite DB (positions/order state) in READ-ONLY mode,
  * writes the equity snapshot + persisted circuit-breaker kill switch (safety
    control-plane, per the bounded policy) so the executor fails closed on breach,
  * sends Telegram status messages.

Cadence is separated: POLL every --interval seconds (default 60); notify IMMEDIATELY
when an asset's signal/position/order state changes; send a full per-asset heartbeat
every --heartbeat-minutes (default 60). No unchanged status is re-spammed.

Usage (from D:\\BOT):
    .venv\\Scripts\\python.exe app\\scripts\\crypto_status_monitor.py --once
    .venv\\Scripts\\python.exe app\\scripts\\crypto_status_monitor.py --interval 60 --heartbeat-minutes 60
    .venv\\Scripts\\python.exe app\\scripts\\crypto_status_monitor.py --recover-kill-switch
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import talib

ROOT = Path(__file__).resolve().parents[1]           # D:\BOT\app
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from notifications.format import format_asset_status  # noqa: E402
from risk import policy  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENV_PATH = ROOT.parent / ".env"
CFG_PATH = ROOT / "configs" / "config.alpaca.paper.json"
DATA_BASE = "https://data.alpaca.markets"
TRADER_BASE = "https://paper-api.alpaca.markets"
STATE_PATH = ROOT / "state" / "crypto_status.json"
TIMEFRAME = "1d"
EMA_PERIOD = 65
STD_PERIOD = 65
# signals for the ACTIVE/EXPERIMENTAL daily-zscore family
STATUS_LABEL = {
    "ACTIVE_BASELINE": "ACTIVE (baseline)",
    "EXPERIMENTAL_PAPER": "EXPERIMENTAL (paper)",
    "STATUS_ONLY": "STATUS-ONLY (not traded)",
    "RESEARCH_ONLY": "RESEARCH (not traded)",
}


def load_env() -> dict:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items()
                if k.startswith(("ALPACA_", "TELEGRAM_")) and v})
    return env


def api_key(env: dict) -> str:
    return env.get("ALPACA_API_KEY_ID") or env.get("ALPACA_PAPER_API_KEY") or env.get("ALPACA_API_KEY") or ""


def api_secret(env: dict) -> str:
    return env.get("ALPACA_API_KEY_SECRET") or env.get("ALPACA_PAPER_API_SECRET") or env.get("ALPACA_API_SECRET") or ""


def tg_token(env: dict) -> str:
    return env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_TOKEN") or ""


def monitored_pairs() -> list[str]:
    """Real market pairs in the registry (skip pseudo research keys without a slash)."""
    out = []
    for p, e in policy.registry().get("pairs", {}).items():
        if "/" not in p:
            continue
        if e.get("status") in ("ACTIVE_BASELINE", "EXPERIMENTAL_PAPER", "STATUS_ONLY"):
            out.append(p)
    return out


def ft_db_path() -> Path | None:
    try:
        url = json.loads(CFG_PATH.read_text(encoding="utf-8")).get("db_url", "")
        if url.startswith("sqlite:///"):
            return Path(url.replace("sqlite:///", ""))
    except Exception:  # noqa: BLE001
        pass
    return None


def open_positions(db: Path | None) -> dict[str, dict]:
    """Read the executor's real open trades (READ-ONLY). keyed by pair."""
    if not db or not db.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        for row in con.execute(
            "SELECT pair, amount, open_rate, stop_loss, take_profit, profit_abs "
            "FROM trades WHERE is_open=1"
        ).fetchall():
            pair, amount, open_rate, stop, tp, _ = row
            out[pair] = {"qty": amount, "entry": open_rate, "stop": stop, "tp": tp,
                         "order_state": "OPEN (confirmed filled)"}
        for pair, realized in con.execute(
            "SELECT pair, SUM(profit_abs) FROM trades WHERE is_open=0 GROUP BY pair"
        ).fetchall():
            if pair in out:
                out[pair]["realized"] = realized
        con.close()
    except Exception:  # noqa: BLE001
        return out
    return out


def fetch_signal(hdrs: dict, pair: str) -> dict:
    start = (datetime.now(timezone.utc) - timedelta(days=500)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{DATA_BASE}/v1beta3/crypto/us/bars", headers=hdrs,
                     params={"symbols": pair, "timeframe": "1D", "start": start}, timeout=30)
    r.raise_for_status()
    bars = (r.json().get("bars", {}) or {}).get(pair) or []
    if not bars:
        return {"signal": "N/A", "reason": "no bars returned", "indicators": {}, "price": None, "candle_ts": None}
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["t"], utc=True)
    today = pd.Timestamp.now(tz="UTC").normalize()
    df = df[df["date"] < today].set_index("date")
    if len(df) < EMA_PERIOD + 5:
        return {"signal": "N/A", "reason": "insufficient daily history (data-quality gate)",
                "indicators": {}, "price": None, "candle_ts": None}
    close = np.asarray(df["c"], dtype=float)
    ema = talib.EMA(close, timeperiod=EMA_PERIOD)
    std = pd.Series(close, index=df.index).rolling(STD_PERIOD).std(ddof=0).replace(0.0, np.nan)
    z = (pd.Series(close, index=df.index) - ema) / std
    z = z.dropna()
    cur, prev = float(z.iloc[-1]), float(z.iloc[-2])
    bull = float(policy.pair_entry(pair).get("risk", {}).get("bull_threshold", 0.5))
    exit_th = float(policy.pair_entry(pair).get("risk", {}).get("exit_threshold", 0.0))
    if cur >= bull and prev < bull:
        signal, reason = "BUY", "fresh cross up through bull threshold"
    elif cur <= exit_th and prev > exit_th:
        signal, reason = "SELL", "fresh cross down through exit threshold (spot exit, not a short)"
    elif cur >= bull:
        signal, reason = "HOLD", "bullish regime maintained"
    else:
        signal, reason = "FLAT", "no position — Z below bull threshold"
    return {"signal": signal, "reason": reason, "price": float(close[-1]),
            "candle_ts": str(df.index[-1].strftime("%Y-%m-%d")),
            "indicators": {"zscore": round(cur, 3), "bull_threshold": bull,
                           "exit_threshold": exit_th, "ema65": round(float(ema[-1]), 4)}}


def account_equity(hdrs: dict) -> dict:
    try:
        r = requests.get(f"{TRADER_BASE}/v2/account", headers=hdrs, timeout=15)
        if r.status_code != 200:
            return {}
        a = r.json()
        return {"equity": float(a.get("equity", 0) or 0), "cash": float(a.get("cash", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {}


def update_equity_and_breaker(hdrs: dict, env: dict) -> dict:
    """Maintain equity history + evaluate circuit breakers; persist kill-switch. Safety only."""
    snap = account_equity(hdrs)
    eq = snap.get("equity")
    prev = policy.read_json(policy.equity_path())
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if eq is None:
        br = policy.breaker_status(None, prev.get("sod_equity"), prev.get("peak_equity"))
        return {"equity": None, "breaker": br}
    sod = prev.get("sod_equity") if prev.get("date") == today else eq
    peak = max(float(prev.get("peak_equity") or eq), eq)
    policy.write_json(policy.equity_path(), {"date": today, "equity": eq, "sod_equity": sod,
                                             "peak_equity": peak, "cash": snap.get("cash"),
                                             "asof": now.isoformat()})
    br = policy.breaker_status(eq, sod, peak)
    blocked = policy.is_blocked()
    if br["triggered"] and not blocked["blocked"]:
        policy.set_kill_switch(True, "; ".join(br["reasons"]), br)
        send(env, "\n".join([
            "*** CRITICAL — CIRCUIT BREAKER TRIGGERED (PAPER) ***",
            f"equity=${eq:,.2f}  reasons: " + "; ".join(br["reasons"]),
            "NEW ENTRIES BLOCKED. Open positions follow the emergency-exit policy.",
            "Manual recovery required: run crypto_status_monitor.py --recover-kill-switch"]))
    return {"equity": eq, "breaker": br, "blocked": blocked["blocked"]}


def build_asset(env: dict, hdrs: dict, pair: str, positions: dict, blocked: bool) -> dict:
    entry = policy.pair_entry(pair)
    status = entry.get("status", "STATUS_ONLY")
    label = STATUS_LABEL.get(status, status)
    tradeable = policy.is_tradeable(pair)
    asset = {"symbol": pair, "status": status, "status_label": label,
             "strategy": entry.get("strategy"), "version": entry.get("version")}
    try:
        sig = fetch_signal(hdrs, pair)
    except Exception as e:  # noqa: BLE001
        sig = {"signal": "ERR", "reason": str(e)[:100], "indicators": {}, "price": None, "candle_ts": None}
    if not tradeable:
        sig["signal"] = "MONITOR"
        sig["reason"] = entry.get("reason_not_traded", "status-only / not enabled for trading")
    asset.update({"signal": sig["signal"], "note": sig["reason"], "price": sig.get("price"),
                  "candle_ts": sig.get("candle_ts"), "indicators": sig.get("indicators", {}),
                  "signal_ts": sig.get("candle_ts")})
    pos = positions.get(pair)
    asset["position"] = pos
    asset["order_state"] = pos["order_state"] if pos else ("no open position")
    if pos:
        cur = sig.get("price")
        if cur and pos.get("entry") and pos.get("qty"):
            pos["upnl"] = round((cur - pos["entry"]) * pos["qty"], 2)
    # reflect the executor's most recent risk verdict for this pair (read from log)
    rej = recent_rejection(pair)
    if rej:
        asset["risk"] = {"decision": f"REJECTED {rej['code']}", "reason": rej["message"]}
    elif blocked:
        asset["risk"] = {"decision": "BLOCKED", "reason": "circuit breaker active — no new entries"}
    elif tradeable and asset["signal"] == "BUY":
        asset["risk"] = {"decision": "AUTO-APPROVED", "reason": "within bounded paper policy (no per-trade approval)"}
    elif tradeable:
        asset["risk"] = {"decision": "N/A", "reason": "no entry signal; monitoring"}
    else:
        asset["risk"] = {"decision": "NOT TRADED", "reason": "status-only / research"}
    return asset


def recent_rejection(pair: str) -> dict | None:
    items = policy.read_json(policy.rejections_path()).get("items", [])
    for it in reversed(items):
        if it.get("pair") == pair:
            age_ok = True
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(it["ts"])).total_seconds()
                age_ok = age < 3600  # only surface a rejection from the last hour
            except Exception:  # noqa: BLE001
                pass
            if age_ok:
                return it
    return None


def send(env: dict, text: str) -> bool:
    token, chat = tg_token(env), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_NOT_CONFIGURED")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=10)
        return bool(r.json().get("ok"))
    except Exception:  # noqa: BLE001
        return False


def load_state() -> dict:
    return policy.read_json(STATE_PATH) or {}


def sweep(env: dict, hdrs: dict, pairs: list[str], notify_mode: str) -> int:
    """notify_mode: 'full' (every asset), 'changes' (only assets whose key changed)."""
    state = load_state()
    positions = open_positions(ft_db_path())
    eqinfo = update_equity_and_breaker(hdrs, env)
    blocked = bool(eqinfo.get("blocked"))
    sent = 0
    for pair in pairs:
        asset = build_asset(env, hdrs, pair, positions, blocked)
        key = (asset["signal"], bool(asset["position"]), asset["order_state"], asset["status"])
        prev = state.get(pair, {}).get("key")
        text = format_asset_status(asset)
        if notify_mode == "full" or key != prev:
            if send(env, text):
                sent += 1
        state[pair] = {"key": list(key), "signal": asset["signal"],
                       "asof": datetime.now(timezone.utc).isoformat()}
    policy.write_json(STATE_PATH, state)
    return sent


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only per-crypto status monitor -> Telegram")
    ap.add_argument("--interval", type=int, default=60, help="poll seconds (default 60)")
    ap.add_argument("--heartbeat-minutes", type=int, default=60, help="full per-asset heartbeat (default 60)")
    ap.add_argument("--once", action="store_true", help="single full sweep then exit")
    ap.add_argument("--recover-kill-switch", action="store_true",
                    help="manual recovery: clear the persisted circuit-breaker kill switch")
    args = ap.parse_args()

    env = load_env()
    akey, asecret = api_key(env), api_secret(env)
    if args.recover_kill_switch:
        policy.set_kill_switch(False, "manual recovery by owner")
        print("KILL_SWITCH_CLEARED")
        return 0
    if not akey or not asecret:
        print("NO_CREDENTIALS: create D:\\BOT\\.env")
        return 2
    hdrs = {"APCA-API-KEY-ID": akey, "APCA-API-SECRET-KEY": asecret}
    pairs = monitored_pairs()

    print(f"=== CRYPTO STATUS MONITOR (read-only) | {len(pairs)} pairs | poll {args.interval}s | "
          f"heartbeat {args.heartbeat_minutes}m ===")
    n = sweep(env, hdrs, pairs, notify_mode="full")  # initial full per-asset status
    print(f"-> {n} per-asset notifications sent (full sweep)")
    if args.once:
        return 0

    last_full = time.time()
    while True:
        time.sleep(args.interval)
        try:
            due = (time.time() - last_full) >= args.heartbeat_minutes * 60
            mode = "full" if due else "changes"
            n = sweep(env, hdrs, pairs, notify_mode=mode)
            if due:
                last_full = time.time()
            if mode == "changes" and n:
                print(f"{datetime.now(timezone.utc):%H:%M:%S} -> {n} change alert(s)")
        except Exception as e:  # noqa: BLE001
            print("CYCLE_ERROR:", str(e)[:160])


if __name__ == "__main__":
    raise SystemExit(main())
