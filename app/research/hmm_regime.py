"""Phase 8 — Optional HMM regime experiment (RESEARCH ONLY, never trades).

This module is an isolated experiment. It is NOT wired into the strategy, the
risk manager, or the executor. The live/paper bot's trading behaviour is
unchanged by anything here (see docs/Phases.md Phase 8 "Default state: Not
active in trading").

What it does:
  * Fits a self-contained univariate Gaussian HMM (Baum-Welch EM, NumPy only —
    no hmmlearn/scikit-learn dependency) on BTC daily log-returns.
  * Uses FORWARD-ONLY filtering for historical/decision-time regimes, so a
    regime assigned at time t never depends on observations after t. A dedicated
    future-append invariance test proves this (P8-05). Full-sequence smoothing
    is deliberately NOT used for trading-relevant labels.
  * Walk-forward out-of-sample evaluation with a predeclared retraining cadence
    (P8-02/P8-04): the model that labels day t is fit only on data before t.
  * Compares, on identical data and a simple cost model (P8-09):
      - Buy & hold
      - Z-score long-proxy (candidate bull threshold from the baseline)
      - HMM-filter allocation (long only in the training-mean-highest regime)
  * Persists versioned artifacts + provenance, writes a regime table and
    evidence notes to the ledger, and emits a markdown report.

Safety: deterministic seeds, no external LLM, no broker access, no orders.
Run:  D:\\BOT\\.venv\\Scripts\\python.exe app/research/hmm_regime.py
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FEATHER = ROOT / "app" / "user_data" / "data" / "binance" / "BTC_USDT-1d.feather"
ART_DIR = ROOT / "app" / "research" / "artifacts"
LEDGER_DB = ROOT / "app" / "ledger" / "unbound.db"
REPORT = ROOT / "docs" / "Phase8_HMM_Report.md"
STRATEGY_VERSION = "BtcZScore@candidate-2026-10"

# ---- Predeclared experiment specification (P8-02) ---- -----------------------
@dataclass
class HMMConfig:
    feature: str = "logret"          # single daily log-return (P8-03: daily obs)
    k_candidates: tuple[int, ...] = (2, 3, 4)  # candidate state counts (P8-06)
    seed: int = 7                          # deterministic init
    em_iters: int = 60
    em_tol: float = 1e-6
    min_train_days: int = 504              # ~2y before first OOS label
    retrain_every: int = 30                # ~1 month of daily bars (cadence)
    holdout_days: int = 730                # OOS window (last ~2y)
    # Simple round-trip cost per position change (taker fee + spread proxy).
    cost_per_change: float = 0.0020
    bull_threshold: float = 0.5            # Z-score long-proxy candidate (unverified)


CFG = HMMConfig()


# ---- Gaussian HMM core (NumPy) ---- ------------------------------------------
def _log_emissions(x: np.ndarray, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
    """log b_k(x_t) for each t (T,) and state k (K,) -> (T,K)."""
    x = x[:, None]
    mu = mu[None, :]
    var = var[None, :]
    return -0.5 * np.log(2 * np.pi * var) - (x - mu) ** 2 / (2 * var)


def _forward_scalars(
    logb: np.ndarray, logA: np.ndarray, logpi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Scaled forward pass. Returns normalized filtered posteriors (T,K) and
    total log-likelihood. Uses only past+present -> causal by construction."""
    T, K = logb.shape
    alpha = np.zeros((T, K))
    c = np.zeros(T)  # per-step scaling factors (log)
    prev = logpi + logb[0]
    m = prev.max()
    w = np.exp(prev - m)
    s = w.sum()
    c[0] = m + np.log(s)
    alpha[0] = w / s
    for t in range(1, T):
        pred = alpha[t - 1] @ np.exp(logA)          # sum_j p_{t-1}(j) A_{jk}
        pred = np.maximum(pred, 1e-300)
        lp = np.log(pred) + logb[t]
        m = lp.max()
        w = np.exp(lp - m)
        s = w.sum()
        c[t] = m + np.log(s)
        alpha[t] = w / s
    return alpha, c.sum()


