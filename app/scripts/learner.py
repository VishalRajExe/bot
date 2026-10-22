"""UnboundBot learning loop (Phase D) — read-only, idempotent.

Consumes the durable ledger that the reconcile step already mirrors (paper_trades) and
produces the two artifacts the trading path consults on every entry:

  * ``app/state/perf.json``          — per-(pair, family) rolling metrics that drive
                                        ``policy.evidence_multiplier`` (sizing scaling).
  * ``app/state/strategy_gate.json`` — auto-demotions (pair stopped making new entries
                                        after n>=N_MIN closed trades with a NON-POSITIVE
                                        after-fee expectancy). Promotion is NEVER
                                        automatic: only an owner re-approval (a fresh
                                        edit of this file or the registry) can undo a
                                        demotion, so the gate cannot flap.

The runner performs ZERO broker interaction, ZERO order placement, and NEVER edits the
committed ``strategy_registry.json``. It only reads the ledger and writes the two state
JSONs. Freqtrade-side journal construction (adding ``family`` and R-multiple to each
closed trade) lives in ``app/learn/journal.py`` — this script just orchestrates it.

NOTE: this file is named ``learner.py`` (not ``learn.py``) to avoid shadowing the
``app/learn/`` package that both this script and the tests import.

Usage:
  python app/scripts/learner.py              # build + emit once
  python app/scripts/learner.py --watch 900  # rerun every 900s (Ctrl-C stops)
Exit codes: 0 = wrote artifacts (or nothing to do), 2 = ledger unavailable.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make app/ importable regardless of the caller's cwd.
_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import obs_lib as O  # noqa: E402
from learn import journal, perf  # noqa: E402
from risk import policy  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_existing(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _merge_gate(existing: dict, new_demotions: list[dict]) -> dict:
    """Append-only merge on the demotions list. A pair/family already demoted keeps its
    original ``since`` timestamp; the runner never removes an entry (no auto-promote).
    Existing owner-authored entries (with any extra keys) are preserved verbatim."""
    prev = existing.get("demoted") or []
    by_key = {(d.get("pair"), d.get("family")): d for d in prev}
    for d in new_demotions:
        key = (d.get("pair"), d.get("family"))
        if key in by_key:
            continue  # already demoted — do not bump the timestamp or rewrite reason
        by_key[key] = d
    merged = sorted(by_key.values(), key=lambda x: (x.get("pair") or "", x.get("family") or ""))
    return {"updated_at": _now_iso(), "demoted": merged,
            "note": "Auto-demotions from the Phase D strategy gate. Never auto-"
                    "promoted: an owner must delete the entry (after a fresh backtest) "
                    "to re-enable a pair/family."}


def run_once() -> int:
    """Build the journal from closed paper_trades, emit perf.json + strategy_gate.json.
    Returns 0 on success (including 'no data yet'), 2 if the ledger is unavailable."""
    try:
        con = O.ledger_connect()
    except Exception as e:  # noqa: BLE001
        print(f"ledger unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        n_written = journal.build_journal(con)
        records = journal.closed_records(con)
    finally:
        con.close()

    stats = perf.by_pair_family(records)
    perf_payload = {
        "asof": _now_iso(),
        "n_closed_in_journal": len(records),
        "n_journal_rows_written": n_written,
        "N_MIN": perf.N_MIN,
        "SCALE_MIN": perf.SCALE_MIN,
        "SCALE_MAX": perf.SCALE_MAX,
        "by_pair_family": stats,
    }
    policy.write_json(policy.perf_path(), perf_payload)

    # Build the demotion delta for pairs/families with enough evidence AND a non-positive
    # expectancy. We only ever ADD demotions, never REMOVE them (no auto-promote).
    new_demos: list[dict] = []
    for key, st in stats.items():
        if not perf.should_demote(st):
            continue
        pair, _, family = key.partition("|")
        new_demos.append({
            "pair": pair,
            "family": family or None,
            "reason": f"expectancy_R={st.get('expectancy_R')} <= 0 at n={st.get('n')} (>= N_MIN {perf.N_MIN})",
            "since": _now_iso(),
            "expectancy_R": st.get("expectancy_R"),
            "n": st.get("n"),
        })

    gate_existing = _load_existing(policy.strategy_gate_path())
    gate_merged = _merge_gate(gate_existing, new_demos)
    policy.write_json(policy.strategy_gate_path(), gate_merged)

    n_demos = len(gate_merged["demoted"])
    print(f"journal rows={n_written} closed={len(records)} groups={len(stats)} "
          f"demoted_total={n_demos} newly_demoted={len(new_demos)}")
    return 0


def main(argv=None) -> int:
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="UnboundBot Phase D learning loop")
    ap.add_argument("--watch", type=int, default=0,
                    help="If > 0, re-run every N seconds until Ctrl-C/SIGTERM.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    code = run_once()
    if args.watch <= 0:
        return code
    stop = {"f": False}

    def _halt(*_a):
        stop["f"] = True

    try:
        signal.signal(signal.SIGINT, _halt)
        signal.signal(signal.SIGTERM, _halt)
    except Exception:  # noqa: BLE001
        pass
    print(f"learning every {args.watch}s (Ctrl-C to stop)...")
    while not stop["f"]:
        time.sleep(args.watch)
        if stop["f"]:
            break
        run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
