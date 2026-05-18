from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import config
from core.app_logging import setup_logging
from handlers.command_handler import CommandHandler
from models.responses import BotResponsePayload
from services.analysis_service import call_btc_analysis
from storage.position_store import load_position_state
from storage.transition_alerts import build_transition_alert

logger = logging.getLogger(__name__)
_MAX_MESSAGE_LEN = 3800


SLASH_COMMAND_ALIASES: dict[str, str] = {
    '/help': 'HELP',
    '/menu': 'HELP',
    '/market': 'BTC 1H',
    '/analysis': 'BTC 1H',
}


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except Exception:
        return None


def normalize_chat_ids(*values: object) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in values:
        if raw is None:
            continue
        text = str(raw).replace(';', ',')
        for part in text.split(','):
            value = _safe_int(part)
            if value is None or value in seen:
                continue
            seen.add(value)
            out.append(value)
    return out


def split_text_chunks(text: str, limit: int = _MAX_MESSAGE_LEN) -> list[str]:
    body = (text or '').strip()
    if not body:
        return ['⚠️ Пустой ответ.']
    if len(body) <= limit:
        return [body]

    chunks: list[str] = []
    current = ''
    for block in body.split('\n\n'):
        block = block.strip()
        if not block:
            continue
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ''
        if len(block) <= limit:
            current = block
            continue

        lines = block.splitlines()
        line_buf = ''
        for line in lines:
            line = line.rstrip()
            candidate_line = f"{line_buf}\n{line}".strip() if line_buf else line
            if len(candidate_line) <= limit:
                line_buf = candidate_line
                continue
            if line_buf:
                chunks.append(line_buf)
            if len(line) <= limit:
                line_buf = line
                continue
            start = 0
            while start < len(line):
                end = start + limit
                chunks.append(line[start:end])
                start = end
            line_buf = ''
        if line_buf:
            current = line_buf
    if current:
        chunks.append(current)
    return chunks or ['⚠️ Пустой ответ.']


def resolve_telegram_text(text: str) -> str:
    raw = str(text or '').strip()
    if not raw:
        return ''
    parts = raw.split(maxsplit=1)
    slash = parts[0].lower()
    if slash in SLASH_COMMAND_ALIASES:
        return SLASH_COMMAND_ALIASES[slash]
    upper = raw.upper()
    aliases = {
        'ГЛАВНОЕ МЕНЮ': 'HELP',
        'ОБНОВИТЬ ИНТЕРФЕЙС': 'HELP',
    }
    return aliases.get(upper, raw)


def _fmt_price(value: object, digits: int = 2) -> str:
    try:
        if value is None:
            return '—'
        return f"{float(value):,.{digits}f}".replace(',', ' ')
    except Exception:
        return str(value or '—')


def _compact_reason(value: object) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    text = text.replace('_', ' ')
    return text[:220]


def _snapshot_manage_hint(snapshot_dict: dict) -> str:
    decision = snapshot_dict.get('decision') if isinstance(snapshot_dict.get('decision'), dict) else {}
    direction = str(decision.get('direction_text') or snapshot_dict.get('forecast_direction') or snapshot_dict.get('signal') or '').strip()
    action = str(decision.get('action_text') or decision.get('action') or snapshot_dict.get('final_decision') or '').strip()
    manager_action = str(decision.get('manager_action_text') or decision.get('manager_action') or '').strip()
    risk = str(decision.get('risk_level') or decision.get('risk') or snapshot_dict.get('risk_level') or '').strip().upper()
    invalidation = _compact_reason(decision.get('invalidation') or snapshot_dict.get('invalidation'))
    entry_reason = _compact_reason(decision.get('entry_reason') or snapshot_dict.get('entry_reason'))
    pressure_reason = _compact_reason(decision.get('pressure_reason') or snapshot_dict.get('pressure_reason'))
    confidence = decision.get('confidence_pct') or decision.get('confidence') or snapshot_dict.get('forecast_confidence') or 0.0
    try:
        confidence = round(float(confidence), 1)
    except Exception:
        confidence = 0.0

    bullets: list[str] = []
    if action:
        bullets.append(f'• вход сейчас: {action}')
    if direction:
        bullets.append(f'• сторона сценария: {direction}')
    if manager_action:
        bullets.append(f'• сопровождение: {manager_action}')
    bullets.append(f'• confidence: {confidence}%')
    if risk:
        bullets.append(f'• риск: {risk}')
    if entry_reason:
        bullets.append(f'• почему: {entry_reason}')
    if pressure_reason and pressure_reason != entry_reason:
        bullets.append(f'• давление/контекст: {pressure_reason}')
    if invalidation:
        bullets.append(f'• отмена сценария: {invalidation}')

    unload = 'держать и ждать подтверждения'
    side_upper = direction.upper()
    manager_upper = manager_action.upper()
    if 'PARTIAL' in manager_upper or 'TP1' in manager_upper or 'REDUCE' in manager_upper:
        unload = 'фиксировать часть / разгружать ступенчато'
    elif 'BE' in manager_upper:
        unload = 'переносить в безубыток и держать остаток'
    elif 'EXIT' in manager_upper or 'CLOSE' in manager_upper or risk == 'HIGH':
        unload = 'разгружать позицию агрессивнее / не добирать'
    elif 'LONG' in side_upper or 'SHORT' in side_upper:
        unload = 'держать только по сценарию, без погони за ценой'
    bullets.append(f'• что делать с позицией: {unload}')
    return '\n'.join(bullets)


def build_market_alert_message(snapshot, timeframe: str, transition_text: str) -> str:
    payload = snapshot.to_dict() if hasattr(snapshot, 'to_dict') else {}
    decision = payload.get('decision') if isinstance(payload.get('decision'), dict) else {}
    price = _fmt_price(payload.get('price'))
    direction = str(decision.get('direction_text') or payload.get('forecast_direction') or payload.get('signal') or '—')
    header = [
        f'🚨 BTCUSDT [{str(timeframe).upper()}]',
        f'Цена: {price}',
        f'Сценарий: {direction}',
    ]
    body = transition_text.strip()
    hint = _snapshot_manage_hint(payload)
    return '\n'.join(header) + '\n\n' + body + '\n\n🧭 ТРЕЙДЕРСКОЕ ДЕЙСТВИЕ\n' + hint


class TelegramResponder:
    def __init__(self, bot) -> None:
        self.bot = bot

    @staticmethod
    def _payload_state(payload: BotResponsePayload | str) -> dict:
        if isinstance(payload, BotResponsePayload):
            position = payload.position_snapshot.to_dict() if getattr(payload, 'position_snapshot', None) else {}
            analysis = payload.analysis_snapshot.to_dict() if getattr(payload, 'analysis_snapshot', None) else {}
            decision = analysis.get('decision') if isinstance(analysis.get('decision'), dict) else {}
            return {
                'has_position': bool(position.get('has_position')),
                'position_side': position.get('side'),
                'direction': decision.get('direction_text') or analysis.get('final_decision') or analysis.get('forecast_direction'),
                'action': decision.get('action_text') or decision.get('action'),
                'confidence': decision.get('confidence_pct') or decision.get('confidence') or analysis.get('forecast_confidence') or 0.0,
                'risk': decision.get('risk_level') or analysis.get('risk_level'),
            }
        return {}

    @staticmethod
    def _keyboard(text: str, payload: BotResponsePayload | str):
        from telegram_ui.keyboards import build_debug_keyboard, build_dynamic_keyboard, build_main_keyboard

        upper = (text or '').upper()
        if 'ОТЛАДКА' in upper or 'DEBUG' in upper:
            return build_debug_keyboard()
        state = TelegramResponder._payload_state(payload)
        return build_dynamic_keyboard(state) if state else build_main_keyboard()

    def send(self, chat_id: int, payload: BotResponsePayload | str) -> None:
        text = payload.text if isinstance(payload, BotResponsePayload) else str(payload)
        chunks = split_text_chunks(text)
        markup = self._keyboard(text, payload)
        for index, chunk in enumerate(chunks):
            reply_markup = markup if index == len(chunks) - 1 else None
            self.bot.send_message(chat_id, chunk, reply_markup=reply_markup)
        if isinstance(payload, BotResponsePayload) and payload.file_path:
            path = Path(payload.file_path)
            if path.exists() and path.is_file():
                with path.open('rb') as fh:
                    self.bot.send_document(chat_id, fh, caption=payload.file_caption or None)


class MarketAlertWorker(threading.Thread):
    def __init__(self, bot, chat_ids: Iterable[int], *, interval_sec: int, timeframes: Iterable[str]) -> None:
        super().__init__(daemon=True, name='market-alert-worker')
        self.bot = bot
        self.chat_ids = list(chat_ids)
        self.interval_sec = max(int(interval_sec), 20)
        self.timeframes = [str(tf).strip() for tf in timeframes if str(tf).strip()] or ['15m', '1h']
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info('alert_worker.start chat_ids=%s timeframes=%s interval=%s', self.chat_ids, self.timeframes, self.interval_sec)
        while not self._stop_event.is_set():
            started = time.time()
            try:
                for timeframe in self.timeframes:
                    snapshot = call_btc_analysis(timeframe)
                    alert_text = build_transition_alert(snapshot)
                    if not alert_text:
                        continue
                    message = build_market_alert_message(snapshot, timeframe, alert_text)
                    for chat_id in self.chat_ids:
                        for chunk in split_text_chunks(message):
                            self.bot.send_message(chat_id, chunk)
                            time.sleep(0.15)
            except Exception:
                logger.exception('alert_worker.loop_failed')
            elapsed = time.time() - started
            sleep_for = max(5.0, self.interval_sec - elapsed)
            self._stop_event.wait(sleep_for)


def _load_anti_spam_cfg() -> dict:
    """Load anti_spam section from config/anti_spam.yaml. Returns defaults on error."""
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "anti_spam.yaml"
    defaults = {
        "enabled": True,
        "cooldowns_sec": {"RSI_EXTREME": 3600, "LEVEL_BREAK": 3600},
        "log_deduped": True,
    }
    if not cfg_path.exists():
        return defaults
    try:
        import yaml
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return raw.get("anti_spam", defaults)
    except Exception:
        logger.exception("anti_spam.cfg_load_failed")
        return defaults


# ── P3 of TZ-DASHBOARD-USABILITY-FIX-PHASE-1: regulation-relevance gating ──
#
# Filter signal-stream events before forwarding to Telegram so the operator
# sees only events that change the admissible action set per
# REGULATION_v0_1_1.md §3, or that affect ongoing cleanup state.
#
# Activation: TELEGRAM_REGULATION_FILTER_ENABLED=1 in env (default OFF — opt-in
# during Phase 1 while operator validates the filter does not silence anything
# important). When OFF, this module is a no-op and behavior matches pre-P3.
#
# Policy:
#   FORWARD always:
#     LIQ_CASCADE          (risk event; already exempted from dedup)
#     REGIME_CHANGE        (changes activation matrix → operator action update)
#   FORWARD only when within cleanup_critical_levels USD distance:
#     LEVEL_BREAK          (key levels operator supplied via env)
#   SUPPRESS:
#     RSI_EXTREME          (raw indicator, no regulation impact alone)
#     other unknown types  (default-suppress; explicit opt-in needed)
#
# Cleanup-critical levels can be set via env TELEGRAM_FILTER_CRITICAL_LEVELS_USD
# as comma-separated USD prices; LEVEL_BREAK signals within
# TELEGRAM_FILTER_CRITICAL_PROXIMITY_USD (default $300) of any listed level
# are forwarded.

_REGULATION_FILTER_ENABLED = bool(
    int(os.environ.get("TELEGRAM_REGULATION_FILTER_ENABLED", "0"))
)


def _regulation_filter_critical_levels() -> list[float]:
    raw = os.environ.get("TELEGRAM_FILTER_CRITICAL_LEVELS_USD", "")
    out: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _regulation_filter_critical_proximity() -> float:
    try:
        return float(os.environ.get("TELEGRAM_FILTER_CRITICAL_PROXIMITY_USD", "300"))
    except ValueError:
        return 300.0


def regulation_relevance_decision(row: dict) -> tuple[bool, str]:
    """Return (should_forward, reason).

    Pure decision function — no side effects. Tested in
    tests/services/test_telegram_regulation_filter.py.
    """
    sig = row.get("signal_type", "")
    # Always-forward: risk events and admissibility changes.
    if sig in ("LIQ_CASCADE", "REGIME_CHANGE"):
        return True, f"always-forward: {sig} affects regulation/risk state"
    # LEVEL_BREAK: forward only near operator-declared critical levels.
    if sig == "LEVEL_BREAK":
        try:
            details = json.loads(row.get("details_json", "{}") or "{}")
        except Exception:
            details = {}
        level = details.get("level")
        try:
            level_f = float(level) if level is not None else None
        except (TypeError, ValueError):
            level_f = None
        if level_f is None:
            return False, "LEVEL_BREAK with unparseable level"
        critical = _regulation_filter_critical_levels()
        if not critical:
            return False, "LEVEL_BREAK suppressed: no critical levels configured"
        proximity = _regulation_filter_critical_proximity()
        for crit in critical:
            if abs(level_f - crit) <= proximity:
                return True, f"LEVEL_BREAK within {proximity:.0f} USD of critical level {crit:.0f}"
        return False, (
            f"LEVEL_BREAK at {level_f:.0f} not within {proximity:.0f} USD of any critical level"
        )
    # RSI_EXTREME and unknown: suppress by default.
    if sig == "RSI_EXTREME":
        return False, "RSI_EXTREME suppressed: raw indicator without regulation impact"
    return False, f"signal_type={sig!r} not in regulation-relevance allowlist"


