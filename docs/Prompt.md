# UnboundBot — Coding-Agent Starter and Phase Prompts

This prompt package does not authorize work by itself. [Phases.md](Phases.md) is the single master checklist, approval register, and evidence record. Execute only the phase explicitly authorized by the owner; do not implement the entire roadmap in one session.

## 1. Master starter prompt

```text
You are working on UnboundBot, a Freqtrade-first BTC/USD spot paper-trading application with a read-only Regime Trader dashboard and an evidence-based research assistant.

AUTHORITATIVE PATHS
Project: D:\BOT
Existing framework: D:\BOT\freqtrade-stable
Documentation: D:\BOT\docs

READ FIRST
1. docs/PRD.md
2. docs/Architecture.md
3. docs/Rules.md
4. docs/Phases.md — master checklist, phase approvals, task IDs, evidence
5. docs/Design.md
6. docs/Prompt.md
7. docs/CRYPTO_BOT_PROJECT_CONTEXT.md
8. docs/Memory.md only if it already exists

CURRENT GATE
Documentation alignment and its requested commit/push are the approved scope.
Phase 0 requires a separate explicit go-ahead. Do not start it because this
prompt describes it. Limited planning source inspection is not a completed
audit, a working install, or proof of Alpaca compatibility.

NON-NEGOTIABLES
- BTC/USD, daily baseline signals, long/cash spot, Alpaca paper orders only.
- No live broker routing/keys, borrowing, margin, shorts, futures, transfers,
  withdrawals, or CoinGecko calls in the approved application workflow.
- Preserve the valid Freqtrade unleveraged spot multiplier of 1.0; no borrowing
  does not mean forcing framework leverage arithmetic to zero.
- Exactly one executor owns orders. Reuse Freqtrade functionality first.
- Local Freqtrade dry_run is not Alpaca paper execution. Separate configs,
  databases, run IDs, and labels. Verify paper endpoint/SDK routing and paper
  authentication; key strings alone do not establish credential environment.
- Missing strategy/risk settings or unknown critical state block new entries.
- Risk-reducing actions require approved policy and verified positions/size.
- Runtime AI has no broker secrets, order authority, active-config writes,
  or automatic execution of generated code.
- No installations, code/order spike, bot startup, or Memory.md in Phase 0.

STRATEGY AND SOURCE LIMITATIONS
The formula is Z = (close - EMA(close, 65)) / STDDEV(close, 65).
Bull/bear numbers and complete implementation semantics are missing from the
provided strategy note. Search lead: DurdenBTCs Dual Signal Trend Sentinel
on TradingView; the note says code is protected. Do not bypass protection.
Recover authorized source details or get explicit approval for a new adapted
specification. Do not label guesses original or published results verified.
Use completed candles and causal signal/fill timing. Check EMA initialization,
standard deviation convention, warm-up, neutral/equality cases, and inherited
Freqtrade ROI/stoploss/trailing/position-adjustment/force-entry defaults.
Video summaries/screenshots are available; original transcripts/URLs have not
been independently inspected. HMM is optional; LSTM is later research only.

WORKFLOW
1. Confirm the currently authorized phase and preserve local changes.
2. Map the bounded task to Phases.md IDs and acceptance criteria.
3. Reuse existing extension points; document concrete gaps before core edits.
4. Keep facts, assumptions, source claims, blocked tests, and proposals separate.
5. Run relevant available checks and inspect results; do not invent passes.
6. Update checklist evidence and Memory.md once coding has begun.
7. Report changes, commands/results, failures/skips, blockers, gate status,
   and the next smallest action. Stop at the phase boundary.

PUBLICATION AND BROWSER CHECKS
The owner requested commit/push to https://github.com/VishalRajExe/bot.git.
Stage only approved changes, preserve remote history, and never force-push,
include secrets/runtime data, or silently publish the whole framework.
Respect any required pre-push review gate. Stop on authentication/history
blockers. Browser checks verify the actual artifact: markdown for docs-only
work; application behavior only after an application exists. Do not invent
an app/server merely to satisfy a browser instruction during documentation.
Do not edit the approved plan cache file.

CODING-AGENT MEMORY
Do not create docs/Memory.md during documentation work or Phase 0.
Create it when Phase 1 coding starts after the route is approved, recording
real findings, changes, tests, blockers, decisions, and next action.
Runtime trade memory is a separate persistent ledger, not this markdown file.
```

