# Asset Universe Classification (Phase A)

Generated 2026-10-22 from a live, read-only Alpaca discovery run
(`app/scripts/discover_assets.py`, 73 tradable crypto assets) plus per-symbol
`/v2/assets` and `/latest/quotes` probes. This table is the authoritative
mapping from the owner's requested assets to how UnboundBot will treat them.

## Eligibility gates (project policy, unchanged)
A symbol is **eligible (LIVE-STRICT)** when it passes all three gates:
- **Liquidity** — median 30d daily notional in the top quartile of Alpaca's
  tradable crypto (relative cutoff; Alpaca's crypto volume feed is thin).
- **Data quality** — >= 25 of the last 30 daily bars present.
- **Cost** — verified bid/ask spread <= 0.50% of mid.

Enabling any pair additionally requires a backtest + owner approval; discovery
never enables trading by itself.

## Owner-requested assets -> classification
| Requested | Alpaca symbol | Spread % | 30d notional (USD) | Class | Why |
|---|---|---|---|---|---|
| LTC | LTC/USD | 0.56 | 3,970 | PAPER-SWING | spread > 0.50% and thin; swing (1h) cost-aware only |
| XRP | XRP/USD | 0.38 | 27,226 | LIVE-STRICT | passes all gates (already trading) |
| UNI | UNI/USD | 0.21 | 11,749 | LIVE-STRICT | passes all gates |
| MATIC | POL/USD | n/a | 46 | RESEARCH-ONLY | MATIC rebranded to POL; POL listed but ~$46/day notional is untradeable; MATIC/USD not listed |
| DOGE | DOGE/USD | 0.35 | 3,788 | PAPER-SWING | cost OK but thin liquidity; swing (1h) cost-aware only |
| AVAX | AVAX/USD | 0.64 | 10,318 | PAPER-SWING | spread > 0.50%; swing (1h) cost-aware only |
| LINK (improve) | LINK/USD | 0.20 | 6,973 | LIVE-STRICT | passes all gates |

## Bonus gate-passing candidates found during discovery
| Symbol | Spread % | 30d notional (USD) | Class | Note |
|---|---|---|---|---|
| SOL/USD | 0.10 | 27,049 | LIVE-STRICT | tight spread, deep; strong add |
| DOT/USD | 0.17 | 6,738 | LIVE-STRICT (borderline) | tight spread; liquidity hovers at the quartile cutoff, kept (already trading) |
| USDC/USD | 0.05 | 874,835 | STATUS_ONLY | stablecoin |
| USDT/USD | 0.12 | 20,803 | STATUS_ONLY | stablecoin |

## Minimum order notional (broker floor lesson)
All target symbols are `tradable=active` and `fractionable=true`. Alpaca's raw
`min_order_size` (base units) is tiny for every alt (~$1-3 notional), so a $10
floor stake is safe for alts. BTC's effective Freqtrade min-stake is ~$15 (the
verified floor from the 2026-10-21 go-live), so BTC stays at $15. Effective
per-pair min-stake is re-verified during executor wiring (Phase E) before a pair
is enabled, to avoid the silent "stake too small -> trade ignored" trap.

## Executor assignment (drives Phase E)
- **daily (1d)** — BTC/USD baseline only (`BtcZScore`, byte-for-byte unchanged).
- **fast (5m)** — LIVE-STRICT alts: ETH, XRP, SOL, UNI, DOT, LINK (per-pair
  strategy family from `strategy_registry.json`).
- **swing (1h, NEW)** — PAPER-SWING names: LTC, AVAX, DOGE (cost-aware stops
  >= ~2x round-trip cost). Owner-approved relaxed gate for PAPER only.
- **RESEARCH-ONLY** — POL, MATIC: backtested on the Binance proxy, forward
  observed, no live orders (cannot be paper-traded meaningfully on this venue).

## Discovery reliability note
Alpaca's free crypto feed intermittently omits symbols from a batched `/bars`
response, which previously dropped actively-traded pairs (e.g. XRP/USD) from the
report. `fetch_bars_notional` now retries every still-missing symbol
individually (up to 3 passes), so `asset_universe.json` is complete and stable.
