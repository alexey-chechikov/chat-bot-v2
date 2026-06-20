"""Forward-test journal для derivative watchlist plays.

Зачем:
- Plays типа taker_imbalance_long, topshort_divergence_long валидированы
  на n=109/55 за 23 дня. Это suggest, не confirm. Чтобы через 60 дней
  понимать "edge живой / edge мёртв" — нужен честный live-журнал каждого
  fire + forward outcome 4h/24h.
- Без него все 3 новых watchlist play слепые: знаем что rule сработало,
  не знаем что было дальше.

Структура записи (state/play_journal.jsonl):
{
  "fire_id":       "play_20260515_223045_funding_squeeze_long",
  "ts_fire":       "2026-05-15T22:30:45+00:00",
  "label":         "funding_squeeze_long",
  "rule_id":       "2b97b344",
  "rule_field":    "funding",
  "rule_op":       "<",
  "rule_threshold": -0.010,
  "trigger_value": -0.012,
  "price_at_fire": 81234.5,
  "expected_dir":  "LONG",     # from play_templates.PLAYS[label]['dir']
  "tp1_pct":       0.46,
  "tp2_pct":       0.68,
  "stop_pct":      -0.40,
  # outcome (filled by evaluate_pending когда время пройдёт):
  "price_4h":      null,
  "price_24h":     null,
  "realized_4h_pct":  null,    # signed by expected_dir: positive = play correct
  "realized_24h_pct": null,
  "hit_tp1":       null,       # bool: TP1 был достигнут в окне 24h
  "hit_tp2":       null,
  "hit_stop":      null,
  "outcome_status": "pending"  # pending | resolved_4h | resolved_24h
}
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
JOURNAL_PATH = ROOT / "state" / "play_journal.jsonl"
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"

OUTCOME_HORIZONS_H = (4, 24)


def _read_all(path: Path = JOURNAL_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    return out


def _write_all(rows: list[dict], path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("play_journal.write_failed")


def _recent_journal_tail(path: Path, n_records: int = 5) -> list[dict]:
    """Return last n_records parsed JSON lines from journal (cheap tail read)."""
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= n_records:
            break
    return out


def append_play_fire(*, label: str, rule_id: str, rule_field: str,
                     rule_op: str, rule_threshold: float, trigger_value: float,
                     play_meta: dict, price_at_fire: float,
                     now: Optional[datetime] = None,
                     path: Path = JOURNAL_PATH) -> str:
    """Append play fire запись. Returns fire_id.

    play_meta: dict from play_templates.PLAYS[label] (dir/tp1_pct/tp2_pct/stop_pct).

    Dedup: если последние 5 записей содержат entry с тем же (label,
    ts_fire-minute, price_at_fire) — пропускаем write и возвращаем существующий
    fire_id. Защита от 3 одновременных fires (e5f6/eth/xrp own taker rules
    шлют один и тот же event в одну секунду — раньше писалось 3 раза).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    fire_id = f"play_{now.strftime('%Y%m%d_%H%M%S')}_{label}"
    ts_fire_iso = now.isoformat(timespec="seconds")
    ts_minute = ts_fire_iso[:16]  # YYYY-MM-DDTHH:MM

    # Dedup pass — skip if same logical event already journaled
    for last in _recent_journal_tail(path):
        if (last.get("label") == label
                and (last.get("ts_fire") or "")[:16] == ts_minute
                and abs(float(last.get("price_at_fire") or 0) - float(price_at_fire)) < 0.01):
            logger.info("play_journal.dedup_skip label=%s ts_minute=%s rule=%s prev_fire=%s",
                        label, ts_minute, rule_id, last.get("fire_id"))
            return last.get("fire_id") or fire_id

    record = {
        "fire_id": fire_id,
        "ts_fire": ts_fire_iso,
        "label": label,
        "rule_id": rule_id,
        "rule_field": rule_field,
        "rule_op": rule_op,
        "rule_threshold": rule_threshold,
        "trigger_value": trigger_value,
        "price_at_fire": price_at_fire,
        "expected_dir": play_meta.get("dir"),
        "tp1_pct": play_meta.get("tp1_pct"),
        "tp2_pct": play_meta.get("tp2_pct"),
        "stop_pct": play_meta.get("stop_pct"),
        "price_4h": None,
        "price_24h": None,
        "realized_4h_pct": None,
        "realized_24h_pct": None,
        "hit_tp1": None,
        "hit_tp2": None,
        "hit_stop": None,
        "outcome_status": "pending",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("play_journal.append_failed")
    return fire_id


def _load_recent_1m(*, csv_path: Path = MARKET_1M_CSV, hours: int = 48):
    """Load tail of market_1m.csv as DataFrame (lazy pandas import)."""
    import pandas as pd
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
    except (OSError, pd.errors.ParserError):
        return None
    if df.empty or "ts_utc" not in df.columns:
        return None
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    cutoff = df.index[-1] - pd.Timedelta(hours=hours)
    return df.loc[df.index >= cutoff]


def _price_at(df, target_ts: datetime, tol_min: int = 5) -> Optional[float]:
    """Nearest close to target_ts within ±tol_min."""
    import pandas as pd
    target = pd.Timestamp(target_ts)
    try:
        idx = df.index.get_indexer([target], method="nearest")[0]
    except Exception:
        return None
    if idx < 0:
        return None
    nearest_ts = df.index[idx]
    if abs((nearest_ts - target).total_seconds()) > tol_min * 60:
        return None
    try:
        return float(df["close"].iloc[idx])
    except (KeyError, IndexError):
        return None


def _hit_check(df, start_ts: datetime, end_ts: datetime, entry_price: float,
               expected_dir: str, tp1_pct: float, tp2_pct: float, stop_pct: float
               ) -> tuple[bool, bool, bool]:
    """Check if TP1/TP2/Stop was hit in window."""
    window = df[(df.index > start_ts) & (df.index <= end_ts)]
    if window.empty:
        return False, False, False
    if expected_dir == "LONG":
        tp1_px = entry_price * (1 + tp1_pct / 100)
        tp2_px = entry_price * (1 + tp2_pct / 100)
        stop_px = entry_price * (1 + stop_pct / 100)
        hit_tp1 = bool((window["high"] >= tp1_px).any())
        hit_tp2 = bool((window["high"] >= tp2_px).any())
        hit_stop = bool((window["low"] <= stop_px).any())
    else:  # SHORT
        tp1_px = entry_price * (1 + tp1_pct / 100)
        tp2_px = entry_price * (1 + tp2_pct / 100)
        stop_px = entry_price * (1 + stop_pct / 100)
        hit_tp1 = bool((window["low"] <= tp1_px).any())
        hit_tp2 = bool((window["low"] <= tp2_px).any())
        hit_stop = bool((window["high"] >= stop_px).any())
    return hit_tp1, hit_tp2, hit_stop


def evaluate_pending(*, now: Optional[datetime] = None,
                     path: Path = JOURNAL_PATH,
                     csv_path: Path = MARKET_1M_CSV) -> int:
    """Update pending entries that have crossed 4h/24h horizons. Returns count touched."""
    if now is None:
        now = datetime.now(timezone.utc)
    rows = _read_all(path=path)
    pendings = [r for r in rows if r.get("outcome_status") != "resolved_24h"]
    if not pendings:
        return 0
    df = _load_recent_1m(csv_path=csv_path, hours=48)
    if df is None or df.empty:
        return 0

    n_touched = 0
    for r in pendings:
        try:
            ts_fire = datetime.fromisoformat(r["ts_fire"])
        except (KeyError, ValueError):
            continue
        entry_px = r.get("price_at_fire")
        expected_dir = r.get("expected_dir")
        if not entry_px or not expected_dir:
            continue
        age_h = (now - ts_fire).total_seconds() / 3600.0

        # 4h horizon
        if r.get("realized_4h_pct") is None and age_h >= 4:
            p4 = _price_at(df, ts_fire + timedelta(hours=4))
            if p4 is not None:
                raw_pct = (p4 / entry_px - 1) * 100
                signed = raw_pct if expected_dir == "LONG" else -raw_pct
                r["price_4h"] = round(p4, 2)
                r["realized_4h_pct"] = round(signed, 3)
                r["outcome_status"] = "resolved_4h"
                n_touched += 1

        # 24h horizon
        if r.get("realized_24h_pct") is None and age_h >= 24:
            p24 = _price_at(df, ts_fire + timedelta(hours=24))
            if p24 is not None:
                raw_pct = (p24 / entry_px - 1) * 100
                signed = raw_pct if expected_dir == "LONG" else -raw_pct
                r["price_24h"] = round(p24, 2)
                r["realized_24h_pct"] = round(signed, 3)
                # Check TP1/TP2/stop hits в окне 24ч
                try:
                    hit1, hit2, hits = _hit_check(
                        df, ts_fire, ts_fire + timedelta(hours=24),
                        entry_px, expected_dir,
                        r.get("tp1_pct") or 0, r.get("tp2_pct") or 0, r.get("stop_pct") or 0,
                    )
                    r["hit_tp1"] = hit1
                    r["hit_tp2"] = hit2
                    r["hit_stop"] = hits
                except Exception:
                    logger.exception("play_journal.hit_check_failed fire=%s", r.get("fire_id"))
                r["outcome_status"] = "resolved_24h"
                n_touched += 1

    if n_touched > 0:
        _write_all(rows, path=path)
    return n_touched


def summarize(*, path: Path = JOURNAL_PATH, min_n: int = 5) -> dict:
    """Aggregate stats by label."""
    rows = _read_all(path=path)
    if not rows:
        return {"total": 0, "by_label": {}}

    by_label: dict[str, dict] = {}
    for r in rows:
        lbl = r.get("label", "unknown")
        if lbl not in by_label:
            by_label[lbl] = {
                "n_fires": 0,
                "n_resolved_4h": 0,
                "n_resolved_24h": 0,
                "wr_4h": [],
                "wr_24h": [],
                "realized_4h_sum": 0.0,
                "realized_24h_sum": 0.0,
                "hit_tp1": 0,
                "hit_tp2": 0,
                "hit_stop": 0,
            }
        d = by_label[lbl]
        d["n_fires"] += 1
        r4 = r.get("realized_4h_pct")
        r24 = r.get("realized_24h_pct")
        if r4 is not None:
            d["n_resolved_4h"] += 1
            d["wr_4h"].append(1 if r4 > 0 else 0)
            d["realized_4h_sum"] += r4
        if r24 is not None:
            d["n_resolved_24h"] += 1
            d["wr_24h"].append(1 if r24 > 0 else 0)
            d["realized_24h_sum"] += r24
        if r.get("hit_tp1"): d["hit_tp1"] += 1
        if r.get("hit_tp2"): d["hit_tp2"] += 1
        if r.get("hit_stop"): d["hit_stop"] += 1

    # Compute final stats
    out_labels = {}
    for lbl, d in by_label.items():
        n4 = d["n_resolved_4h"]
        n24 = d["n_resolved_24h"]
        out_labels[lbl] = {
            "n_fires": d["n_fires"],
            "n_resolved_4h": n4,
            "n_resolved_24h": n24,
            "wr_4h_pct": round(100 * sum(d["wr_4h"]) / n4, 1) if n4 else None,
            "wr_24h_pct": round(100 * sum(d["wr_24h"]) / n24, 1) if n24 else None,
            "mean_realized_4h_pct": round(d["realized_4h_sum"] / n4, 3) if n4 else None,
            "mean_realized_24h_pct": round(d["realized_24h_sum"] / n24, 3) if n24 else None,
            "tp1_hit_rate": round(100 * d["hit_tp1"] / n24, 1) if n24 else None,
            "tp2_hit_rate": round(100 * d["hit_tp2"] / n24, 1) if n24 else None,
            "stop_hit_rate": round(100 * d["hit_stop"] / n24, 1) if n24 else None,
            "sufficient_sample": n24 >= min_n,
        }
    return {"total_fires": len(rows), "by_label": out_labels}
