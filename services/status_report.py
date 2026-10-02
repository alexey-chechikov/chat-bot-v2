"""On-demand /status report for Telegram.

Aggregates:
  - heartbeat freshness (age since last heartbeat.tick in logs)
  - process pids (app_runner, tracker, collectors, state_snapshot)
  - last emitted setup (type, pair, age)
  - last GC fire (direction, score, age)
  - P-15 open legs per (pair, direction) with layers/DD/age
  - restarts last hour count
  - top emit_type last 24h

Designed for /status TG command — readable in ~15 lines.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP_LOG = _ROOT / "logs" / "app.log"
_SETUPS = _ROOT / "state" / "setups.jsonl"
_GC_FIRES = _ROOT / "state" / "grid_coordinator_fires.jsonl"
_P15_STATE = _ROOT / "state" / "p15_state.json"
_APP_RUNNER_STARTS = _ROOT / "state" / "app_runner_starts.jsonl"
_PIPELINE_METRICS = _ROOT / "state" / "pipeline_metrics.jsonl"
_DERIV_LIVE = _ROOT / "state" / "deriv_live.json"
_P15_EQUITY = _ROOT / "state" / "p15_equity.jsonl"


def _read_last_lines(path: Path, n: int = 50) -> list[str]:
    """Tail-style read of last n lines without loading whole file."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            # Read last ~64KB and split lines.
            offset = max(0, size - 65536)
            f.seek(offset)
            chunk = f.read()
        lines = chunk.decode("utf-8", errors="ignore").splitlines()
        return lines[-n:]
    except OSError:
        return []


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _age_minutes(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    return (now - dt).total_seconds() / 60


def _heartbeat_age(now: datetime) -> tuple[float | None, str | None]:
    """Find last 'heartbeat.tick' line in app.log; return (age_min, raw_ts_str)."""
    if not _APP_LOG.exists():
        return None, None
    try:
        # Last 200 lines is usually enough — heartbeat every 60s.
        lines = _read_last_lines(_APP_LOG, n=200)
        for line in reversed(lines):
            if "heartbeat.tick" not in line:
                continue
            # Format: "2026-05-10 23:30:54,647 | INFO | ..."
            ts_match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if ts_match:
                # Local time → convert to UTC by reading the embedded t=
                t_match = re.search(r"t=([\d\-T:+Z]+)", line)
                if t_match:
                    dt = _parse_iso(t_match.group(1))
                    if dt:
                        return _age_minutes(dt, now), t_match.group(1)
                return None, ts_match.group(1)
        return None, None
    except OSError:
        return None, None


def _processes_status() -> dict[str, int | None]:
    try:
        import psutil
    except ImportError:
        return {"app_runner": None, "tracker": None, "collectors": None, "state_snapshot": None}
    out = {"app_runner": None, "tracker": None, "collectors": None, "state_snapshot": None}
    needles = {
        "app_runner": "app_runner.py",
        "tracker": "ginarea_tracker",
        "collectors": "market_collector.collector",
        "state_snapshot": "state_snapshot_loop.py",
    }
    for proc in psutil.process_iter(["pid", "cmdline", "name"]):
        try:
            cl = " ".join(proc.info.get("cmdline") or [])
            # 2026-10-01: требование «.venv» в строке давало ложное «down» —
            # macOS показывает разрешённый путь Homebrew-питона, без .venv
            # (state_snapshot жил, PID 41966, а статус писал «мёртв»).
            is_python = ".venv" in cl or "python" in cl.lower()
            for key, needle in needles.items():
                if out[key] is None and needle in cl and is_python:
                    out[key] = proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def _last_setup(now: datetime) -> dict | None:
    if not _SETUPS.exists():
        return None
    last_line = None
    try:
        lines = _read_last_lines(_SETUPS, n=5)
        for line in reversed(lines):
            line = line.strip()
            if line:
                last_line = line
                break
        if last_line is None:
            return None
        rec = json.loads(last_line)
        dt = _parse_iso(rec.get("detected_at", ""))
        return {
            "type": rec.get("setup_type", "?"),
            "pair": rec.get("pair", "?"),
            "age_min": _age_minutes(dt, now),
            "strength": rec.get("strength"),
            "conf": rec.get("confidence_pct"),
        }
    except (OSError, json.JSONDecodeError):
        return None


def _last_gc_fire(now: datetime) -> dict | None:
    if not _GC_FIRES.exists():
        return None
    try:
        lines = _read_last_lines(_GC_FIRES, n=5)
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            dt = _parse_iso(rec.get("ts", ""))
            return {
                "direction": rec.get("direction"),
                "score": rec.get("score"),
                "age_min": _age_minutes(dt, now),
            }
        return None
    except (OSError, json.JSONDecodeError):
        return None


def _p15_legs(now: datetime) -> list[dict]:
    if not _P15_STATE.exists():
        return []
    try:
        raw = json.loads(_P15_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for key, leg in raw.items():
        if not isinstance(leg, dict):
            continue
        if not leg.get("in_pos"):
            continue
        try:
            pair, direction = key.split(":", 1)
        except ValueError:
            continue
        opened_at = _parse_iso(leg.get("opened_at_ts", ""))
        out.append({
            "key": key,
            "pair": pair,
            "direction": direction,
            "layers": int(leg.get("layers", 0)),
            "size_usd": float(leg.get("total_size_usd", 0)),
            "dd_pct": float(leg.get("cum_dd_pct", 0)),
            "age_min": _age_minutes(opened_at, now),
        })
    return out


def _restarts_last_hour(now: datetime) -> int:
    if not _APP_RUNNER_STARTS.exists():
        return 0
    cutoff = now - timedelta(hours=1)
    n = 0
    try:
        with _APP_RUNNER_STARTS.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dt = _parse_iso(rec.get("ts", ""))
                if dt and dt >= cutoff:
                    n += 1
        return n
    except OSError:
        return 0


def _pipeline_summary_last_hour(now: datetime) -> dict:
    """Quick funnel: events / emitted / detector_failed in last 1h."""
    if not _PIPELINE_METRICS.exists():
        return {"total": 0, "emitted": 0, "failed": 0, "blocked": 0}
    cutoff = now - timedelta(hours=1)
    total = emitted = failed = blocked = 0
    try:
        # Tail last ~5000 lines is enough — 1h ~= ~2000 events typically.
        lines = _read_last_lines(_PIPELINE_METRICS, n=5000)
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = _parse_iso(rec.get("ts", ""))
            if not dt or dt < cutoff:
                continue
            total += 1
            outcome = rec.get("stage_outcome", "")
            if outcome == "emitted":
                emitted += 1
            elif outcome == "detector_failed":
                failed += 1
            elif outcome.startswith("gc_blocked") or outcome.startswith("combo_blocked") \
                    or outcome.endswith("_dedup_skip") or outcome == "env_disabled":
                blocked += 1
    except OSError:
        pass
    return {"total": total, "emitted": emitted, "failed": failed, "blocked": blocked}


def _disabled_summary() -> dict:
    """Pull from runtime_disabled what's currently off."""
    try:
        from services.setup_detector.runtime_disabled import list_disabled
        return list_disabled()
    except Exception:
        return {"env": [], "state_file": []}


def _trader_positions() -> dict:
    """Read deriv_live.json to get top trader long/short % per pair."""
    if not _DERIV_LIVE.exists():
        return {}
    try:
        d = json.loads(_DERIV_LIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    if isinstance(d, dict):
        for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
            p = d.get(pair) or {}
            if not isinstance(p, dict): continue
            # Field names vary across data sources — try both styles.
            long_pct = p.get("top_trader_long_pct") or p.get("top_trader_long_account_pct")
            short_pct = p.get("top_trader_short_pct") or p.get("top_trader_short_account_pct")
            global_long = p.get("global_long_pct") or p.get("global_long_account_pct")
            global_short = p.get("global_short_pct") or p.get("global_short_account_pct")
            funding = p.get("funding_rate_8h")
            oi_change = p.get("oi_change_1h_pct")
            if long_pct is not None or global_long is not None or funding is not None:
                out[pair] = {
                    "top_long": long_pct,
                    "top_short": short_pct,
                    "global_long": global_long,
                    "global_short": global_short,
                    "funding": funding,
                    "oi_change": oi_change,
                }
    return out


def _p15_pnl_24h() -> float:
    """Sum realized PnL from p15_equity.jsonl over last 24h."""
    if not _P15_EQUITY.exists():
        return 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    total = 0.0
    try:
        with _P15_EQUITY.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    dt = _parse_iso(rec.get("ts", ""))
                    if dt and dt >= cutoff:
                        v = rec.get("realized_pnl_usd")
                        if v is not None:
                            total += float(v)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError:
        pass
    return total


def _bar(value: float, max_val: float = 100, width: int = 10) -> str:
    """Simple ASCII bar like ▰▰▰▱▱▱▱▱▱▱ for ratio display."""
    if max_val <= 0: return "─" * width
    filled = int(round(value / max_val * width))
    filled = max(0, min(width, filled))
    return "▰" * filled + "▱" * (width - filled)


def _setup_type_ru(setup_type: str) -> str:
    """Human-readable Russian name for setup_type."""
    mapping = {
        "p15_long_open": "P-15 LONG открыт",
        "p15_long_harvest": "P-15 LONG harvest",
        "p15_long_reentry": "P-15 LONG re-entry",
        "p15_long_close": "P-15 LONG закрыт",
        "p15_short_open": "P-15 SHORT открыт",
        "p15_short_harvest": "P-15 SHORT harvest",
        "p15_short_reentry": "P-15 SHORT re-entry",
        "p15_short_close": "P-15 SHORT закрыт",
        "short_pdh_rejection": "SHORT от PDH",
        "short_rally_fade": "SHORT fade rally",
        "short_mfi_multi_ga": "SHORT MFI multi",
        "long_pdl_bounce": "LONG bounce PDL",
        "long_dump_reversal": "LONG разворот после дампа",
        "long_double_bottom": "LONG двойное дно",
        "long_multi_divergence": "LONG multi-дивергенция",
        "short_double_top": "SHORT двойная вершина",
    }
    return mapping.get(setup_type, setup_type)


def build_status_report() -> str:
    now = datetime.now(timezone.utc)
    hb_age, hb_ts = _heartbeat_age(now)
    procs = _processes_status()
    last_setup = _last_setup(now)
    last_gc = _last_gc_fire(now)
    legs = _p15_legs(now)
    restarts = _restarts_last_hour(now)
    pipeline = _pipeline_summary_last_hour(now)
    disabled = _disabled_summary()
    traders = _trader_positions()
    p15_pnl = _p15_pnl_24h()

    lines = []
    lines.append(f"📊 СТАТУС БОТА  ({now:%H:%M UTC, %d.%m})")
    lines.append("")

    # === 1. ЗДОРОВЬЕ БОТА ===
    if hb_age is None:
        lines.append("🔴 Бот: НЕТ СВЯЗИ (heartbeat молчит)")
    elif hb_age < 3:
        lines.append(f"🟢 Бот живой ({hb_age:.0f} мин назад был tick)")
    elif hb_age < 15:
        lines.append(f"🟡 Бот замедлен ({hb_age:.0f} мин с последнего tick)")
    else:
        lines.append(f"🔴 Бот завис ({hb_age:.0f} мин без tick — watchdog скоро поднимет)")

    procs_up = sum(1 for v in procs.values() if v)
    procs_total = len(procs)
    if procs_up == procs_total:
        lines.append(f"🟢 Процессы: все {procs_total} живы")
    else:
        down = [k for k, v in procs.items() if not v]
        lines.append(f"🟡 Процессы: {procs_up}/{procs_total} живы (down: {', '.join(down)})")
    lines.append("")

    # === 2. ПОЗИЦИИ P-15 ===
    # 2026-10-01: P-15 выключен, p15_state.json не обновлялся с 23.05 — статус
    # показывал бумажные ноги «держим 189920м» как активные позиции. Если
    # файлу больше суток, это не позиции, а остаток выключенной стратегии.
    stale_since = None
    try:
        mtime = datetime.fromtimestamp(_P15_STATE.stat().st_mtime, timezone.utc)
        if now - mtime > timedelta(days=1):
            stale_since = mtime
    except OSError:
        pass
    if legs and stale_since is not None:
        lines.append(f"💼 P-15 выключен (бумажная стратегия, данные от "
                     f"{stale_since:%d.%m}) — реальных позиций в нём нет")
        legs = []
    elif legs:
        total_size = sum(l["size_usd"] for l in legs)
        avg_dd = sum(abs(l["dd_pct"]) for l in legs) / len(legs)
        lines.append(f"💼 АКТИВНЫЕ ПОЗИЦИИ P-15: {len(legs)} (всего ${total_size:.0f})")
        for leg in legs:
            dir_emoji = "🟢" if leg["direction"] == "long" else "🔴"
            dd = leg["dd_pct"]
            dd_emoji = "✅" if abs(dd) < 1 else ("⚠️" if abs(dd) < 2 else "🚨")
            lines.append(
                f"  {dir_emoji} {leg['pair']} {leg['direction']:<5}  "
                f"${leg['size_usd']:>5.0f}  слоёв={leg['layers']}  "
                f"DD={dd:+.2f}% {dd_emoji}  держим {leg['age_min']:.0f}м"
            )
        if avg_dd > 1.5:
            lines.append(f"  ⚠️ Средний DD {avg_dd:.2f}% — близко к лимиту 3%")
    else:
        lines.append("💼 АКТИВНЫХ ПОЗИЦИЙ P-15 нет")
    lines.append("")

    # === 3. P-15 PnL 24h ===
    pnl_emoji = "🟢" if p15_pnl >= 0 else "🔴"
    lines.append(f"{pnl_emoji} P-15 за сутки: ${p15_pnl:+.2f}")
    lines.append("")

    # === 4. ПОЗИЦИИ ТРЕЙДЕРОВ BINANCE ===
    if traders:
        lines.append("📈 ТОП-ТРЕЙДЕРЫ BINANCE (long vs short):")
        for pair, t in traders.items():
            tl = t.get("top_long")
            ts = t.get("top_short")
            gl = t.get("global_long")
            gs = t.get("global_short")
            if tl is not None and ts is not None:
                bar = _bar(tl, 100)
                bias = "🟢 LONG bias" if tl > 55 else ("🔴 SHORT bias" if tl < 45 else "⚖️ нейтрал")
                lines.append(f"  {pair} топ:  {bar} {tl:.0f}%/{ts:.0f}%  {bias}")
            if gl is not None and gs is not None:
                bar = _bar(gl, 100)
                lines.append(f"  {pair} все:  {bar} {gl:.0f}%/{gs:.0f}%")
            fr = t.get("funding")
            if fr is not None:
                fr_pct = float(fr) * 100
                fr_emoji = "🔴 шорт-плата" if fr_pct < -0.005 else ("🟢 лонг-плата" if fr_pct > 0.005 else "⚖️")
                lines.append(f"  {pair} funding: {fr_pct:+.4f}%  {fr_emoji}")
    else:
        lines.append("📈 Trader-positions недоступно (deriv_live.json пустой)")
    lines.append("")

    # === 5. ПОСЛЕДНИЙ СИГНАЛ ===
    if last_setup:
        ru_type = _setup_type_ru(last_setup['type'])
        age = last_setup['age_min']
        age_str = f"{age:.0f} мин" if age < 60 else f"{age/60:.1f} ч"
        lines.append(f"🎯 Последний сигнал: {ru_type} на {last_setup['pair']}")
        lines.append(f"   {age_str} назад, уверенность {last_setup['conf']:.0f}%")
    else:
        lines.append("🎯 Последний сигнал: нет за сутки")
    lines.append("")

    # === 6. PIPELINE 1h ===
    if pipeline['total'] > 0:
        emit_pct = pipeline['emitted'] / pipeline['total'] * 100
        lines.append(f"⚙️ Pipeline 1ч: {pipeline['total']} событий → "
                      f"{pipeline['emitted']} в TG ({emit_pct:.0f}%)")
        if pipeline['failed'] > 0:
            lines.append(f"   🚨 Ошибок детекторов: {pipeline['failed']}")
    lines.append("")

    # === 7. РЕЖИМ И УПРАВЛЕНИЕ ===
    all_disabled = list(disabled.get("env", [])) + list(disabled.get("state_file", []))
    if all_disabled:
        lines.append(f"⏸️ Отключены: {', '.join(all_disabled)}")
    if restarts > 5:
        lines.append(f"⚠️ Рестартов за час: {restarts} (норма ≤5)")

    # === ВЫВОДЫ ===
    lines.append("")
    lines.append("📋 ВЫВОДЫ:")
    conclusions = []
    if hb_age is None or hb_age > 15:
        conclusions.append("• бот не отвечает — проверь watchdog")
    elif procs_up < procs_total:
        conclusions.append(f"• часть процессов мертва ({procs_total - procs_up})")
    else:
        conclusions.append("• бот работает штатно")
    if p15_pnl < -50:
        conclusions.append(f"• ⚠️ значимая просадка P-15 за сутки: ${p15_pnl:+.2f}")
    elif p15_pnl > 50:
        conclusions.append(f"• 💚 хороший день P-15: ${p15_pnl:+.2f}")
    if legs and any(abs(l["dd_pct"]) > 2 for l in legs):
        bad_legs = [l for l in legs if abs(l["dd_pct"]) > 2]
        conclusions.append(f"• 🚨 {len(bad_legs)} leg(ов) в DD>2% — рассмотри ручное закрытие")
    if not last_setup or (last_setup and last_setup['age_min'] > 240):
        conclusions.append("• рынок тихий — мало сигналов")
    if all_disabled:
        conclusions.append(f"• {len(all_disabled)} детектор отключён (нормально, выжидаем данных)")
    for c in conclusions:
        lines.append(c)

    return "\n".join(lines)
