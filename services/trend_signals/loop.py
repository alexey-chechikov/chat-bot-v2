"""Трендовые сигналы ETH/XRP: вход, стоп-трейл, истощение — в TG + журнал.

Зачем: валидированный на 2 годах эдж (ETH +109% PF 1.68, XRP +113% PF 1.48)
не приносит денег, пока о сигнале никто не знает. Сервис следит и пингует
ТОЛЬКО три события, каждое требует решения оператора:
  🟢 ВХОД      — пробой 5д-экстремума при ADX≥20
  🛑 ВЫХОД     — цена за Chandelier ATR×3 (закрыть/развернуть)
  ⚠️ ИСТОЩЕНИЕ — 3+ из 4 факторов (фиксировать раньше стопа)

Частота по истории: ~3.2 сделки/мес ETH + 3.8 XRP ≈ 7 сигналов входа в
месяц на двоих. Это не спам.

Работают только активы с trend_bot_ok в state/asset_profiles.json
(калибровка tools/calibrate_assets.py). BTC/SOL туда не попали — у них
трендового эджа нет, они остаются грид-активами.

ТЕНЕВОЙ УЧЁТ: журнал state/trend_signals.jsonl пишет вход/выход и считает
PnL сам, без кнопок (урок session_breakout: гейт по user_action убил
статистику 428 сигналов). Через 3 месяца — честный замер факта vs бэктеста.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "state" / "asset_profiles.json"
JOURNAL = ROOT / "state" / "trend_signals.jsonl"
STATE = ROOT / "state" / "trend_signals_state.json"
CONFIG = ROOT / "state" / "trend_signals_config.json"

POLL_INTERVAL_SEC = 900          # 15 мин: сигналы на 4h барах, чаще незачем
DEFAULT_CONFIG = {
    "enabled": True,
    "position_usd": 1500,        # размер позиции для расчёта риска в карточке
    "notify_entry": True,
    "notify_exit": True,
    "notify_exhaustion": True,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config() -> dict:
    out = dict(DEFAULT_CONFIG)
    try:
        out.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("trend_signals.config_read_failed")
    return out


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(d: dict) -> None:
    try:
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except OSError:
        logger.exception("trend_signals.state_write_failed")


def _journal(rec: dict) -> None:
    rec.setdefault("ts", _now())
    try:
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("trend_signals.journal_failed")


def active_assets() -> dict:
    """Активы с подтверждённым трендовым эджем (trend_bot_ok)."""
    try:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("trend_signals.profiles_read_failed")
        return {}
    return {s: p for s, p in (data.get("assets") or {}).items()
            if p.get("trend_bot_ok")}


def format_entry(sym: str, s: dict, prof: dict, pos_usd: float) -> str:
    side = s["pos"]
    stop = s["stop"]
    risk_pct = abs(s["px"] - stop) / s["px"] * 100
    e = prof.get("trend_edge", {})
    return (
        f"🟢 ТРЕНД {side} {sym.replace('USDT', '')} @ {s['px']:,.4f}\n"
        f"  стоп-трейл: {stop:,.4f} (риск {risk_pct:.1f}% = "
        f"−${risk_pct * pos_usd / 100:.0f} при позиции ${pos_usd:,.0f})\n"
        f"  ADX {s['adx']:.0f} · типичная нога {prof.get('leg_move_pct_med')}% / "
        f"{prof.get('leg_days_med')}д\n"
        f"  эдж 2г: {e.get('total_pct')}% PF {e.get('pf')} WR {e.get('wr_pct')}% "
        f"(плюс {e.get('avg_win')}% / минус {e.get('avg_loss')}%)\n"
        f"  стоп подтягивается за ценой — держать до его пробоя"
    )


def format_exit(sym: str, s: dict, rec: dict) -> str:
    entry = rec.get("entry_px")
    side = rec.get("side")
    pnl = (((s["px"] / entry - 1) if side == "LONG" else (1 - s["px"] / entry))
           * 100 if entry else 0)
    return (f"🛑 ВЫХОД {side} {sym.replace('USDT', '')} @ {s['px']:,.4f}\n"
            f"  вход был {entry:,.4f} → результат {pnl:+.1f}%\n"
            f"  стоп-трейл пробит — закрывать (по истории после этого "
            f"~половина случаев = полный разворот)")


def format_exhaustion(sym: str, s: dict, hit: int, checks: list[str],
                      p: float, prof: dict) -> str:
    body = "\n".join(f"     {c}" for c in checks if c.startswith("✔"))
    return (f"⚠️ ИСТОЩЕНИЕ {sym.replace('USDT', '')} @ {s['px']:,.4f} — "
            f"{hit}/4 факторов, P(конец) ≈ {p:.0f}% (база 36%)\n{body}\n"
            f"  дальше: полный разворот {prof.get('after_full_reversal_pct')}%, "
            f"глубокая коррекция {prof.get('after_deep_pct')}%, "
            f"мелкая {prof.get('after_small_pct')}%\n"
            f"  → фиксировать, не дожидаясь стопа")


def tick(send_fn=None) -> int:
    """Один проход по активам. Возвращает число отправленных сигналов."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return 0
    assets = active_assets()
    if not assets:
        return 0

    from tools.trend_state import analyze, exhaustion

    st = _read_state()
    pos_usd = float(cfg.get("position_usd", 1500))
    sent = 0
    for sym, prof in assets.items():
        try:
            s = analyze(sym, prof)
        except Exception:
            logger.exception("trend_signals.analyze_failed %s", sym)
            continue
        if not s:
            continue
        prev = st.get(sym) or {}
        prev_pos = prev.get("side")
        hit, checks, p = exhaustion(s, prof)

        # ── ВХОД: тренда не было → появился
        if s["pos"] and not prev_pos:
            rec = {"side": s["pos"], "entry_px": s["px"],
                   "entry_ts": _now(), "stop": s["stop"], "exh_sent": False}
            st[sym] = rec
            _journal({"event": "ENTRY", "symbol": sym, "side": s["pos"],
                      "px": s["px"], "stop": s["stop"], "adx": s["adx"]})
            if send_fn and cfg.get("notify_entry"):
                try:
                    send_fn(format_entry(sym, s, prof, pos_usd))
                    sent += 1
                except Exception:
                    logger.exception("trend_signals.send_failed %s", sym)

        # ── ВЫХОД: тренд был → пропал
        elif prev_pos and not s["pos"]:
            entry = prev.get("entry_px")
            pnl = ((s["px"] / entry - 1) if prev_pos == "LONG"
                   else (1 - s["px"] / entry)) * 100 if entry else None
            _journal({"event": "EXIT", "symbol": sym, "side": prev_pos,
                      "entry_px": entry, "exit_px": s["px"],
                      "pnl_pct": round(pnl, 2) if pnl is not None else None,
                      "entry_ts": prev.get("entry_ts")})
            if send_fn and cfg.get("notify_exit"):
                try:
                    send_fn(format_exit(sym, s, prev))
                    sent += 1
                except Exception:
                    logger.exception("trend_signals.send_failed %s", sym)
            st.pop(sym, None)

        # ── ИСТОЩЕНИЕ в открытой позиции (один раз на эпизод)
        elif s["pos"] and prev_pos and hit >= 3 and not prev.get("exh_sent"):
            prev["exh_sent"] = True
            st[sym] = prev
            _journal({"event": "EXHAUSTION", "symbol": sym, "side": s["pos"],
                      "px": s["px"], "hits": hit, "p_pct": p})
            if send_fn and cfg.get("notify_exhaustion"):
                try:
                    send_fn(format_exhaustion(sym, s, hit, checks, p, prof))
                    sent += 1
                except Exception:
                    logger.exception("trend_signals.send_failed %s", sym)

        # обновляем стоп в состоянии (трейл едет)
        elif s["pos"] and prev_pos:
            prev["stop"] = s["stop"]
            st[sym] = prev

    _write_state(st)
    return sent


def summarize() -> dict:
    """Факт по журналу: сколько сделок и какой суммарный %."""
    rows = []
    try:
        for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    except OSError:
        return {"n": 0}
    exits = [r for r in rows if r.get("event") == "EXIT"
             and r.get("pnl_pct") is not None]
    if not exits:
        return {"n": 0, "entries": sum(1 for r in rows if r.get("event") == "ENTRY")}
    pnls = [r["pnl_pct"] for r in exits]
    wins = [p for p in pnls if p > 0]
    return {"n": len(exits), "wr_pct": round(len(wins) / len(exits) * 100),
            "total_pct": round(sum(pnls), 1),
            "avg_pct": round(sum(pnls) / len(pnls), 2)}


async def trend_signals_loop(stop_event, *, send_fn=None,
                             interval_sec: int = POLL_INTERVAL_SEC):
    logger.info("trend_signals.start interval=%ds assets=%s",
                interval_sec, list(active_assets()))
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(tick, send_fn)
        except Exception:
            logger.exception("trend_signals.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                   timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("trend_signals.stopped")
