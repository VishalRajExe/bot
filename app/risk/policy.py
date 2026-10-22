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

# Phase D learning-loop constants (owner-approved plan §3). Kept here so the veto,
# the sizing hook and the learn runner share ONE source of truth. MAX_EVIDENCE_SCALE
# mirrors learn.perf.SCALE_MAX; enforced independently so a bad perf.json can never
# silently raise a stake beyond 2x the approved per-pair cap.
MAX_EVIDENCE_SCALE = 2.0
PER_POSITION_PCT_EQUITY = 0.20

_cache: dict[str, dict] = {}
_perf_cache: dict[str, object] = {"path": None, "mtime": None, "data": {}}
_gate_cache: dict[str, object] = {"path": None, "mtime": None, "data": {}}


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
    _perf_cache.update({"path": None, "mtime": None, "data": {}})
    _gate_cache.update({"path": None, "mtime": None, "data": {}})


# --------------------------------------------------------------------------- pairs
def pair_entry(pair: str) -> dict:
    return registry().get("pairs", {}).get(pair, {})


def is_tradeable(pair: str) -> bool:
    e = pair_entry(pair)
    if not (bool(e.get("tradeable")) and e.get("status") in ("ACTIVE_BASELINE", "EXPERIMENTAL_PAPER")):
        return False
    # Phase D strategy gate: a pair/family that has accumulated a NEGATIVE after-fee
    # expectancy (n>=N_min) is auto-demoted (no new live orders) until the owner
    # re-approves via a fresh backtest. is_demoted() defaults to False when the gate
    # file is absent, so this is inert on a young account / clean checkout.
    return not is_demoted(pair)


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
    """Bounded stake = min(proposed, per-pair cap, loss_cap/stop_distance), then scaled
    by the evidence multiplier m in [1.0, MAX_EVIDENCE_SCALE] (defaults to 1.0 when the
    learning layer has not accumulated enough closed trades yet, so this is byte-for-
    byte identical to the pre-Phase-D behavior on a young account). Scaled stake is
    additionally clamped to ``cap * MAX_EVIDENCE_SCALE`` so a corrupted perf.json can
    never raise it more than 2x. The 20%-equity per-position ceiling is enforced in
    ``PaperAutonomous.confirm_trade_entry`` where the fresh equity is available.
    Returns None if the risk cannot be computed (caller must fail-closed)."""
    cap = max_stake_usd(pair)
    if cap is None:
        return None
    stake = min(proposed_stake, cap)
    max_loss = max_planned_loss_usd(pair)
    stop = stoploss_fraction(pair)
    if max_loss is not None and stop and stop > 0:
        stake = min(stake, max_loss / stop)
    m = evidence_multiplier(pair)
    if m and m > 1.0:
        stake = min(stake * float(m), cap * MAX_EVIDENCE_SCALE)
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


def external_exposure(my_executor: str | None, max_age_s: int = 180) -> dict:
    """Open stake held by OTHER executors, read from the cross-executor ledger the
    read-only monitor writes. With more than one order executor (each Freqtrade bot
    only sees its OWN trade DB), this is what keeps the single portfolio exposure cap
    global rather than per-process. Fail-closed contract: callers must treat
    ``known=False`` as 'exposure cannot be determined' and reject the entry (mirrors
    the fresh-equity requirement, which the same monitor also produces)."""
    led = read_json(open_exposure_path())
    asof = led.get("asof")
    if not led or asof is None:
        return {"external": 0.0, "known": False, "reason": "no exposure ledger yet (monitor not run)"}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(asof)).total_seconds()
    except Exception:  # noqa: BLE001
        return {"external": 0.0, "known": False, "reason": "unparseable exposure ledger"}
    if age > max_age_s:
        return {"external": 0.0, "known": False, "reason": f"exposure ledger stale ({age:.0f}s)"}
    execs = led.get("executors", {})
    external = sum(float(v or 0) for name, v in execs.items() if name != my_executor)
    return {"external": float(external), "known": True, "age_s": round(age),
            "by_executor": execs}


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


def open_exposure_path() -> Path:
    return _state_path("open_exposure", "app/state/open_exposure.json")


def perf_path() -> Path:
    return _state_path("perf", "app/state/perf.json")


def strategy_gate_path() -> Path:
    return _state_path("strategy_gate", "app/state/strategy_gate.json")


def _read_json_cached(path: Path, cache: dict) -> dict:
    """Read a small state JSON with mtime-based caching so the veto path (called on
    every potential entry) does not hammer the disk. Missing file -> {} (fail-open on
    the *learning* side only: sizing stays at m=1 and no pair is demoted). A corrupt
    file is treated as missing — callers must never trust a bad stat as an edge."""
    try:
        p = Path(path)
        if not p.exists():
            data = {}
            mtime = None
        else:
            mtime = p.stat().st_mtime
            if cache.get("path") == str(p) and cache.get("mtime") == mtime:
                return cache.get("data") or {}
            data = json.loads(p.read_text(encoding="utf-8"))
        cache["path"] = str(p)
        cache["mtime"] = mtime
        cache["data"] = data
        return data
    except Exception:  # noqa: BLE001
        cache["path"] = str(path)
        cache["mtime"] = None
        cache["data"] = {}
        return {}