def _forward_backward(
    logb: np.ndarray, logA: np.ndarray, logpi: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return filtered posteriors gamma (T,K) and expected transitions xi (T-1,K,K)
    plus log-likelihood, via scaled forward-backward for EM."""
    T, K = logb.shape
    alpha, ll = _forward_scalars(logb, logA, logpi)
    # backward (scaled)
    beta = np.ones((T, K))
    logA = logA  # already log
    for t in range(T - 2, -1, -1):
        b_next = beta[t + 1] * np.exp(logb[t + 1])       # b_k(x_{t+1}) beta_{t+1}(k)
        beta[t] = np.exp(logA) @ b_next
        beta[t] = np.maximum(beta[t], 1e-300)
        beta[t] /= beta[t].sum()
    # gamma from alpha*beta
    ab = alpha * beta
    gamma = ab / ab.sum(axis=1, keepdims=True)
    # xi_t(j,k) = alpha_t(j) A_jk b_k(x_{t+1}) beta_{t+1}(k) / sum
    xi = np.zeros((T - 1, K, K))
    for t in range(T - 1):
        num = alpha[t][:, None] * np.exp(logA) * (np.exp(logb[t + 1]) * beta[t + 1])[None, :]
        denom = num.sum()
        xi[t] = num / denom if denom > 0 else num
    return gamma, xi, ll


def fit_gaussian_hmm(x: np.ndarray, K: int, cfg: HMMConfig) -> dict:
    """Baum-Welch EM for a univariate Gaussian HMM. Deterministic init from
    quantile seeds so it is reproducible (P8-02)."""
    rng = np.random.default_rng(cfg.seed)
    T = len(x)
    qs = np.quantile(x, np.linspace(0.1, 0.9, K))
    mu = np.asarray(qs, dtype=float)
    var = np.full(K, x.var() + 1e-9, dtype=float)
    A = np.full((K, K), 0.1 / (K - 1), dtype=float) if K > 1 else np.ones((1, 1))
    np.fill_diagonal(A, 0.9)
    pi = np.full(K, 1.0 / K)
    prev_ll = -np.inf
    for _ in range(cfg.em_iters):
        logb = _log_emissions(x, mu, var)
        gamma, xi, ll = _forward_backward(logb, np.log(A), np.log(pi))
        if not np.isfinite(ll):
            break
        # M-step
        gamma_sum = gamma.sum(axis=0) + 1e-12
        mu = (gamma * x[:, None]).sum(axis=0) / gamma_sum
        var = (gamma * (x[:, None] - mu[None, :]) ** 2).sum(axis=0) / gamma_sum
        var = np.maximum(var, 1e-9)
        xi_sum = xi.sum(axis=0)
        A = xi_sum / (xi_sum.sum(axis=1, keepdims=True) + 1e-12)
        pi = gamma[0] / (gamma[0].sum() + 1e-12)
        # Floor + renormalize so np.log(A)/np.log(pi) stay finite even if EM
        # collapses a state (prevents -inf -> NaN propagation, divide-by-zero warn).
        A = np.maximum(A, 1e-9)
        A /= A.sum(axis=1, keepdims=True)
        pi = np.maximum(pi, 1e-12)
        pi /= pi.sum()
        if abs(ll - prev_ll) < cfg.em_tol:
            break
        prev_ll = ll
    logb = _log_emissions(x, mu, var)
    _, ll = _forward_scalars(logb, np.log(A), np.log(pi))
    n_params = K * 2 + K * (K - 1) + (K - 1)
    bic = -2 * ll + n_params * np.log(T)
    return {"K": K, "mu": mu, "var": var, "A": A, "pi": pi,
            "loglik": float(ll), "bic": float(bic)}


def filter_regimes(x: np.ndarray, params: dict) -> np.ndarray:
    """Causal filtered posterior over states for each observation (forward-only)."""
    logb = _log_emissions(x, np.asarray(params["mu"]), np.asarray(params["var"]))
    alpha, _ = _forward_scalars(logb, np.log(np.asarray(params["A"])),
                                np.log(np.asarray(params["pi"])))
    return alpha


def select_K(x: np.ndarray, cfg: HMMConfig) -> tuple[int, dict]:
    """Pick the state count by BIC on the given (training) window (P8-06)."""
    best = None
    for K in cfg.k_candidates:
        p = fit_gaussian_hmm(x, K, cfg)
        if best is None or p["bic"] < best[1]["bic"]:
            best = (K, p)
    return best  # type: ignore[return-value]


# ---- State -> label mapping from training statistics (P8-06) ---- --------------
def label_map(mu: np.ndarray) -> dict:
    order = np.argsort(mu)              # ascending mean return
    names = ["bearish", "neutral", "bullish", "high_vol_bull"]
    out = {}
    ranked = {int(s): i for i, s in enumerate(order)}  # rank 0..K-1
    for s in range(len(mu)):
        r = ranked[s]
        if len(mu) == 2:
            lab = "bearish" if r == 0 else "bullish"
        elif len(mu) == 3:
            lab = names[r]
        else:
            lab = f"state_rank_{r}"
        out[s] = lab
    return out


# ---- Causality proof (P8-05) ---- ----------------------------------------------
def future_append_invariance(x: np.ndarray, params: dict, m: int) -> float:
    """Max abs difference in the filtered posterior at index m whether we feed
    x[:m+1] or the full x. Should be ~0 (causal). Returns that difference."""
    full = filter_regimes(x, params)
    trunc = filter_regimes(x[: m + 1], params)
    return float(np.max(np.abs(full[m] - trunc[-1])))


# ---- Evaluation helpers ---- ---------------------------------------------------
def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(-dd.min()) if len(dd) else 0.0


def evaluate(long_flag: np.ndarray, fwd_ret: np.ndarray, cost: float) -> dict:
    """Apply a next-day long/cash position flag series with change-costs.
    long_flag[t] means 'hold BTC from close t to close t+1'. fwd_ret[t] is the
    log return realized over (t, t+1]."""
    pos = long_flag.astype(float)
    gross = pos * fwd_ret
    turnover = np.abs(np.diff(pos, prepend=pos[0]))  # entries+exits
    net = gross - turnover * cost
    eq_bh = np.exp(np.cumsum(fwd_ret))
    eq_net = np.exp(np.cumsum(net))
    return {
        "cum_return_pct": float((np.exp(net.sum()) - 1) * 100),
        "buy_hold_pct": float((np.exp(fwd_ret.sum()) - 1) * 100),
        "max_drawdown_pct": round(max_drawdown(eq_net) * 100, 2),
        "num_position_changes": int((turnover > 0).sum()),
        "exposure_frac": float(pos.mean()),
        "final_equity_bh": float(eq_bh[-1]),
        "final_equity_net": float(eq_net[-1]),
    }


# ---- Ledger + provenance ---- --------------------------------------------------
def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


def write_regime_table(rows: list[dict]) -> None:
    if not LEDGER_DB.exists():
        return
    con = sqlite3.connect(LEDGER_DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS regime_states (
            date TEXT PRIMARY KEY, zscore REAL, regime TEXT, p_bull REAL,
            model_version TEXT
        );
        """
    )
    # regime_states holds only this experiment's output -> clear for idempotent reruns.
    con.execute("DELETE FROM regime_states")
    for r in rows:
        con.execute(
            "INSERT OR REPLACE INTO regime_states "
            "(date,zscore,regime,p_bull,model_version) VALUES (?,?,?,?,?)",
            (r["date"], r["zscore"], r["regime"], r["p_bull"], r["model_version"]),
        )
    con.commit()
    con.close()


