"""Живая 60-дневная статистика эджа PRE-CASCADE и GC-импульса.

Проблема (аудит 2026-07-18): карточки печатали статичные числа из
валидаций 19.05 («70.8% DOWN», «P≈73%»), а живой эдж к июлю умер:
PRE-CASCADE 49% down@24h, GC down 48.5% lower@4h. Мёртвая строка жила,
потому что статистику никто не пересчитывал автоматически.

Этот модуль считает скользящие 60 дней ИЗ СОБСТВЕННЫХ журналов fires +
1m свечей (без кнопок/ручной разметки) и кэширует в
state/edge_live_stats.json (пересчёт раз в сутки, ~секунда: из 2-летнего
CSV читается только хвост).

Порог гейта = 60% на >= 30 событий — тот же, что в edge_drift_guard
(acc < 60% => drifted), вторую константу не плодим.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "state" / "edge_live_stats.json"
CANDLES_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
PC_FIRES = ROOT / "state" / "liq_pre_cascade_fires.jsonl"
GC_FIRES = ROOT / "state" / "grid_coordinator_fires.jsonl"

WINDOW_DAYS = 60
MIN_N = 30
GATE_ACC_PCT = 60.0          # единый порог с edge_drift_guard
CACHE_MAX_AGE_H = 24.0
# хвост CSV: 60д окна + 24ч горизонт + запас; ~55 байт/строка
_TAIL_BYTES = (WINDOW_DAYS + 3) * 1440 * 80


def _load_recent_closes(path: Path = CANDLES_CSV) -> dict[int, float]:
    """{минута unix//60: close} по хвосту CSV (ts_ms,open,high,low,close,vol)."""
    closes: dict[int, float] = {}
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        logger.exception("edge_stats.candles_read_failed")
        return closes
    for ln in chunk.splitlines()[1:]:  # первая строка может быть обрезана
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        try:
            ts = int(parts[0])
            if ts > 10 ** 12:
                ts //= 1000
            closes[ts // 60] = float(parts[4])
        except ValueError:
            continue
    return closes


def _close_at(closes: dict[int, float], dt: datetime) -> float | None:
    """close на минуту dt; при дыре — скан вперёд до 15 минут."""
    m = int(dt.timestamp()) // 60
    for k in range(m, m + 16):
        px = closes.get(k)
        if px is not None:
            return px
    return None


def compute_stats(now: datetime | None = None, *,
                  candles_path: Path = CANDLES_CSV,
                  pc_path: Path = PC_FIRES,
                  gc_path: Path = GC_FIRES) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    closes = _load_recent_closes(candles_path)

    # ── PRE-CASCADE: P(цена ниже через 24ч) по уникальным кластер-событиям ──
    pc_n = pc_down = 0
    seen_ts: set[str] = set()
    try:
        for ln in pc_path.open(encoding="utf-8"):
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ts_iso = r.get("ts", "")
            if ts_iso in seen_ts:
                continue  # double-fire long+short одной секунды = одно событие
            seen_ts.add(ts_iso)
            try:
                t0 = datetime.fromisoformat(ts_iso)
            except ValueError:
                continue
            if t0 < cutoff or t0 + timedelta(hours=24) > now:
                continue  # вне окна или горизонт ещё не дозрел
            p0 = _close_at(closes, t0)
            p24 = _close_at(closes, t0 + timedelta(hours=24))
            if p0 is None or p24 is None:
                continue
            pc_n += 1
            if p24 < p0:
                pc_down += 1
    except OSError:
        logger.exception("edge_stats.pc_fires_read_failed")

    # ── GC down-импульс: P(ниже через 4ч) от btc_close карточки ────────────
    gc_n = gc_lower = 0
    try:
        for ln in gc_path.open(encoding="utf-8"):
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("direction") != "down":
                continue
            try:
                t0 = datetime.fromisoformat(str(r.get("ts", "")).replace("Z", "+00:00"))
            except ValueError:
                continue
            ref = (r.get("details") or {}).get("btc_close")
            if not ref or t0 < cutoff or t0 + timedelta(hours=4) > now:
                continue
            p4 = _close_at(closes, t0 + timedelta(hours=4))
            if p4 is None:
                continue
            gc_n += 1
            if p4 < float(ref):
                gc_lower += 1
    except OSError:
        logger.exception("edge_stats.gc_fires_read_failed")

    return {
        "computed_at": now.isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS,
        "pre_cascade_24h": {
            "n": pc_n,
            "p_down_pct": round(pc_down / pc_n * 100, 1) if pc_n else None,
        },
        "gc_down_4h": {
            "n": gc_n,
            "p_lower_pct": round(gc_lower / gc_n * 100, 1) if gc_n else None,
        },
    }


def get_stats(max_age_h: float = CACHE_MAX_AGE_H) -> dict | None:
    """Кэшированная статистика; пересчёт если кэш старше max_age_h."""
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(cached["computed_at"])).total_seconds() / 3600
        if age_h < max_age_h:
            return cached
    except Exception:
        cached = None
    try:
        stats = compute_stats()
        CACHE_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        return stats
    except Exception:
        logger.exception("edge_stats.compute_failed — отдаю устаревший кэш")
        return cached


def gate_ok(entry: dict | None) -> bool:
    """True = эдж подтверждён (>= 60% на >= 30 событий) — можно давать план."""
    if not entry:
        return False
    n = entry.get("n") or 0
    p = entry.get("p_down_pct") or entry.get("p_lower_pct")
    return n >= MIN_N and p is not None and p >= GATE_ACC_PCT


def format_line(stats: dict | None, key: str, label: str) -> str:
    """Строка живого эджа для карточки, напр. 'P(ниже 4ч)=48% (n=468, 60д)'."""
    if not stats or not stats.get(key) or stats[key].get("n", 0) == 0:
        return f"{label}: нет данных"
    e = stats[key]
    p = e.get("p_down_pct") or e.get("p_lower_pct")
    return f"{label} = {p:.0f}% (n={e['n']}, 60д)"
