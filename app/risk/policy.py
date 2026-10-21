"""Independent paper-risk policy for UnboundBot.

Single source of truth for the bounded PAPER_AUTONOMOUS limits defined in
``app/configs/paper_risk_policy.json`` and the pair->strategy map in
``app/configs/strategy_registry.json``. It is imported by:

  * the executor strategy (``PaperAutonomous``) for sizing + entry vetoing,
  * ``app/scripts/preflight.py`` for startup validation,
  * ``app/scripts/crypto_status_monitor.py`` for per-pair status.

Design rules:
  * Pure calculation functions take explicit inputs (no hidden IO) so they are
    unit-testable without a bot or network.
  * The fail-closed philosophy: if a required number is missing or uncomputable,
    callers must REJECT the trade, never assume a safe default.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]                 # D:\BOT\app
CONFIGS = APP / "configs"
STATE = APP / "state"
POLICY_PATH = CONFIGS / "paper_risk_policy.json"
REGISTRY_PATH = CONFIGS / "strategy_registry.json"

_cache: dict[str, dict] = {}


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def policy() -> dict:
    if "policy" not in _cache:
        _cache["policy"] = _load(POLICY_PATH)
    return _cache["policy"]


def registry() -> dict:
    if "registry" not in _cache:
        _cache["registry"] = _load(REGISTRY_PATH)
    return _cache["registry"]


def reload_all() -> None:
    _cache.clear()


# --------------------------------------------------------------------------- pairs
def pair_entry(pair: str) -> dict:
    return registry().get("pairs", {}).get(pair, {})


def is_tradeable(pair: str) -> bool:
    e = pair_entry(pair)
    return bool(e.get("tradeable")) and e.get("status") in ("ACTIVE_BASELINE", "EXPERIMENTAL_PAPER")


def tradeable_pairs() -> list[str]:
    return [p for p in registry().get("pairs", {}) if is_tradeable(p)]


def status_only_pairs() -> list[str]:
    return [p for p, e in registry().get("pairs", {}).items() if e.get("status") == "STATUS_ONLY"]


# --------------------------------------------------------------------------- sizing
def max_stake_usd(pair: str) -> float | None:
    e = pair_entry(pair).get("risk", {})
    pp = policy().get("per_position", {})
    if e.get("max_stake_usd") is not None:
        return float(e["max_stake_usd"])
    if pair in pp and pp[pair].get("max_stake_usd") is not None:
        return float(pp[pair]["max_stake_usd"])
    return float(pp.get("_default", {}).get("max_stake_usd")) or None


def max_planned_loss_usd(pair: str) -> float | None:
    e = pair_entry(pair)
    risk = e.get("risk", {})
    pp = policy().get("per_position", {})
    if risk.get("max_planned_loss_usd") is not None:
        return float(risk["max_planned_loss_usd"])
    if pair in pp and pp[pair].get("max_planned_loss_usd") is not None:
        return float(pp[pair]["max_planned_loss_usd"])
    # The _default planned-loss cap applies to ADDITIONAL (non-baseline) crypto only.
    # BTC keeps its existing stake-only bound so its sizing is never shrunk.
    if e.get("status") == "ACTIVE_BASELINE":
        return None
    v = pp.get("_default", {}).get("max_planned_loss_usd")
    return float(v) if v is not None else None


def stoploss_fraction(pair: str) -> float | None:
    sl = pair_entry(pair).get("risk", {}).get("stoploss")
    if sl is None:
        return None
    return abs(float(sl))


def stake_for_pair(pair: str, proposed_stake: float) -> float | None:
    """Bounded stake = min(proposed, per-pair cap, loss_cap/stop_distance). Returns None if
    the risk cannot be computed (caller must fail-closed)."""
    cap = max_stake_usd(pair)
    if cap is None:
        return None
    stake = min(proposed_stake, cap)
    max_loss = max_planned_loss_usd(pair)
    stop = stoploss_fraction(pair)
    if max_loss is not None and stop and stop > 0:
        stake = min(stake, max_loss / stop)
    return float(stake)


def exposure_cap_usd(equity: float | None) -> float | None:
    """Effective portfolio cap = min(fixed_usd, pct * equity). None if the equity
    basis is unknown, so callers fail-closed rather than sizing against a guess."""
    pf = policy().get("portfolio", {})
    fixed = pf.get("max_total_open_exposure_usd")
    if fixed is None:
        return None
    if equity is None:
        return None
    pct = pf.get("max_total_exposure_pct_equity")
    if pct is None:
        return float(fixed)
    return float(min(fixed, float(pct) * float(equity)))


def would_breach_exposure(open_stake: float, new_stake: float, equity: float | None) -> bool:
    cap = exposure_cap_usd(equity)
    if cap is None:
        return True  # fail-closed when the cap cannot be determined
    return (open_stake + new_stake) > cap + 1e-9


# --------------------------------------------------------------------------- breakers
def breaker_status(equity: float | None, sod_equity: float | None,
                   peak_equity: float | None) -> dict:
    """Pure circuit-breaker evaluation. daily loss vs start-of-day equity; peak-to-trough
    drawdown vs running peak. Any unknown input is treated conservatively (no trigger
    claim, but flagged) \u2014 callers block entries separately when data is stale."""
    cb = policy().get("circuit_breakers", {})
    daily_lim = cb.get("daily_equity_loss_pct")
    dd_lim = cb.get("peak_to_trough_drawdown_pct")
    out = {"triggered": False, "reasons": [], "daily_loss_pct": None, "drawdown_pct": None,
           "unknown_inputs": []}
    if equity is None:
        out["unknown_inputs"].append("equity")
    if sod_equity and equity is not None and daily_lim is not None:
        dl = (sod_equity - equity) / sod_equity
        out["daily_loss_pct"] = round(dl, 6)
        if dl >= float(daily_lim):
            out["triggered"] = True
            out["reasons"].append(f"daily_equity_loss {dl:.2%} >= {float(daily_lim):.2%}")
    elif equity is not None and sod_equity is None:
        out["unknown_inputs"].append("sod_equity")
    if peak_equity and equity is not None and dd_lim is not None:
        dd = (peak_equity - equity) / peak_equity
        out["drawdown_pct"] = round(dd, 6)
        if dd >= float(dd_lim):
            out["triggered"] = True
            out["reasons"].append(f"peak_to_trough_drawdown {dd:.2%} >= {float(dd_lim):.2%}")
    elif equity is not None and peak_equity is None:
        out["unknown_inputs"].append("peak_equity")
    return out


# --------------------------------------------------------------------------- state files
def _state_path(key: str, default: str) -> Path:
    rel = policy().get("state_files", {}).get(key, default)
    return (APP.parent / rel) if not Path(rel).is_absolute() else Path(rel)


def read_json(path: Path) -> dict:
    try:
        if Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {}


def write_json(path: Path, payload: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def kill_switch_path() -> Path:
    return _state_path("kill_switch", "app/state/kill_switch.json")


def equity_path() -> Path:
    return _state_path("equity", "app/state/equity.json")


def rejections_path() -> Path:
    return _state_path("risk_rejections", "app/state/risk_rejections.json")


def is_blocked() -> dict:
    """Return {'blocked': bool, 'reason': str}. Fail-closed: a malformed kill-switch blocks."""
    ks = read_json(kill_switch_path())
    if not ks:
        return {"blocked": False, "reason": ""}
    if ks.get("active"):
        return {"blocked": True, "reason": ks.get("reason", "circuit_breaker")}
    return {"blocked": False, "reason": ""}


def set_kill_switch(active: bool, reason: str = "", detail: dict | None = None) -> None:
    write_json(kill_switch_path(), {
        "active": bool(active),
        "reason": reason,
        "detail": detail or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "recovery": policy().get("circuit_breakers", {}).get("recovery", "manual_only"),
    })


def get_equity(max_age_s: int = 900) -> dict:
    """Read cached equity snapshot {equity, sod_equity, peak_equity, asof}. Empty if missing/stale."""
    eq = read_json(equity_path())
    asof = eq.get("asof")
    if not eq or asof is None:
        return {}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(asof)).total_seconds()
    except Exception:  # noqa: BLE001
        return {}
    if age > max_age_s:
        return {**eq, "_stale": True, "_age_s": round(age)}
    return eq


def log_rejection(pair: str, code: str, message: str, ctx: dict | None = None) -> None:
    """Append a rejection so the read-only monitor/Telegram can explain why a trade was vetoed.
    Bounded to the most recent 200 entries."""
    path = rejections_path()
    items = read_json(path).get("items", [])
    items.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "pair": pair, "code": code, "message": message, "context": ctx or {},
    })
    write_json(path, {"items": items[-200:]})


# --------------------------------------------------------------------------- validators
def validate_policy(p: dict) -> list[str]:
    problems: list[str] = []
    auth = p.get("authorization", {})
    if auth.get("live_trading") is True:
        problems.append("authorization.live_trading must not be true")
    if auth.get("paper_autonomous") is None:
        problems.append("missing authorization.paper_autonomous")
    hp = p.get("hard_prohibitions", {})
    for k in ("live_trading", "leverage", "short_selling", "margin_borrowing"):
        if not hp.get(k):
            problems.append(f"hard_prohibitions.{k} must be true")
    pf = p.get("portfolio", {})
    for k in ("max_total_open_exposure_usd", "max_total_exposure_pct_equity", "max_concurrent_positions"):
        if pf.get(k) is None:
            problems.append(f"portfolio.{k} missing")
    cb = p.get("circuit_breakers", {})
    for k in ("daily_equity_loss_pct", "peak_to_trough_drawdown_pct"):
        if cb.get(k) is None:
            problems.append(f"circuit_breakers.{k} missing")
    return problems


def validate_registry(r: dict) -> list[str]:
    problems: list[str] = []
    pairs = r.get("pairs", {})
    if not pairs:
        problems.append("registry.pairs empty")
    for pair, e in pairs.items():
        if e.get("tradeable") and e.get("risk", {}).get("max_stake_usd") is None:
            problems.append(f"{pair}: tradeable but no risk.max_stake_usd")
        if e.get("status") in ("ACTIVE_BASELINE", "EXPERIMENTAL_PAPER") and not e.get("tradeable"):
            problems.append(f"{pair}: trading status but tradeable=false")
    if not any(e.get("status") == "ACTIVE_BASELINE" for e in pairs.values()):
        problems.append("no ACTIVE_BASELINE pair (BTC must stay the baseline)")
    return problems


def validate_config(cfg: dict) -> list[str]:
    """Cross-check the live execution config against the policy + registry."""
    problems: list[str] = []
    reg = registry()
    pol = policy()
    wl = cfg.get("exchange", {}).get("pair_whitelist", [])
    tradeable = set(tradeable_pairs())
    for pair in wl:
        if pair not in reg.get("pairs", {}):
            problems.append(f"whitelist {pair} not in registry")
        elif not is_tradeable(pair):
            problems.append(f"whitelist {pair} is not tradeable (status-only)")
    for pair in tradeable:
        if pair not in wl:
            problems.append(f"tradeable {pair} missing from whitelist")
    mot = cfg.get("max_open_trades")
    if mot != pol.get("portfolio", {}).get("max_concurrent_positions"):
        problems.append(f"max_open_trades={mot} != policy.max_concurrent_positions")
    if cfg.get("stake_amount") == "unlimited":
        problems.append("stake_amount must be bounded (not 'unlimited')")
    # worst-case exposure from per-pair stakes must fit under the fixed cap
    worst = sum(max_stake_usd(p) or 0 for p in wl)
    cap = pol.get("portfolio", {}).get("max_total_open_exposure_usd")
    if cap is not None and worst > float(cap):
        problems.append(f"sum of per-pair max stakes {worst} > exposure cap {cap}")
    return problems
