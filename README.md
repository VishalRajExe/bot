# UnboundBot

**PAPER-only** crypto trading system layered on top of an unmodified Freqtrade
checkout. Multi-asset, multi-strategy, **expectancy-gated** — every order runs
through an independent fail-closed risk veto; nothing here trades real money.

> **What this system is *not*.** No machine learning. No dashboard (Telegram is
> the only ops surface, and the Streamlit "Regime Trader" UI in
> [`docs/Design.md`](docs/Design.md) is spec-only, unimplemented). No continuous
> market auto-discovery (an operator runs `discover_assets.py` by hand to
> expand the whitelist). No backtest-to-live feedback loop (backtest CSVs are
> static artifacts a human reviews). No model training. "Expectancy-gated"
> below means: after ≥ 20 closed trades, a family/pair whose average
> R-multiple has fallen to ≤ 0 is automatically blocked from new entries. The
> gate is one-way — the system can demote but never self-promote; only an
> owner edit re-enables a pair.

> **Objective (honest, reframed 2026-10-22).** Maximize *risk-adjusted expectancy*
> (after fees + spread) under hard safety caps, and keep learning continuously.
> There is no profit target. No `$`-return is promised or encoded anywhere in the
> configs or code. PAPER ONLY.

---

## Architecture at a glance

```
                                          ┌──────────────────────────────┐
                                          │  Alpaca PAPER  (broker)      │
                                          │  paper-api.alpaca.markets    │
                                          └───────────────┬──────────────┘
                                                          │  market/limit orders
                                                          │  (long-only, spot,
                                                          │   unleveraged)
                                                          ▼
   ┌─────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐
   │  daily  executor (1d)   │   │   fast  executor (5m)   │   │  swing  executor (1h)   │
   │  PaperAutonomous        │   │   MomentumAlt           │   │  SwingAlt               │
   │   └─ BtcZScore (baseline│   │   └─ FamilyDispatcher   │   │  └─ FamilyDispatcher    │
   │      byte-for-byte)     │   │        └─ families.py   │   │        └─ families.py   │
   │  BTC/USD                │   │  ETH XRP DOT LINK SOL UNI│  │  LTC/USD AVAX/USD DOGE  │
   │  stake 15 · max 1       │   │  stake 10 ea · max 2     │   │  stake 10 ea · max 1    │
   └────────────┬────────────┘   └────────────┬────────────┘   └────────────┬────────────┘
                │                              │                             │
                │  every entry consults the   │                             │
                ▼  veto + sizing hooks        ▼                             ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │   app/risk/policy.py   +   PaperAutonomous.confirm_trade_entry   (single source)    │
   │   ─ per-pair stake cap (registry max_stake_usd)                                     │
   │   ─ per-position 20% × equity ceiling (plan §3, Phase D)                            │
   │   ─ evidence-scaled sizing (m ∈ [1.0, 2.0] after n ≥ 20 closed trades)              │
   │   ─ is_tradeable(pair) respects the strategy gate (auto-demote, never auto-promote) │
   │   ─ global exposure cap  min($105 fixed, 40% × equity)  — via cross-executor ledger │
   │   ─ kill-switch / circuit-breakers / stale-equity fail-closed                       │
   └─────────────────────────────────────────────────────────────────────────────────────┘
                ▲                              ▲                             ▲
                │      read-only open_exposure ledger (aggregates 3 DBs)    │
                └──────────────────────────────┬────────────────────────────┘
                                               │
   ┌───────────────────────────────────────────┴───────────────────────────────────────┐
   │                    app/scripts/crypto_status_monitor.py                            │
   │                    (read-only observer → Telegram)                                 │
   │   🟢 BUY · ✅ FILLED · 🔴 EXIT · 💰 PROFIT / 💸 LOSS · ⚠️ REJECTED · ⛔ DEMOTED     │
   └───────────────────────────────────────────┬───────────────────────────────────────┘
                                               │  writes equity / exposure / breaker
                                               ▼
   ┌───────────────────────────────────────────────────────────────────────────────────┐
   │                    app/ledger/unbound.db   (durable, mirrored)                     │
   │   paper_trades  ·  reconcile_log  ·  account_equity  ·  trade_journal              │
   └───────────────────────────────────────────┬───────────────────────────────────────┘
                                               │  closed rows -> (pair, family, R, PnL)
                                               ▼
   ┌───────────────────────────────────────────────────────────────────────────────────┐
   │                    app/scripts/learner.py     (read-only, idempotent)              │
   │                    app/learn/{perf,journal}.py                                     │
   │   ─ writes  app/state/perf.json            (per pair|family stats → sizing hook)   │
   │   ─ writes  app/state/strategy_gate.json   (append-only auto-demotions)            │
   └───────────────────────────────────────────────────────────────────────────────────┘
                                               ▲
                                               │  supervised alongside the bots
   ┌───────────────────────────────────────────┴───────────────────────────────────────┐
   │                    app/scripts/supervise.py     (24/7 PAPER watchdog)              │
   │   never relaunches an executor while the kill-switch is active — alerts instead    │
   └───────────────────────────────────────────────────────────────────────────────────┘
```

