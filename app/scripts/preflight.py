"""Preflight safety verifier — Freqtrade-fundamentals ported to our layer.

Freqtrade validates config schema, but it does NOT encode *our* product guardrails
(paper-only endpoint, spot/no-short/no-leverage, bounded sizing, an owner risk-
approval record). This module turns those rules into an explicit, testable gate so
actionable trading stays DISABLED until every check passes and an owner approval
exists. It is READ-ONLY: it never places an order and never starts the bot.

Model: audit_config(cfg, strategy_meta) -> (ready, findings). Each finding has
level in {BLOCK, WARN, OK}. `ready` is True only with zero BLOCK and an existing
risk-approval record (we do not invent one).

Usage:
  python app/scripts/preflight.py            # human report + exit code
Exit codes: 0 = trading-ready gates pass, 3 = BLOCKED (missing approval/config),
4 = CRITICAL (live endpoint or unsafe config).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPER_CFG = ROOT / "app" / "configs" / "config.alpaca.paper.json"
RISK_APPROVAL = ROOT / "app" / "configs" / "risk_approval.json"

PAPER_HOST = "paper-api.alpaca.markets"
LIVE_HOSTS = ("api.alpaca.markets", "trade-polygon", "live")


def _url_trader(cfg: dict) -> str:
    return (cfg.get("exchange", {}).get("ccxt_config", {})
            .get("urls", {}).get("api", {}).get("trader", "") or "")


def audit_config(cfg: dict, strategy_meta: dict) -> tuple[bool, list[dict]]:
    """Pure gate. Returns (ready, findings). No IO, no orders."""
    f: list[dict] = []

    def add(level, code, msg):
        f.append({"level": level, "code": code, "message": msg})

    # 1. Endpoint must be Alpaca PAPER; a live host is CRITICAL.
    trader = _url_trader(cfg)
    if not trader:
        add("BLOCK", "ENDPOINT_MISSING", "No trader URL override — orders would hit the default (live) host.")
    elif any(h in trader for h in LIVE_HOSTS) and PAPER_HOST not in trader:
        add("BLOCK", "LIVE_ENDPOINT", f"Trader endpoint '{trader}' is NOT the paper host.")
    elif PAPER_HOST in trader:
        add("OK", "PAPER_ENDPOINT", f"Trader endpoint is paper: {trader}")
    else:
        add("BLOCK", "ENDPOINT_UNKNOWN", f"Unrecognized trader endpoint: {trader}")

    # 2. No committed credentials (keys must be injected from env at runtime).
    ex = cfg.get("exchange", {})
    if ex.get("key") or ex.get("secret"):
        add("BLOCK", "INLINE_SECRETS", "Credentials found in config; must be empty and injected via env.")
    else:
        add("OK", "NO_INLINE_SECRETS", "Config carries no credentials.")

    # 3. dry_run + endpoint consistency.
    dry = cfg.get("dry_run")
    if dry is False and PAPER_HOST in trader:
        add("OK", "PAPER_LIVE_ORDERS", "dry_run=false but endpoint is paper -> orders go to Alpaca PAPER only.")
    elif dry is True:
        add("OK", "DRY_RUN", "dry_run=true (local simulation, no broker orders).")
    else:
        add("WARN", "DRY_RUN_STATE", f"dry_run={dry!r} — confirm intended execution mode.")

    # 4. Spot, no short, no leverage.
    if cfg.get("trading_mode") != "spot":
        add("BLOCK", "NOT_SPOT", f"trading_mode='{cfg.get('trading_mode')}' must be spot.")
    if cfg.get("margin_mode"):
        add("BLOCK", "MARGIN_ON", f"margin_mode='{cfg.get('margin_mode')}' must be empty.")
    if strategy_meta.get("can_short"):
        add("BLOCK", "SHORT_ENABLED", "Strategy can_short=True is not allowed.")
    lev = strategy_meta.get("leverage", 1.0)
    if float(lev or 1.0) != 1.0:
        add("BLOCK", "LEVERAGE_ON", f"Leverage {lev} != 1.0 (no borrowing).")
    if not any(x["code"] in ("NOT_SPOT", "MARGIN_ON", "SHORT_ENABLED", "LEVERAGE_ON") for x in f):
        add("OK", "SPOT_NO_SHORT_NO_LEVERAGE", "Spot, long-only, unleveraged.")

    # 5. Bounded sizing (docs/Rules.md §5: never leave unlimited stake enabled).
    mot = cfg.get("max_open_trades")
    if not isinstance(mot, int) or mot < 1:
        add("BLOCK", "UNBOUNDED_OPEN_TRADES", f"max_open_trades={mot!r} must be a positive bound.")
    if cfg.get("stake_amount") == "unlimited":
        add("BLOCK", "UNLIMITED_STAKE", "stake_amount='unlimited' => all-in position; bounded sizing is mandatory.")
    else:
        add("OK", "STAKE_BOUND", f"stake_amount={cfg.get('stake_amount')}")

    # 6. Risk controls configured.
    if int(strategy_meta.get("protections_count", 0) or 0) < 1:
        add("BLOCK", "NO_PROTECTIONS", "No risk protections configured.")
    else:
        add("OK", "PROTECTIONS", f"{strategy_meta['protections_count']} protection(s) configured.")
    sl = strategy_meta.get("stoploss")
    if sl is None or float(sl) >= 0:
        add("BLOCK", "NO_STOPLOSS", f"stoploss={sl!r} missing or non-negative.")

    # 7. Thresholds documented (candidate values must be explicit, not None).
    for k in ("bull_threshold", "exit_threshold"):
        if strategy_meta.get(k) is None:
            add("BLOCK", "THRESHOLD_UNSET", f"{k} unset — entries must fail closed.")

    ready = (not any(x["level"] == "BLOCK" for x in f)) and approval_exists()
    if not approval_exists():
        add("BLOCK", "RISK_APPROVAL_MISSING",
            "No owner risk-approval record (app/configs/risk_approval.json). "
            "Trading stays disabled until thresholds/limits are approved.")
    return ready, f


def approval_exists() -> bool:
    return RISK_APPROVAL.exists()


def load_strategy_meta() -> dict:
    """Import the authoritative strategy and read its safety-relevant attributes."""
    sys.path.insert(0, str(ROOT / "app" / "user_data" / "strategies"))
    meta = {"can_short": None, "leverage": 1.0, "stoploss": None,
            "bull_threshold": None, "exit_threshold": None,
            "protections_count": 0, "timeframe": None, "startup_candle_count": None}
    try:
        from BtcZScore import BtcZScore as S  # noqa: E402
        meta["can_short"] = bool(getattr(S, "can_short", False))
        meta["stoploss"] = getattr(S, "stoploss", None)
        meta["bull_threshold"] = getattr(S, "bull_threshold", None)
        meta["exit_threshold"] = getattr(S, "exit_threshold", None)
        meta["timeframe"] = getattr(S, "timeframe", None)
        meta["startup_candle_count"] = getattr(S, "startup_candle_count", None)
        prot = S.protections  # @property on class? access via fget if needed
        try:
            meta["protections_count"] = len(prot)
        except TypeError:
            fget = getattr(S.__dict__.get("protections", None), "fget", None)
            meta["protections_count"] = len(fget(None)) if fget else 0
    except Exception as e:  # noqa: BLE001
        meta["load_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return meta


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    cfg = json.loads(PAPER_CFG.read_text(encoding="utf-8"))
    meta = load_strategy_meta()
    ready, findings = audit_config(cfg, meta)

    print(f"Preflight (config={PAPER_CFG.name})")
    print(f"strategy_meta={meta}")
    for x in findings:
        print(f"  [{x['level']:5}] {x['code']}: {x['message']}")
    print(f"\nTRADING READY: {ready}")
    if any(x["code"] == "LIVE_ENDPOINT" for x in findings):
        return 4
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
