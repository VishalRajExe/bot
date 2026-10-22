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
from notifications.format import (  # noqa: E402
    format_asset_status,
    format_risk_rejection,
    format_trade_entry,
    format_trade_exit,
    format_trade_filled,
    format_trade_outcome,
)
from risk import policy  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENV_PATH = ROOT.parent / ".env"
CFG_PATH = ROOT / "configs" / "config.alpaca.paper.json"
FAST_CFG_PATH = ROOT / "configs" / "config.alpaca.paper.fast.json"
SWING_CFG_PATH = ROOT / "configs" / "config.alpaca.paper.swing.json"
DATA_BASE = "https://data.alpaca.markets"
TRADER_BASE = "https://paper-api.alpaca.markets"
STATE_PATH = ROOT / "state" / "crypto_status.json"
TRADE_EVENTS_PATH = ROOT / "state" / "trade_events.json"
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


def _db_from_cfg(cfg_path: Path) -> Path | None:
    try:
        url = json.loads(cfg_path.read_text(encoding="utf-8")).get("db_url", "")
        if url.startswith("sqlite:///"):
            return Path(url.replace("sqlite:///", ""))
    except Exception:  # noqa: BLE001
        pass
    return None


def ft_db_paths() -> dict[str, Path]:
    """label -> trade DB for BOTH executors. Only paths that exist are returned (an
    executor that has not traded yet has no DB). Used to read positions/emit trade
    events across the daily and fast processes together."""
    out: dict[str, Path] = {}
    for label, cfg in (("daily", CFG_PATH), ("fast", FAST_CFG_PATH), ("swing", SWING_CFG_PATH)):
        p = _db_from_cfg(cfg)
        if p and p.exists():
            out[label] = p
    return out


def ft_db_path() -> Path | None:
    return _db_from_cfg(CFG_PATH)


def open_positions(db: Path | None) -> dict[str, dict]:
    """Read the executor's real open trades (READ-ONLY). keyed by pair."""
    if not db or not db.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
        # realized-per-pair needs a money column; 2026.9 renamed profit_abs ->
        # close_profit_abs. Selecting a nonexistent column would error the whole
        # query, which the broad except used to swallow silently.
        money = next((c for c in ("close_profit_abs", "profit_abs", "realized_profit") if c in cols), None)
        sel = ["pair", "amount", "open_rate", "stop_loss"]
        sel += ["take_profit"] if "take_profit" in cols else ["NULL"]
        sel += [money] if money else ["NULL"]
        for pair, amount, open_rate, stop, tp, realized in con.execute(
            f"SELECT {', '.join(sel)} FROM trades WHERE is_open=1"
        ).fetchall():
            out[pair] = {"qty": amount, "entry": open_rate, "stop": stop, "tp": tp,
                         "order_state": "OPEN (confirmed filled)"}
            if realized is not None:
                out[pair]["realized"] = realized
        if money:
            for pair, realized in con.execute(
                f"SELECT pair, SUM({money}) FROM trades WHERE is_open=0 GROUP BY pair"
            ).fetchall():
                if pair in out:
                    out[pair]["realized"] = realized
        con.close()
    except Exception:  # noqa: BLE001
        return out
    return out


def _bars(hdrs: dict, pair: str, timeframe: str, start: str) -> pd.DataFrame:
    r = requests.get(f"{DATA_BASE}/v1beta3/crypto/us/bars", headers=hdrs,
                     params={"symbols": pair, "timeframe": timeframe, "start": start}, timeout=30)
    r.raise_for_status()
    bars = (r.json().get("bars", {}) or {}).get(pair) or []
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["t"], utc=True)
    return df.set_index("date")