The Freqtrade engine itself lives under `freqtrade-stable/**` and is **never
modified**. Everything UnboundBot adds lives under `app/**` and is loaded by
Freqtrade through its standard seams (custom strategy path, custom config,
optional exchange patch registered from the strategy module). Thin layer, no
engine fork.

## Repository layout

```
D:\BOT\
├── app\
│   ├── configs\              ← Freqtrade configs + risk policy + strategy registry
│   ├── indicators\           ← families.py (pure, causal signal math)
│   ├── learn\                ← Phase D learning layer (perf.py + journal.py)
│   ├── notifications\        ← emoji Telegram formatters (pure)
│   ├── risk\                 ← policy.py — the single independent risk authority
│   ├── scripts\              ← discover_assets, preflight, run_paper, reconcile,
│   │                           crypto_status_monitor, learner, supervise, run_backtest
│   ├── tests\                ← pytest suite (184 passing, all hermetic)
│   ├── exchange_ext\         ← gated Alpaca fee-net-settlement patch
│   └── user_data\strategies\ ← BtcZScore, PaperAutonomous, FamilyDispatcher,
│                               MomentumAlt, SwingAlt, ResearchFamily
├── docs\                     ← PRD, Design, Architecture, Phases, audits, backtests
├── freqtrade-stable\         ← unmodified Freqtrade checkout (2026.9)
└── .env                      ← Alpaca / Telegram credentials (gitignored)
```

## Executors (three, structurally disjoint)

| Executor | Timeframe | Pairs                              | Strategy                | Stake | Max open |
|----------|-----------|------------------------------------|-------------------------|-------|----------|
| daily    | 1d        | BTC/USD                            | PaperAutonomous         | $15   | 1        |
| fast     | 5m        | ETH/XRP/DOT/LINK/SOL/UNI/USD       | MomentumAlt             | $10   | 2        |
| swing    | 1h        | LTC/AVAX/DOGE/USD                  | SwingAlt                | $10   | 1        |

Sum of per-pair caps = **$105** structural. Runtime `min($105, 40% × equity)`
binds to **$40** on the $100 preset — breadth of pairs adds *learning surface*,
not more simultaneous dollars at risk.

## Quickstart

### Prerequisites

- Python **3.12** (Freqtrade 2026.9 compatibility; see `docs/Audit_Remediation_2026-10-21.md`).
- Alpaca **paper** credentials (never live) in `D:\BOT\.env`:
  ```
  ALPACA_API_KEY_ID=...
  ALPACA_API_KEY_SECRET=...
  TELEGRAM_BOT_TOKEN=...      # optional; notifications no-op if absent
  TELEGRAM_CHAT_ID=...        # optional
  ```

### Bring-up order (each command must be verified before the next)

```powershell
# 1) Verify the multi-executor wiring is safe to trade
python app\scripts\preflight.py
#    → "TRADING READY: True" across all three executors

# 2) Start the read-only observer (Telegram + ledger + breaker evaluation)
python app\scripts\crypto_status_monitor.py --interval 60

# 3) Start the daily BTC executor FIRST (baseline; keep it stable)
python app\scripts\run_paper.py                 # --daily is the default

# 4) Optionally add the fast + swing executors after the $100 daily path is verified
python app\scripts\run_paper.py --fast
python app\scripts\run_paper.py --swing

# 5) Or let the supervisor orchestrate all of the above
python app\scripts\supervise.py --only all
```

### Reconciliation & learning (both are read-only, safe to run any time)

```powershell
python app\scripts\reconcile.py                 # one snapshot of broker vs. bot vs. ledger
python app\scripts\reconcile.py --watch 900     # repeat every 15 min

python app\scripts\learner.py                   # rebuild journal + perf + strategy gate
python app\scripts\learner.py --watch 900       # continuous learning loop
```

### Backtest the families (Binance USDT proxy — signal-quality only)

```powershell
# full per-pair × per-family matrix over the tradeable set
python app\scripts\run_backtest.py --matrix --timeframe 1d --timerange 20240101-

# one-off
python app\scripts\run_backtest.py --strategy ResearchFamily --pairs BTC/USDT ETH/USDT --timerange 20240101-
```

The matrix writes `docs\Backtest_Results_<date>.csv` + `.md` with per-cell
expectancy so the registry can be re-tagged based on evidence.

## What "learning" actually does here

The `learner.py` process is **not** a model-training loop. It does exactly
three things, in order, every 15 minutes:

1. Read `paper_trades` from all three Freqtrade trade DBs, filter to
   `is_open = 0`, compute the R-multiple per closed trade,
   and upsert rows into `app/ledger/unbound.db::trade_journal`.
2. Group those closed trades by `(pair, family)`, compute `n`, `expectancy_R`,
   `win_rate`, `avg_R`. Write the whole map into `app/state/perf.json`.
3. For every `(pair, family)` with `n ≥ 20` **and** `expectancy_R ≤ 0`, append
   an entry to `app/state/strategy_gate.json`. Never remove an entry.

The `policy.evidence_multiplier()` sizing hook reads `perf.json` and scales a
pair's stake up (never down, never past `MAX_EVIDENCE_SCALE = 2.0`) once that
pair has proven positive expectancy. `policy.is_tradeable(pair)` returns False
while the pair is in `strategy_gate.json`.

On a **young account** with zero closed trades — which is exactly the state
right now — the entire layer is deliberately inert: `by_pair_family={}`,
`demoted=[]`, every `evidence_multiplier(pair)=1.0`, and the sizing / gating
behavior is byte-for-byte identical to the pre-expansion BTC-only baseline.
The pipeline exists so it can start producing signal *after* trades close.

## Testing

```powershell
python -m pytest app\tests\ -q
# 184 passing, all hermetic — no broker, no live IO, no order side-effects.
```

Every risky code path has a test: risk policy, three-executor `validate_executors`,
dispatcher veto identity (`MomentumAlt.confirm_trade_entry is PaperAutonomous.confirm_trade_entry`),
circuit breakers, fee-net-settlement patch, journal R-multiple fail-closed,
`should_demote` boundaries, `size_multiplier` clamp, evidence-scaled stake, and
the 20%-equity per-position guard.

## What "safety" means here

- **Paper-only.** `authorization.live_trading = "NOT APPROVED"` in
  `paper_risk_policy.json`; enforced by config, preflight, and the veto.
- **Fail-closed everywhere.** Missing / stale / uncomputable data → REJECT the
  entry (never default to "safe"). This includes stale equity, an unreadable
  cross-executor exposure ledger, and a demoted pair.
- **Circuit breakers** with a **manual-recovery-only** kill switch. The
  supervisor refuses to relaunch an order executor while the breaker is active —
  it alerts via Telegram instead.
- **One position per pair**, structurally disjoint pair sets across executors,
  single global exposure cap enforced via the cross-executor ledger.
- **BTC baseline is byte-for-byte preserved.** All new behavior is layered on
  top via `PaperAutonomous` subclassing + `FamilyDispatcher`; the `BtcZScore`
  math (EMA65/STD65/Z-score, thresholds, timeframe, protections, transitions)
  is unchanged.
- **No secrets in tracked files.** `.env` is gitignored; every config uses
  empty-string placeholders that Freqtrade resolves from env at runtime.
- **Thin layer.** No Freqtrade engine fork, no vendored-file edits.

## Documentation index

- [`docs/PRD.md`](docs/PRD.md) — product requirements.
- [`docs/Design.md`](docs/Design.md) — proposed contracts (v0.2).
- [`docs/Architecture.md`](docs/Architecture.md) — architecture + implementation addendum.
- [`docs/Phases.md`](docs/Phases.md) — original phase-by-phase approval checklist.
- [`docs/Audit_Remediation_2026-10-21.md`](docs/Audit_Remediation_2026-10-21.md) — pre-expansion single-executor audit.
- [`docs/Audit_2026-10-22.md`](docs/Audit_2026-10-22.md) — **current authoritative state** after the multi-asset / expectancy-gated expansion (includes the open swing-OHLCV defect).
- [`docs/Asset_Universe_Classification.md`](docs/Asset_Universe_Classification.md) — Phase A verified asset list.
- [`docs/Backtest_Results_2026-10-22.md`](docs/Backtest_Results_2026-10-22.md) — Phase C matrix results.
- [`docs/Strategy_FVG_OB.md`](docs/Strategy_FVG_OB.md) — research-only FVG/OB sequence (never wired to trading).

## Not in scope

- **Live trading** — requires a separate written authorization + a full re-audit.
- **Leverage / shorts / margin / futures / transfers / withdrawals / averaging
  down / martingale** — all listed under `hard_prohibitions`.
- **HMM / LSTM regime models** — deferred; see `docs/Phase8_HMM_Report.md`.
- **Per-trade human approval** — autonomous execution inside the bounded policy
  is exactly what this system was authorized to do; unsafe entries are rejected
  and *explained* via Telegram rather than paged for a human yes/no.

## License

Freqtrade is GPLv3. UnboundBot's own code under `app/` and `docs/` is original
work; it interacts with Freqtrade only through the standard plugin seams
(custom strategy, config, optional exchange patch). No Freqtrade file under
`freqtrade-stable/` is modified.
