"""Confluence scoring — детект совпадения 2+ сигналов в одну сторону.

Идея: если в течение CONFLUENCE_WINDOW_MIN несколько сигналов (watchlist play,
range_hunter, cascade alert) фаерят в одном направлении, это **high-conviction**
сетап с лучшим expectancy. Bot шлёт отдельную "🔥 CONFLUENCE" карточку с
recommended 2× size.

Источники мониторинга:
- state/play_journal.jsonl       — watchlist play fires (expected_dir)
- state/cascade_alert_dedup.json — cascade alerts (side → direction)
- state/range_hunter_signals*.jsonl — RH signals (нейтральные, не включаем)

Direction mapping для cascade-сигналов (2026 regime):
- short_cascade → ожидание UP (LONG bias)
- long_cascade (drifted) → ожидание DOWN (SHORT bias) — inverted edge

Confluence требует >= 2 sources в одну сторону за CONFLUENCE_WINDOW_MIN минут.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PLAY_JOURNAL = ROOT / "state" / "play_journal.jsonl"
CASCADE_DEDUP = ROOT / "state" / "cascade_alert_dedup.json"
CONFLUENCE_JOURNAL = ROOT / "state" / "confluence_fires.jsonl"

CONFLUENCE_WINDOW_MIN = 5
# Multi-threshold cascade keys (2/5/10BTC + mega) представляют ОДНО событие —
# крупная лавина одновременно пробивает несколько порогов. Конфлюэнс не должен
# считать их как независимые источники. Cobиратрb эти keys в один source
# при detect_confluence.
CASCADE_BULL = ("short_2.0", "short_5.0", "short_10.0_mega")
CASCADE_BEAR = ("long_2.0", "long_5.0", "long_10.0_mega")
# Также: если в окне есть несколько cascade-keys одного side — это все та же
# лавина (5BTC пробивает 2BTC автоматически, 10BTC mega — это вообще тот же
# момент). Collapse в один source.
CASCADE_COLLAPSE = True


def _recent_play_fires(*, direction: str, now: datetime,
                        window_min: int = CONFLUENCE_WINDOW_MIN,
                        path: Path = PLAY_JOURNAL) -> list[dict]:
    """Read play_journal, return fires within window in given direction."""
    if not path.exists():
        return []
    cutoff = now - timedelta(minutes=window_min)
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("expected_dir") != direction:
                continue
            try:
                ts = datetime.fromisoformat(rec.get("ts_fire", ""))
            except (ValueError, TypeError):
                continue
            if ts >= cutoff:
                out.append({"label": rec.get("label"), "ts": ts.isoformat(),
                            "price": rec.get("price_at_fire")})
    except OSError:
        return []
    return out


def _recent_cascade_signals(*, direction: str, now: datetime,
                              window_min: int = CONFLUENCE_WINDOW_MIN,
                              dedup_path: Path = CASCADE_DEDUP) -> list[dict]:
    """Read cascade_alert_dedup, return cascades within window matching direction.

    Multi-threshold cascades (2/5/10BTC) of the same side в окне коллапсятся в
    ОДИН source — это одно событие, пробившее несколько порогов. Берём самый
    жирный threshold как primary label.
    """
    if not dedup_path.exists():
        return []
    try:
        dedup = json.loads(dedup_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = now - timedelta(minutes=window_min)
    keys = CASCADE_BULL if direction == "LONG" else CASCADE_BEAR
    raw: list[tuple[str, datetime]] = []
    for key in keys:
        ts_str = dedup.get(key)
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            raw.append((key, ts))
    if not raw:
        return []
    if CASCADE_COLLAPSE:
        # Берём cascade с самым старшим threshold (mega > 5 > 2) как primary
        def _rank(k: str) -> int:
            if "10.0_mega" in k:
                return 3
            if "5.0" in k:
                return 2
            return 1
        raw.sort(key=lambda kv: (_rank(kv[0]), kv[1]), reverse=True)
        primary_key, primary_ts = raw[0]
        return [{"label": f"cascade_{primary_key}", "ts": primary_ts.isoformat(),
                  "collapsed_count": len(raw)}]
    return [{"label": f"cascade_{k}", "ts": ts.isoformat()} for k, ts in raw]


def detect_confluence(*, direction: str, now: Optional[datetime] = None,
                       window_min: int = CONFLUENCE_WINDOW_MIN,
                       min_sources: int = 2) -> Optional[dict]:
    """Detect confluence in `direction` (LONG/SHORT) within window.

    Returns dict {sources: [...], count: N} if min_sources reached, else None.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    plays = _recent_play_fires(direction=direction, now=now, window_min=window_min)
    cascades = _recent_cascade_signals(direction=direction, now=now, window_min=window_min)
    sources = []
    seen = set()
    for src in plays + cascades:
        lbl = src["label"]
        if lbl in seen:
            continue
        seen.add(lbl)
        sources.append(src)
    if len(sources) < min_sources:
        return None
    return {"direction": direction, "count": len(sources), "sources": sources}