## 2. Phase 0 — Audit prompt, use only after authorization

```text
Execute P0-01 through P0-28 in docs/Phases.md only.
Inventory framework provenance/version, local changes, requirements, available
runtime/tests, strategy/exchange/order/wallet/storage paths, backtesting,
protections, API/UI, notification paths, and CoinGecko initialization.
Do not install, implement, start a bot, authenticate with a broker, place
orders, or create Memory.md. Run only safe isolated existing checks; report
unavailable tests. Do not invent Git ancestry for an archive extraction.

Inspect current official docs and https://github.com/aidinstinct/freqtrade-alpaca
remotely. Ask before creating a separate local comparison copy. Compare exact
contracts, source versions, dependencies, lifecycle behavior, tests, and
maintenance risks. Do not overwrite the existing framework.

Write docs/Phase0_Audit.md with the feature-parity matrix, provenance, evidence,
limitations, candidate Route A/B/C, remaining proof steps, and runtime proposal.
Route C needs explicit approval. Distinguish local simulation from broker paper
execution and source plausibility from tested compatibility. Stop for route
and Phase 1 approval; actual paper lifecycle proof comes later.
```

## 3. Phase 1 — Foundation prompt

```text
Execute P1-01 through P1-11 only after the route is approved. Explain any needed
isolated dependency installation. Build only missing extensions, typed safe
settings, paper-routing guards, logging/health, schema ownership, and test
scaffolding. No CoinGecko runtime conversion. No live broker config. Keep
strategy submission disabled until prerequisites pass; use mocks for broker
contracts and stop on a route contract blocker.
Create docs/Memory.md now that coding begins. Test unsafe overrides, paper
routing, missing configuration, no-CoinGecko requests, and redaction. Record
actual commands/results and stop at the gate.
```

## 4. Phase 2 — Data prompt

```text
Execute P2-01 through P2-10. Validate Alpaca BTC/USD data, actual coverage,
pagination, source/feed, UTC boundaries, quality, revisions, and completeness.
Keep raw/normalized provenance and hashes. Separate candle, quote, account,
and reconciliation freshness. Do not fabricate gaps, use incomplete bars,
or assume history begins in 2014. Ask before an alternate named archive;
never silently substitute BTC/USDT. Test rollover/clock skew/gaps/reload.
No orders. Update evidence/Memory.md and stop.
```

## 5. Phase 3 — Strategy prompt

```text
Execute P3-01 through P3-11. Source or obtain approval for thresholds and exact
semantics; missing values block actionable entries. Label adaptations honestly.
Implement pure EMA65/STDDEV65 Z-score and deterministic long/cash transitions,
with warm-up, equality, invalid/zero variance, neutral/restart/risk-exit policy,
and causal fill timing. Inspect inherited framework exit/entry defaults.
Persist versioned as-of decisions now, before execution exists. Test fixtures,
repeat candles, replay, and future-data perturbation. Stop at the gate.
```

## 6. Phase 4 — Research prompt

```text
Execute P4-01 through P4-12. Reuse compatible Freqtrade backtesting and analysis.
Save exact data/config/code/run metadata and costs/fill assumptions. Separate
reported/model costs and fee currency. Preserve chronological holdouts; compare
cash, buy-and-hold, and a documented trend baseline. Test accounting and
lookahead/recursive/timestamp behavior, cost/delay sensitivity, and outlier
dependence. Published returns remain claims unless faithfully reproduced.
Report negative results honestly; do not tune merely to match claimed CAGR.
Update evidence/Memory.md and stop for the research gate decision.
```

## 7. Phase 5 — Risk prompt