def write_notes(summary: dict, caus_diff: float) -> None:
    if not LEDGER_DB.exists():
        return
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(LEDGER_DB)
    con.execute("CREATE TABLE IF NOT EXISTS ai_notes (id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, text TEXT)")
    # Idempotent reruns: drop this experiment's previously written notes.
    con.executescript(
        """
        DELETE FROM ai_notes WHERE text LIKE 'Phase 8 HMM (research%';
        DELETE FROM ai_notes WHERE text LIKE 'OOS window%';
        DELETE FROM ai_notes WHERE text LIKE 'Whether the HMM regime filter%';
        DELETE FROM ai_notes WHERE text LIKE 'Phase 8 is DEFERRED%';
        """
    )
    notes = [
        ("FACT", f"Phase 8 HMM (research, non-trading): K={summary['K']} by BIC, "
                 f"causal forward filtering; future-append invariance max|Δ|={caus_diff:.2e} "
                 f"(≈0 → earlier regimes never rewritten by later data)."),
        ("FACT", f"OOS window {summary['oos_start']}→{summary['oos_end']} "
                 f"({summary['oos_days']}d), retrain every {CFG.retrain_every}d. "
                 f"HMM-filter: {round(summary['hmm']['cum_return_pct'],1)}% "
                 f"(DD {summary['hmm']['max_drawdown_pct']}%, {summary['hmm']['num_position_changes']} changes, "
                 f"exposure {round(summary['hmm']['exposure_frac']*100)}%) vs "
                 f"buy-hold {round(summary['hmm']['buy_hold_pct'],1)}%."),
        ("HYPOTHESIS", "Whether the HMM regime filter adds economic value after costs "
                       "is NOT established; results are on a single asset/window and "
                       "sensitive to K, cadence and cost. See docs/Phase8_HMM_Report.md."),
        ("GUARDRAIL", "Phase 8 is DEFERRED for trading activation. No HMM output feeds the "
                      "strategy, risk manager, or executor. Activation needs out-of-sample "
                      "evidence AND explicit owner approval (Phases.md P8-10/P8-11)."),
    ]
    for kind, text in notes:
        con.execute("INSERT INTO ai_notes (created_at,kind,text) VALUES (?,?,?)", (now, kind, text))
    con.commit()
    con.close()