def _dedup_path(direction: str) -> Path:
    return ROOT / "state" / f"confluence_dedup_{direction.lower()}.json"


def _check_dedup(direction: str, *, cooldown_min: int = 30,
                  now: Optional[datetime] = None) -> bool:
    """True if confluence in direction was emitted recently (skip)."""
    if now is None:
        now = datetime.now(timezone.utc)
    p = _dedup_path(direction)
    if not p.exists():
        return False
    try:
        last = datetime.fromisoformat(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (now - last).total_seconds() < cooldown_min * 60


def _set_dedup(direction: str, *, now: Optional[datetime] = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    p = _dedup_path(direction)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(now.isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        logger.exception("confluence.dedup_write_failed")


def _journal_confluence(record: dict, *, path: Path = CONFLUENCE_JOURNAL) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("confluence.journal_failed")


def format_confluence_card(confluence: dict, last_price: Optional[float] = None) -> str:
    direction = confluence["direction"]
    sources = confluence["sources"]
    src_lines = []
    for s in sources:
        src_lines.append(f"  ▸ {s['label']}  ({s['ts'][11:19]} UTC)")
    lines = [
        f"🔥 CONFLUENCE → {direction} ({confluence['count']} источников за {CONFLUENCE_WINDOW_MIN} мин)",
        "",
        "Сошедшиеся сигналы:",
        *src_lines,
        "",
        f"Это HIGH-CONVICTION сетап: 2+ независимых эджа в одну сторону.",
        f"Рекомендуемый size: 2× обычный (вместо одиночного $5K → $10K).",
    ]
    if last_price:
        lines.append(f"BTC mid: ${last_price:,.0f}")
    lines.append("")
    lines.append("⚠ Не складывай с уже открытыми ногами — проверь свои позиции до входа.")
    return "\n".join(lines)


def _recent_constituent_fire(direction: str, *,
                              window_min: int = 3,
                              now: Optional[datetime] = None) -> bool:
    """True if a same-direction constituent signal (cascade or play) already
    fired in the last `window_min` minutes. Used to suppress redundant
    confluence cards — if the operator already saw the cascade or the
    taker_imbalance card 1-2 min ago, a "CONFLUENCE → DIR" wrapper alert is
    just dup noise (2026-05-23: colleague flagged 16:57 inverted SHORT +
    confluence SHORT pair on the same event)."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_min)
    # cascade-side fires
    dedup = _read_cascade_dedup()
    cascade_side = "long" if direction == "SHORT" else "short"  # cascade dir = liq side, fade
    for k, ts_str in dedup.items():
        if not k.startswith(f"{cascade_side}_"):
            continue
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            return True
    # play_journal fires (taker_imbalance et al)
    try:
        if PLAY_JOURNAL.exists():
            tail = PLAY_JOURNAL.read_text(encoding="utf-8").splitlines()[-30:]
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("expected_dir") != direction:
                        continue
                    ts = datetime.fromisoformat(
                        str(rec.get("ts_fire", "")).replace("Z", "+00:00"))
                    if ts >= cutoff:
                        return True
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    continue
    except OSError:
        pass
    return False


def check_and_emit_confluence(*, send_fn=None,
                                 now: Optional[datetime] = None) -> Optional[dict]:
    """Single tick: check both directions, emit if confluence detected and not dedupped."""
    if now is None:
        now = datetime.now(timezone.utc)
    for direction in ("LONG", "SHORT"):
        if _check_dedup(direction, now=now):
            continue
        confluence = detect_confluence(direction=direction, now=now)
        if confluence is None:
            continue
        # Suppress when a constituent signal already informed the operator
        # within the last few minutes — confluence is redundant aggregation.
        if _recent_constituent_fire(direction, now=now):
            logger.info("confluence.suppressed_redundant direction=%s "
                        "(constituent fired within 3min)", direction)
            continue
        # Build card
        last_price = None
        try:
            from services.watchlist.play_templates import _last_btc_price
            last_price = _last_btc_price()
        except Exception:
            pass
        text = format_confluence_card(confluence, last_price=last_price)
        logger.info("confluence.detected direction=%s count=%d sources=%s",
                    direction, confluence["count"],
                    [s["label"] for s in confluence["sources"]])
        if send_fn is not None:
            try:
                send_fn(text)
            except Exception:
                logger.exception("confluence.send_failed")
        _set_dedup(direction, now=now)
        _journal_confluence({
            "ts": now.isoformat(timespec="seconds"),
            "direction": direction,
            "count": confluence["count"],
            "sources": confluence["sources"],
            "last_price": last_price,
        })
        return confluence
    return None
