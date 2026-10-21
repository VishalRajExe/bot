# FVG/OB Strategy — Deterministic Sequence (Research Layer)

Status: **RESEARCH ONLY — NOT wired to the live executor. Not owner-approved for
trading.** The live paper strategy remains the separate BTC Z-score baseline
(`BtcZScore`) per owner decision #1. Nothing in this document enables a pair or
places an order.

This document specifies the exact Fair-Value-Gap / Order-Block (FVG/OB) entry
sequence the owner asked for, the deterministic core that implements it, the
tests that pin every step, the real-data research backtest, and the honest
limitations.

Source of truth (code):
- `app/strategies_core/fvg_ob.py` — pure functions + `SetupTracker` state machine.
- `app/strategies_core/state_store.py` — restart-safe per-pair JSON snapshots.
- `app/tests/test_fvg_ob.py` — 21 unit + integration tests.
- `app/scripts/discover_assets.py` — availability + eligibility (read-only).
- `app/scripts/research_fvg_backtest.py` — research replay on real Alpaca candles.

## 1. The exact sequence (owner decision #2)

The bot must **not** buy just because an FVG exists. A long entry requires every
step, each recorded with a timestamp, in order:

```
IDLE
  → HTF_BIAS_CONFIRMED              1H trend is bullish (EMA rising & close>EMA)
  → HTF_CONFLUENCE_ZONE_IDENTIFIED  a 1H FVG ∩ (optional) 1H order block zone
  → HTF_ZONE_TAPPED                 a LATER 1H bar trades back into the zone
  → LTF_FVG_CONFIRMED               a NEW 5M bullish FVG, formed AFTER the tap,
                                    overlapping the HTF zone
  → WAITING_FOR_FIRST_LTF_RETEST     …
  → ENTRY_TRIGGERED                 the FIRST 5M retest dips into the 5M FVG;
                                    entry at that bar's CLOSE
```

Rules baked into the state machine (each has a test):
- **No early acceptance.** A 5M FVG seen before the HTF zone is tapped is rejected
  (`test_entry_before_tap_is_never_accepted`, `test_ltf_fvg_before_htf_tap_ts_rejected`).
- The 5M FVG must **overlap** the HTF zone (`test_ltf_fvg_must_overlap_htf_zone`).
- **Only the first qualifying retest** triggers; later ones never duplicate
  (`test_second_retest_does_not_duplicate_entry`; ENTRY/POSITION states don't
  re-fire until `reset()`).
- **Fixed 1:2 reward:risk.** stop = HTF-zone-bottom − `stop_atr_mult·ATR`;
  risk = entry − stop; take-profit = entry + 2·risk. If `risk ≤ 0` (stop on the
  wrong side) the setup is INVALIDATED, never forced (`test_stop_wrong_side_is_rejected_no_entry`).
- **Spot / long-only.** A bearish FVG never opens a long zone; there are no
  shorts (`test_spot_only_bearish_never_long_entry`).
- **Expiry.** An untapped zone expires after `zone_ttl_bars`; an untested 5M FVG
  expires after `retest_window_5m` (`test_zone_expires_if_not_tapped`,
  `test_retest_window_expiry`).
- **No lookahead.** Signals are only read at a bar's CLOSE; `evaluate_ohlcv`
  merges 1H/5M events ordered by close-time; detection functions are
  append-invariant (`test_no_lookahead_append_invariance`,
  `test_bias_does_not_use_future`, `test_evaluate_no_lookahead_prefix_invariance`).

Deterministic primitives: 3-candle FVG (bull `low[i]>high[i-2]`, bear mirror),
confirmed swings (k-bar forward lag), Wilder-style ATR (rolling mean of true
range, warm-up NaN back-filled with per-bar TR), EMA trend-bias, and an order
block = last opposite bar before a displacement that breaks a confirmed swing.
Confluence zone = the price intersection of a same-direction 1H FVG and the most
recent overlapping 1H OB.

## 2. Restart-safety & duplicate protection (owner decision #2)