# ---- Main ---- -----------------------------------------------------------------
def main() -> int:
    # Windows console defaults to cp1252; force UTF-8 so Δ/→ prints don't crash.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    if not FEATHER.exists():
        raise SystemExit(f"missing research data: {FEATHER}")
    df = pd.read_feather(FEATHER)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float).to_numpy()
    logret = np.diff(np.log(close))            # aligns to date[i+1]
    dates = df["date"].dt.strftime("%Y-%m-%d").to_list()[1:]  # one per logret
    # Z-score (same definition as dashboard/baseline) for the long-proxy comparison.
    ema = pd.Series(close).ewm(span=65, adjust=False).mean().to_numpy()
    std = pd.Series(close).rolling(65).std(ddof=0).to_numpy()
    zscore = (close - ema) / std
    zscore_dates = df["date"].dt.strftime("%Y-%m-%d").to_list()

    T = len(logret)
    cfg = CFG
    oos_start = max(cfg.min_train_days, T - cfg.holdout_days)

    # Choose K by BIC on the first training window (predeclared rule, P8-06).
    init_K, _init_p = select_K(logret[:cfg.min_train_days], cfg)
    bic_table = {K: fit_gaussian_hmm(logret[:cfg.min_train_days], K, cfg)["bic"]
                 for K in cfg.k_candidates}

    regime_rows: list[dict] = []
    hmm_flag = np.zeros(T, dtype=bool)          # long-in-bull (next-day)
    z_flag = np.zeros(T, dtype=bool)            # Z>=threshold long-proxy
    params = None
    label_ver = f"hmm-K{init_K}-{STRATEGY_VERSION.split('@')[1]}"

    for t in range(cfg.min_train_days, T):
        if params is None or (t - cfg.min_train_days) % cfg.retrain_every == 0:
            params = fit_gaussian_hmm(logret[:t], init_K, cfg)
            lm = label_map(np.asarray(params["mu"]))
        post = filter_regimes(logret[: t + 1], params)[-1]   # causal, uses <=t
        state = int(np.argmax(post))
        lab = lm[state]
        # bull regime = the training-mean-highest state (stable label via mapping)
        is_bull = lab == "bullish"
        hmm_flag[t] = is_bull                    # decision at t → act over (t,t+1]
        z_flag[t] = (zscore[t] >= cfg.bull_threshold) if np.isfinite(zscore[t]) else False
        regime_rows.append({
            "date": dates[t], "zscore": round(float(zscore[t]), 4) if np.isfinite(zscore[t]) else None,
            "regime": lab, "p_bull": round(float(post[int(np.argmax(params['mu']))]), 4),
            "model_version": label_ver,
        })

    # Next-day forward returns aligned to decision index t: fwd[t] = logret[t+1].
    fwd = np.full(T, 0.0)
    fwd[:-1] = logret[1:]
    eval_slice = slice(oos_start, T - 1)
    hmm_eval = evaluate(hmm_flag[eval_slice], fwd[eval_slice], cfg.cost_per_change)
    z_eval = evaluate(z_flag[eval_slice], fwd[eval_slice], cfg.cost_per_change)
    bh_eval = evaluate(np.ones(T - oos_start - 1, dtype=bool), fwd[eval_slice], 0.0)

    # Causality proof on a mid-window index.
    m = T // 2
    params_final = fit_gaussian_hmm(logret[:m], init_K, cfg)
    caus_diff = future_append_invariance(logret, params_final, m)

    oos_days = T - 1 - oos_start
    summary = {
        "K": init_K, "bic_candidates": {k: round(v, 2) for k, v in bic_table.items()},
        "oos_start": dates[oos_start], "oos_end": dates[T - 1], "oos_days": int(oos_days),
        "retrain_every": cfg.retrain_every, "cost_per_change": cfg.cost_per_change,
        "hmm": hmm_eval, "z_proxy": z_eval, "buy_hold": bh_eval,
        "causality_max_abs_delta": caus_diff, "data_sha256_16": hash_file(FEATHER),
        "model_version": label_ver, "strategy_version": STRATEGY_VERSION,
    }

    ART_DIR.mkdir(parents=True, exist_ok=True)
    (ART_DIR / "hmm_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (ART_DIR / "hmm_regimes.csv").write_text(
        pd.DataFrame(regime_rows).to_csv(index=False), encoding="utf-8")
    write_regime_table(regime_rows)
    write_notes(summary, caus_diff)
    write_report(summary)

    print("=== Phase 8 HMM regime experiment (RESEARCH ONLY, not trading) ===")
    print(f"K selected by BIC: {init_K}  candidates={ {k: round(v,1) for k,v in bic_table.items()} }")
    print(f"Causality (future-append invariance) max|Δ| = {caus_diff:.3e}  -> {'PASS' if caus_diff < 1e-6 else 'CHECK'}")
    print(f"OOS {summary['oos_start']} -> {summary['oos_end']} ({oos_days}d), retrain {cfg.retrain_every}d")
    print(f"  HMM filter : {hmm_eval['cum_return_pct']:.1f}%  DD {hmm_eval['max_drawdown_pct']}%  "
          f"changes {hmm_eval['num_position_changes']}  exposure {hmm_eval['exposure_frac']*100:.0f}%")
    print(f"  Z-proxy    : {z_eval['cum_return_pct']:.1f}%  DD {z_eval['max_drawdown_pct']}%")
    print(f"  Buy & hold : {bh_eval['buy_hold_pct']:.1f}%")
    print(f"artifacts -> {ART_DIR}")
    print(f"report    -> {REPORT}")
    print("Activation status: DEFERRED (non-trading). No rule/order changed.")
    return 0