class SignalAlertWorker(threading.Thread):
    """Polls signals.csv and sends new signals to Telegram.

    Anti-spam deduplication: RSI_EXTREME and LEVEL_BREAK are deduplicated by
    (signal_type, key_fields) within a configurable cooldown window.
    LIQ_CASCADE is never deduplicated here (handled by counter_long_manager).
    """

    _PREFIXES = {
        "LIQ_CASCADE": "⚠️ LIQ_CASCADE",
        "RSI_EXTREME": "📊 RSI_EXTREME",
        "LEVEL_BREAK": "🎯 LEVEL_BREAK",
    }

    def __init__(
        self,
        bot,
        chat_ids: Iterable[int],
        signals_csv: Path,
        *,
        poll_interval_sec: int = 30,
    ) -> None:
        super().__init__(daemon=True, name="signal-alert-worker")
        self.bot = bot
        self.chat_ids = list(chat_ids)
        self.signals_csv = signals_csv
        self.poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._last_ts: str = ""

        # Anti-spam state
        _cfg = _load_anti_spam_cfg()
        self._spam_enabled: bool = bool(_cfg.get("enabled", True))
        self._cooldowns: dict[str, int] = dict(_cfg.get("cooldowns_sec", {}))
        self._log_deduped: bool = bool(_cfg.get("log_deduped", True))
        # Persistent dedup: переживает рестарт supervisor/worker, иначе после
        # каждого крэша cooldown обнулялся и LEVEL_BREAK / RSI_EXTREME слали повторно.
        self._dedup_state_path = Path("state/signal_alert_last_sent.json")
        self._last_sent: dict[str, float] = self._load_last_sent()

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------ persistent dedup

    def _load_last_sent(self) -> dict[str, float]:
        try:
            if self._dedup_state_path.exists():
                raw = json.loads(self._dedup_state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return {str(k): float(v) for k, v in raw.items()}
        except Exception:
            logger.exception("signal_alert_worker.dedup_state_load_failed")
        return {}

    def _save_last_sent(self) -> None:
        try:
            self._dedup_state_path.parent.mkdir(parents=True, exist_ok=True)
            # Prune entries старше максимального cooldown × 2, чтобы файл не рос.
            max_cd = max(self._cooldowns.values(), default=3600)
            cutoff = time.time() - max_cd * 2
            d = {k: v for k, v in self._last_sent.items() if v >= cutoff}
            self._last_sent = d
            self._dedup_state_path.write_text(json.dumps(d), encoding="utf-8")
        except Exception:
            logger.exception("signal_alert_worker.dedup_state_save_failed")

    # ------------------------------------------------------------------ dedup

    @staticmethod
    def _dedup_key(row: dict) -> str | None:
        """Compute dedup key for a signal row. Returns None to skip dedup."""
        sig = row.get("signal_type", "")
        if sig == "LIQ_CASCADE":
            return None  # handled by counter_long_manager
        try:
            details = json.loads(row.get("details_json", "{}") or "{}")
        except Exception:
            return None
        if sig == "RSI_EXTREME":
            tf = details.get("timeframe", "")
            cond = details.get("condition", "")
            rsi = details.get("rsi", 0)
            return f"RSI_EXTREME|{tf}|{cond}|{round(float(rsi))}"
        if sig == "LEVEL_BREAK":
            # Direction NOT in key — это анти-флап: цена качается через уровень
            # туда-сюда внутри cooldown окна, но это один и тот же "пробой",
            # не два независимых события. Иначе шлём 2× на каждое колебание.
            #
            # 2026-05-10 ANTI-SPAM: округляем до $200-bucket чтобы 80601, 80638,
            # 80641, 80676, 80742 (все в скрине оператора) дедуплицировались.
            # Раньше ping-pong'ал между 5 уровнями каждые 5-10 мин.
            level = details.get("level", 0)
            try:
                bucket = int(round(float(level) / 200.0)) * 200
            except (TypeError, ValueError):
                bucket = 0
            return f"LEVEL_BREAK|bucket{bucket}"
        return None

    def _should_send(self, row: dict) -> bool:
        """Return True if signal should be sent, False if deduplicated.

        Two filters apply in order:
          1. Raw-duplicate suppression: LIQ_CASCADE и RSI_EXTREME из triggers.py
             уже выдают форматированные алерты через cascade_alert/loop (LIQ)
             либо вообще не нужны оператору (RSI). Подавляем чтобы не дублировать.
             Включается env SIGNAL_ALERT_SUPPRESS_RAW=1 (default ON 2026-05-13).
          2. P3 regulation-relevance filter (opt-in via env, default OFF)
          3. anti-spam dedup (existing behavior)
        """
        # Raw-duplicate suppression (default ON; override via env).
        suppress_raw = os.environ.get("SIGNAL_ALERT_SUPPRESS_RAW", "1") == "1"
        if suppress_raw:
            sig = row.get("signal_type", "")
            if sig in ("LIQ_CASCADE", "RSI_EXTREME"):
                if self._log_deduped:
                    logger.info(
                        "signal_alert.raw_suppressed signal_type=%s (use cascade_alert/loop instead)",
                        sig,
                    )
                return False
        # P3 regulation-relevance filter: when enabled, suppress events that
        # do not change admissible action set or affect cleanup state.
        if _REGULATION_FILTER_ENABLED:
            forward, reason = regulation_relevance_decision(row)
            if not forward:
                if self._log_deduped:
                    logger.info(
                        "signal_alert.regulation_filter_suppressed signal_type=%s reason=%s",
                        row.get("signal_type", ""), reason,
                    )
                return False
            # Annotate logs when forwarded for observability
            logger.info(
                "signal_alert.regulation_filter_forward signal_type=%s reason=%s",
                row.get("signal_type", ""), reason,
            )
        if not self._spam_enabled:
            return True
        key = self._dedup_key(row)
        if key is None:
            return True
        sig = row.get("signal_type", "")
        cooldown = self._cooldowns.get(sig, 0)
        if cooldown <= 0:
            return True
        now = time.time()
        last = self._last_sent.get(key, 0.0)
        if now - last < cooldown:
            if self._log_deduped:
                last_ts = time.strftime("%H:%M:%S", time.gmtime(last))
                logger.info(
                    "signal_alert.deduped key=%s last_sent=%s ago=%.0fmin",
                    key, last_ts, (now - last) / 60,
                )
            return False
        self._last_sent[key] = now
        self._save_last_sent()
        return True

    # ------------------------------------------------------------------ helpers

    def _read_new_signals(self) -> list[dict]:
        if not self.signals_csv.exists():
            return []
        new: list[dict] = []
        try:
            with self.signals_csv.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ts = row.get("ts_utc", "")
                    if ts > self._last_ts:
                        new.append(dict(row))
        except Exception:
            logger.exception("signal_alert_worker.read_failed")
        return new

    def _format_signal(self, row: dict) -> str:
        signal_type = row.get("signal_type", "")
        prefix = self._PREFIXES.get(signal_type, f"📡 {signal_type}")
        try:
            details = json.loads(row.get("details_json", "{}") or "{}")
        except Exception:
            details = {}
        ts_s = row.get("ts_utc", "")
        ts_short = ts_s[11:19] if len(ts_s) >= 19 else ts_s
        detail_s = "  ".join(f"{k}={v}" for k, v in details.items())
        return f"{prefix}  [{ts_short}]  {detail_s}"

    def _batch_level_breaks(self, rows: list[dict]) -> list[dict]:
        """Объединяет множественные LEVEL_BREAK с одной direction в один синтетический row.

        Сценарий: один тик пробивает 3 уровня сразу (например 80676/80638/80601 down)
        → раньше шло 3 отдельных алерта. Теперь — один: "LEVEL_BREAK down levels=80676,80638,80601 price=80546".

        Не-LEVEL_BREAK сигналы возвращаются без изменений. LEVEL_BREAK группируются
        по direction в пределах текущей пачки rows. Внутри группы dedup-ключи всех
        уровней регистрируются (через _should_send) чтобы повторный пробой того же
        уровня в следующем окне не прошёл.
        """
        non_lb: list[dict] = []
        groups: dict[str, list[dict]] = {}  # direction -> list of rows
        for row in rows:
            if row.get("signal_type") != "LEVEL_BREAK":
                non_lb.append(row)
                continue
            try:
                d = json.loads(row.get("details_json", "{}") or "{}")
            except Exception:
                non_lb.append(row)
                continue
            direction = str(d.get("direction", "?"))
            groups.setdefault(direction, []).append(row)

        result = list(non_lb)
        for direction, group_rows in groups.items():
            if len(group_rows) == 1:
                result.append(group_rows[0])
                continue
            # Aggregate: сортируем уровни, берём ts/price у последнего (новейшего)
            levels = []
            prices = []
            ts_max = ""
            for r in group_rows:
                try:
                    dd = json.loads(r.get("details_json", "{}") or "{}")
                    lvl = float(dd.get("level", 0))
                    levels.append(lvl)
                    p = dd.get("price")
                    if p is not None:
                        prices.append(float(p))
                except Exception:
                    pass
                ts = r.get("ts_utc", "")
                if ts > ts_max:
                    ts_max = ts
            if not levels:
                result.extend(group_rows)
                continue
            levels_sorted = sorted(set(int(round(x)) for x in levels), reverse=(direction == "down"))
            price = round(prices[-1], 2) if prices else 0
            agg_details = {
                "direction": direction,
                "levels": levels_sorted,
                "count": len(levels_sorted),
                "price": price,
            }
            result.append({
                "ts_utc": ts_max,
                "signal_type": "LEVEL_BREAK",
                "details_json": json.dumps(agg_details, ensure_ascii=False),
                "_aggregated_levels": levels_sorted,  # для регистрации dedup-ключей
            })
        return result

    def run(self) -> None:
        # Initialize last_ts so we don't replay already-existing signals on startup
        existing = self._read_new_signals()
        if existing:
            self._last_ts = max(s.get("ts_utc", "") for s in existing)
        logger.info("signal_alert_worker.start last_ts=%s", self._last_ts)
        while not self._stop_event.is_set():
            try:
                new_signals = self._read_new_signals()
                if new_signals:
                    self._last_ts = max(s.get("ts_utc", "") for s in new_signals)
                    # Batch LEVEL_BREAK ребят в один алерт когда пробито несколько уровней
                    # одним тиком (см. _batch_level_breaks).
                    new_signals = self._batch_level_breaks(new_signals)
                    from services.telegram.send_dedup import (
                        should_send as _ss, mark_sent as _ms,
                        is_rate_limited as _irl, mark_sent_rate as _msr,
                    )
                    for row in new_signals:
                        if not self._should_send(row):
                            continue
                        # Если это агрегированный LEVEL_BREAK — регистрируем
                        # dedup-ключи всех уровней, чтобы повторный пробой того же
                        # уровня в окне cooldown был отдедуплен.
                        agg_levels = row.pop("_aggregated_levels", None)
                        if agg_levels:
                            now_t = time.time()
                            for lvl in agg_levels:
                                self._last_sent[f"LEVEL_BREAK|{int(lvl)}"] = now_t
                            self._save_last_sent()
                        text = self._format_signal(row)
                        for chat_id in self.chat_ids:
                            # Belt-and-suspenders: persistent file-based dedup
                            # protects against duplicate alerts caused by parallel
                            # workers / process restarts / race conditions.
                            if not _ss(chat_id, text):
                                continue
                            # Rate limit: 3 sends per 90s per chat. Suppresses
                            # alert floods (e.g. 10 cascading bot fails firing
                            # back-to-back). Caller logs the suppression.
                            if _irl(chat_id):
                                continue
                            try:
                                self.bot.send_message(chat_id, text)
                                _ms(chat_id, text)
                                _msr(chat_id)
                                time.sleep(0.1)
                            except Exception:
                                logger.exception("signal_alert_worker.send_failed chat_id=%s", chat_id)
            except Exception:
                logger.exception("signal_alert_worker.loop_failed")
            self._stop_event.wait(self.poll_interval_sec)


# Telegram alert dedup window — suppress semantically identical pings within this period.
# Different from detector's 5-min JSONL dedup: here we compare payload content, not just type.
_ALERT_DEDUP_WINDOW_MINUTES = 30

# TZ-DEDUP-WIRE-PRODUCTION.
# Production wire-up of services.telegram.dedup_layer for selected emitters
# with frozen tuned thresholds. Other event types keep using only the
# signature-based _is_duplicate_recent path until separately wired.
DEDUP_LAYER_ENABLED_FOR_POSITION_CHANGE = bool(
    int(os.environ.get("DEDUP_LAYER_ENABLED_FOR_POSITION_CHANGE", "1"))
)
DEDUP_LAYER_ENABLED_FOR_BOUNDARY_BREACH = bool(
    int(os.environ.get("DEDUP_LAYER_ENABLED_FOR_BOUNDARY_BREACH", "1"))
)
# P3 of TZ-DASHBOARD-AND-TELEGRAM-USABILITY-PHASE-1: extend DedupLayer wiring
# to PNL_EVENT and PNL_EXTREME with loosened thresholds. Default = ON; env can
# disable for diagnostics.
DEDUP_LAYER_ENABLED_FOR_PNL_EVENT = bool(
    int(os.environ.get("DEDUP_LAYER_ENABLED_FOR_PNL_EVENT", "1"))
)
DEDUP_LAYER_ENABLED_FOR_PNL_EXTREME = bool(
    int(os.environ.get("DEDUP_LAYER_ENABLED_FOR_PNL_EXTREME", "1"))
)


class DecisionLogAlertWorker(threading.Thread):
    def __init__(self, bot, chat_ids: Iterable[int], events_path: Path, *, poll_interval_sec: int = 15, silent_mode: bool = False, dedup_state_path: Path | None = None) -> None:
        super().__init__(daemon=True, name="decision-log-alert-worker")
        self.bot = bot
        self.chat_ids = list(chat_ids)
        self.events_path = events_path
        self.poll_interval_sec = max(int(poll_interval_sec), 5)
        self._silent_mode = silent_mode
        self._stop_event = threading.Event()
        self._seen_event_ids: set[str] = self._load_seen_ids()
        self._recent_pings: deque[dict] = deque(maxlen=200)

        self._position_change_layer = None
        self._boundary_breach_layer = None
        self._pnl_event_layer = None
        self._pnl_extreme_layer = None
        self._dedup_counters = {
            "POSITION_CHANGE": {"emitted": 0, "suppressed_layer": 0, "suppressed_signature": 0},
            "BOUNDARY_BREACH": {"emitted": 0, "suppressed_layer": 0, "suppressed_signature": 0},
            "PNL_EVENT":       {"emitted": 0, "suppressed_layer": 0, "suppressed_signature": 0},
            "PNL_EXTREME":     {"emitted": 0, "suppressed_layer": 0, "suppressed_signature": 0},
        }
        try:
            from services.telegram.dedup_layer import DedupLayer, _STATE_PATH
            from services.telegram.dedup_configs import (
                BOUNDARY_BREACH_DEDUP_CONFIG,
                POSITION_CHANGE_DEDUP_CONFIG,
                PNL_EVENT_DEDUP_CONFIG,
                PNL_EXTREME_DEDUP_CONFIG,
            )

            state_path = dedup_state_path if dedup_state_path is not None else _STATE_PATH
            if DEDUP_LAYER_ENABLED_FOR_POSITION_CHANGE:
                cfg = POSITION_CHANGE_DEDUP_CONFIG
                self._position_change_layer = DedupLayer(cfg, state_path=state_path)
                logger.info(
                    "decision_log_alert_worker.dedup_layer_enabled type=POSITION_CHANGE "
                    "cooldown_sec=%d value_delta_min=%.2f state=%s",
                    cfg.cooldown_sec, cfg.value_delta_min, state_path,
                )
            if DEDUP_LAYER_ENABLED_FOR_BOUNDARY_BREACH:
                cfg = BOUNDARY_BREACH_DEDUP_CONFIG
                self._boundary_breach_layer = DedupLayer(cfg, state_path=state_path)
                logger.info(
                    "decision_log_alert_worker.dedup_layer_enabled type=BOUNDARY_BREACH "
                    "cooldown_sec=%d value_delta_min=%.2f state=%s",
                    cfg.cooldown_sec, cfg.value_delta_min, state_path,
                )
            if DEDUP_LAYER_ENABLED_FOR_PNL_EVENT:
                cfg = PNL_EVENT_DEDUP_CONFIG
                self._pnl_event_layer = DedupLayer(cfg, state_path=state_path)
                logger.info(
                    "decision_log_alert_worker.dedup_layer_enabled type=PNL_EVENT "
                    "cooldown_sec=%d value_delta_min=%.2f state=%s",
                    cfg.cooldown_sec, cfg.value_delta_min, state_path,
                )
            if DEDUP_LAYER_ENABLED_FOR_PNL_EXTREME:
                cfg = PNL_EXTREME_DEDUP_CONFIG
                self._pnl_extreme_layer = DedupLayer(cfg, state_path=state_path)
                logger.info(
                    "decision_log_alert_worker.dedup_layer_enabled type=PNL_EXTREME "
                    "cooldown_sec=%d value_delta_min=%.2f state=%s",
                    cfg.cooldown_sec, cfg.value_delta_min, state_path,
                )
        except Exception:
            logger.exception("decision_log_alert_worker.dedup_layer_init_failed")

    def stop(self) -> None:
        self._stop_event.set()

    def _load_seen_ids(self) -> set[str]:
        """Pre-seed seen IDs from existing JSONL so restart doesn't re-send historical events."""
        from services.decision_log import iter_events

        seen: set[str] = set()
        try:
            for event in iter_events(self.events_path):
                seen.add(event.event_id)
        except Exception:
            logger.exception("decision_log_alert_worker.seed_seen_ids_failed")
        logger.info("decision_log_alert_worker.seed_seen_ids loaded=%d", len(seen))
        return seen

    def _read_new_events(self) -> list:
        from services.decision_log import EventSeverity, iter_events

        events = []
        for event in iter_events(self.events_path):
            if event.event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event.event_id)
            if event.severity in (EventSeverity.WARNING, EventSeverity.CRITICAL):
                events.append(event)
        return events

    def _compute_signature(self, event) -> str:
        """Canonical payload signature used for Telegram dedup comparison."""
        et = event.event_type
        p: dict = event.payload or {}
        if et == "PNL_EVENT":
            bucket = round(float(p.get("delta_pnl_usd", 0)) / 100) * 100
            return f"pnl_delta_{bucket}"
        if et == "PNL_EXTREME":
            bucket = round(float(p.get("value", 0)) / 100) * 100
            return f"pnl_extreme_{bucket}"
        if et == "BOUNDARY_BREACH":
            direction = "above" if "border_top" in p else "below"
            return f"boundary_{direction}"
        if et == "POSITION_CHANGE":
            bucket = round(float(p.get("delta_ratio", 0)) * 100)
            return f"pos_{bucket}"
        return hashlib.sha256(
            json.dumps(p, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def _position_change_value(self, event) -> float:
        """Extract the dedup-layer value for a POSITION_CHANGE event."""
        portfolio = getattr(event, "portfolio_context", None)
        if portfolio is None:
            return 0.0

        def _get(obj, key, default=0.0):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        shorts = abs(float(_get(portfolio, "shorts_position_btc") or 0.0))
        longs_usd = float(_get(portfolio, "longs_position_usd") or 0.0)
        longs_btc = longs_usd / 80000.0
        return round(shorts + longs_btc, 4)

    def _boundary_breach_value(self, event) -> float:
        """Extract the dedup-layer value for a BOUNDARY_BREACH event."""
        market = getattr(event, "market_context", None)
        if market is None:
            return 0.0
        if isinstance(market, dict):
            return float(market.get("price_btc") or 0.0)
        return float(getattr(market, "price_btc", 0.0) or 0.0)

    @staticmethod
    def _pnl_event_value(event) -> float:
        """Extract dedup-layer value for PNL_EVENT — current cumulative PnL USD.

        Prefer cumulative PnL (state-change semantics: value moves to a new
        level). If only delta is available, fall back to delta.
        """
        p = getattr(event, "payload", None) or {}
        if isinstance(p, dict):
            for key in ("pnl_total_usd", "current_pnl_usd", "delta_pnl_usd"):
                v = p.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
        return 0.0

    @staticmethod
    def _pnl_extreme_value(event) -> float:
        """Extract dedup-layer value for PNL_EXTREME — extreme PnL value USD."""
        p = getattr(event, "payload", None) or {}
        if isinstance(p, dict):
            for key in ("value", "extreme_pnl_usd", "pnl_total_usd"):
                v = p.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
        return 0.0

    @staticmethod
    def _event_ts(event) -> float | None:
        try:
            return event.ts.timestamp() if hasattr(event.ts, "timestamp") else None
        except Exception:
            return None

    def _evaluate_position_change_layer(self, event):
        layer = self._position_change_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        return layer.evaluate(
            emitter="POSITION_CHANGE",
            key=str(bot_id),
            value=self._position_change_value(event),
            now_ts=self._event_ts(event),
        )

    def _evaluate_boundary_breach_layer(self, event):
        layer = self._boundary_breach_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        return layer.evaluate(
            emitter="BOUNDARY_BREACH",
            key=str(bot_id),
            value=self._boundary_breach_value(event),
            now_ts=self._event_ts(event),
        )

    def _evaluate_pnl_event_layer(self, event):
        layer = self._pnl_event_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        return layer.evaluate(
            emitter="PNL_EVENT",
            key=str(bot_id),
            value=self._pnl_event_value(event),
            now_ts=self._event_ts(event),
        )

    def _evaluate_pnl_extreme_layer(self, event):
        layer = self._pnl_extreme_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        return layer.evaluate(
            emitter="PNL_EXTREME",
            key=str(bot_id),
            value=self._pnl_extreme_value(event),
            now_ts=self._event_ts(event),
        )

    def _record_position_change_emit(self, event) -> None:
        layer = self._position_change_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        layer.record_emit(
            emitter="POSITION_CHANGE",
            key=str(bot_id),
            value=self._position_change_value(event),
            now_ts=self._event_ts(event),
        )

    def _record_boundary_breach_emit(self, event) -> None:
        layer = self._boundary_breach_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        layer.record_emit(
            emitter="BOUNDARY_BREACH",
            key=str(bot_id),
            value=self._boundary_breach_value(event),
            now_ts=self._event_ts(event),
        )

    def _record_pnl_event_emit(self, event) -> None:
        layer = self._pnl_event_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        layer.record_emit(
            emitter="PNL_EVENT",
            key=str(bot_id),
            value=self._pnl_event_value(event),
            now_ts=self._event_ts(event),
        )

    def _record_pnl_extreme_emit(self, event) -> None:
        layer = self._pnl_extreme_layer
        bot_id = getattr(event, "bot_id", None) or "global"
        layer.record_emit(
            emitter="PNL_EXTREME",
            key=str(bot_id),
            value=self._pnl_extreme_value(event),
            now_ts=self._event_ts(event),
        )

    def dedup_metrics(self) -> dict:
        return {
            "POSITION_CHANGE": dict(self._dedup_counters["POSITION_CHANGE"]),
            "BOUNDARY_BREACH": dict(self._dedup_counters["BOUNDARY_BREACH"]),
            "PNL_EVENT":       dict(self._dedup_counters["PNL_EVENT"]),
            "PNL_EXTREME":     dict(self._dedup_counters["PNL_EXTREME"]),
            "layer_enabled_position_change": self._position_change_layer is not None,
            "layer_enabled_boundary_breach": self._boundary_breach_layer is not None,
            "layer_enabled_pnl_event":       self._pnl_event_layer is not None,
            "layer_enabled_pnl_extreme":     self._pnl_extreme_layer is not None,
        }

    def _is_duplicate_recent(self, event) -> bool:
        try:
            sig = self._compute_signature(event)
            # Window-cutoff is relative to the event's timestamp, not wall-clock.
            # An event observed at T is considered duplicate of any recent ping
            # within [T - window, T]. Fixed 2026-05-11: was using now() which
            # made the dedup check unusable for backfill / replayed events and
            # for unit tests with fixed timestamps.
            ev_ts = getattr(event, "ts", None) or datetime.now(timezone.utc)
            if isinstance(ev_ts, datetime) and ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            cutoff = ev_ts - timedelta(minutes=_ALERT_DEDUP_WINDOW_MINUTES)
            for recent in self._recent_pings:
                if recent["ts"] < cutoff:
                    continue
                if recent["event_type"] != event.event_type:
                    continue
                if recent["bot_id"] != event.bot_id:
                    continue
                if recent["payload_signature"] == sig:
                    return True
            return False
        except Exception:
            logger.exception("decision_log_alert_worker.dedup_check_failed")
            return False

    def run(self) -> None:
        logger.info("decision_log_alert_worker.start path=%s", self.events_path)
        while not self._stop_event.is_set():
            try:
                from services.decision_log import build_event_keyboard, format_event_message

                for event in self._read_new_events():
                    emitter = str(event.event_type)
                    if self._is_duplicate_recent(event):
                        logger.info(
                            "decision_log_alert_worker.dedup_skip event_type=%s bot_id=%s",
                            event.event_type, event.bot_id,
                        )
                        if emitter in self._dedup_counters:
                            self._dedup_counters[emitter]["suppressed_signature"] += 1
                        continue

                    decision = None
                    if self._position_change_layer is not None and emitter == "POSITION_CHANGE":
                        decision = self._evaluate_position_change_layer(event)
                    elif self._boundary_breach_layer is not None and emitter == "BOUNDARY_BREACH":
                        decision = self._evaluate_boundary_breach_layer(event)
                    elif self._pnl_event_layer is not None and emitter == "PNL_EVENT":
                        decision = self._evaluate_pnl_event_layer(event)
                    elif self._pnl_extreme_layer is not None and emitter == "PNL_EXTREME":
                        decision = self._evaluate_pnl_extreme_layer(event)

                    if decision is not None and not decision.should_emit:
                        self._dedup_counters[emitter]["suppressed_layer"] += 1
                        logger.info(
                            "decision_log_alert_worker.dedup_layer_suppress "
                            "event_type=%s reason=%s",
                            emitter,
                            decision.reason_ru,
                        )
                        continue

                    if self._silent_mode:
                        logger.info(
                            "decision_log_alert_worker.silent_mode event_type=%s bot_id=%s",
                            event.event_type, event.bot_id,
                        )
                    else:
                        text = format_event_message(event)
                        markup = build_event_keyboard(event.event_id)
                        for chat_id in self.chat_ids:
                            self.bot.send_message(chat_id, text, reply_markup=markup)
                            time.sleep(0.1)

                    self._recent_pings.append({
                        "event_type": event.event_type,
                        "bot_id": event.bot_id,
                        "ts": datetime.now(timezone.utc),
                        "payload_signature": self._compute_signature(event),
                    })
                    if self._position_change_layer is not None and emitter == "POSITION_CHANGE":
                        self._record_position_change_emit(event)
                        self._dedup_counters["POSITION_CHANGE"]["emitted"] += 1
                    elif self._boundary_breach_layer is not None and emitter == "BOUNDARY_BREACH":
                        self._record_boundary_breach_emit(event)
                        self._dedup_counters["BOUNDARY_BREACH"]["emitted"] += 1
                    elif self._pnl_event_layer is not None and emitter == "PNL_EVENT":
                        self._record_pnl_event_emit(event)
                        self._dedup_counters["PNL_EVENT"]["emitted"] += 1
                    elif self._pnl_extreme_layer is not None and emitter == "PNL_EXTREME":
                        self._record_pnl_extreme_emit(event)
                        self._dedup_counters["PNL_EXTREME"]["emitted"] += 1
            except Exception:
                logger.exception("decision_log_alert_worker.loop_failed")
            self._stop_event.wait(self.poll_interval_sec)


class TelegramBotApp:
    def __init__(self) -> None:
        setup_logging()
        token = str(config.BOT_TOKEN or '').strip()
        if not token or ':' not in token:
            raise RuntimeError('BOT_TOKEN не найден. Проверь .env или bot_local_config.json')

        try:
            import telebot
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('Не установлен pyTelegramBotAPI. Выполни pip install -r requirements.txt') from exc

        self.allowed_chat_ids = normalize_chat_ids(
            os.getenv('ALLOWED_CHAT_IDS', ''),
            getattr(config, 'CHAT_ID', ''),
        )
        self.bot = telebot.TeleBot(token, parse_mode=None)
        self.responder = TelegramResponder(self.bot)
        self.command_handler = CommandHandler(self.responder.send)
        self.alert_worker = MarketAlertWorker(
            self.bot,
            self.allowed_chat_ids,
            interval_sec=getattr(config, 'AUTO_EDGE_ALERTS_INTERVAL_SEC', 60),
            timeframes=str(getattr(config, 'AUTO_EDGE_ALERTS_TIMEFRAMES', '15m,1h')).split(','),
        )
        _signals_csv = Path(__file__).resolve().parents[1] / "market_live" / "signals.csv"
        self.signal_alert_worker = SignalAlertWorker(
            self.bot,
            self.allowed_chat_ids,
            _signals_csv,
            poll_interval_sec=30,
        )
        self._decision_log_pending_reason: dict[int, str] = {}
        self.decision_log_alert_worker = DecisionLogAlertWorker(
            self.bot,
            self.allowed_chat_ids,
            self._decision_log_events_path(),
            poll_interval_sec=15,
            silent_mode=True,
        )
        # P2 of TZ-DASHBOARD-AND-TELEGRAM-USABILITY-PHASE-1: VERBOSE channel
        # subscription registry. Default = OFF for all chats; operator opts in
        # per-chat via /verbose.
        try:
            from services.telegram.alert_router import VerboseSubscriptionRegistry
            self.verbose_subs = VerboseSubscriptionRegistry()
        except Exception:
            logger.exception('verbose_subs.init_failed')
            self.verbose_subs = None
        self._register_handlers()

    def _is_allowed(self, chat_id: int) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def _send_long_text(self, chat_id: int, text: str, *,
                         filename: str = "report.txt",
                         max_inline: int = 3800) -> None:
        """Send `text` to TG. Short → message. Long → attached file."""
        if len(text) <= max_inline:
            self.bot.send_message(chat_id, f"```\n{text}\n```",
                                    parse_mode='Markdown')
            return
        # Long: write to temp file, send as document
        try:
            import tempfile
            from pathlib import Path as _Path
            tmp = _Path(tempfile.gettempdir()) / f"bot7_{filename}"
            tmp.write_text(text, encoding="utf-8")
            with tmp.open("rb") as fh:
                self.bot.send_document(chat_id, fh,
                                        caption=f"{filename} ({len(text):,} chars)")
        except Exception as exc:
            logger.exception('_send_long_text.failed')
            # Fallback: truncate inline
            self.bot.send_message(
                chat_id,
                f"```\n{text[:max_inline]}\n... (truncated, send_document failed: {exc})\n```",
                parse_mode='Markdown'
            )

    def _dispatch(self, chat_id: int, text: str) -> None:
        resolved = resolve_telegram_text(text)
        if not resolved:
            self.bot.send_message(chat_id, 'Напиши команду или нажми кнопку.')
            return
        if resolved == 'МОЯ ПОЗИЦИЯ':
            state = load_position_state()
            if not bool((state or {}).get('has_position')):
                self.bot.send_message(
                    chat_id,
                    '📭 Сейчас открытая позиция не зафиксирована.\n\nДля рынка используй /market или /entry. Для сопровождения после входа — /exit или /manage.',
                )
                return
        self.command_handler.handle(chat_id, resolved)

    def _decision_log_events_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "state" / "decision_log" / "events.jsonl"

    def _decision_log_annotations_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "state" / "decision_log" / "annotations.jsonl"

    def _decision_log_outcomes_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "state" / "decision_log" / "outcomes.jsonl"

    def _register_handlers(self) -> None:
        from telegram_ui.keyboards import build_main_keyboard

        @self.bot.message_handler(commands=['start', 'menu'])
        def handle_start(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            self.bot.send_message(
                chat_id,
                'Бот запущен.\n\nДоступно:\n/help\n/market\nBTC 5M / BTC 15M / BTC 1H / BTC 4H / BTC 1D\nBTC GINAREA',
                reply_markup=build_main_keyboard(),
            )

        @self.bot.message_handler(commands=['help', 'market', 'analysis'])
        def handle_commands(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            self._dispatch(chat_id, str(message.text or '').strip())

        @self.bot.message_handler(commands=['playbook'])
        def handle_playbook(message) -> None:
            """Full position playbook on-demand (replaces the hourly noise).
            Hourly alert now compact; full playbook only when operator asks."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.exit_advisor.position_state import (
                    build_position_state_snapshot,
                )
                from services.exit_advisor.honest_renderer import (
                    format_honest_advisory,
                )
                state = build_position_state_snapshot()
                text = format_honest_advisory(state)
                if not text:
                    text = 'Нет активной позиции — playbook не применим.'
                self.bot.send_message(chat_id, text)
            except Exception as exc:
                logger.exception('playbook.failed')
                self.bot.send_message(chat_id, f'⚠️ /playbook failed: {exc}')

        @self.bot.message_handler(commands=['confluence_now', 'cn'])
        def handle_confluence_now(message) -> None:
            """Show current confluence buffer: which detectors fired same side
            in last 6h. Helps operator see why confidence got boosted (or not).
            2026-05-12, related to services.setup_detector.confluence_score.
            """
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            try:
                from services.setup_detector.confluence_score import (
                    get_tracker, BOOST_K2, BOOST_K3, BOOST_K4_PLUS,
                )
                from datetime import datetime, timezone
                tracker = get_tracker()
                now = datetime.now(timezone.utc)
                tracker._prune(now)
                items = list(tracker._items)
                long_dets: dict[str, str] = {}
                short_dets: dict[str, str] = {}
                for item in items:
                    rel_min = int((now - item.ts).total_seconds() / 60)
                    age = f"{rel_min}м назад"
                    if item.side == "long":
                        # keep most recent per detector
                        long_dets[item.detector] = age
                    else:
                        short_dets[item.detector] = age
                n_long = len(long_dets)
                n_short = len(short_dets)
                lines = ["📊 CONFLUENCE BUFFER (последние 6 ч)", ""]
                lines.append(f"🟢 LONG: {n_long} detector(s)")
                if long_dets:
                    for det, age in sorted(long_dets.items()):
                        lines.append(f"   • {det} — {age}")
                else:
                    lines.append("   (нет активных сигналов)")
                lines.append("")
                lines.append(f"🔴 SHORT: {n_short} detector(s)")
                if short_dets:
                    for det, age in sorted(short_dets.items()):
                        lines.append(f"   • {det} — {age}")
                else:
                    lines.append("   (нет активных сигналов)")
                lines.append("")
                # Boost forecast
                def _boost_str(n: int) -> str:
                    if n >= 4: return f"×{BOOST_K4_PLUS} (K≥4)"
                    if n >= 3: return f"×{BOOST_K3} (K≥3)"
                    if n >= 2: return f"×{BOOST_K2} (K≥2)"
                    return "×1.0 (нет boost)"
                lines.append("⚙️ Если детектор сейчас сработает:")
                lines.append(f"   LONG → confidence {_boost_str(n_long)}")
                lines.append(f"   SHORT → confidence {_boost_str(n_short)}")
                lines.append("")
                lines.append(f"Всего setups в буфере: {len(items)}")
                self.bot.send_message(chat_id, "\n".join(lines))
            except Exception as exc:
                logger.exception('confluence_now.failed')
                self.bot.send_message(chat_id, f'⚠️ /confluence_now failed: {exc}')

        @self.bot.message_handler(commands=['verbose'])
        def handle_verbose(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            if self.verbose_subs is None:
                self.bot.send_message(chat_id, '⚠️ VERBOSE registry недоступен (init failed).')
                return
            from services.telegram.alert_router import handle_verbose_command
            text = str(message.text or '').strip()
            # Strip leading `/verbose` to get args
            args = text[len('/verbose'):].strip() if text.lower().startswith('/verbose') else ''
            reply = handle_verbose_command(chat_id, args, self.verbose_subs)
            self.bot.send_message(chat_id, reply)

        @self.bot.message_handler(commands=['protect_status'])
        def handle_protect_status(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.protection_alerts import ProtectionAlerts
            self.bot.send_message(chat_id, ProtectionAlerts.instance().status_text())

        @self.bot.message_handler(commands=['protect_off'])
        def handle_protect_off(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.protection_alerts import ProtectionAlerts
            ProtectionAlerts.instance().set_enabled(False)
            self.bot.send_message(chat_id, '⏸ Защита отключена.')

        @self.bot.message_handler(commands=['protect_on'])
        def handle_protect_on(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.protection_alerts import ProtectionAlerts
            ProtectionAlerts.instance().set_enabled(True)
            self.bot.send_message(chat_id, '✅ Защита включена.')

        @self.bot.message_handler(commands=['protect_threshold'])
        def handle_protect_threshold(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            # Usage: /protect_threshold position_stress critical -250
            parts = str(message.text or '').strip().split()
            if len(parts) != 4:
                self.bot.send_message(chat_id, 'Формат: /protect_threshold <alert> <level> <value>\nПример: /protect_threshold position_stress critical -250')
                return
            _, alert, level, raw_value = parts
            try:
                value = float(raw_value)
            except ValueError:
                self.bot.send_message(chat_id, f'Неверное значение: {raw_value}')
                return
            from services.protection_alerts import ProtectionAlerts
            ok = ProtectionAlerts.instance().set_threshold(alert, level, value)
            if ok:
                self.bot.send_message(chat_id, f'✅ {alert}.{level} = {value}')
            else:
                self.bot.send_message(chat_id, f'❌ Неизвестный алерт/уровень: {alert}/{level}')

        @self.bot.message_handler(commands=['boundary_status'])
        def handle_boundary_status(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.boundary_expand_manager import BoundaryExpandManager
            self.bot.send_message(chat_id, BoundaryExpandManager.instance().status_text())

        @self.bot.message_handler(commands=['boundary_off'])
        def handle_boundary_off(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.boundary_expand_manager import BoundaryExpandManager
            BoundaryExpandManager.instance().set_enabled(False)
            self.bot.send_message(chat_id, '⏸ Boundary expand отключён.')

        @self.bot.message_handler(commands=['boundary_on'])
        def handle_boundary_on(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.boundary_expand_manager import BoundaryExpandManager
            BoundaryExpandManager.instance().set_enabled(True)
            self.bot.send_message(chat_id, '✅ Boundary expand включён.')

        @self.bot.message_handler(commands=['grid_status'])
        def handle_grid_status(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.adaptive_grid_manager import AdaptiveGridManager
            self.bot.send_message(chat_id, AdaptiveGridManager.instance().status_text())

        @self.bot.message_handler(commands=['grid_off'])
        def handle_grid_off(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.adaptive_grid_manager import AdaptiveGridManager
            AdaptiveGridManager.instance().set_enabled(False)
            self.bot.send_message(chat_id, '⏸ Adaptive grid отключён.')

        @self.bot.message_handler(commands=['grid_on'])
        def handle_grid_on(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            from services.adaptive_grid_manager import AdaptiveGridManager
            AdaptiveGridManager.instance().set_enabled(True)
            self.bot.send_message(chat_id, '✅ Adaptive grid включён.')

        # ── TZ-028: /logs and /restart ────────────────────────────────────────

        @self.bot.message_handler(commands=['logs'])
        def handle_logs(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = str(message.text or '').strip().split()
            component = parts[1] if len(parts) > 1 else 'all'
            try:
                from src.supervisor.process_config import ALL_COMPONENTS, log_path
                from src.utils.logging_config import CURRENT_DIR
                names = ALL_COMPONENTS if component == 'all' else [component]
                out_parts = []
                for name in names:
                    lp = log_path(name) if name in ALL_COMPONENTS else CURRENT_DIR / f'{name}.log'
                    if not lp.exists():
                        out_parts.append(f'[{name}] нет лога')
                        continue
                    lines = lp.read_text(encoding='utf-8', errors='replace').splitlines()
                    warn_lines = [l for l in lines if ' WARNING ' in l or ' ERROR ' in l or ' CRITICAL ' in l]
                    tail = warn_lines[-20:] if warn_lines else lines[-5:]
                    out_parts.append(f'[{name}]\n' + '\n'.join(tail))
                self.bot.send_message(chat_id, '\n\n'.join(out_parts)[:3800])
            except Exception as exc:
                self.bot.send_message(chat_id, f'Ошибка: {exc}')

        @self.bot.message_handler(commands=['restart'])
        def handle_restart(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = str(message.text or '').strip().split()
            if len(parts) < 2:
                self.bot.send_message(chat_id, 'Формат: /restart <component>\nКомпоненты: app_runner, tracker, collectors')
                return
            component = parts[1]
            try:
                from src.supervisor.process_config import ALL_COMPONENTS, pid_path
                from src.supervisor.daemon import DAEMON_PID_PATH, _pid_alive, _read_pid
                import os, signal as _signal
                if component not in ALL_COMPONENTS:
                    self.bot.send_message(chat_id, f'Неизвестный компонент: {component}')
                    return
                pid = _read_pid(pid_path(component))
                if pid and _pid_alive(pid):
                    os.kill(pid, _signal.SIGTERM)
                    self.bot.send_message(chat_id, f'♻️ {component} (PID={pid}) — отправлен SIGTERM. Supervisor перезапустит через 30s.')
                else:
                    self.bot.send_message(chat_id, f'⚠️ {component} не запущен (PID файл пуст или процесс мёртв). Supervisor перезапустит.')
            except Exception as exc:
                self.bot.send_message(chat_id, f'Ошибка: {exc}')

        # ── /watch (D2 watchlist 2026-05-07) ──────────────────────────────────
        # Operator-defined alerts когда условие срабатывает.
        # Examples: /watch add funding > 0.01 ; /watch del 4f3a8b1 ; /watch
        @self.bot.message_handler(commands=['watch', 'watchlist'])
        def handle_watch(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.watchlist import (
                load_rules, format_rule_summary, add_rule as _add,
                remove_rule as _remove, toggle_rule as _toggle,
            )
            text = (message.text or "").strip()
            parts = text.split(maxsplit=2)
            if len(parts) <= 1:
                self.bot.send_message(chat_id, format_rule_summary(load_rules()))
                return
            sub = parts[1].lower()
            arg = parts[2] if len(parts) > 2 else ""
            if sub == "add":
                rule = _add(arg)
                if rule is None:
                    self.bot.send_message(chat_id, f"❌ Не разобрал правило '{arg}'. Формат: /watch add <field> <op> <value>")
                else:
                    self.bot.send_message(chat_id, f"✅ Добавлено [{rule.id}]: {rule.field} {rule.op} {rule.threshold}")
            elif sub in ("del", "delete", "remove", "rm"):
                if _remove(arg):
                    self.bot.send_message(chat_id, f"✅ Удалено [{arg}]")
                else:
                    self.bot.send_message(chat_id, f"❌ Не найдено [{arg}]")
            elif sub in ("toggle", "on", "off"):
                rule = _toggle(arg)
                if rule:
                    flag = "ВКЛ" if rule.enabled else "ВЫКЛ"
                    self.bot.send_message(chat_id, f"✅ [{rule.id}] {flag}")
                else:
                    self.bot.send_message(chat_id, f"❌ Не найдено [{arg}]")
            else:
                self.bot.send_message(chat_id, "Команды: /watch | /watch add <rule> | /watch del <id> | /watch toggle <id>")

        # ── /momentum_check (TZ-MOMENTUM-CHECK 2026-05-07) ───────────────────
        # Intraday-tool: character движения, истощение, дивергенции, сессия,
        # liquidations, OI/funding flow. Дополняет /advise (общая картина).
        @self.bot.message_handler(commands=['momentum_check', 'momentum'])
        def handle_momentum_check(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.momentum_check import build_momentum_check, format_momentum_check
                snap = build_momentum_check()
                text = format_momentum_check(snap)
            except Exception as exc:
                logger.exception("handle_momentum_check.failed")
                self.bot.send_message(chat_id, f'❌ momentum_check failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        # ── /audit — health snapshot for the operator (TZ-AUDIT-CMD 2026-05-08).
        # Surfaces silent failures: stale state files, detectors firing but
        # being combo-blocked, DL push volume, paper-trader activity. Same
        # checks I (the assistant) run during manual audits — just packaged.
        @self.bot.message_handler(commands=['disable'])
        def handle_disable(message) -> None:
            """`/disable <token>` adds detector token to runtime disable list.
            `/disable` (no arg) lists current state. Token is substring-matched
            against detector function names."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.setup_detector.runtime_disabled import (
                add_runtime_disabled, list_disabled,
            )
            text = str(message.text or '').strip()
            args = text.split(maxsplit=1)
            if len(args) < 2:
                # No arg → list current
                d = list_disabled()
                self.bot.send_message(
                    chat_id,
                    f"Currently disabled:\n"
                    f"  via .env: {d['env'] or '(none)'}\n"
                    f"  via /disable: {d['state_file'] or '(none)'}\n\n"
                    f"Usage: /disable <token>  (e.g. /disable multi_divergence)"
                )
                return
            token = args[1].strip()
            added = add_runtime_disabled(token)
            d = list_disabled()
            if added:
                self.bot.send_message(
                    chat_id,
                    f"✓ Added '{token}' to runtime disable list.\n"
                    f"Now disabled: {d['env'] + d['state_file']}\n"
                    f"Takes effect within 60s (cache TTL)."
                )
            else:
                self.bot.send_message(
                    chat_id, f"'{token}' was already disabled — no change."
                )

        @self.bot.message_handler(commands=['positions', 'pos'])
        def handle_positions(message) -> None:
            """/positions — снапшот BitMEX баланс + open positions + dist_liq +
            активные Range Hunter ноги + статус edge_drift. Visibility без UI BitMEX."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            import json as _json
            from pathlib import Path as _Path
            from datetime import datetime as _dt, timezone as _tz
            ROOT = _Path('/Users/alexeychechikov/code/bot7')
            lines = ["📊 СНАПШОТ ПОЗИЦИЙ"]
            # 1) BitMEX margin
            try:
                margin_file = ROOT / 'state' / 'margin_automated.jsonl'
                if margin_file.exists():
                    last_margin = None
                    with margin_file.open() as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                last_margin = line
                    if last_margin:
                        m = _json.loads(last_margin)
                        lines.append(f"\n💰 BitMEX (последнее обновление {m.get('ts', '?')}):")
                        lines.append(f"  Wallet balance:  ${m.get('wallet_balance_usd', 0):,.2f}")
                        lines.append(f"  Margin balance:  ${m.get('margin_balance_usd', 0):,.2f}")
                        lines.append(f"  Available:       ${m.get('available_margin_usd', 0):,.2f}")
                        lines.append(f"  Used margin:     ${m.get('used_margin_usd', 0):,.2f}")
                        lines.append(f"  Distance to liq: {m.get('distance_to_liquidation_pct', 0):.1f}%")
                        lines.append(f"  Open positions:  {m.get('positions_count', 0)}")
                        lines.append(f"  BTC mark price:  ${m.get('btc_mark_price', 0):,.0f}")
            except Exception:
                lines.append("  ❌ BitMEX state недоступен")
            # 2) Range Hunter pending signals (placed legs)
            try:
                from services.range_hunter.journal import (
                    read_all as _rh_read, journal_path_for as _rh_path,
                )
                lines.append("\n🎯 Range Hunter pending signals:")
                any_rh = False
                for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
                    for variant in ("1m", "5m"):
                        path = _rh_path(sym, variant)
                        rows = _rh_read(path=path)
                        placed = [r for r in rows if r.get("user_action") == "placed" and r.get("exit_reason") is None]
                        if placed:
                            any_rh = True
                            for r in placed[-3:]:
                                lines.append(f"  [{sym} {variant}] {r['signal_id']} ${r['buy_level']:,.0f}/${r['sell_level']:,.0f}")
                if not any_rh:
                    lines.append("  (нет активных placed-сигналов)")
            except Exception:
                lines.append("  ❌ Range Hunter journal недоступен")
            # 3) Edge drift status
            try:
                drift_file = ROOT / 'state' / 'cascade_edge_drift.json'
                if drift_file.exists():
                    drift = _json.loads(drift_file.read_text())
                    lines.append("\n⚠️ Cascade edge drift:")
                    for key, d in drift.items():
                        if d.get('drifted'):
                            lines.append(f"  ❌ {key}: acc {d.get('accuracy')}% (n={d.get('n')}) — DRIFTED")
                        else:
                            lines.append(f"  ✓ {key}: acc {d.get('accuracy')}% (n={d.get('n')})")
            except Exception:
                pass
            # 4) Volatility regime
            try:
                from services.volatility_regime import current_regime
                lines.append("\n🌊 Volatility regime (last 4h):")
                for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
                    reg, vol = current_regime(sym)
                    emoji = "🟢" if reg == "low" else "🟡" if reg == "medium" else "🔴"
                    vol_s = f"{vol:.1f}%" if vol is not None else "N/A"
                    lines.append(f"  {emoji} {sym}: {reg.upper()} ({vol_s} annualized)")
            except Exception:
                pass
            self.bot.send_message(chat_id, "\n".join(lines))

        @self.bot.message_handler(commands=['tv_status', 'tv'])
        def handle_tv_status(message) -> None:
            """/tv_status [N] — last N TradingView webhook alerts (default 10).
            Verifies the TV → bot7 webhook flow is live + shows recent signals."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            import json as _json
            from pathlib import Path as _Path
            args = (message.text or "").split()[1:]
            n = int(args[0]) if args and args[0].isdigit() else 10
            path = _Path('/Users/alexeychechikov/code/bot7/state/tv_alerts.jsonl')
            if not path.exists():
                self.bot.send_message(chat_id,
                    "📡 TV webhook не получал alerts ещё.\n"
                    "Setup: docs/TV_WEBHOOK_SETUP_2026-05-17.md\n"
                    "Endpoint: /tv/<TOKEN>/alert на порту 8770")
                return
            try:
                lines = path.read_text(encoding='utf-8').splitlines()
            except OSError:
                self.bot.send_message(chat_id, "❌ tv_alerts.jsonl read failed")
                return
            recent = []
            for line in lines[-n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    recent.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
            if not recent:
                self.bot.send_message(chat_id,
                    "📡 TV webhook: журнал пуст (или строки невалидны)")
                return
            out_lines = [f"📡 TV alerts (last {len(recent)} of {len(lines)} total):"]
            for r in recent:
                ts = (r.get('ingest_ts') or '?')[:19]
                p = r.get('payload') or {}
                tkr = p.get('ticker', '?')
                ind = p.get('indicator', '?')
                dir_ = p.get('direction', '?')
                price = p.get('price', '?')
                out_lines.append(f"  {ts}  {tkr:8} {ind:25} {dir_:10} @ {price}")
            self.bot.send_message(chat_id, "\n".join(out_lines))

        @self.bot.message_handler(commands=['bot', 'bots'])
        def handle_bot(message) -> None:
            """/bot <tier> <cmd> — TG-управление managed botом GinArea.
            Commands:
              pause       — set p=False (idempotent)
              resume      — set p=True
              status      — read current params via GinArea API
              history [N] — last N bot_brain proposals for this bot (default 10)
              resize <N>  — multiply maxQ/minQ × N (testbed only)
              tighten <N> — multiply gs × N
              widen <N>   — multiply gs × N
            tier ∈ T1/T2/T3/TB/LONG-D/LONG-V5  (или bot_id)
            /bots — список всех managed bots + статус (no args)."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            import json as _json
            from pathlib import Path as _Path
            ROOT = _Path('/Users/alexeychechikov/code/bot7')
            args = (message.text or "").split()[1:]

            # Load managed bots
            managed_path = ROOT / 'state' / 'short_bots_managed.json'
            try:
                managed = _json.loads(managed_path.read_text(encoding='utf-8'))
                bots = managed.get('managed_bots', [])
            except Exception as e:
                self.bot.send_message(chat_id, f'❌ short_bots_managed.json read failed: {e}')
                return

            # /bots — overview with runtime status + position
            if not args:
                from services.short_bots_guard.control import _build_api
                api, api_err = _build_api()
                lines = ["🤖 Managed bots:"]
                if api is None:
                    lines.append(f"  ⚠ API unavailable: {api_err}")
                    for b in bots:
                        tb = " [TB]" if b.get('testbed') else ""
                        lines.append(f"  {b['tier']:8}{tb}  {b['alias']:30}  id={b['bot_id']}")
                else:
                    status_emoji = {
                        "ACTIVE": "🟢", "PAUSED": "⏸", "FAILED": "🔴",
                        "STARTING": "🟡", "STOPPING": "🟡", "STOPPED": "⚫",
                        "FINISHED": "✅", "TP_STOPPED": "💰", "SL_STOPPED": "🛑",
                        "CREATED": "🆕", "DISABLE_IN": "🟠", "CLOSING": "🟠",
                    }
                    for b in bots:
                        tb = " [TB]" if b.get('testbed') else ""
                        bid = str(b['bot_id'])
                        try:
                            bot_obj = api.get_bot(int(bid))
                            stat = api.get_stat(int(bid))
                            emo = status_emoji.get(bot_obj.status.name, "❓")
                            pos = getattr(stat, 'position', None) or 0
                            profit = getattr(stat, 'currentProfit', None) or getattr(stat, 'current_profit', None) or 0
                            lines.append(
                                f"  {emo} {b['tier']:8}{tb}  {bot_obj.status.name:9}  "
                                f"pos={pos:>+9}  unr=${float(profit):>+7.2f}"
                            )
                        except Exception:
                            lines.append(f"  ❓ {b['tier']:8}{tb}  ERR")
                lines.append("\nUsage:")
                lines.append("  /bot <tier> status    — детали бота")
                lines.append("  /bot <tier> pause     — остановить (PUT /stop)")
                lines.append("  /bot <tier> resume    — запустить (PUT /start)")
                lines.append("  /bot <tier> history   — последние proposals")
                lines.append("  /bot <tier> resize <N> | tighten <N> | widen <N>")
                self.bot.send_message(chat_id, "\n".join(lines))
                return

            tier = args[0]
            cmd = args[1].lower() if len(args) >= 2 else "status"
            extra_arg = args[2] if len(args) >= 3 else None

            # Resolve tier → bot_id (also accept raw bot_id directly)
            bot = None
            for b in bots:
                if str(b.get('tier')).lower() == tier.lower() or str(b.get('bot_id')) == tier:
                    bot = b
                    break
            if bot is None:
                self.bot.send_message(chat_id, f"❌ tier '{tier}' не найден. /bots для списка.")
                return

            bot_id = str(bot['bot_id'])
            is_testbed = bool(bot.get('testbed'))
            tier_label = bot['tier']

            try:
                if cmd == 'status':
                    from services.short_bots_guard.control import get_bot_state
                    st = get_bot_state(bot_id)
                    # Runtime status enum (source of truth) vs config-level p flag
                    rt_status = st.get('status_name') or '?'
                    rt_code = st.get('status')
                    status_emoji = {
                        "ACTIVE": "🟢", "PAUSED": "⏸", "FAILED": "🔴",
                        "STARTING": "🟡", "STOPPING": "🟡", "STOPPED": "⚫",
                        "FINISHED": "✅", "TP_STOPPED": "💰", "SL_STOPPED": "🛑",
                    }.get(rt_status, "❓")
                    msg = (f"🤖 [{tier_label}] {bot.get('alias')}\n"
                           f"  bot_id: {bot_id}\n"
                           f"  testbed: {is_testbed}\n"
                           f"  side: {bot.get('side')}\n"
                           f"  {status_emoji} runtime status: {rt_status}({rt_code})\n"
                           f"  config active (p): {st.get('p')}\n"
                           f"  otcPassed: {st.get('otcPassed')}\n"
                           f"  gs (grid_step): {st.get('gs')}\n")
                    if rt_status == "FAILED":
                        msg += "  ⚠ Бот в FAILED — кликни ▶ Restart в GinArea UI\n"
                    if rt_status == "ACTIVE" and st.get('otcPassed') is False:
                        msg += "  ⚠ otcPassed=False — бот активен но ждёт start condition\n"
                    if st.get('error'):
                        msg += f"  error: {st['error']}\n"
                    self.bot.send_message(chat_id, msg)
                    return

                if cmd == 'history':
                    # Show last N bot_brain proposals + actions for this bot
                    n = int(extra_arg) if extra_arg and extra_arg.isdigit() else 10
                    proposals_path = ROOT / 'state' / 'bot_brain_proposals.jsonl'
                    actions_path = ROOT / 'state' / 'bot_brain_actions.jsonl'
                    lines = [f"📜 [{tier_label}] history (last {n}):"]
                    proposals_for_bot = []
                    if proposals_path.exists():
                        try:
                            with proposals_path.open(encoding='utf-8') as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        rec = _json.loads(line)
                                    except _json.JSONDecodeError:
                                        continue
                                    if str(rec.get('bot_id')) == bot_id:
                                        proposals_for_bot.append(rec)
                        except OSError:
                            pass
                    if not proposals_for_bot:
                        lines.append("  (no proposals yet)")
                    else:
                        for r in proposals_for_bot[-n:]:
                            ts = (r.get('ts') or '?')[:19]
                            rid = r.get('rule_id', '?')
                            act = r.get('action', '?')
                            mode = r.get('mode', '?')
                            status = r.get('result_status', '?')
                            reason = (r.get('reason') or '')[:60]
                            lines.append(f"  {ts}  {rid:30}  {act:10} {mode:8} {status}")
                            if reason:
                                lines.append(f"      └ {reason}")
                    self.bot.send_message(chat_id, "\n".join(lines))
                    return

                if cmd == 'pause':
                    # 2026-05-17 v2: now uses captured proper endpoint
                    # PUT /bots/{id}/stop via control.pause_bot.
                    from services.short_bots_guard.control import pause_bot
                    res = pause_bot(bot_id, dry_run=False,
                                     reason=f"manual TG /bot {tier} pause",
                                     trigger=f"tg_manual:{chat_id}")
                    self.bot.send_message(chat_id, f"⏸ [{tier_label}] pause → {res.get('action')}")
                    return

                if cmd == 'resume':
                    # 2026-05-17 v2: now uses captured proper endpoint
                    # PUT /bots/{id}/start via control.resume_bot.
                    from services.short_bots_guard.control import resume_bot
                    res = resume_bot(bot_id, dry_run=False,
                                      reason=f"manual TG /bot {tier} resume",
                                      trigger=f"tg_manual:{chat_id}")
                    self.bot.send_message(chat_id, f"▶ [{tier_label}] resume → {res.get('action')}")
                    return

                if cmd in ('resize', 'tighten', 'widen'):
                    if extra_arg is None:
                        self.bot.send_message(chat_id, f"Usage: /bot {tier} {cmd} <factor>  (e.g. 0.5 / 0.7 / 1.3)")
                        return
                    try:
                        factor = float(extra_arg)
                    except ValueError:
                        self.bot.send_message(chat_id, f"❌ factor должен быть число: {extra_arg}")
                        return
                    # resize is testbed-only by default; warn for prod
                    if cmd == 'resize' and not is_testbed:
                        self.bot.send_message(chat_id,
                            f"⚠ resize на production bot ({tier_label}) — будет применено LIVE. "
                            f"Подтверди явно через /bot {tier} resize_force {factor}")
                        return
                    from services.bot_brain.actions import dispatch
                    action_name = {"resize": "resize", "tighten": "tighten_grid",
                                    "widen": "widen_grid"}[cmd]
                    res = dispatch(action_name, bot_id, params={"factor": factor},
                                    mode="live",
                                    reason=f"manual TG /bot {tier} {cmd} {factor}",
                                    rule_id=f"tg_manual:{chat_id}")
                    self.bot.send_message(chat_id,
                        f"🔧 [{tier_label}] {cmd} × {factor} → {res.get('status')}\n"
                        f"  details: {res}")
                    return

                if cmd == 'resize_force':
                    if extra_arg is None:
                        self.bot.send_message(chat_id, f"Usage: /bot {tier} resize_force <factor>")
                        return
                    factor = float(extra_arg)
                    from services.bot_brain.actions import dispatch
                    res = dispatch("resize", bot_id, params={"factor": factor},
                                    mode="live",
                                    reason=f"manual TG /bot {tier} resize_force {factor}",
                                    rule_id=f"tg_manual_force:{chat_id}")
                    self.bot.send_message(chat_id,
                        f"🔧 [{tier_label}] resize × {factor} FORCED → {res.get('status')}")
                    return

                self.bot.send_message(chat_id,
                    f"❌ unknown command '{cmd}'. Допустимо: pause/resume/status/resize/tighten/widen.")
            except Exception as e:
                logger.exception("tg.bot_command_failed tier=%s cmd=%s", tier, cmd)
                self.bot.send_message(chat_id, f"❌ {cmd} failed: {e}")

        @self.bot.message_handler(commands=['levels'])
        def handle_levels(message) -> None:
            """/levels — показать текущие уровни VPVR.
            /levels BTCUSD poc=81500 vah=82200 val=80800 [hvn=...] [lvn=...] — обновить.
            /levels clear BTCUSD — очистить.
            Источник: оператор смотрит TV → копирует POC/VAH/VAL → шлёт боту.
            Range Hunter и cascade_alert будут читать эти уровни для snap."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.manual_levels import (
                parse_levels_text, update_levels, clear_symbol,
                format_levels_summary, get_levels,
            )
            text = str(message.text or '').strip()
            # /levels (no args) → show
            args = text.split(maxsplit=2)
            if len(args) < 2:
                self.bot.send_message(chat_id, format_levels_summary("BTCUSD"))
                return
            # /levels clear SYMBOL
            if args[1].lower() == 'clear':
                sym = args[2].upper() if len(args) > 2 else "BTCUSD"
                if clear_symbol(sym):
                    self.bot.send_message(chat_id, f"✓ Уровни {sym} очищены.")
                else:
                    self.bot.send_message(chat_id, f"⚠ {sym} уже отсутствовал.")
                return
            # /levels BTCUSD poc=... vah=... val=...
            body = text.split(maxsplit=1)[1]
            sym, levels = parse_levels_text(body)
            if not levels:
                self.bot.send_message(
                    chat_id,
                    "❌ Не нашёл уровней в команде. Пример:\n"
                    "  /levels BTCUSD poc=81500 vah=82200 val=80800 hvn=82100,81100"
                )
                return
            sym = sym or "BTCUSD"
            entry = update_levels(sym, levels, source="tg_manual")
            self.bot.send_message(
                chat_id,
                f"✓ Сохранено {sym}: {len(levels)} уровн{'я' if len(levels)<5 else 'ей'}.\n\n"
                + format_levels_summary(sym)
            )

        @self.bot.message_handler(commands=['enable'])
        def handle_enable(message) -> None:
            """`/enable <token>` removes from runtime disable list. Does NOT
            touch .env DISABLED_DETECTORS — that's permanent config."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.setup_detector.runtime_disabled import (
                remove_runtime_disabled, list_disabled,
            )
            text = str(message.text or '').strip()
            args = text.split(maxsplit=1)
            if len(args) < 2:
                self.bot.send_message(chat_id, 'Usage: /enable <token>')
                return
            token = args[1].strip()
            removed = remove_runtime_disabled(token)
            d = list_disabled()
            if removed:
                env_still = [t for t in d['env'] if t in token or token in t]
                extra = ""
                if env_still:
                    extra = (f"\n[NOTE] '{token}' is ALSO listed in .env "
                             f"DISABLED_DETECTORS — still disabled there. "
                             f"Edit .env.local to remove permanently.")
                self.bot.send_message(
                    chat_id,
                    f"✓ Removed '{token}' from runtime disable list.{extra}\n"
                    f"Now disabled: env={d['env']}, runtime={d['state_file']}"
                )
            else:
                # Helpful: if token is in env but not runtime, tell operator
                # to edit .env.local — not silently say "not in runtime".
                env_match = [t for t in d['env'] if t in token or token in t]
                if env_match:
                    self.bot.send_message(
                        chat_id,
                        f"[NOTE] '{token}' is in .env DISABLED_DETECTORS "
                        f"({env_match}), not in runtime list.\n"
                        f"To enable: edit .env.local, remove the token from "
                        f"DISABLED_DETECTORS, restart bot."
                    )
                    return
                self.bot.send_message(
                    chat_id, f"'{token}' was not in runtime list. "
                            f"Current: {d['state_file']}"
                )

        @self.bot.message_handler(commands=['cron'])
        def handle_cron(message) -> None:
            """List registered Windows Task Scheduler bot7-* tasks."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.cron_report import build_cron_report
                text = build_cron_report()
            except Exception as exc:
                logger.exception('handle_cron.failed')
                self.bot.send_message(chat_id, f'❌ /cron failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="cron.txt")

        @self.bot.message_handler(commands=['inspect'])
        def handle_inspect(message) -> None:
            """`/inspect [pid]` — process details. Without pid: lists all
            .venv bot7 processes with cpu/mem/age."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.inspect_report import build_inspect_report
            args = str(message.text or "").strip().split(maxsplit=1)
            pid = None
            if len(args) >= 2:
                try:
                    pid = int(args[1].strip())
                except ValueError:
                    self.bot.send_message(chat_id, f"Bad pid: '{args[1]}'")
                    return
            text = build_inspect_report(pid=pid)
            self._send_long_text(chat_id, text, filename="inspect.txt")

        @self.bot.message_handler(commands=['histogram', 'pipeline7d'])
        def handle_histogram(message) -> None:
            """Pipeline 7d daily histogram."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                import subprocess
                import sys as _sys
                from pathlib import Path as _P
                result = subprocess.run(
                    [_sys.executable, "scripts/pipeline_histogram_7d.py"],
                    cwd=str(_P.cwd()), capture_output=True, text=True, timeout=15,
                )
                text = result.stdout or 'No output'
            except Exception as exc:
                logger.exception('handle_histogram.failed')
                self.bot.send_message(chat_id, f'❌ /histogram failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="histogram_7d.txt")

        @self.bot.message_handler(commands=['precision'])
        def handle_precision(message) -> None:
            """Setup precision: per-detector + per-pair status with CI."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                import subprocess
                import sys as _sys
                from pathlib import Path as _P
                result = subprocess.run(
                    [_sys.executable, "scripts/setup_precision_tracker.py"],
                    cwd=str(_P.cwd()), capture_output=True, text=True, timeout=30,
                )
                text = result.stdout or result.stderr or 'No output'
            except Exception as exc:
                logger.exception('handle_precision.failed')
                self.bot.send_message(chat_id, f'❌ /precision failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="precision.txt")

        @self.bot.message_handler(commands=['pipeline'])
        def handle_pipeline(message) -> None:
            """Setup detector pipeline funnel — per-detector yield."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                import subprocess
                import sys as _sys
                from pathlib import Path as _P
                result = subprocess.run(
                    [_sys.executable, "scripts/pipeline_analyzer.py",
                     "--hours", "24"],
                    cwd=str(_P.cwd()), capture_output=True, text=True, timeout=10,
                )
                text = result.stdout or 'No output'
            except Exception as exc:
                logger.exception('handle_pipeline.failed')
                self.bot.send_message(chat_id, f'❌ /pipeline failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="pipeline.txt")

        @self.bot.message_handler(commands=['changelog_archive', 'log_history'])
        def handle_changelog_archive(message) -> None:
            """`/changelog_archive [YYYY-MM-DD]` — show archived day.
            No date → list available archives."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from pathlib import Path as _P
            arch_dir = _P("docs/changelog_archive")
            if not arch_dir.exists():
                self.bot.send_message(chat_id, 'No archive yet.')
                return
            args = str(message.text or '').strip().split(maxsplit=1)
            files = sorted(arch_dir.glob("*.md"))
            if len(args) < 2:
                if not files:
                    self.bot.send_message(chat_id, 'No archive entries.')
                    return
                lst = "\n".join(f"  {f.stem}" for f in files[-30:])
                self.bot.send_message(
                    chat_id,
                    f"Archive (last 30):\n{lst}\n\n"
                    f"Usage: /changelog_archive YYYY-MM-DD"
                )
                return
            target = arch_dir / f"{args[1].strip()}.md"
            if not target.exists():
                self.bot.send_message(chat_id, f"No archive for '{args[1]}'")
                return
            try:
                text = target.read_text(encoding="utf-8")
                if len(text) > 3800:
                    text = text[:3800] + "\n... (truncated)"
            except OSError as exc:
                self.bot.send_message(chat_id, f'❌ read failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['changelog', 'log24'])
        def handle_changelog(message) -> None:
            """Last 24h commits + pipeline summary + GC decisions."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from pathlib import Path as _P
            p = _P("docs/CHANGELOG_DAILY.md")
            if not p.exists():
                self.bot.send_message(chat_id, 'No change log yet — cron fires daily 09:30.')
                return
            try:
                text = p.read_text(encoding="utf-8")
                # Truncate to telegram limit
                if len(text) > 3800:
                    text = text[:3800] + "\n... (truncated)"
            except OSError as exc:
                self.bot.send_message(chat_id, f'❌ /changelog read failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['setups', 'trades'])
        def handle_setups(message) -> None:
            """Подробный список paper-позиций + P-15 legs + свежие сигналы:
            entry/SL/TP/R-R/PnL/action — всё что нужно для ручной сделки."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.setups_report import build_setups_report
                text = build_setups_report()
            except Exception as exc:
                logger.exception('handle_setups.failed')
                self.bot.send_message(chat_id, f'❌ /setups failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="setups.txt")

        @self.bot.message_handler(commands=['audit_filters'])
        def handle_audit_filters(message) -> None:
            """Эффективность paper_trader-фильтров за N дней. /audit_filters [7]"""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = (message.text or "").split()
            days = 7
            if len(parts) > 1:
                try:
                    days = max(1, min(60, int(parts[1])))
                except ValueError:
                    pass
            try:
                from services.paper_trader.audit_report import build_filter_audit
                text = build_filter_audit(days=days)
            except Exception as exc:
                logger.exception('handle_audit_filters.failed')
                self.bot.send_message(chat_id, f'❌ /audit_filters failed: {exc}')
                return
            self.bot.send_message(chat_id, text, parse_mode='Markdown')

        @self.bot.message_handler(commands=['portfolio_summary', 'portfolio'])
        def handle_portfolio_summary(message) -> None:
            """Сводка по активным GinArea live-ботам + прогноз rebate."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.ginarea_api.portfolio_summary import build_portfolio_summary
                text = build_portfolio_summary()
            except Exception as exc:
                logger.exception('handle_portfolio_summary.failed')
                self.bot.send_message(chat_id, f'❌ /portfolio_summary failed: {exc}')
                return
            self.bot.send_message(chat_id, text, parse_mode='Markdown')

        @self.bot.message_handler(commands=['filter_dashboard'])
        def handle_filter_dashboard(message) -> None:
            """Накопительная статистика фильтров paper_trader по дням.
            /filter_dashboard [N=14]"""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = (message.text or "").split()
            days = 14
            if len(parts) > 1:
                try:
                    days = max(1, min(90, int(parts[1])))
                except ValueError:
                    pass
            try:
                from services.paper_trader.filter_dashboard import render_dashboard
                text = render_dashboard(days=days)
            except Exception as exc:
                logger.exception('handle_filter_dashboard.failed')
                self.bot.send_message(chat_id, f'❌ /filter_dashboard failed: {exc}')
                return
            self._send_long_text(chat_id, text, filename="filter_dashboard.txt")

        @self.bot.message_handler(commands=['ginarea', 'bots'])
        def handle_ginarea(message) -> None:
            """Read-only summary of GinArea bot states."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.ginarea_report import build_ginarea_report
                text = build_ginarea_report()
            except Exception as exc:
                logger.exception('handle_ginarea.failed')
                self.bot.send_message(chat_id, f'❌ /ginarea failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['p15'])
        def handle_p15(message) -> None:
            """Detailed P-15 per-leg report with recent equity events."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.p15_report import build_p15_report
                text = build_p15_report()
            except Exception as exc:
                logger.exception('handle_p15.failed')
                self.bot.send_message(chat_id, f'❌ /p15 failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['status'])
        def handle_status(message) -> None:
            """On-demand status snapshot: heartbeat, procs, last setup,
            last GC fire, P-15 open legs, restarts last 1h."""
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.status_report import build_status_report
                text = build_status_report()
            except Exception as exc:
                logger.exception('handle_status.failed')
                self.bot.send_message(chat_id, f'❌ /status failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['audit'])
        def handle_audit(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.advisor.audit_view import build_audit_text
                text = build_audit_text()
            except Exception as exc:
                logger.exception('handle_audit.failed')
                self.bot.send_message(chat_id, f'❌ /audit failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        # ── /report_today, /report_week — manual on-demand reports (TZ-REPORTS 2026-05-08).
        # Same content as the scheduled 21:00 UTC daily/weekly posts but
        # generated for the current moment. Useful for mid-day check-in.
        @self.bot.message_handler(commands=['report_today', 'daily_summary'])
        def handle_report_today(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.advisor.daily_report import build_daily_report
                text = build_daily_report()
            except Exception as exc:
                logger.exception('handle_report_today.failed')
                self.bot.send_message(chat_id, f'❌ /report_today failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        @self.bot.message_handler(commands=['bots_kpi', 'kpi'])
        def handle_bots_kpi(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            # Optional arg: window in days (default 7)
            try:
                parts = (message.text or '').split()
                window = float(parts[1]) if len(parts) > 1 else 7.0
            except (ValueError, IndexError):
                window = 7.0
            try:
                from services.bots_kpi import build_bots_kpi_report
                text = build_bots_kpi_report(window_days=window)
            except Exception as exc:
                logger.exception('handle_bots_kpi.failed')
                self.bot.send_message(chat_id, f'❌ /bots_kpi failed: {exc}')
                return
            self.bot.send_message(chat_id, text, parse_mode='Markdown')

        @self.bot.message_handler(commands=['report_week', 'weekly_summary'])
        def handle_report_week(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.advisor.daily_report import build_weekly_report
                text = build_weekly_report()
            except Exception as exc:
                logger.exception('handle_report_week.failed')
                self.bot.send_message(chat_id, f'❌ /report_week failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        # ── /confirm <token>, /reject <token>, /proposals (TZ-PROPOSE-CONFIRM 2026-05-08).
        # Operator decides whether to open a paper trade based on a high-conviction
        # detector signal. CONFIRMED proposals get tagged operator_confirmed=True
        # in the paper journal so we can later compare confirmed vs raw detector
        # win rates.
        @self.bot.message_handler(commands=['confirm'])
        def handle_confirm(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = (message.text or "").strip().split()
            if len(parts) < 2:
                self.bot.send_message(chat_id, "Использование: /confirm <token>")
                return
            token = parts[1].strip()
            try:
                from services.setup_detector.proposals import confirm_proposal
                ok, msg, proposal = confirm_proposal(token, chat_id)
                self.bot.send_message(chat_id, msg)
                if ok and proposal is not None:
                    # Open paper trade with operator_confirmed=True flag.
                    try:
                        from services.paper_trader.trader import open_paper_trade_from_proposal
                        open_paper_trade_from_proposal(proposal)
                    except Exception:
                        logger.exception("handle_confirm.open_paper_failed token=%s", token)
                        self.bot.send_message(chat_id, "⚠️ Paper trade не открылся (см. логи).")
            except Exception as exc:
                logger.exception("handle_confirm.failed")
                self.bot.send_message(chat_id, f"❌ /confirm failed: {exc}")

        @self.bot.message_handler(commands=['reject'])
        def handle_reject(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = (message.text or "").strip().split()
            if len(parts) < 2:
                self.bot.send_message(chat_id, "Использование: /reject <token>")
                return
            token = parts[1].strip()
            try:
                from services.setup_detector.proposals import reject_proposal
                ok, msg = reject_proposal(token, chat_id)
                self.bot.send_message(chat_id, msg)
            except Exception as exc:
                logger.exception("handle_reject.failed")
                self.bot.send_message(chat_id, f"❌ /reject failed: {exc}")

        @self.bot.message_handler(commands=['proposals'])
        def handle_proposals(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.setup_detector.proposals import list_pending, format_proposal_card, Proposal
                pending = list_pending()
                if not pending:
                    self.bot.send_message(chat_id, "📭 Нет активных proposals.")
                    return
                lines = [f"📋 PENDING PROPOSALS ({len(pending)}):", ""]
                for r in pending:
                    p = Proposal(**{k: v for k, v in r.items() if k in Proposal.__dataclass_fields__})
                    lines.append(format_proposal_card(p))
                    lines.append("─" * 30)
                self.bot.send_message(chat_id, "\n".join(lines))
            except Exception as exc:
                logger.exception("handle_proposals.failed")
                self.bot.send_message(chat_id, f"❌ /proposals failed: {exc}")

        # ── /setups_15m — 15-minute timeframe view for manual trading.
        # Shows live LONG_DIV_BOS_15M / SHORT_DIV_BOS_15M setups + paper-trade
        # performance scoped to those types. Backtest 2026-05-08 walk-forward
        # showed both directions stable PF>=2 across 4 folds.
        @self.bot.message_handler(commands=['setups_15m', 'setups15m', '15m'])
        def handle_setups_15m(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.advisor.setups_15m import build_setups_15m_text
                text = build_setups_15m_text()
            except Exception as exc:
                logger.exception('handle_setups_15m.failed')
                self.bot.send_message(chat_id, f'❌ /setups_15m failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        # ── /morning_brief — executive summary (TZ-MORNING-BRIEF 2026-05-08).
        # Replaces the operator's morning routine of running 5+ commands
        # (advise, momentum_check, regime, status). Surfaces ACTION first,
        # then night events / current state / best setup / calendar.
        @self.bot.message_handler(commands=['morning_brief', 'morning', 'brief'])
        def handle_morning_brief(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            try:
                from services.advisor.morning_brief import build_morning_brief
                text = build_morning_brief()
            except Exception as exc:
                logger.exception('handle_morning_brief.failed')
                self.bot.send_message(chat_id, f'❌ /morning_brief failed: {exc}')
                return
            self.bot.send_message(chat_id, text)

        # ── TZ-D-ADVISOR-V1: /advise ──────────────────────────────────────────

        @self.bot.message_handler(commands=['advise'])
        def handle_advise(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            parts = str(message.text or '').strip().split()
            subcmd = parts[1].lower() if len(parts) > 1 else ''

            # Default `/advise` (без подкоманд) → advisor v2: рынок + сетапы +
            # paper trades, без legacy "ADVISOR v2 — multi-asset / cold start".
            # См. требование оператора 2026-05-07: давать выводы и сетапы.
            if not subcmd:
                try:
                    from services.advisor import build_advisor_v2_text
                    text = build_advisor_v2_text()
                except Exception as exc:
                    logger.exception('handle_advise.v2_failed')
                    self.bot.send_message(chat_id, f'❌ /advise failed: {exc}')
                    return
                self.bot.send_message(chat_id, text)
                return

            # Подкоманды (setups / setup_stats / stats / log) сохраняются для
            # backward compatibility с legacy advisor v0.1.
            try:
                from src.advisor.v2.portfolio import read_portfolio_state
                from src.advisor.v2.size_mode import pick_size_mode
                from src.advisor.v2.cascade import evaluate as advisor_evaluate
                from src.advisor.v2 import dedup as advisor_dedup
                from src.advisor.v2 import telemetry as advisor_telemetry
                from core.pipeline import build_full_snapshot
            except Exception as exc:
                self.bot.send_message(chat_id, f'❌ Advisor (legacy subcmd) недоступен: {exc}')
                return

            if subcmd == 'setups':
                # Active setup_detector setups
                try:
                    from services.setup_detector.storage import SetupStorage
                    store = SetupStorage()
                    active = store.list_active()
                    recent = store.list_recent(hours=24)
                except Exception as exc:
                    self.bot.send_message(chat_id, f'Ошибка setup_detector: {exc}')
                    return
                lines_s = [f'📍 Активные сетапы: {len(active)}', '']
                for s in active:
                    lines_s.append(
                        f'▸ {s.setup_type.value} {s.pair} | '
                        f'Сила {s.strength}/10 | {s.confidence_pct:.0f}% | '
                        f'до {s.expires_at.strftime("%H:%M")} UTC'
                    )
                lines_s.append('')
                lines_s.append(f'За 24ч обнаружено: {len(recent)} сетапов')
                self.bot.send_message(chat_id, '\n'.join(lines_s))
                return

            if subcmd == 'setup_stats':
                # Setup stats from setup_detector
                try:
                    from services.setup_detector.stats_aggregator import compute_setup_stats, format_stats_card
                    stats_sd = compute_setup_stats(lookback_days=7, include_backtest=True)
                    card = format_stats_card(stats_sd)
                except Exception as exc:
                    self.bot.send_message(chat_id, f'Ошибка setup_stats: {exc}')
                    return
                self.bot.send_message(chat_id, card)
                return

            if subcmd == 'stats':
                stats = advisor_telemetry.get_stats()
                by_count = stats.get('by_play_count', {})
                by_out = stats.get('by_play_outcomes', {})
                lines = [f'📊 Advisor stats ({stats.get("days", 7)}д, всего: {stats["total"]})', '']
                all_plays = sorted(set(list(by_count.keys()) + list(by_out.keys())))
                if not all_plays:
                    lines.append('Нет данных в advisor_log.jsonl')
                for pid in all_plays:
                    cnt = by_count.get(pid, 0)
                    out = by_out.get(pid)
                    if out:
                        lines.append(
                            f'  {pid}: {cnt}x рек | hit {out["hit_rate"]:.0f}% (n={out["n"]}) | '
                            f'actual≈${out["mean_actual_pnl"]:.0f} vs exp≈${out["mean_expected_pnl"]:.0f}'
                        )
                    else:
                        lines.append(f'  {pid}: {cnt}x рек | нет outcomes')
                self.bot.send_message(chat_id, '\n'.join(lines))
                return

            if subcmd == 'log':
                entries = advisor_telemetry.get_recent_log(n=5)
                if not entries:
                    self.bot.send_message(chat_id, 'advisor_log.jsonl пуст.')
                    return
                lines = ['📋 Последние рекомендации:', '']
                for e in reversed(entries):
                    lines.append(
                        f"{e.get('ts_utc','?')} | {e.get('play_id','?')} | "
                        f"{e.get('size_mode','?')} | pnl≈${e.get('expected_pnl',0):.0f} | "
                        f"{e.get('trigger','')}"
                    )
                self.bot.send_message(chat_id, '\n'.join(lines)[:3800])
                return

            # Default: run advisor on current snapshot — show all 3 symbols (TZ-035-FIX-1)
            _SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']
            try:
                from src.advisor.v2.feature_writer import read_latest_features as _read_pq
            except Exception:
                _read_pq = None

            try:
                snapshot = build_full_snapshot(symbol='BTCUSDT')
            except Exception as exc:
                self.bot.send_message(chat_id, f'❌ Ошибка получения snapshot: {exc}')
                return

            portfolio = read_portfolio_state()
            size_mode, size_reason = pick_size_mode(portfolio)

            lines = [
                '🧠 *ADVISOR v2 — multi-asset*',
                f'Режим размера: *{size_mode}* ({size_reason})',
                f'Портфель: ${portfolio.depo_total:,.0f} (доступно ${portfolio.depo_available:,.0f}) | '
                f'DD: {portfolio.dd_pct:.1f}% | Margin free: {portfolio.free_margin_pct:.0f}%',
                '',
            ]

            for sym in _SYMBOLS:
                # Resolve live features for price display and cold-start detection
                live = _read_pq(sym) if _read_pq else None
                btc_price = snapshot.get('price') if isinstance(snapshot, dict) else None
                sym_price = (live or {}).get('price') if sym != 'BTCUSDT' else btc_price
                price_str = f'${sym_price:,.2f}' if sym_price else 'н/д'

                features = snapshot if sym == 'BTCUSDT' else {}
                rec = advisor_evaluate(features, portfolio, size_mode, symbol=sym)

                if live is None and rec is None:
                    # No parquet yet — cold start
                    lines.append(f'▸ *{sym}* {price_str} | ⏳ cold start')
                elif rec is None:
                    lines.append(f'▸ *{sym}* {price_str} | ✅ нет сигналов')
                else:
                    already_seen = advisor_dedup.is_duplicate(rec)
                    tag = ' _(уже)_' if already_seen else ''
                    lines += [
                        f'▸ *{sym}* {price_str} | 📌 *{rec.play_id}* {rec.play_name}{tag}',
                        f'  Триггер: {rec.trigger}',
                        f'  Причина: {rec.reason}',
                        f'  Размер: {rec.size_btc:.2f} BTC | Ожид. pnl: ~${rec.expected_pnl:.0f}'
                        f' | Win: {rec.win_rate*100:.0f}% | DD: {rec.dd_pct:.1f}%',
                    ]
                    if rec.params:
                        lines.append(f'  Параметры: {rec.params}')
                    if not already_seen:
                        advisor_dedup.record(rec)
                        advisor_telemetry.log_recommendation(rec, portfolio.balance)
                        ref_price = float(sym_price or btc_price or 0)
                        advisor_telemetry.schedule_outcome_check(rec, ref_price)

            self.bot.send_message(chat_id, '\n'.join(lines), parse_mode='Markdown')

        @self.bot.message_handler(commands=['events'])
        def handle_events(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.decision_log import iter_annotations, iter_events

            parts = str(message.text or "").strip().split()
            subcmd = parts[1].lower() if len(parts) > 1 else "today"
            events = list(iter_events(self._decision_log_events_path()))
            if subcmd == "today":
                today = datetime.now(timezone.utc).date()
                events = [event for event in events if event.ts.astimezone(timezone.utc).date() == today]
            elif subcmd == "pending":
                annotated_ids = {item.event_id for item in iter_annotations(self._decision_log_annotations_path())}
                events = [event for event in events if event.event_id not in annotated_ids]
            if not events:
                self.bot.send_message(chat_id, "Событий не найдено.")
                return
            lines = ["📒 События decision log:", ""]
            for event in events[-10:]:
                lines.append(f"{event.event_id} | {event.event_type.value} | {event.severity.value} | {event.summary}")
            self.bot.send_message(chat_id, "\n".join(lines)[:3800])

        @self.bot.message_handler(commands=['event'])
        def handle_event_details(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.decision_log import format_event_message, iter_events, iter_outcomes

            parts = str(message.text or "").strip().split()
            if len(parts) != 2:
                self.bot.send_message(chat_id, "Формат: /event <event_id>")
                return
            event_id = parts[1]
            event = next((item for item in iter_events(self._decision_log_events_path()) if item.event_id == event_id), None)
            if event is None:
                self.bot.send_message(chat_id, "Событие не найдено.")
                return
            outcomes = [item for item in iter_outcomes(self._decision_log_outcomes_path()) if item.event_id == event_id]
            lines = [format_event_message(event), ""]
            if outcomes:
                lines.append("Outcomes:")
                for outcome in outcomes:
                    lines.append(
                        f"• {outcome.checkpoint_minutes}m | pnl {outcome.delta_pnl_since_event:+.0f} USD | {outcome.delta_pnl_classification}"
                    )
            self.bot.send_message(chat_id, "\n".join(lines)[:3800])

        @self.bot.message_handler(commands=['outcomes'])
        def handle_outcomes(message) -> None:
            chat_id = int(message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён.')
                return
            from services.decision_log import iter_outcomes

            parts = str(message.text or "").strip().split()
            subcmd = parts[1].lower() if len(parts) > 1 else "today"
            outcomes = list(iter_outcomes(self._decision_log_outcomes_path()))
            if subcmd == "today":
                today = datetime.now(timezone.utc).date()
                outcomes = [item for item in outcomes if item.checkpoint_ts.astimezone(timezone.utc).date() == today]
            if not outcomes:
                self.bot.send_message(chat_id, "Outcomes не найдены.")
                return
            lines = ["🧾 Outcomes decision log:", ""]
            for outcome in outcomes[-10:]:
                lines.append(
                    f"{outcome.event_id} | {outcome.checkpoint_minutes}m | {outcome.delta_pnl_since_event:+.0f} USD | {outcome.delta_pnl_classification}"
                )
            self.bot.send_message(chat_id, "\n".join(lines)[:3800])

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("rh_hedge:"))
        def handle_rh_hedge_callback(call) -> None:
            """RH Hedge Advisory inline buttons: [A: Hedged] [B: Closed] [C: Hold]."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, signal_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            valid = {"hedged", "closed", "hold"}
            if action not in valid:
                self.bot.answer_callback_query(call.id, f"⚠ unknown action '{action}'")
                return
            try:
                from services.range_hunter.journal import mark_hedge_action
                ok = mark_hedge_action(signal_id, action)
                if ok:
                    msg = {"hedged": "✅ Записано: hedged",
                            "closed": "✅ Записано: closed leg",
                            "hold": "✅ Записано: hold"}[action]
                else:
                    msg = f"⚠ signal_id {signal_id} не найден"
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("rh_hedge.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("rh:"))
        def handle_range_hunter_callback(call) -> None:
            """Inline-кнопки [✅ Placed both] / [⏭ Skip] для Range Hunter."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, signal_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            try:
                from services.range_hunter.journal import mark_user_action
                ok = mark_user_action(signal_id, "placed" if action == "placed" else "skipped")
                if ok:
                    msg = "✅ Зафиксировано: обе лимитки поставлены" if action == "placed" \
                        else "⏭ Пропущено (для статистики)"
                else:
                    msg = f"⚠ signal_id {signal_id} не найден"
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("range_hunter.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("exit:"))
        def handle_exit_advisor_callback(call) -> None:
            """Exit advisor inline buttons: [A: Hedge] [B: Close 25%] [C: Hold]."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, alert_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            action_map = {"hedge": "hedge_opposite",
                           "close25": "close_25pct",
                           "hold": "monitor"}
            if action not in action_map:
                self.bot.answer_callback_query(call.id, f"⚠ unknown action '{action}'")
                return
            try:
                from services.exit_advisor.decisions_log import log_decision
                scenario_class = alert_id.split("_")[1] if "_" in alert_id else "unknown"
                log_decision(
                    scenario_class=scenario_class,
                    action_taken=action_map[action],
                    snapshot={"alert_id": alert_id, "source": "tg_button"},
                )
                msg = {"hedge": "✅ Logged: hedge",
                        "close25": "✅ Logged: close 25%",
                        "hold": "✅ Logged: hold"}[action]
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("exit_advisor.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("cliff:"))
        def handle_cliff_callback(call) -> None:
            """Cliff monitor inline buttons: [⛔ Pause bot] [✓ Ack]."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, bot_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            if action == "ack":
                self.bot.answer_callback_query(call.id, "✓ Acknowledged")
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
                return
            if action != "pause":
                self.bot.answer_callback_query(call.id, f"⚠ unknown action '{action}'")
                return
            # Pause action: call GinArea pause_bot API
            try:
                from services.short_bots_guard.control import _build_api
                api, err = _build_api()
                if api is None:
                    self.bot.answer_callback_query(call.id, f"⚠ API: {err}")
                    return
                api.pause_bot(int(bot_id))
                self.bot.answer_callback_query(call.id, f"⛔ Bot {bot_id} paused")
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("cliff.callback_pause_failed bot_id=%s", bot_id)
                self.bot.answer_callback_query(call.id, "Ошибка при паузе")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("pc:"))
        def handle_pre_cascade_callback(call) -> None:
            """Inline-кнопки [✅ Placed] / [⏭ Skip] для pre-cascade offensive plan."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, signal_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            try:
                from services.pre_cascade_alert.liq_clustering import mark_user_action
                ok = mark_user_action(signal_id,
                                       "placed" if action == "placed" else "skipped")
                if ok:
                    msg = "✅ Зафиксировано: сделка размещена" if action == "placed" \
                        else "⏭ Пропущено (для статистики)"
                else:
                    msg = f"⚠ signal_id {signal_id} не найден"
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("pre_cascade.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("sb:"))
        def handle_session_breakout_callback(call) -> None:
            """Inline-кнопки [✅ Placed] / [⏭ Skip] для Session Breakout."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, signal_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            try:
                from services.session_breakout.journal import mark_user_action
                ok = mark_user_action(signal_id,
                                       "placed" if action == "placed" else "skipped")
                if ok:
                    msg = "✅ Зафиксировано: сделка размещена" if action == "placed" \
                        else "⏭ Пропущено (для статистики)"
                else:
                    msg = f"⚠ signal_id {signal_id} не найден"
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("session_breakout.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("td:"))
        def handle_twap_defender_callback(call) -> None:
            """Inline-кнопки [✅ Executed] / [⏭ Skip] / [🔕 Mute 1h] для TWAP defender."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, action, alert_id = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            action_map = {"exec": "executed", "skip": "skipped", "mute": "muted"}
            if action not in action_map:
                self.bot.answer_callback_query(call.id, f"⚠ unknown action '{action}'")
                return
            try:
                from services.twap_defender.journal import mark_user_action
                ok = mark_user_action(alert_id, action_map[action])
                if ok:
                    msg = {
                        "exec": "✅ Зафиксировано: контра-trade выполнен",
                        "skip": "⏭ Пропущено (для статистики)",
                        "mute": "🔕 Серия muted на 60 мин",
                    }[action]
                else:
                    msg = f"⚠ alert_id {alert_id} не найден"
                self.bot.answer_callback_query(call.id, msg)
                try:
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                       reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logger.exception("twap_defender.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("brain:"))
        def handle_brain_callback(call) -> None:
            """Bot Brain inline buttons: [✅ Apply] [⏭ Skip] [🚫 Disable rule].

            callback_data format: brain:<verb>:<arg>
              brain:apply:<proposal_id>     — execute proposal action LIVE
              brain:skip:<proposal_id>      — log decision, no action
              brain:disable:<rule_id>       — disable rule via
                                              state/bot_brain_rules_disabled.json

            Proposals saved to state/bot_brain_proposals.jsonl include a
            unique proposal_id field. On Apply we look up the proposal
            and dispatch through services.bot_brain.actions.dispatch().
            On Disable we persist to a JSON set that rules.evaluate_all
            consults before firing."""
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            try:
                _, verb, arg = str(call.data).split(":", 2)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Invalid callback data")
                return
            import json as _json
            from pathlib import Path as _Path
            ROOT = _Path('/Users/alexeychechikov/code/bot7')
            proposals_path = ROOT / 'state' / 'bot_brain_proposals.jsonl'
            disabled_path = ROOT / 'state' / 'bot_brain_rules_disabled.json'

            def _find_proposal(pid: str) -> dict | None:
                if not proposals_path.exists():
                    return None
                try:
                    with proposals_path.open(encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                r = _json.loads(line)
                            except _json.JSONDecodeError:
                                continue
                            if r.get('proposal_id') == pid:
                                return r
                except OSError:
                    pass
                return None

            def _record_decision(record: dict) -> None:
                """Append operator decision to bot_brain_decisions.jsonl."""
                try:
                    decisions_path = ROOT / 'state' / 'bot_brain_decisions.jsonl'
                    decisions_path.parent.mkdir(parents=True, exist_ok=True)
                    with decisions_path.open('a', encoding='utf-8') as f:
                        f.write(_json.dumps(record, ensure_ascii=False) + "\n")
                except OSError:
                    logger.exception("brain.decision_log_failed")

            from datetime import datetime as _dt, timezone as _tz
            now_iso = _dt.now(_tz.utc).isoformat(timespec='seconds')

            try:
                if verb == 'apply':
                    proposal = _find_proposal(arg)
                    if proposal is None:
                        self.bot.answer_callback_query(call.id, f"⚠ proposal {arg} не найден")
                        return
                    # Check if action is currently blocked (e.g. set_params-based
                    # pause is DISABLED until proper endpoint found)
                    action = proposal.get('action')
                    if action in ('pause', 'resume'):
                        self.bot.answer_callback_query(call.id,
                            f"⛔ {action} временно отключён (set_params broken)")
                        _record_decision({"ts": now_iso, "verb": "apply_blocked",
                                          "proposal_id": arg, "action": action,
                                          "chat_id": chat_id})
                        return
                    # Otherwise dispatch via bot_brain.actions
                    from services.bot_brain.actions import dispatch
                    bot_id = proposal.get('bot_id')
                    rule_id = proposal.get('rule_id')
                    params = proposal.get('params') or {}
                    result = dispatch(action, str(bot_id), params=params,
                                       mode='live',
                                       reason=f"manual TG apply by chat {chat_id}",
                                       rule_id=rule_id or 'manual')
                    _record_decision({"ts": now_iso, "verb": "apply", "proposal_id": arg,
                                      "action": action, "bot_id": bot_id,
                                      "result_status": result.get('status'),
                                      "chat_id": chat_id})
                    self.bot.answer_callback_query(call.id,
                        f"✅ Applied: {action} → {result.get('status')}")
                    try:
                        self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                            reply_markup=None)
                    except Exception:
                        pass
                    return

                if verb == 'skip':
                    _record_decision({"ts": now_iso, "verb": "skip",
                                      "proposal_id": arg, "chat_id": chat_id})
                    self.bot.answer_callback_query(call.id, "⏭ Skipped (logged)")
                    try:
                        self.bot.edit_message_reply_markup(chat_id, call.message.message_id,
                                                            reply_markup=None)
                    except Exception:
                        pass
                    return

                if verb == 'disable':
                    # Persist rule_id to disabled set
                    disabled = {"rule_ids": []}
                    if disabled_path.exists():
                        try:
                            disabled = _json.loads(disabled_path.read_text(encoding='utf-8'))
                        except (_json.JSONDecodeError, OSError):
                            pass
                    rule_ids = set(disabled.get('rule_ids', []))
                    rule_ids.add(arg)
                    disabled['rule_ids'] = sorted(rule_ids)
                    disabled['updated_at'] = now_iso
                    try:
                        disabled_path.parent.mkdir(parents=True, exist_ok=True)
                        disabled_path.write_text(
                            _json.dumps(disabled, ensure_ascii=False, indent=2),
                            encoding='utf-8')
                    except OSError:
                        logger.exception("brain.disable_write_failed")
                    _record_decision({"ts": now_iso, "verb": "disable_rule",
                                      "rule_id": arg, "chat_id": chat_id})
                    self.bot.answer_callback_query(call.id,
                        f"🚫 Rule {arg} disabled — see state/bot_brain_rules_disabled.json")
                    return

                self.bot.answer_callback_query(call.id, f"⚠ unknown verb '{verb}'")
            except Exception:
                logger.exception("brain.callback_failed")
                self.bot.answer_callback_query(call.id, "Ошибка")

        @self.bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("decision_log:"))
        def handle_decision_log_callback(call) -> None:
            chat_id = int(call.message.chat.id)
            if not self._is_allowed(chat_id):
                self.bot.answer_callback_query(call.id, "Доступ запрещён.")
                return
            from services.decision_log import handle_callback

            result = handle_callback(
                str(call.data),
                pending_reasons=self._decision_log_pending_reason,
                chat_id=chat_id,
                annotations_path=self._decision_log_annotations_path(),
            )
            self.bot.answer_callback_query(call.id, result.get("message", "ok"))
            try:
                self.bot.send_message(chat_id, result.get("message", "ok"))
            except Exception:
                logger.exception("decision_log.callback_reply_failed")

        @self.bot.message_handler(func=lambda m: True, content_types=['text'])
        def handle_text(message) -> None:
            chat_id = int(message.chat.id)
            text = str(message.text or '').strip()
            if not self._is_allowed(chat_id):
                self.bot.send_message(chat_id, '⛔ Доступ запрещён для этого чата.')
                return
            if not text:
                self.bot.send_message(chat_id, 'Напиши команду или нажми кнопку.', reply_markup=build_main_keyboard())
                return
            if chat_id in self._decision_log_pending_reason:
                from services.decision_log import handle_reason_message

                result = handle_reason_message(
                    chat_id,
                    text,
                    pending_reasons=self._decision_log_pending_reason,
                    annotations_path=self._decision_log_annotations_path(),
                )
                if result is not None:
                    self.bot.send_message(chat_id, result.get("message", "Причина сохранена."))
                    return
            # TV-bridge: если сообщение похоже на TradingView alert с уровнями
            # ("LEVELS BTCUSD poc=... vah=... val=..."), парсим и сохраняем.
            # Регистр-нечувствительно, без команды-префикса.
            text_upper = text.upper()
            if text_upper.startswith("LEVELS ") or text_upper.startswith("TV:LEVELS") or text_upper.startswith("VPVR "):
                try:
                    from services.manual_levels import (
                        parse_levels_text, update_levels, format_levels_summary,
                    )
                    sym, levels = parse_levels_text(text)
                    if levels:
                        sym = sym or "BTCUSD"
                        update_levels(sym, levels, source="tv_tg_bridge")
                        self.bot.send_message(
                            chat_id,
                            f"📊 TV LEVELS получены ({sym}, {len(levels)} полей):\n\n"
                            + format_levels_summary(sym)
                        )
                        return
                except Exception:
                    logger.exception("tv_levels_bridge.parse_failed")
            self._dispatch(chat_id, text)

    def run(self) -> None:
        if getattr(config, 'AUTO_EDGE_ALERTS_ENABLED', True) and self.allowed_chat_ids:
            self.alert_worker.start()
        if self.allowed_chat_ids:
            self.signal_alert_worker.start()
        if self.allowed_chat_ids and not self.decision_log_alert_worker.is_alive():
            self.decision_log_alert_worker.start()
        logger.info('telegram_bot.start config_source=%s allowed_chat_ids=%s', getattr(config, 'CONFIG_SOURCE', ''), self.allowed_chat_ids)
        # Same custom-polling pattern as run_polling_blocking (handles 409 cleanly).
        offset = 0
        consecutive_errors = 0
        while True:
            try:
                updates = self.bot.get_updates(offset=offset, timeout=25, long_polling_timeout=25)
                for upd in updates:
                    offset = upd.update_id + 1
                    try:
                        self.bot.process_new_updates([upd])
                    except Exception:
                        logger.exception('telegram_bot.update_dispatch_failed update_id=%s', upd.update_id)
                consecutive_errors = 0
            except KeyboardInterrupt:
                logger.info('telegram_bot.stopped_by_keyboard')
                raise
            except Exception as exc:
                consecutive_errors += 1
                msg = str(exc)
                if '409' in msg or 'Conflict' in msg:
                    backoff = min(60, 5 * consecutive_errors)
                    logger.warning('telegram_bot.polling_conflict (409); backoff %ds', backoff)
                    time.sleep(backoff)
                else:
                    backoff = min(30, 2 * consecutive_errors)
                    logger.exception('telegram_bot.polling_failed; backoff %ds (consecutive=%d)', backoff, consecutive_errors)
                    time.sleep(backoff)

    def run_polling_blocking(self) -> None:
        if (
            getattr(config, 'AUTO_EDGE_ALERTS_ENABLED', True)
            and self.allowed_chat_ids
            and not self.alert_worker.is_alive()
        ):
            self.alert_worker.start()
        signal_worker = getattr(self, 'signal_alert_worker', None)
        if signal_worker is not None and self.allowed_chat_ids and not signal_worker.is_alive():
            signal_worker.start()
        decision_log_worker = getattr(self, 'decision_log_alert_worker', None)
        if decision_log_worker is not None and self.allowed_chat_ids and not decision_log_worker.is_alive():
            decision_log_worker.start()
        logger.info(
            'telegram_bot.start config_source=%s allowed_chat_ids=%s',
            getattr(config, 'CONFIG_SOURCE', ''),
            self.allowed_chat_ids,
        )
        import time as _time
        # Custom polling loop with explicit 409-Conflict backoff. The library's
        # infinity_polling() spam-loops on Conflict (>100/s) which masks
        # everything else and makes the bot non-responsive. Here we drive
        # get_updates() manually so any error exits cleanly with backoff.
        offset = 0
        consecutive_errors = 0
        while True:
            try:
                updates = self.bot.get_updates(offset=offset, timeout=25, long_polling_timeout=25)
                for upd in updates:
                    offset = upd.update_id + 1
                    try:
                        self.bot.process_new_updates([upd])
                    except Exception:
                        logger.exception('telegram_bot.update_dispatch_failed update_id=%s', upd.update_id)
                consecutive_errors = 0
            except KeyboardInterrupt:
                logger.info('telegram_bot.stopped_by_keyboard')
                raise
            except Exception as exc:
                consecutive_errors += 1
                msg = str(exc)
                if '409' in msg or 'Conflict' in msg:
                    backoff = min(60, 5 * consecutive_errors)
                    logger.warning(
                        'telegram_bot.polling_conflict (409) — likely concurrent poller; backoff %ds',
                        backoff,
                    )
                    _time.sleep(backoff)
                else:
                    backoff = min(30, 2 * consecutive_errors)
                    logger.exception(
                        'telegram_bot.polling_failed; backoff %ds (consecutive=%d)',
                        backoff, consecutive_errors,
                    )
                    _time.sleep(backoff)
