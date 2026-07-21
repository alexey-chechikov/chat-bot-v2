"""Session Breakout pure signal logic — testable, без I/O.

Session conventions (UTC):
  asia:     00:00 — 08:00
  london:   08:00 — 13:00
  ny_am:    13:00 — 17:00
  ny_lunch: 17:00 — 19:00
  ny_pm:    19:00 — 24:00

Prior-session map (transition → what was BEFORE):
  asia    ← ny_pm  (previous day)
  london  ← asia
  ny_am   ← london
  ny_lunch← ny_am
  ny_pm   ← ny_lunch
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional

import pandas as pd


# Session start hours (UTC) — inclusive lower bound.
SESSION_STARTS = [
    ("asia", 0),
    ("london", 8),
    ("ny_am", 13),
    ("ny_lunch", 17),
    ("ny_pm", 19),
]

PRIOR_OF = {
    "asia": "ny_pm",     # prior session was YESTERDAY's ny_pm
    "london": "asia",
    "ny_am": "london",
    "ny_lunch": "ny_am",
    "ny_pm": "ny_lunch",
}


@dataclass
class SessionBreakoutParams:
    entry_window_min: int = 15    # окно входа после смены сессии
    buffer_pct: float = 0.0       # касание уровня = вход (0%)
    hold_h: int = 3               # держим 3 часа
    stop_loss_pct: float = 0.6    # SL = entry ± 0.6%
    tp_ratio: float = 1.5         # TP = SL × 1.5 (RR 1:1.5)
    size_usd: float = 1_000.0     # из бэктеста
    contract: str = "XBTUSDT"     # BitMEX linear


@dataclass
class SessionBreakoutSignal:
    ts: str
    side: str                     # "long" | "short"
    transition: str               # e.g. "ny_pm_to_asia"
    new_session: str
    prior_session: str
    time_in_session_min: int
    mid: float
    entry: float
    stop: float
    tp: float
    prior_high: float
    prior_low: float
    breakout_level: float         # which level was broken
    size_usd: float
    contract: str
    hold_h: int

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = SessionBreakoutParams()


def session_at(ts: datetime) -> tuple[str, int]:
    """Return (session_name, time_in_session_min) for given UTC ts.

    No "dead" gap — ny_pm extends 19:00 to next 00:00.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hour = ts.hour
    minute = ts.minute

    # Iterate from latest start backwards — find session whose start <= ts.hour
    current = "ny_pm"
    start_hour = 19
    for name, h in SESSION_STARTS:
        if hour >= h:
            current = name
            start_hour = h
    tis = (hour - start_hour) * 60 + minute
    return current, tis