```text
Execute P5-01 through P5-12. Obtain numeric policy approvals before paper orders.
Size against eligible cash/holdings, not margin buying power. Preserve valid
1.0 spot accounting. Enforce risk for every submit path, including framework
exits/retries/RPC/recovery. Monitor risk independently of daily signals, persist
UTC baselines/equity peaks/cash-flow adjustments/kill switches, and test one
executor. Separate entry blocking from validated risk-reducing actions.
Test unknown/stale inputs, exceptions, precision, restarts, and duplicates.
Re-backtest integrated risk/sizing changes. Record evidence and stop.
```

## 8. Phase 6 — Paper execution prompt

```text
Execute P6-01 through P6-13 via the sole approved integration. Verify paper
endpoint/SDK/authentication, asset metadata, fresh state, and approved strategy
and risk versions. Persist intent/client ID before submit. Handle every state,
partial fills, fee currency, duplicates, and crash windows. Reconcile ambiguous
writes before retrying and use authoritative reads, not streams alone.
Complete mocked/fault tests first. Obtain a bounded paper account/test budget
before a finite lifecycle test; reconcile residual orders/positions. No live
fallback. Prove actual Alpaca records, not local dry-run artifacts. Update the
parity matrix and Memory.md; stop after reporting the gate evidence.
```

## 9. Phase 7 — AI research prompt

```text
Execute P7-01 through P7-12 by extending the existing durable ledger. Generate
facts deterministically; notes separate fact/interpretation/hypothesis/validation/
approval and cite evidence, sample size, counterexamples, and limitations.
Approve provider/data-sharing/budget before external LLM use. Give the reviewer
no secrets, orders, active-config writes, or automatic code execution. Treat
retrieved text as untrusted. Isolate experiments, predeclare objectives, preserve
holdouts/negative results, and require human promotion plus rollback.
Test schemas, evidence references, idempotence, restart, injection, and reviewer
failure without disabling core risk. Record evidence and stop.
```

## 10. Phase 8 — Optional HMM prompt

```text
First record whether this optional phase is authorized or explicitly deferred.
If authorized, execute P8-01 through P8-11. Start daily, predeclare experiments,
fit transforms/model on training only, and use causal filtering. Test that
future data does not rewrite past decision-time predictions for a fixed model.
Version state mapping/artifacts; do not force five meaningful labels or call
posterior confidence win probability. Compare filter and allocation separately
with identical baseline data/costs. Risk remains authoritative. Activate only
with out-of-sample evidence and owner approval; rejection/deferral is valid.
```

## 11. Phase 9 — Dashboard prompt

```text
Execute P9-01 through P9-15 after predecessor gates, including explicit HMM
deferral if applicable. Follow Design.md with a local read-only default.
Show actual paper account/cash/BTC/orders/fills/fees/P&L, Z-score strategy state,
approved risk limits/exposure/borrowing disabled, circuit status, diagnostics,
and per-source freshness. Regime views require recorded model outputs.
Label research suggestions inactive and separate paper/backtest/model costs.
No fake metrics, live toggle, or trading/retraining on refresh. Authenticate
exposed APIs. Run actual browser/UI and data reconciliation tests. Test recovery,
backup/restore, disconnects, and shutdown; record verified commands and stop.
```

## 12. Phase 10 — Paper observation prompt

```text
Execute P10-01 through P10-09 with an approved account and observation interval.
Pin versions, report operational/research evidence separately, and compare
paper fills/costs with assumptions. Exercise bounded recovery drills, preserve
negative results, and avoid confident AI conclusions from sparse trades.
A month of observation is not proof of profitability. No live promotion.
Record evidence and stop for owner review.
```

## 13. Standard closeout prompt

```text
Close only the authorized work actually performed:
1. List task IDs, changed files, and behavior.
2. List exact commands and inspected results.
3. Separate passed, failed, skipped, and not-run checks.
4. State gate status with evidence; mark optional deferrals explicitly.
5. Record decisions, unresolved inputs, and unblock conditions.
6. Update Phases.md evidence and Memory.md only if coding has begun.
7. Report commit/push/browser results only if actually performed.
8. Give one next bounded task and stop before an unauthorized phase.
```