def _fetch_momentum(hdrs: dict, pair: str) -> dict:
    """Intraday momentum read (matches MomentumAlt): fresh EMA cross + volume surge."""
    entry = policy.pair_entry(pair).get("risk", {})
    m = entry.get("momentum", {})
    fast_p = int(m.get("ema_fast", 9))
    slow_p = int(m.get("ema_slow", 21))
    vol_p = int(m.get("vol_window", 20))
    start = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    df = _bars(hdrs, pair, "5Min", start)
    if len(df) < slow_p + vol_p + 2:
        return {"signal": "N/A", "reason": "insufficient 5m history (data-quality gate)",
                "indicators": {}, "price": None, "candle_ts": None}
    now5 = pd.Timestamp.now(tz="UTC").floor("5min")
    df = df[df.index < now5]           # drop the current partial candle
    if len(df) < slow_p + vol_p + 2:
        return {"signal": "N/A", "reason": "insufficient completed 5m candles",
                "indicators": {}, "price": None, "candle_ts": None}
    close = df["c"].to_numpy(dtype=float)
    vol = df["v"].to_numpy(dtype=float)
    ef = talib.EMA(close, timeperiod=fast_p)
    es = talib.EMA(close, timeperiod=slow_p)
    volma = pd.Series(vol).rolling(vol_p).mean().to_numpy()
    f, s = float(ef[-1]), float(es[-1])
    pf, ps = float(ef[-2]), float(es[-2])
    vsurge = bool(vol[-1] > (volma[-1] if not np.isnan(volma[-1]) else 0))
    if f > s and pf <= ps and vsurge:
        signal, reason = "BUY", f"fresh ema{fast_p}x{slow_p} cross-up + volume surge"
    elif f < s and pf >= ps:
        signal, reason = "SELL", f"ema{fast_p} crossed back below ema{slow_p} (exit)"
    elif f > s:
        signal, reason = "HOLD", "momentum on — fast EMA above slow"
    else:
        signal, reason = "FLAT", "no position — fast EMA below slow"
    return {"signal": signal, "reason": reason, "price": float(close[-1]),
            "candle_ts": str(df.index[-1].strftime("%Y-%m-%dT%H:%M")),
            "indicators": {"ema_fast": round(f, 6), "ema_slow": round(s, 6),
                           "ema_fast_period": fast_p, "ema_slow_period": slow_p,
                           "vol_ratio": round(float(vol[-1] / volma[-1]), 3) if volma[-1] else None}}


def _fetch_daily_zscore(hdrs: dict, pair: str) -> dict:
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


def fetch_signal(hdrs: dict, pair: str) -> dict:
    """Evaluate the ACTUAL live signal for a pair using its executor's real method:
    5m momentum for fast-executor alts, daily Z-score for the BTC baseline."""
    family = policy.pair_entry(pair).get("strategy_family", "daily_zscore")
    if family == "momentum_ema_vol":
        return _fetch_momentum(hdrs, pair)
    return _fetch_daily_zscore(hdrs, pair)


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
    dbs = ft_db_paths()
    positions: dict[str, dict] = {}
    for _label, db in dbs.items():
        positions.update(open_positions(db))   # executors are disjoint, so no pair collides
    write_exposure_ledger(dbs)                 # global cross-executor exposure for the veto
    eqinfo = update_equity_and_breaker(hdrs, env)
    blocked = bool(eqinfo.get("blocked"))
    sent = 0
    for pair in pairs:
        asset = build_asset(env, hdrs, pair, positions, blocked)
        key = (asset["signal"], bool(asset["position"]), asset["order_state"], asset["status"])
        # JSON round-trips tuples as lists — normalize before comparing, else
        # every sweep "detects" a false change (tuple != list in Python).
        prev = state.get(pair, {}).get("key")
        prev = tuple(prev) if prev is not None else None
        text = format_asset_status(asset)
        if notify_mode == "full" or key != prev:
            if send(env, text):
                sent += 1
        state[pair] = {"key": list(key), "signal": asset["signal"],
                       "asof": datetime.now(timezone.utc).isoformat()}
    policy.write_json(STATE_PATH, state)
    sent += notify_trade_events(env, dbs)
    return sent


