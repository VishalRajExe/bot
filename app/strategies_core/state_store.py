"""Persistent, restart-safe store for FVG/OB per-pair setup state.

The owner spec requires the bot to remember its sequence state across restarts and
never duplicate an entry because of a restart or a repeated signal. This writes one
small JSON file (atomic tmp+replace) keyed by pair. It is deliberately independent of
the Freqtrade trade DB: it stores *intent/sequence* state, not execution truth.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "app" / "state" / "fvg_ob"


def _path(pair: str) -> Path:
    safe = pair.replace("/", "_")
    return STATE_DIR / f"{safe}.json"


def save(pair: str, snapshot: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(snapshot)
    payload["_saved_at"] = datetime.now(timezone.utc).isoformat()
    p = _path(pair)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def load(pair: str) -> Optional[dict]:
    p = _path(pair)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt file => treated as no state
        return None


def clear(pair: str) -> None:
    p = _path(pair)
    if p.exists():
        p.unlink()