`SetupTracker.snapshot()` serializes the full `SetupState` (state, direction,
zone bounds, and each step timestamp). `state_store.py` writes one small atomic
JSON file per pair (independent of the Freqtrade trade DB — it stores *intent*,
not execution truth). After a restart the tracker is rebuilt from the snapshot;
ENTRY_TRIGGERED/POSITION_OPEN states do not re-fire, so a restart can never
duplicate an entry (`test_restart_recovery_no_duplicate`).

## 3. Asset availability vs enablement (owner decision #3)

`discover_assets.py` (read-only) enforces the two-layer rule:
- **Availability** comes only from Alpaca's tradable crypto list (`GET
  /v2/assets?asset_class=crypto`, `tradable=true`).
- **Eligibility** is a *proposal* ranked by 30d median traded notional (from the
  crypto bars feed) with gates: data quality (≥25/30 daily bars), top-quartile
  liquidity (relative, because Alpaca's own crypto volume feed is thin), and a
  verified bid/ask spread ≤ 0.50% for the shortlist.
- **Nothing is auto-enabled** (`enabled=0` on every run). Enabling a pair is a
  separate owner-approved step that requires a backtest first. BTC/USD is flagged
  `[BASELINE]` and excluded from FVG/OB candidacy.

Last run: 73 available, 6 eligible (BTC baseline + ETH/XRP/USDT/DOT/LINK proposed);
AVAX dropped on spread, PAXG/LTC/BCH on spread, small caps below the liquidity
cutoff. Written to `app/configs/asset_universe.json`.

## 4. Research backtest — real Alpaca candles, honest result

`research_fvg_backtest.py` is **not a second trading engine** (per the owner's
explicit instruction). It replays the same tested core over real Alpaca 1H+5M
candles and resolves each setup by first-touch of TP vs stop on later 5M bars.

Window reality: the Alpaca free-tier crypto feed only returned ~8 days of 5M
bars (≈2300) and ~30 days of 1H. Findings (pessimistic tie-break = stop first;
fees ~0.50% round trip):

| Config | Pair | Setups | W/L/TO | Net R (after fees) |
|---|---|---|---|---|
| shipped (`require_overlap=True`) | BTC/ETH/XRP/LINK/DOT | 0 | — | — |
| sensitivity (`--no-overlap`) | BTC/USD | 5 | 2/2/1 | −2.31 |
| sensitivity | ETH/USD | 3 | 0/3/0 | −7.78 |
| sensitivity | XRP/USD | 1 | 0/1/0 | −2.06 |
| sensitivity | LINK/USD | 4 | 0/4/0 | −8.77 |

Conclusion: **no demonstrated edge.** The strict shipped sequence is so selective
it produced zero setups in the available window; relaxing the OB-confluence gate
produced a handful (≈12), ~17% winners (< the 33% breakeven for 1:2), and a
negative expectancy after fees. This is far too small to be significant.

## 5. Limitations (stated plainly)

- The exact gated sequence rarely completes; on the available data it does not
  beat doing nothing. The shipped OB-confluence requirement yielded 0 in-sample.
- Freqtrade cannot backtest the Alpaca exchange (ccxt-alpaca `load_markets()` hits
  a private endpoint the backtest bootstrap won't authenticate), so this replay is
  a research approximation, not a Freqtrade `backtesting` run with execution parity.
- Intra-bar TP/stop order is unknowable → ties counted as losses (pessimistic).
- ~8-day 5M window is tiny; Alpaca's own crypto volume feed is thin (relative
  liquidity ranking used). Free-tier history depth limits the sample.
- Nothing here changes risk, enables a pair, or touches the live executor.

## 6. Path to activation (not yet met)

FVG/OB may only be promoted from research to a live strategy after: (a) a longer,
statistically meaningful sample on the intended venue/pairs; (b) tuning validated
out-of-sample; (c) a written owner approval in `app/configs/risk_approval.json`
covering the FVG/OB-specific bounded settings; and (d) wiring through the single
Freqtrade executor with the preflight gate still green. Until then it stays in
`app/strategies_core` where an untested strategy cannot become actionable.