def open_stake(db: Path | None) -> float:
    """Read-only sum of open stake (USD) in one executor DB. 0.0 if DB absent."""
    if not db or not db.exists():
        return 0.0
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        v = con.execute("SELECT COALESCE(SUM(stake_amount),0) FROM trades WHERE is_open=1").fetchone()[0]
        con.close()
        return float(v or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def write_exposure_ledger(dbs: dict[str, Path]) -> dict:
    """Persist the cross-executor open-exposure ledger consumed by every
    confirm_trade_entry so the SINGLE portfolio cap is enforced GLOBALLY, not per
    process. Read-only w.r.t. trading: it only records what each executor already
    holds. Includes both known executor names (a missing DB contributes 0)."""
    execs = {"daily": 0.0, "fast": 0.0, "swing": 0.0}
    for label, path in dbs.items():
        execs[label] = round(open_stake(path), 2)
    payload = {"executors": execs, "total": round(sum(execs.values()), 2),
               "asof": datetime.now(timezone.utc).isoformat()}
    policy.write_json(policy.open_exposure_path(), payload)
    return payload


def notify_trade_events(env: dict, dbs) -> int:
    """Emoji trade-alert pipeline (owner request 2026-10-21). READ-ONLY on the executor DB(s).

    Diffs the Freqtrade trades table(s) + the risk-rejection log against the last
    notified watermark (app/state/trade_events.json) and sends one clear message per
    lifecycle event: 🟢 BUY → ✅ FILLED on a new open trade, 🔴 EXIT → 💰/💸 outcome on
    a close, ⚠️ RISK REJECTED for each new policy veto. Accepts a single Path, None, or
    a {label: Path} dict covering BOTH executors (a fast fill then alerts the owner too).
    With two DBs, ids namespace as "label:id" since each executor has its own
    autoincrement. A brand-new state file initializes from current data WITHOUT
    replaying history (no spam across restarts). This monitor still never places or
    alters an order — the events were decided and executed by the Freqtrade executors.
    """
    if dbs is None:
        sources: list[tuple[str | None, Path]] = []
    elif isinstance(dbs, dict):
        sources = [(label, p) for label, p in dbs.items()]
    else:
        sources = [(None, Path(dbs))]
    multi = len(sources) > 1

    state = policy.read_json(TRADE_EVENTS_PATH)
    rejections = policy.read_json(policy.rejections_path()).get("items", [])
    n = 0

    def _send(text: str) -> None:
        nonlocal n
        if send(env, text):
            n += 1

    def _key(label, tid):
        return f"{label}:{tid}" if multi else tid

    trades: list[tuple[str | None, dict]] = []
    for label, db in sources:
        if db and Path(db).exists():
            try:
                con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                for r in con.execute("SELECT * FROM trades ORDER BY id").fetchall():
                    trades.append((label, dict(r)))
                con.close()
            except Exception:  # noqa: BLE001
                pass

    known = bool(state.get("known"))
    open_ids = set(state.get("open_ids", []))
    closed_ids = set(state.get("closed_ids", []))

    if not known:
        open_ids = {_key(l, t["id"]) for l, t in trades if t["is_open"]}
        closed_ids = {_key(l, t["id"]) for l, t in trades if not t["is_open"]}
        known = True
    else:
        cur_open = {_key(l, t["id"]) for l, t in trades if t["is_open"]}
        cur_closed = {_key(l, t["id"]) for l, t in trades if not t["is_open"]}
        for label, t in trades:
            k = _key(label, t["id"])
            if t["is_open"] and k not in open_ids and k not in closed_ids:
                _send(format_trade_entry(t))                 # 🟢 BUY (SUBMITTED)
                _send(format_trade_filled(t))                # ✅ confirmed position record
                open_ids.add(k)
            elif (not t["is_open"]) and k in open_ids and k not in closed_ids:
                _send(format_trade_exit(t))                  # 🔴 EXIT observed
                _send(format_trade_outcome(t))               # 💰/💸 recorded outcome
                open_ids.discard(k)
                closed_ids.add(k)
        # trades that opened AND closed between two polls: report the outcome once
        for label, t in trades:
            k = _key(label, t["id"])
            if (not t["is_open"]) and k not in closed_ids and k not in open_ids:
                _send(format_trade_outcome(t))
                closed_ids.add(k)
        open_ids = {k for k in open_ids if k in cur_open} | (cur_open - closed_ids)

    last_rej = int(state.get("last_rejection_count", 0))
    if len(rejections) > last_rej:
        for rej in rejections[last_rej:]:
            _send(format_risk_rejection(rej))                # ⚠️ veto with explanation
        last_rej = len(rejections)

    policy.write_json(TRADE_EVENTS_PATH, {
        "known": known, "open_ids": sorted(open_ids, key=str), "closed_ids": sorted(closed_ids, key=str),
        "last_rejection_count": last_rej,
        "asof": datetime.now(timezone.utc).isoformat(),
    })
    return n


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