def write_report(summary: dict) -> None:
    h = summary["hmm"]; z = summary["z_proxy"]; bh = summary["buy_hold"]
    md = f"""# Phase 8 — HMM Regime Experiment Report (RESEARCH ONLY)

> **Status: not active in trading.** This experiment did not change the
> strategy, risk limits, or executor, and placed no orders. Activation would
> require out-of-sample evidence **and** explicit owner approval (Phases.md P8-10/P8-11).

Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC ·
data sha256[:16] `{summary['data_sha256_16']}` · model `{summary['model_version']}` ·
strategy `{summary['strategy_version']}`.

## Method
- Feature: single BTC **daily log-return** (P8-03). Self-contained univariate
  Gaussian HMM (Baum-Welch EM), NumPy only — no external ML dependency.
- State count chosen by **BIC** over candidates {summary['bic_candidates']} → K={summary['K']} (P8-06).
- **Causal forward-only filtering** for decision-time regimes. Future-append
  invariance max|Δ| = **{summary['causality_max_abs_delta']:.2e}** (≈0), proving earlier
  regimes are never rewritten by later data (P8-05). Full-sequence smoothing not used.
- **Walk-forward OOS**: {summary['oos_start']} → {summary['oos_end']} ({summary['oos_days']} days),
  retrain every {summary['retrain_every']} bars, fit only on data before each decision (P8-04).
- Cost: {summary['cost_per_change']*100:.2f}% per position change (fee+spread proxy).

## Comparison on identical data (P8-09)
| Approach | Cum. return | Max DD | Position changes | Exposure |
|---|---:|---:|---:|---:|
| HMM-filter (long in top-mean regime) | {h['cum_return_pct']:.1f}% | {h['max_drawdown_pct']}% | {h['num_position_changes']} | {h['exposure_frac']*100:.0f}% |
| Z-score long-proxy (Z≥{CFG.bull_threshold}) | {z['cum_return_pct']:.1f}% | {z['max_drawdown_pct']}% | {z['num_position_changes']} | {z['exposure_frac']*100:.0f}% |
| Buy & hold | {bh['buy_hold_pct']:.1f}% | {bh['max_drawdown_pct']}% | 0 | 100% |

## Interpretation
A posterior regime probability is **not** a probability of a profitable trade
(P8-07). These are single-asset, single-window results sensitive to K, cadence
and cost, and are **not** adopted. The functioning baseline bot is unaffected.

## Decision (P8-11)
**DEFERRED** for trading activation. Retained as a versioned research artifact.
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
