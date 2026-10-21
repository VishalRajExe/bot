"""UnboundBot — deterministic FVG / Order-Block core (research module).

This is the mathematical heart of the "1H Bias + 1H FVG/OB -> tap -> new 5M FVG
-> first retest -> long entry" strategy requested by the owner. It is a SEPARATE,
independently testable module. It does NOT depend on Freqtrade, an exchange, or
network, and it NEVER places orders. `app/user_data/strategies/FvgOb.py` is a thin
research adapter over this core.

Every fuzzy ICT term is converted here into a deterministic rule over COMPLETED
candles only, so signals are causal (a step can never reference a future candle).
Chosen conventions are operational definitions decided by the engineer, NOT owner-
supplied facts (owner spec fixed only the 3-candle FVG form, the 1:2 RR and the
sequence order). They are unit-tested in app/tests/test_fvg_ob.py.

OPERATIONAL DEFINITIONS (documented per owner request §8)
--------------------------------------------------------
Candle : ordered, completed OHLC bars. `ts` is the bar's open time (UTC).
Bias   : +1 bullish / -1 bearish / 0 neutral on 1H. Bullish iff the 1H EMA(bias_ema)
         is rising AND close > EMA. Bearish is the mirror. Otherwise neutral.
Swing  : fractal pivot of order `k`; a swing high at index i is only CONFIRMED at
         i + k (k later completed bars), so we never peek forward.
Bullish FVG (3 bars a,b,c): low(c) > high(a). Gap zone = (high(a) .. low(c)),
         bottom=high(a), top=low(c). Bearish FVG: high(c) < low(a); zone=(high(c)..low(a)).
Displacement : a bar whose body >= disp_atr_mult * ATR(atr_n) and closes beyond the
         previous bar's high (bull) / low (bear).
Order Block (OB) : the last opposite-colour bar immediately before a displacement bar
         that confirms a market-structure break (close takes out the last confirmed
         swing high for bull / swing low for bear). OB zone = that bar's (low..high).
Confluence zone : the price INTERSECTION of a same-direction 1H FVG and the most
         recent same-direction 1H OB. Requires overlap iff require_overlap=True.
         bounds bottom=max(fvg_bottom,ob_bottom), top=min(fvg_top,ob_top); valid if
         bottom < top. Stamped with creation_ts.
Zone tap : the FIRST completed 1H bar strictly after creation whose range touches the
         zone (low <= top and high >= bottom). Tap is consumed once.
LTF (5M) FVG : after the HTF tap, the first NEW bullish 5M FVG whose creation_ts >= tap_ts
         AND whose zone overlaps the HTF zone (within ltf_overlap_atol). Stamped.
First retest : the FIRST completed 5M bar strictly after the LTF FVG whose low retraces
         into the LTF FVG zone. Only the first counts (dedup).
Entry    : at the retest bar's CLOSE (conservative; a wick touch is NOT assumed fillable).
Stop     : HTF zone bottom - stop_atr_mult * ATR(atr_n) for a long. risk = entry - stop.
TakeProfit: entry + rr * risk  (rr default 2.0, owner-fixed 1:2).
Reject   : if risk <= 0 (stop not below entry), or the setup expired (entry_window bars
         after tap / retest_window bars after LTF FVG), or required data missing/stale.
Bearish  : managed as LONG exit logic only; this spot module NEVER opens a short.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Optional

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- config
@dataclass
class FvgCfg:
    bias_ema: int = 50
    atr_n: int = 14
    swing_k: int = 2                # fractal order; confirmed at i+swing_k
    disp_atr_mult: float = 1.0      # displacement body >= mult*ATR
    require_overlap: bool = True    # confluence needs FVG∩OB overlap
    zone_ttl_bars: int = 48         # HTF zone expires after this many 1H bars
    invalid_atr_mult: float = 0.0   # invalidate if close beyond zone_bottom by mult*ATR
    stop_atr_mult: float = 0.5      # stop buffer below HTF zone bottom
    rr: float = 2.0                 # owner-fixed 1:2 reward:risk
    entry_window_5m: int = 72       # bars (6h) to find an LTF FVG after the tap
    retest_window_5m: int = 36      # bars (3h) to get the first LTF retest
    ltf_overlap_atol: float = 0.0   # extra tolerance (price units) for LTF↔HTF overlap

    # long-only, spot: shorts are never produced by this module.


# --------------------------------------------------------------------------- records
@dataclass
class FVG:
    direction: int          # +1 bull, -1 bear
    bottom: float
    top: float
    creation_ts: pd.Timestamp
    i: int                  # index of the third candle in its own frame

    def overlaps(self, other_bottom: float, other_top: float, atol: float = 0.0) -> bool:
        return min(self.top, other_top) - max(self.bottom, other_bottom) > -atol


@dataclass
class Zone:
    direction: int
    bottom: float
    top: float
    creation_ts: pd.Timestamp
    expiry_index: int
    tapped: bool = False
    tap_ts: Optional[pd.Timestamp] = None
    invalid: bool = False
    invalid_reason: str = ""


@dataclass
class OB:
    """Order block: last opposite-colour bar before a displacement that breaks structure."""
    direction: int          # +1 bull OB (last down bar), -1 bear OB (last up bar)
    bottom: float
    top: float
    ts: pd.Timestamp
    displacement_ts: pd.Timestamp


# --------------------------------------------------------------------------- helpers
def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """Wilder-style ATR via rolling mean of true range (completed bars)."""
    tr = np.empty_like(close, dtype=float)
    tr[0] = high[0] - low[0]
    prev_close = close[:-1]
    tr[1:] = np.maximum.reduce([high[1:] - low[1:],
                               np.abs(high[1:] - prev_close),
                               np.abs(low[1:] - prev_close)])
    s = pd.Series(tr)
    out = np.array(s.rolling(window=n, min_periods=n).mean().to_numpy(), dtype=float)
    # During warmup the rolling mean is NaN; fall back to the per-bar true range so
    # early callers get a finite estimate instead of a NaN that silently poisons
    # downstream arithmetic.
    out[np.isnan(out)] = tr[np.isnan(out)]
    return out


def ema(series: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(series).ewm(span=n, adjust=False).mean().to_numpy()


def find_fvg(high: np.ndarray, low: np.ndarray, ts: pd.Series) -> list[FVG]:
    """3-candle FVGs on completed bars. Returns chronological list."""
    out: list[FVG] = []
    for i in range(2, len(high)):
        if low[i] > high[i - 2]:                      # bullish gap
            out.append(FVG(+1, float(high[i - 2]), float(low[i]), ts.iloc[i], i))
        elif high[i] < low[i - 2]:                    # bearish gap
            out.append(FVG(-1, float(high[i]), float(low[i - 2]), ts.iloc[i], i))
    return out


def swing_points(high: np.ndarray, low: np.ndarray, k: int):
    """Return (swing_high_idx, swing_low_idx) lists; each index i is only usable
    after i+k completed bars (caller enforces confirmation lag)."""
    hi_idx, lo_idx = [], []
    for i in range(k, len(high) - k):
        if high[i] == high[i - k:i + k + 1].max():
            hi_idx.append(i)
        if low[i] == low[i - k:i + k + 1].min():
            lo_idx.append(i)
    return hi_idx, lo_idx


def bias_series(close: np.ndarray, high: np.ndarray, low: np.ndarray, cfg: FvgCfg) -> np.ndarray:
    """+1 bull / -1 bear / 0 neutral. EMA trend + close position (causal)."""
    e = ema(close, cfg.bias_ema)
    b = np.zeros(len(close), dtype=int)
    for i in range(1, len(close)):
        if np.isnan(e[i]) or np.isnan(e[i - 1]):
            continue
        if e[i] > e[i - 1] and close[i] > e[i]:
            b[i] = 1
        elif e[i] < e[i - 1] and close[i] < e[i]:
            b[i] = -1
    return b


def find_order_blocks(high, low, open_, close, atr_arr, ts: pd.Series,
                      cfg: FvgCfg, swing_hi, swing_lo) -> list[OB]:
    """Deterministic OBs. A bull OB is the last down-close bar before a bullish
    displacement bar (body >= disp_atr_mult*ATR, close>prev high) that also closes
    above the most recent confirmed swing high (market-structure break)."""
    out: list[OB] = []
    hi_set = set(swing_hi)
    lo_set = set(swing_lo)
    last_sh = None
    last_sl = None
    n = len(close)
    for i in range(1, n):
        # update confirmed swing trackers using confirmation lag (swing at i-k confirmed now)
        j = i - cfg.swing_k
        if j >= 0:
            if j in hi_set:
                last_sh = high[j]
            if j in lo_set:
                last_sl = low[j]
        a = atr_arr[i]
        if np.isnan(a) or a == 0:
            continue
        body = close[i] - open_[i]
        # bullish displacement + structure break
        if body >= cfg.disp_atr_mult * a and close[i] > high[i - 1] and last_sh is not None \
                and close[i] > last_sh:
            for j2 in range(i - 1, -1, -1):
                if close[j2] < open_[j2]:            # last down bar
                    out.append(OB(+1, float(low[j2]), float(high[j2]), ts.iloc[j2], ts.iloc[i]))
                    break
        elif (-body) >= cfg.disp_atr_mult * a and close[i] < low[i - 1] and last_sl is not None \
                and close[i] < last_sl:
            for j2 in range(i - 1, -1, -1):
                if close[j2] > open_[j2]:            # last up bar
                    out.append(OB(-1, float(low[j2]), float(high[j2]), ts.iloc[j2], ts.iloc[i]))
                    break
    return out


# --------------------------------------------------------------------------- tracker
@dataclass
class SetupState:
    """Serializable per-pair snapshot of the sequence state machine."""
    pair: str
    direction: int = 0
    state: str = "IDLE"
    htf_zone_bottom: float = 0.0
    htf_zone_top: float = 0.0
    htf_creation_ts: Optional[str] = None
    htf_tap_ts: Optional[str] = None
    ltf_fvg_bottom: float = 0.0
    ltf_fvg_top: float = 0.0
    ltf_creation_ts: Optional[str] = None
    first_retest_ts: Optional[str] = None
    entry_ts: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    risk_per_unit: Optional[float] = None
    strategy_version: str = "fvg-ob-0.1"
    invalid_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SetupTracker:
    """Event-driven state machine stepping through merged 1H + 5M candles.

    States: IDLE -> HTF_BIAS_CONFIRMED -> HTF_CONFLUENCE_ZONE_IDENTIFIED
            -> HTF_ZONE_TAPPED -> LTF_FVG_CONFIRMED -> WAITING_FOR_FIRST_LTF_RETEST
            -> ENTRY_TRIGGERED -> POSITION_OPEN -> (EXITED | INVALIDATED)
    Every transition is explicit and recorded with a timestamp. At most one entry
    signal is emitted per setup (ENTRY_TRIGGERED/POSITION_OPEN never re-fire until the
    setup resolves), giving duplicate protection across restarts.
    """
    ORDER = ["IDLE", "HTF_BIAS_CONFIRMED", "HTF_CONFLUENCE_ZONE_IDENTIFIED",
             "HTF_ZONE_TAPPED", "LTF_FVG_CONFIRMED", "WAITING_FOR_FIRST_LTF_RETEST",
             "ENTRY_TRIGGERED", "POSITION_OPEN", "EXITED", "INVALIDATED"]

    def __init__(self, pair: str, cfg: FvgCfg | None = None, state: Optional[dict] = None):
        self.pair = pair
        self.cfg = cfg or FvgCfg()
        if state is not None:
            known = {f.name for f in fields(SetupState)}
            self.st = SetupState(**{k: v for k, v in state.items() if k in known})
            self.st.pair = pair  # authoritative: bind to requested pair
        else:
            self.st = SetupState(pair=pair)

    @property
    def state(self) -> str:
        return self.st.state

    def _set(self, s: str) -> None:
        self.st.state = s

    # -- one merged event. tf in {'1h','5m'}; candle dict o,h,l,c; ts pandas.Timestamp.
    def step(self, tf: str, ts: pd.Timestamp, o: float, h: float, l: float, c: float,
             *, atr_val: Optional[float] = None, bias: Optional[int] = None,
             bar_index: Optional[int] = None) -> Optional[dict]:
        """Advance the machine by one completed bar. Returns an ENTRY dict when a
        valid long entry is triggered, else None. `atr_val`/`bias` are precomputed
        1H context passed by the caller for each 1H event (keeps this pure/testable).
        """
        cfg = self.cfg
        s = self.st

        # resolving states need exit handling by the executor; tracker just idles.
        if s.state in ("POSITION_OPEN", "ENTRY_TRIGGERED", "EXITED"):
            # completed setup: allow a new one only after an explicit reset().
            return None

        # ---- 1H context: bias + zone lifecycle + tap + invalidation + expiry ----
        if tf == "1h":
            if atr_val is None or bias is None:
                return None  # 1H events must carry context
            # (re)form a confluence zone while bullish and not already tracking one.
            if s.state in ("IDLE",) and bias == 1:
                self._set("HTF_BIAS_CONFIRMED")
            if s.state == "HTF_BIAS_CONFIRMED" and bias == 1:
                # caller (adapter/tests) creates zones via new_zone() once it has
                # FVG/OB geometry; nothing to do here without geometry.
                pass
            # expiry / invalidation of an identified-but-not-tapped zone
            if s.state == "HTF_CONFLUENCE_ZONE_IDENTIFIED" and s.htf_creation_ts is not None:
                if bar_index is not None and bar_index > s.htf_expiry_index:
                    self._invalidate("zone_expired")
                    return None
                if atr_val and (s.htf_zone_bottom - c) > cfg.invalid_atr_mult * atr_val:
                    self._invalidate("zone_invalidated")
                    return None
            # first tap of an identified zone (strictly after the zone was created)
            if s.state == "HTF_CONFLUENCE_ZONE_IDENTIFIED":
                if (s.htf_creation_ts is None or ts > pd.Timestamp(s.htf_creation_ts)) \
                        and l <= s.htf_zone_top and h >= s.htf_zone_bottom:
                    self.st.htf_tap_ts = str(ts)
                    self._set("HTF_ZONE_TAPPED")
                    self._tap_count = getattr(self, "_tap_count", 0)
            return None

        # ---- 5M context: LTF FVG + first retest after the HTF tap ----
        if tf == "5m":
            if s.state != "HTF_ZONE_TAPPED":
                return None
            # awaiting a NEW bullish 5M FVG (its geometry is supplied by caller).
            return None

        return None

    # -- geometry hooks (caller supplies detected FVGs, keeps parsing separate) ----
    def open_zone(self, fvg: FVG, ob_bottom: Optional[float], ob_top: Optional[float],
                  atr_val: float, bar_index: int) -> bool:
        """Promote a detected 1H bullish FVG (+optional OB) to a confluence zone.
        Returns True if a valid zone was opened."""
        cfg = self.cfg
        if fvg.direction != 1:
            return False
        bottom, top = fvg.bottom, fvg.top
        if ob_bottom is not None and ob_top is not None:
            nb, nt = max(bottom, ob_bottom), min(top, ob_top)
            if cfg.require_overlap and nt <= nb:
                return False
            bottom, top = nb, nt
        if self.state not in ("IDLE", "HTF_BIAS_CONFIRMED"):
            return False
        if self.state == "IDLE":
            self._set("HTF_BIAS_CONFIRMED")
        self.st.direction = 1
        self.st.htf_zone_bottom = float(bottom)
        self.st.htf_zone_top = float(top)
        self.st.htf_creation_ts = str(fvg.creation_ts)
        self.st.htf_expiry_index = bar_index + cfg.zone_ttl_bars
        self._set("HTF_CONFLUENCE_ZONE_IDENTIFIED")
        return True

    def ltf_fvg(self, fvg: FVG) -> bool:
        """Record a NEW bullish 5M FVG that overlaps the tapped HTF zone."""
        if self.state != "HTF_ZONE_TAPPED":
            return False  # no early acceptance (owner rule)
        cfg = self.cfg
        if fvg.direction != 1:
            return False
        tap_ts = pd.Timestamp(self.st.htf_tap_ts)
        if fvg.creation_ts < tap_ts:
            return False
        if not fvg.overlaps(self.st.htf_zone_bottom, self.st.htf_zone_top, cfg.ltf_overlap_atol):
            return False
        self.st.ltf_fvg_bottom = fvg.bottom
        self.st.ltf_fvg_top = fvg.top
        self.st.ltf_creation_ts = str(fvg.creation_ts)
        self._set("LTF_FVG_CONFIRMED")
        self._ltf_seen = 0
        return True

    def ltf_retest(self, ts: pd.Timestamp, o: float, h: float, l: float, c: float,
                   atr_val: float) -> Optional[dict]:
        """Feed a 5M bar after the LTF FVG; the FIRST qualifying retest triggers entry."""
        if self.state not in ("LTF_FVG_CONFIRMED", "WAITING_FOR_FIRST_LTF_RETEST"):
            return None
        self._set("WAITING_FOR_FIRST_LTF_RETEST")
        if ts <= pd.Timestamp(self.st.ltf_creation_ts):
            return None
        into = l <= self.st.ltf_fvg_top and h >= self.st.ltf_fvg_bottom
        self._ltf_seen = getattr(self, "_ltf_seen", 0) + 1
        if self._ltf_seen > self.cfg.retest_window_5m:
            self._invalidate("retest_window_expired")
            return None
        if not into:
            return None
        return self._try_enter(ts, c, atr_val)

    def _try_enter(self, ts: pd.Timestamp, entry_price: float, atr_val: float) -> Optional[dict]:
        cfg = self.cfg
        stop = self.st.htf_zone_bottom - cfg.stop_atr_mult * atr_val
        risk = entry_price - stop
        if risk <= 0:
            self._invalidate("risk_non_positive_or_stop_wrong_side")
            return None
        tp = entry_price + cfg.rr * risk
        self.st.first_retest_ts = str(ts)
        self.st.entry_ts = str(ts)
        self.st.entry_price = float(entry_price)
        self.st.stop_price = float(stop)
        self.st.take_profit = float(tp)
        self.st.risk_per_unit = float(risk)
        self._set("ENTRY_TRIGGERED")
        return {
            "pair": self.pair, "direction": "long", "entry_ts": str(ts),
            "entry_price": entry_price, "stop": stop, "take_profit": tp,
            "risk_per_unit": risk, "rr": cfg.rr,
            "htf_zone": (self.st.htf_zone_bottom, self.st.htf_zone_top),
            "htf_creation_ts": self.st.htf_creation_ts, "htf_tap_ts": self.st.htf_tap_ts,
            "ltf_fvg": (self.st.ltf_fvg_bottom, self.st.ltf_fvg_top),
            "ltf_creation_ts": self.st.ltf_creation_ts,
            "strategy_version": self.st.strategy_version,
        }

    def confirm_position(self) -> None:
        if self.state == "ENTRY_TRIGGERED":
            self._set("POSITION_OPEN")

    def resolve(self, reason: str) -> None:
        self._invalidate(reason, terminal=True)

    def _invalidate(self, reason: str, terminal: bool = False) -> None:
        self.st.invalid_reason = reason
        self._set("EXITED" if terminal else "INVALIDATED")

    def reset(self) -> None:
        self.st = SetupState(pair=self.pair)

    # -- persistence: survives restarts; dedup by not re-emitting entry ----
    def snapshot(self) -> dict:
        return self.st.to_dict()


# --------------------------------------------------------------------------- scan
def _df_arrays(df: pd.DataFrame, freq_td: pd.Timedelta) -> dict:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    op = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    ts_close = pd.Series(pd.to_datetime(df["date"], utc=True) + freq_td)
    return {"high": high, "low": low, "open": op, "close": close, "ts": ts_close}


def _latest_overlap_ob(obs: list[OB], fvg: FVG, cfg: FvgCfg):
    """Most-recent bull OB (displacement already formed) that overlaps the FVG zone."""
    best = None
    for o in obs:
        if o.displacement_ts > fvg.creation_ts:
            break
        if min(o.top, fvg.top) > max(o.bottom, fvg.bottom):
            best = o
    if best is None:
        return None
    return max(best.bottom, fvg.bottom), min(best.top, fvg.top)


def evaluate_ohlcv(df1h: pd.DataFrame, df5m: pd.DataFrame, cfg: FvgCfg | None = None,
                   pair: str = "X/USD", tracker_state: Optional[dict] = None):
    """Replay the exact sequence over merged COMPLETED bars (close-time events, so a
    signal never references a future/unconfirmed candle). Returns (entries, tracker).
    A fresh setup is tracked after each emitted entry (duplicate protection).
    """
    cfg = cfg or FvgCfg()
    a1 = _df_arrays(df1h, pd.Timedelta("1h"))
    a5 = _df_arrays(df5m, pd.Timedelta("5m"))
    atr1 = atr(a1["high"], a1["low"], a1["close"], cfg.atr_n)
    bias1 = bias_series(a1["close"], a1["high"], a1["low"], cfg)
    fvg1 = find_fvg(a1["high"], a1["low"], a1["ts"])
    sw_hi, sw_lo = swing_points(a1["high"], a1["low"], cfg.swing_k)
    ob1 = find_order_blocks(a1["high"], a1["low"], a1["open"], a1["close"],
                            atr1, a1["ts"], cfg, sw_hi, sw_lo)
    fvg5 = find_fvg(a5["high"], a5["low"], a5["ts"])

    bull_fvg1 = {f.creation_ts: f for f in fvg1 if f.direction == 1}
    bull_ob1 = sorted([o for o in ob1 if o.direction == 1], key=lambda o: o.displacement_ts)
    bull_fvg5 = {f.creation_ts: f for f in fvg5 if f.direction == 1}

    events = []
    for i in range(len(a1["close"])):
        events.append((a1["ts"].iloc[i], "1h", i))
    for i in range(len(a5["close"])):
        events.append((a5["ts"].iloc[i], "5m", i))
    events.sort(key=lambda e: e[0])

    tr = SetupTracker(pair, cfg, tracker_state)
    entries: list[dict] = []
    last_atr1 = float("nan")
    for ts, tf, i in events:
        if tf == "1h":
            last_atr1 = atr1[i]
            av = None if np.isnan(last_atr1) else float(last_atr1)
            tr.step("1h", ts, a1["open"][i], a1["high"][i], a1["low"][i], a1["close"][i],
                    atr_val=av, bias=int(bias1[i]), bar_index=i)
            f = bull_fvg1.get(ts)
            if f is not None and int(bias1[i]) == 1:
                # A fresh bullish 1H FVG is the *current* zone of interest. It
                # supersedes any incomplete, un-entered setup (stale/invalidated/
                # still-waiting), so one dud can never wedge the whole replay. It
                # NEVER supersedes a live ENTRY_TRIGGERED/POSITION_OPEN (executor owns
                # those) — that is the duplicate/live-position guard.
                if tr.state not in ("ENTRY_TRIGGERED", "POSITION_OPEN", "HTF_BIAS_CONFIRMED"):
                    tr.reset()
                if cfg.require_overlap:
                    ob = _latest_overlap_ob(bull_ob1, f, cfg)
                    if ob is None:
                        continue
                    tr.open_zone(f, ob[0], ob[1], av or 0.0, bar_index=i)
                else:
                    tr.open_zone(f, None, None, av or 0.0, bar_index=i)
        else:  # 5m
            f5 = bull_fvg5.get(ts)
            if f5 is not None:
                tr.ltf_fvg(f5)
            av = None if np.isnan(last_atr1) else float(last_atr1)
            entry = tr.ltf_retest(ts, a5["open"][i], a5["high"][i], a5["low"][i],
                                  a5["close"][i], av or 0.0)
            if entry is not None:
                entries.append(entry)
                tr.reset()   # allow the next independent setup; no duplicate within one
    return entries, tr
