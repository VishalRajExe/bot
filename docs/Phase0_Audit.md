# Phase 0 — Audit & Integration Decision

Status: COMPLETE (findings below). Evidence gathered on 2026-10-20.
Scope: read-only repository/environment inspection + live feasibility probes. No
strategy logic, no order placement.

## 1. Environment (observed)

| Item | Value |
| --- | --- |
| OS | Windows 11 (25H2), PowerShell |
| Freqtrade | **2026.9** (source: `freqtrade/__init__.py`) |
| Local checkout | `D:\BOT\freqtrade-stable` — extracted archive, **no `.git`** (no provenance/SHA available locally) |
| Installed interpreters | Python 3.14.6 (default `py`), 3.13, and uv-managed 3.14.0 + **3.12.13** |
| Docker | **Not installed** |
| Package tool | `uv 0.11.21` (Astral) available |
| Chosen runtime | `D:\BOT\.venv` → **Python 3.12.13** (3.14 too new for pinned native deps) |

## 2. Install verification (observed)

`uv pip install -e .` into the 3.12 venv succeeded (83 packages). Confirmed:

- `freqtrade --version` → `freqtrade 2026.9`, CCXT `4.5.89`, Python 3.12.13.
- `ta-lib==0.8.2` installed from a **binary wheel** (no manual C-library build needed on Windows).
- `pandas 3.0.6`, `numpy 2.5.4`, `ccxt 4.5.89`, `pycoingecko 3.2.0` present.

## 3. Alpaca availability (observed)

- CCXT 4.5.89 lists `alpaca` (`'alpaca' in ccxt.exchanges == True`).
- `freqtrade list-exchanges` shows: `Alpaca | alpaca | spot | missing opt: fetchL2OrderBook`.
  - Alpaca is instantiable by Freqtrade's CCXT layer; the only gap is an **optional**
    order-book method we do not need (we configure `use_order_book: false`).
- Conclusion: the **local 2026.9 checkout can target Alpaca directly via CCXT**. The
  `aidinstinct/freqtrade-alpaca` fork is **not required** for BTC/USD crypto spot; it
  mainly adds US-equities, extended-hours, and dynamic-fee features we do not use.

## 4. BLOCKER — Alpaca paper credentials (observed)

Direct authenticated calls to the paper API were rejected:

- `GET https://paper-api.alpaca.markets/v2/account` → **401 `{"message":"unauthorized."}`**
- `GET https://paper-api.alpaca.markets/v2/clock` → **401**
- CCXT `alpaca.load_markets()` (sandbox/paper) → **AuthenticationError 401**

The key/secret pair is being refused. Likely cause: transcription error from the
screenshot (Alpaca keys contain ambiguous `O`/`0`, `I`/`l`/`1`), or the secret was
regenerated after capture (Alpaca shows the secret only once). **No credential
guessing/retry is performed** (avoids account lockout).

Impact: **live Alpaca data and paper order execution are blocked** until valid keys
are supplied. Everything else (skeleton, strategy, backtest, dashboard on local
data) proceeds. Keys are stored only in git-ignored `D:\BOT\.env`, never committed.

## 5. Data source for research/backtesting (observed)

Public OHLCV works without keys. Selected source: **Kraken BTC/USD** (USD-quoted,
matches target quote currency). Freqtrade supports Kraken natively for
`download-data`. Data-source caveat recorded per Rules: backtest candles come from
Kraken, **not** the Alpaca feed — treat results as research, not execution parity.

## 6. Strategy blocker (unchanged from brief)

`strategy.txt` "Dual Signal Trend Sentinel" (daily BTC Z-score: `(close - EMA65) /
STDDEV65`) does **not** include the bull/bear thresholds. Reported metrics (65.92%
CAGR, 26.79% max DD, 53 trades) are **unverified claims**, not accepted as fact.
Per Rules, thresholds are **not invented as source-verified**; they are implemented
as **configurable strategy parameters** with a clearly-labeled candidate default,
tuned/validated by backtest and subject to owner approval.

## 7. Route decision

**Adopt Route B (native CCXT on the local 2026.9 checkout).** Rationale: Alpaca is
already reachable through CCXT in this exact Freqtrade version; no fork divergence,
no second execution engine, minimal surface area. Fork retained only as a documented
fallback if a specific Alpaca order-lifecycle gap appears during Phase 6.

## 8. Execution environments (confirmed semantics)

- Freqtrade `dry_run: true` = **local simulation** using real market data. No broker.
- Alpaca **paper** = real orders to `paper-api.alpaca.markets` (needs valid keys).
- These are distinct. Current buildable-now mode: `dry_run` + Kraken data.
  Target mode once keys are valid: Alpaca paper via CCXT sandbox.

## 9. Leverage / CoinGecko (confirmed from source)

- Spot uses Freqtrade's unleveraged `1.0` multiplier; **do not force to 0**.
- `pycoingecko` is a dependency and `CryptoToFiatConverter` initializes only when
  `fiat_display_currency` is set. We keep it unset to avoid CoinGecko runtime calls.

## 10. Next-phase authorization

Owner authorized autonomous progression. Proceeding to Phase 1 (skeleton, paper-only
config, guards, Memory.md) and Phase 2/3/4 (data, strategy, backtest) using Kraken
data. Phase 6 (Alpaca paper execution) is **gated on valid credentials** and will be
wired but not exercised until keys authenticate.