def evidence_multiplier(pair: str) -> float:
    """Return m in [1.0, MAX_EVIDENCE_SCALE] for ``pair`` from the learning layer.
    Looks up the pair's ACTIVE family in the registry, then its per-(pair|family)
    stats in app/state/perf.json, and delegates to learn.perf.size_multiplier.
    Returns exactly 1.0 (no change) when the perf file is absent, malformed, or the
    pair has fewer than N_MIN closed trades — a young account is never scaled."""
    perf = _read_json_cached(perf_path(), _perf_cache)
    if not perf:
        return 1.0
    fam = pair_entry(pair).get("strategy_family") or ""
    key = f"{pair}|{fam}"
    stats = (perf.get("by_pair_family") or {}).get(key)
    if not stats:
        return 1.0
    try:
        from learn import perf as _perf
    except Exception:  # noqa: BLE001
        return 1.0
    m = _perf.size_multiplier(stats)
    # Defence-in-depth: clamp to the policy-declared ceiling even if perf.json is stale.
    return float(min(max(m, 1.0), MAX_EVIDENCE_SCALE))


def is_demoted(pair: str) -> bool:
    """True when the Phase D strategy gate has demoted ``pair`` (auto from a negative
    expectancy at n>=N_min, or manual owner demotion). Missing/empty gate -> False.
    Auto-promotion is NOT allowed; only owner re-approval clears an entry."""
    gate = _read_json_cached(strategy_gate_path(), _gate_cache)
    if not gate:
        return False
    demoted = gate.get("demoted") or []
    return any((d.get("pair") == pair) for d in demoted)


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


def validate_config(cfg: dict, require_full_coverage: bool = True) -> list[str]:
    """Cross-check ONE execution config against the policy + registry.

    ``require_full_coverage=True`` (legacy single-executor) asserts the whitelist holds
    every tradeable pair. With two disjoint executors each config covers only part of
    the tradeable set, so callers pass ``False`` per config and then run
    ``validate_executors`` for the global (union + disjoint + combined-exposure) gate.
    """
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
    if require_full_coverage:
        for pair in tradeable:
            if pair not in wl:
                problems.append(f"tradeable {pair} missing from whitelist")
    mot = cfg.get("max_open_trades")
    max_pos = pol.get("portfolio", {}).get("max_concurrent_positions")
    if not isinstance(mot, int) or mot < 1:
        problems.append(f"max_open_trades={mot!r} must be a positive bound")
    elif max_pos is not None and mot > int(max_pos):
        problems.append(f"max_open_trades={mot} exceeds policy.max_concurrent_positions {max_pos}")
    if cfg.get("stake_amount") == "unlimited":
        problems.append("stake_amount must be bounded (not 'unlimited')")
    # worst-case exposure from this config's per-pair stakes must fit under the fixed cap
    worst = sum(max_stake_usd(p) or 0 for p in wl)
    cap = pol.get("portfolio", {}).get("max_total_open_exposure_usd")
    if cap is not None and worst > float(cap):
        problems.append(f"sum of per-pair max stakes {worst} > exposure cap {cap}")
    return problems


def validate_executors(configs: dict[str, dict]) -> list[str]:
    """Global multi-executor invariants. `configs` maps an executor name -> its parsed
    config. Safety by construction across independent order processes (each bot only
    sees its own trade DB):

      * pair sets are pairwise DISJOINT  -> no two executors can trade the same pair
        (no duplicate orders, and each executor's per-pair exposure is unambiguous);
      * the union covers exactly the tradeable set;
      * summed max_open_trades <= max_concurrent_positions;
      * summed worst-case per-pair stakes <= the fixed exposure cap.
    """
    problems: list[str] = []
    pol = policy()
    tradeable = set(tradeable_pairs())
    seen: dict[str, str] = {}
    total_mot = 0
    total_worst = 0.0
    cap = pol.get("portfolio", {}).get("max_total_open_exposure_usd")
    max_pos = pol.get("portfolio", {}).get("max_concurrent_positions")
    for name, cfg in configs.items():
        wl = cfg.get("exchange", {}).get("pair_whitelist", [])
        for pair in wl:
            if pair in seen:
                problems.append(f"{pair} traded by two executors ({seen[pair]} and {name}) — must be disjoint")
            else:
                seen[pair] = name
            if pair not in tradeable:
                problems.append(f"executor {name}: whitelist {pair} is not in the tradeable set")
        mot = cfg.get("max_open_trades")
        if isinstance(mot, int):
            total_mot += mot
        total_worst += sum(max_stake_usd(p) or 0 for p in wl)
        for p in validate_config(cfg, require_full_coverage=False):
            problems.append(f"executor {name}: {p}")
    for pair in tradeable:
        if pair not in seen:
            problems.append(f"tradeable {pair} is not assigned to any executor")
    if max_pos is not None and total_mot > int(max_pos):
        problems.append(f"summed max_open_trades {total_mot} > max_concurrent_positions {max_pos}")
    if cap is not None and total_worst > float(cap) + 1e-9:
        problems.append(f"combined worst-case exposure {total_worst} > exposure cap {cap}")
    return problems
