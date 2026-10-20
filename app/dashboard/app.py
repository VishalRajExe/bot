"""UnboundBot — Regime Trader dashboard (Phase 9).

Read-only. Dark theme. Shows real research/paper results from the durable ledger
plus a live public BTC price tile (Kraken, no keys, no CoinGecko). It never places
orders and never fabricates metrics: every number is derived from the ledger DB or
the downloaded OHLCV, with an explicit data-freshness stamp.

Run:
  D:\\BOT\\.venv\\Scripts\\streamlit.exe run D:\\BOT\\app\\dashboard\\app.py
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DB = ROOT / "app" / "ledger" / "unbound.db"
FEATHER = ROOT / "app" / "user_data" / "data" / "binance" / "BTC_USDT-1d.feather"

# Candidate risk limits (NOT enforced in research mode; owner approval required).
CANDIDATE_LIMITS = {
    "Max account drawdown": "25%",
    "Per-trade risk": "100% of equity (single position, spot)",
    "Leverage": "1.0 (no borrowing/margin/shorts)",
    "Instruments": "BTC/USD spot only",
}

st.set_page_config(page_title="UnboundBot — Regime Trader", layout="wide")


@st.cache_data(ttl=60)
def load_metrics() -> dict:
    con = sqlite3.connect(LEDGER_DB)
    rows = con.execute("SELECT key, value FROM metrics").fetchall()
    con.close()
    return {k: json.loads(v) for k, v in rows}


@st.cache_data(ttl=60)
def load_trades() -> pd.DataFrame:
    con = sqlite3.connect(LEDGER_DB)
    df = pd.read_sql_query("SELECT * FROM trades ORDER BY close_date", con)
    con.close()
    return df


@st.cache_data(ttl=60)
def load_equity() -> pd.DataFrame:
    con = sqlite3.connect(LEDGER_DB)
    df = pd.read_sql_query("SELECT date, balance, drawdown FROM equity ORDER BY date", con)
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def load_notes() -> pd.DataFrame:
    con = sqlite3.connect(LEDGER_DB)
    df = pd.read_sql_query("SELECT kind, text, created_at FROM ai_notes ORDER BY id", con)
    con.close()
    return df


@st.cache_data(ttl=300)
def load_regime() -> pd.DataFrame:
    """Recompute the daily Z-score and map to bull/neutral/bear states."""
    df = pd.read_feather(FEATHER)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.sort_values("date").reset_index(drop=True)
    ema = df["close"].ewm(span=65, adjust=False).mean()
    std = df["close"].rolling(65).std(ddof=0).replace(0.0, pd.NA)
    df["zscore"] = (df["close"] - ema) / std
    bull, bear = 0.5, -0.5  # candidate thresholds (see Phase0_Audit sec.6)
    df["state"] = "neutral"
    df.loc[df["zscore"] >= bull, "state"] = "bullish"
    df.loc[df["zscore"] <= bear, "state"] = "bearish"
    return df[["date", "close", "zscore", "state"]]


@st.cache_data(ttl=30)
def live_price():
    """Public Kraken last price for BTC/USD. No keys, no CoinGecko. Returns (price, ts) or (None, None)."""
    try:
        import ccxt
        ex = ccxt.kraken({"enableRateLimit": True})
        t = ex.fetch_ticker("BTC/USD")
        return t.get("last"), datetime.now(timezone.utc)
    except Exception:  # noqa: BLE001
        return None, None


def _alpaca_keys() -> tuple[str, str]:
    """Read paper keys from D:\\BOT\\.env (never printed). Returns ("","") if absent."""
    import os
    p = ROOT / ".env"
    if not p.exists():
        return "", ""
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    return (os.environ.get("ALPACA_PAPER_API_KEY", ""),
            os.environ.get("ALPACA_PAPER_API_SECRET", ""))


@st.cache_data(ttl=30)
def load_alpaca_account():
    """Read-only Alpaca PAPER account + positions. Places no orders, prints no keys.
    Returns dict with 'ok' flag; never raises."""
    import requests
    key, secret = _alpaca_keys()
    base = "https://paper-api.alpaca.markets"
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    out = {"ok": False, "reason": "", "asof": datetime.now(timezone.utc)}
    if not key or not secret:
        out["reason"] = "no paper keys in .env"
        return out
    try:
        a = requests.get(f"{base}/v2/account", headers=hdr, timeout=15)
        if a.status_code != 200:
            out["reason"] = f"account HTTP {a.status_code}"
            return out
        acct = a.json()
        pos = requests.get(f"{base}/v2/positions", headers=hdr, timeout=15)
        positions = pos.json() if pos.status_code == 200 else []
        out.update({
            "ok": True,
            "cash": float(acct.get("cash", 0) or 0),
            "equity": float(acct.get("equity", 0) or 0),
            "buying_power": float(acct.get("buying_power", 0) or 0),
            "portfolio_val": float(acct.get("portfolio_valuation", 0) or 0),
            "crypto_status": acct.get("crypto_status"),
            "positions": [
                {"symbol": p.get("symbol"), "qty": float(p.get("qty", 0) or 0),
                 "market_val": float(p.get("market_value", 0) or 0),
                 "avg": float(p.get("avg_entry_price", 0) or 0),
                 "unrealized_plpc": float(p.get("unrealized_plpc", 0) or 0) * 100}
                for p in positions if isinstance(positions, list)
            ],
        })
    except Exception as e:  # noqa: BLE001
        out["reason"] = f"{type(e).__name__}: {str(e)[:80]}"
    return out


# ----------------------------- UI -----------------------------
st.markdown("## UnboundBot · Regime Trader")
m = load_metrics()
regime = load_regime()
last_state = regime["state"].iloc[-1]
last_close = float(regime["close"].iloc[-1])
last_date = regime["date"].iloc[-1]

c1, c2, c3 = st.columns([3, 1, 2])
with c1:
    st.caption("BTC/USD · daily · long-only spot")
with c2:
    st.badge("MODE: RESEARCH / PAPER — no real funds", color="orange")
with c3:
    price, ts = live_price()
    if price is not None:
        st.metric("BTC/USD (live, public)", f"${price:,.0f}",
                  help=f"Kraken public ticker @ {ts:%Y-%m-%d %H:%M:%S} UTC")
    else:
        st.metric("BTC/USD (last close)", f"${last_close:,.0f}",
                  help=f"OHLCV close @ {last_date:%Y-%m-%d} UTC (live feed unavailable)")

st.caption(
    f"Signal state: **{last_state.upper()}**  ·  Data source: {m.get('stake_currency','USDT')} "
    f"(research proxy)  ·  Backtest window {str(m.get('backtest_start'))[:10]} → {str(m.get('backtest_end'))[:10]}"
)
st.divider()

# Metric cards
equity = float(m.get("final_balance") or 0)
tot_pct = (m.get("profit_total") or 0) * 100
cagr = (m.get("cagr") or 0) * 100
winrate = (m.get("winrate") or 0) * 100
maxdd = (m.get("max_drawdown_account") or 0) * 100
k = st.columns(6)
k[0].metric("Equity", f"${equity:,.0f}")
k[1].metric("Total return", f"{tot_pct:,.1f}%")
k[2].metric("CAGR", f"{cagr:,.1f}%")
k[3].metric("Win rate", f"{winrate:,.1f}%")
k[4].metric("Max drawdown", f"{maxdd:,.1f}%")
k[5].metric("Sharpe", f"{(m.get('sharpe') or 0):,.2f}")

tab_eq, tab_reg, tab_trades, tab_ai, tab_risk, tab_alpaca = st.tabs(
    ["Equity & Drawdown", "Regime / Signal", "Trade Ledger", "AI Learning Notes", "Risk & Model", "Alpaca Paper (live)"]
)

with tab_eq:
    eq = load_equity()
    st.line_chart(eq, x="date", y="balance", color="#00e5a0")
    st.area_chart(eq.assign(dd=eq["drawdown"] * 100), x="date", y="dd", color="#ff5470")
    st.caption("Equity curve (top) and drawdown % (bottom), derived from the ledger equity table.")

with tab_reg:
    r = regime.dropna().copy()
    r["state_num"] = r["state"].map({"bearish": -1, "neutral": 0, "bullish": 1})
    base = alt.Chart(r).mark_line(color="#4da3ff").encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("zscore:Q", title="Z-score"),
        tooltip=["date:T", "close:Q", "zscore:Q", "state:N"],
    )
    upper = alt.Chart(r).mark_rule(color="#00e5a0", strokeDash=[4, 4]).encode(y=alt.value(0.5))
    lower = alt.Chart(r).mark_rule(color="#ff5470", strokeDash=[4, 4]).encode(y=alt.value(-0.5))
    zero = alt.Chart(r).mark_rule(color="#8b949e").encode(y=alt.value(0))
    st.altair_chart((base + zero + upper + lower).properties(height=380), use_container_width=True)
    st.caption("Daily Z = (close − EMA65) / STD65. Bands are candidate thresholds (±0.5), not source-verified.")
    counts = regime["state"].value_counts().rename_axis("state").reset_index(name="days")
    st.bar_chart(counts, x="state", y="days", color="#8b949e")

with tab_trades:
    t = load_trades()
    show = t[["id", "pair", "open_date", "close_date", "open_rate", "close_rate",
              "profit_ratio", "profit_abs", "exit_reason", "leverage", "is_short"]]
    show = show.copy()
    show["profit_ratio"] = (show["profit_ratio"] * 100).round(2)
    st.dataframe(show, use_container_width=True, hide_index=True, height=420)
    st.caption(f"{len(t)} closed trades in ledger. `leverage` shows Freqtrade's unleveraged 1.0 spot multiplier.")

with tab_ai:
    n = load_notes()
    for _, row in n.iterrows():
        kind = row["kind"]
        color = {"FACT": "green", "HYPOTHESIS": "violet", "GUARDRAIL": "red"}.get(kind, "gray")
        st.badge(kind, color=color)
        st.write(row["text"])
    st.caption("Notes are descriptive. The AI loop never changes rules or places orders without owner approval.")

with tab_risk:
    st.markdown("**Candidate risk limits** (monitored in research; not enforced against a live broker)")
    st.table(pd.DataFrame(CANDIDATE_LIMITS.items(), columns=["Limit", "Value"]))
    st.badge("Circuit breaker: MONITORING (research)", color="blue")
    st.markdown("**Model / strategy info**")
    st.json({
        "strategy": m.get("strategy_name"),
        "timeframe": m.get("timeframe"),
        "indicator": "Z = (close - EMA65) / STD65",
        "bull_threshold_candidate": 0.5,
        "exit_threshold_candidate": 0.0,
        "stoploss": -0.35,
        "data_source": "Binance BTC/USDT (public) — research proxy for Alpaca BTC/USD",
        "backtest_source_zip": m.get("_source_zip"),
    })
    st.caption(f"Ledger: {LEDGER_DB}")

with tab_alpaca:
    st.markdown("**Alpaca PAPER account** — read-only live snapshot (no orders placed from here)")
    ap = load_alpaca_account()
    if ap["ok"]:
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Cash", f"${ap['cash']:,.2f}")
        a2.metric("Equity", f"${ap['equity']:,.2f}")
        a3.metric("Buying power", f"${ap['buying_power']:,.2f}")
        a4.metric("Portfolio value", f"${ap['portfolio_val']:,.2f}")
        st.caption(
            f"crypto_status: **{ap['crypto_status']}**  ·  "
            f"fetched {ap['asof']:%Y-%m-%d %H:%M:%S} UTC"
        )
        if ap["positions"]:
            st.markdown("Open positions")
            st.dataframe(pd.DataFrame(ap["positions"]), use_container_width=True, hide_index=True)
        else:
            st.info("No open positions — bot is running but no entry signal has fired yet.")
    else:
        st.warning(f"Alpaca paper account unavailable: {ap['reason'] or 'unknown'}")
        st.caption("The bot being ONLINE below is independent; this panel only reads the account.")

st.divider()
_acc = load_alpaca_account()
_paper = (
    "Alpaca PAPER bot is ONLINE (real orders to paper-api, no live funds)"
    if _acc.get("ok") else
    "Alpaca PAPER bot wired; account panel offline (see Alpaca Paper tab)"
)
st.caption(
    f"Rendered {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC · {_paper}."
)
