"""Rolling performance metrics for the UnboundBot learning layer (Phase D).

Pure, deterministic, IO-free functions that turn a list of CLOSED trade records into
per-(pair, family) statistics and the two decisions the self-learning loop needs:

  * STRATEGY GATE  — should_demote(): a pair/family that has produced enough closed
    trades (n >= N_MIN) but a NON-POSITIVE after-fee expectancy is flagged for demotion
    to RESEARCH_ONLY (stop new live orders). Promotion is never automatic (it needs a
    fresh backtest + owner approval) so the gate cannot flap.
  * EVIDENCE-SCALED SIZING — size_multiplier(): grow a pair's stake only after enough
    evidence and only proportionally to its average R-multiple, clamped to [1.0, 2.0]
    and defaulted to exactly 1.0 until the evidence threshold is met (so behaviour is
    unchanged on a young account).

A "record" is any mapping with keys: pair, family, and r (R-multiple, the realized
profit measured in units of the trade's planned risk) and pnl (realized PnL in USD,
after fees). Missing/None values are treated fail-closed (ignored, never as 0 profit).
"""
from __future__ import annotations

from typing import Iterable

# Learning-loop constants (owner-approved plan Phase D/§3).
N_MIN = 20                 # closed trades before an edge (or lack of it) is "evidence"
SCALE_MIN = 1.0
SCALE_MAX = 2.0            # never more than 2x the bounded per-pair base stake


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def summarize(records: Iterable[dict]) -> dict:
    """Aggregate closed-trade records into stable metrics.

    Returns {n, win_rate, avg_R, expectancy_R, profit_factor, gross_win, gross_loss,
    realized_pnl}. All values are None when there is no data (never a fabricated 0), so
    callers can tell 'no evidence' from 'evidence of zero'. Deterministic for a given
    input list (order-independent).
    """
    rs: list[float] = []
    pnls: list[float] = []
    for rec in records:
        r = rec.get("r")
        if r is not None:
            rs.append(float(r))
        p = rec.get("pnl")
        if p is not None:
            pnls.append(float(p))
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_R": None, "expectancy_R": None,
                "profit_factor": None, "gross_win": None, "gross_loss": None,
                "realized_pnl": None}
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)          # positive magnitude
    avg_r = sum(rs) / n
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "avg_R": round(avg_r, 4),
        "expectancy_R": round(avg_r, 4),      # expectancy measured in R units
        "profit_factor": (round(pf, 4) if pf not in (None, float("inf")) else pf),
        "gross_win": round(gross_win, 4),
        "gross_loss": round(gross_loss, 4),
        "realized_pnl": round(sum(pnls), 6) if pnls else None,
    }


def by_pair_family(records: Iterable[dict]) -> dict[str, dict]:
    """Group closed-trade records by 'pair|family' and summarize each group."""
    groups: dict[str, list[dict]] = {}
    for rec in records:
        key = f"{rec.get('pair')}|{rec.get('family')}"
        groups.setdefault(key, []).append(rec)
    return {k: summarize(v) for k, v in groups.items()}


def should_demote(stats: dict, n_min: int = N_MIN) -> bool:
    """Fail-closed demotion gate: enough closed trades AND a non-positive expectancy.
    'Not enough data' is NEVER a demotion (we do not punish young strategies)."""
    n = stats.get("n") or 0
    exp = stats.get("expectancy_R")
    if n < n_min or exp is None:
        return False
    return exp <= 0.0


def size_multiplier(stats: dict, n_min: int = N_MIN,
                    scale_max: float = SCALE_MAX) -> float:
    """Evidence-scaled sizing multiplier, defaulting to 1.0 (no change) until the pair
    has >= n_min closed trades; then m = clamp(1 + 0.5*avg_R, 1.0, scale_max). A losing
    or flat edge keeps m at 1.0 (the 1.0 floor), so sizing never shrinks below base
    here — the strategy GATE handles bad strategies by demoting them."""
    n = stats.get("n") or 0
    avg_r = stats.get("avg_R")
    if n < n_min or avg_r is None:
        return 1.0
    return round(_clamp(1.0 + 0.5 * float(avg_r), SCALE_MIN, scale_max), 4)
