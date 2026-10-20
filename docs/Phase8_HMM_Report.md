# Phase 8 — HMM Regime Experiment Report (RESEARCH ONLY)

> **Status: not active in trading.** This experiment did not change the
> strategy, risk limits, or executor, and placed no orders. Activation would
> require out-of-sample evidence **and** explicit owner approval (Phases.md P8-10/P8-11).

Generated 2026-10-20 19:27 UTC ·
data sha256[:16] `5f0fe1494a782488` · model `hmm-K2-candidate-2026-10` ·
strategy `BtcZScore@candidate-2026-10`.

## Method
- Feature: single BTC **daily log-return** (P8-03). Self-contained univariate
  Gaussian HMM (Baum-Welch EM), NumPy only — no external ML dependency.
- State count chosen by **BIC** over candidates {2: -1686.43, 3: -1672.34, 4: -1639.08} → K=2 (P8-06).
- **Causal forward-only filtering** for decision-time regimes. Future-append
  invariance max|Δ| = **0.00e+00** (≈0), proving earlier
  regimes are never rewritten by later data (P8-05). Full-sequence smoothing not used.
- **Walk-forward OOS**: 2024-10-20 → 2026-10-19 (729 days),
  retrain every 30 bars, fit only on data before each decision (P8-04).
- Cost: 0.20% per position change (fee+spread proxy).

## Comparison on identical data (P8-09)
| Approach | Cum. return | Max DD | Position changes | Exposure |
|---|---:|---:|---:|---:|
| HMM-filter (long in top-mean regime) | 6.2% | 51.31% | 100 | 89% |
| Z-score long-proxy (Z≥0.5) | 24.9% | 29.68% | 41 | 43% |
| Buy & hold | 18.7% | 52.97% | 0 | 100% |

## Interpretation
A posterior regime probability is **not** a probability of a profitable trade
(P8-07). These are single-asset, single-window results sensitive to K, cadence
and cost, and are **not** adopted. The functioning baseline bot is unaffected.

## Decision (P8-11)
**DEFERRED** for trading activation. Retained as a versioned research artifact.