def session_start_for(ts: datetime, session: str) -> datetime:
    """Return start datetime of the named session for the day of ts."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    starts = dict(SESSION_STARTS)
    start_hour = starts.get(session, 0)
    return ts.replace(hour=start_hour, minute=0, second=0, microsecond=0)


def prior_session_window(ts: datetime, current_session: str) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetime of the PRIOR session for given current session.

    For asia (00:00-08:00) prior is ny_pm of YESTERDAY (19:00-24:00 prev day).
    For london (08:00-13:00) prior is asia TODAY (00:00-08:00).
    Etc.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    prior = PRIOR_OF[current_session]

    # If current is asia, prior is ny_pm of YESTERDAY
    if current_session == "asia":
        prior_start = (ts - timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        prior_end = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return prior_start, prior_end

    # Otherwise prior is same day, immediately before current session
    starts = dict(SESSION_STARTS)
    prior_start_hour = starts[prior]
    cur_start_hour = starts[current_session]
    prior_start = ts.replace(hour=prior_start_hour, minute=0, second=0, microsecond=0)
    prior_end = ts.replace(hour=cur_start_hour, minute=0, second=0, microsecond=0)
    return prior_start, prior_end


def prior_session_ohlc(df_1m: pd.DataFrame, ts: datetime,
                       current_session: str) -> Optional[tuple[float, float]]:
    """Compute (high, low) of prior session from 1m OHLCV.

    df_1m must have DatetimeIndex (UTC) and columns 'high','low'.
    Returns None if window has no bars.
    """
    if df_1m.empty:
        return None
    start, end = prior_session_window(ts, current_session)

    idx = df_1m.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
        df_1m = df_1m.copy()
        df_1m.index = idx

    mask = (df_1m.index >= start) & (df_1m.index < end)
    win = df_1m[mask]
    if win.empty:
        return None
    return float(win["high"].max()), float(win["low"].min())


def compute_signal(df_1m: pd.DataFrame, *,
                   now: datetime,
                   params: SessionBreakoutParams = DEFAULT_PARAMS,
                   ) -> Optional[SessionBreakoutSignal]:
    """Check if a session breakout signal fires at `now`.

    Conditions:
      1. time_in_session_min ≤ entry_window_min
      2. prior_session high/low computable from df_1m
      3. recent bars (from session start) high broke prior_high → LONG,
         OR low broke prior_low → SHORT.
      4. Caller is responsible for dedup (1 signal per session boundary).
    """
    if df_1m.empty:
        return None

    new_session, tis = session_at(now)
    if tis > params.entry_window_min:
        return None

    ohlc = prior_session_ohlc(df_1m, now, new_session)
    if ohlc is None:
        return None
    prior_high, prior_low = ohlc

    # Look at bars within current session so far
    sess_start = session_start_for(now, new_session)
    idx = df_1m.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
        df_1m = df_1m.copy()
        df_1m.index = idx
    cur = df_1m[df_1m.index >= sess_start]
    if cur.empty:
        return None

    recent_high = float(cur["high"].max())
    recent_low = float(cur["low"].min())
    mid = float(cur["close"].iloc[-1])

    target_high = prior_high * (1.0 + params.buffer_pct / 100.0)
    target_low = prior_low * (1.0 - params.buffer_pct / 100.0)

    side: Optional[str] = None
    broken_level = 0.0
    if recent_high >= target_high:
        side = "long"
        broken_level = target_high
    elif recent_low <= target_low:
        side = "short"
        broken_level = target_low
    if side is None:
        return None

    sl_frac = params.stop_loss_pct / 100.0
    tp_frac = sl_frac * params.tp_ratio
    if side == "long":
        entry = mid
        stop = entry * (1.0 - sl_frac)
        tp = entry * (1.0 + tp_frac)
    else:
        entry = mid
        stop = entry * (1.0 + sl_frac)
        tp = entry * (1.0 - tp_frac)

    prior = PRIOR_OF[new_session]
    transition = f"{prior}_to_{new_session}"

    return SessionBreakoutSignal(
        ts=now.replace(microsecond=0).isoformat(),
        side=side,
        transition=transition,
        new_session=new_session,
        prior_session=prior,
        time_in_session_min=int(tis),
        mid=round(mid, 2),
        entry=round(entry, 2),
        stop=round(stop, 2),
        tp=round(tp, 2),
        prior_high=round(prior_high, 2),
        prior_low=round(prior_low, 2),
        breakout_level=round(broken_level, 2),
        size_usd=params.size_usd,
        contract=params.contract,
        hold_h=params.hold_h,
    )


def format_tg_card(sig: SessionBreakoutSignal, *,
                    expiry_ts: Optional[datetime] = None) -> str:
    """Build TG message text. Per docs/STRATEGIES/SESSION_BREAKOUT_BACKTEST.md
    expected metrics: PF 1.85, WR 56% across all transitions."""
    if expiry_ts is None:
        expiry_ts = datetime.now(timezone.utc) + timedelta(hours=sig.hold_h)
    expiry_str = expiry_ts.strftime("%H:%M UTC")

    arrow = "🟢 LONG" if sig.side == "long" else "🔴 SHORT"
    sl_usd = sig.size_usd * abs(sig.entry - sig.stop) / sig.entry
    tp_usd = sig.size_usd * abs(sig.tp - sig.entry) / sig.entry

    lines = [
        f"⚡ SESSION BREAKOUT {arrow} [{sig.transition}]",
        f"BTC mid: ${sig.mid:,.2f}  (in {sig.time_in_session_min}min of new session)",
        f"Prior {sig.prior_session}: H=${sig.prior_high:,.2f} / L=${sig.prior_low:,.2f}",
        f"Broken level: ${sig.breakout_level:,.2f}",
        "",
        f"📋 Market {'BUY' if sig.side == 'long' else 'SELL'} {sig.contract}:",
        f"  Entry: ${sig.entry:,.2f}",
        f"  Stop:  ${sig.stop:,.2f}  (≈${sl_usd:.0f} risk)",
        f"  TP:    ${sig.tp:,.2f}  (≈${tp_usd:.0f} target)",
        f"  Size:  ${sig.size_usd:,.0f} (RR 1:{(tp_usd/max(sl_usd,1)):.1f})",
        "",
        f"⏱ Hold до {expiry_str} (+{sig.hold_h}h) или TP/SL раньше",
    ]
    # 2026-07-21: статичная строка «Backtest PF 1.85, WR 56% (N=1833 за 2y)»
    # печаталась как живой эдж 2 месяца, пока живые 40 сигналов давали WR 48%
    # / PF 1.21 (нетто минус после комиссий). Теперь — только свои исходы.
    try:
        from services.session_breakout.stats import live_line
        lines.append(live_line(sig.transition))
    except Exception:
        lines.append("📊 Живой эдж: статистика недоступна")
    return "\n".join(lines)
