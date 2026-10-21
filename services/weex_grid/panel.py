"""Пульт сеток WEEX в Telegram (21.10, оператор: «кнопки управления ботами — пауза всем, закрыть все позиции, старт
отдельного бота, заранее настроенные шорт-боты, ордер +/− кнопкой»).

Кнопки только формируют те же команды, что /weex (loop.command): своего торгового пути у пульта нет. Опасные действия —
в два нажатия, подтверждение живёт CONFIRM_TTL секунд; «ордер ±» — сразу (каждое нажатие ≈ $50, в пределах /weex set).
«Закрыть» — только лоты ботов (ручные позиции не трогаются, решение оператора 21.10).

callback_data (≤ 64 байт): wx:a:<действие>:<сетка> — нажатие; wx:y:<действие>:<сетка>:<unix> — подтверждено;
wx:n — отмена; wx:r — обновить пульт. Сетка ALL — действие для всех.
Модуль без Telegram и без сети: состояние сеток и цены передаются снаружи (state_fn, price_fn) — проверяется тестами.
"""
from __future__ import annotations

import json
import time

CONFIRM_TTL = 120
PANEL_GRIDS = ("BTC", "ETH", "B34", "B49", "B89", "SB", "SE")
# код: (команда loop.command, подтверждение, вопрос для подтверждения)
ACTIONS = {
    "go": ("go", True, "ЗАПУСТИТЬ ЖИВЫМ"),
    "st": ("stop", True, "поставить на паузу (новые входы снять, тейки оставить)"),
    "cl": ("close", True, "ЗАКРЫТЬ ПО РЫНКУ позиции бота и выключить"),
    "q+": ("qty+", False, ""),
    "q-": ("qty-", False, ""),
    "pa": ("pauseall", True, "поставить на паузу ВСЕ живые сетки (входы снять, тейки оставить)"),
    "ca": ("closeall", True, "ЗАКРЫТЬ ПО РЫНКУ позиции ВСЕХ ботов (ручные не трогаю) и выключить их"),
}


def command_for(action: str, name: str) -> str:
    """Строка для loop.command: «pauseall», «sb go», «btc qty+»…"""
    cmd = ACTIONS[action][0]
    return cmd if name == "ALL" else f"{name.lower()} {cmd}"


def parse(data: str) -> dict | None:
    """Разбор callback_data; чужое или битое — None (кнопка игнорируется)."""
    parts = str(data or "").split(":")
    if len(parts) < 2 or parts[0] != "wx":
        return None
    kind = parts[1]
    if kind in ("n", "r") and len(parts) == 2:
        return {"kind": kind}
    if kind == "a" and len(parts) == 4 and parts[2] in ACTIONS and (parts[3] in PANEL_GRIDS or parts[3] == "ALL"):
        return {"kind": "a", "action": parts[2], "name": parts[3]}
    if kind == "y" and len(parts) == 5 and parts[2] in ACTIONS and (parts[3] in PANEL_GRIDS or parts[3] == "ALL"):
        try:
            ts = int(parts[4])
        except ValueError:
            return None
        return {"kind": "y", "action": parts[2], "name": parts[3], "ts": ts}
    return None


def needs_confirm(action: str) -> bool:
    return ACTIONS[action][1]


def expired(p: dict, now: float) -> bool:
    return not 0 <= now - p["ts"] <= CONFIRM_TTL


def confirm_data(action: str, name: str, now: float) -> str:
    return f"wx:y:{action}:{name}:{int(now)}"


def question(action: str, name: str, info: dict | None) -> str:
    """Текст подтверждения: что именно произойдёт, с параметрами сетки."""
    what = ACTIONS[action][2]
    if name == "ALL":
        return f"Подтверди: {what}?"
    i = info or {}
    side = {"LONG": "лонг", "SHORT": "шорт"}
    sides = "/".join(side.get(s, s) for s in i.get("sides") or [])
    params = (f"{sides} {i.get('symbol', '')} шаг {i.get('step', '?')}% цель {i.get('target', '?')}%, "
              f"ордер {i.get('qty', '?')}, потолок ${float(i.get('cap_usd') or 0):,.0f} / {i.get('max_lots', '?')} ордеров")
    regime = " без режима SMA" if not i.get("regime") else f" режим SMA{i['regime']}"
    return f"Подтверди: {name} — {what}?\n{params}{regime}."


def grid_info(name: str, cfg: dict, st: dict | None) -> dict:
    """Сводка сетки для пульта из конфига и живого учёта (без сети)."""
    lots = {s: len(((st or {}).get(s) or {}).get("lots") or []) for s in ("LONG", "SHORT")}
    return {"name": name, "symbol": cfg.get("symbol", ""), "sides": list(cfg.get("sides") or []),
            "enabled": bool(cfg.get("enabled")), "dry": bool(cfg.get("dry_run")),
            "step": cfg.get("step_pct"), "target": cfg.get("target_pct"), "qty": cfg.get("order_qty"),
            "cap_usd": cfg.get("max_notional_usd"), "max_lots": cfg.get("max_lots_per_side"),
            "regime": int(cfg.get("regime_sma") or 0), "lots": lots,
            "closing": bool(cfg.get("flatten_request")) and any(lots.values()),
            "halted": bool((st or {}).get("halted"))}


def _status(i: dict) -> str:
    if i["halted"]:
        return "🛑 остановлена"
    if i["closing"]:
        return "⛔ закрывается"
    if i["dry"]:
        return "⚪ заряжена (выкл)" if not i["enabled"] else "🧪 холостая"
    return "🟢 ЖИВАЯ" if i["enabled"] else "⏸ пауза"


def build(infos: list[dict], prices: dict) -> tuple[str, list[list[tuple[str, str]]]]:
    """(текст, ряды кнопок [(подпись, callback_data)]) — пульт целиком."""
    side = {"LONG": "лонг", "SHORT": "шорт"}
    lines = ["🎛 Пульт сеток WEEX"]
    rows: list[list[tuple[str, str]]] = [[("⏸ Пауза всем", "wx:a:pa:ALL"), ("⛔ Закрыть позиции ботов", "wx:a:ca:ALL")]]
    for i in infos:
        px = prices.get(i["symbol"])
        usd = f" ≈${float(i['qty']) * px:,.0f}" if px and i.get("qty") else ""
        nl = sum(i["lots"].values())
        lines.append(f"{i['name']} {'/'.join(side.get(s, s) for s in i['sides'])} {i['symbol'].replace('USDT', '')} "
                     f"{i['step']}/{i['target']} · ордер {i['qty']}{usd} · {_status(i)}" + (f" · лотов {nl}" if nl else ""))
        live_on = i["enabled"] and not i["dry"]
        row = [(f"⏸ {i['name']}", f"wx:a:st:{i['name']}") if live_on else (f"▶️ {i['name']}", f"wx:a:go:{i['name']}")]
        if nl or i["closing"]:
            row.append((f"⛔ {i['name']}", f"wx:a:cl:{i['name']}"))
        row += [(f"➖ {i['name']}", f"wx:a:q-:{i['name']}"), (f"➕ {i['name']}", f"wx:a:q+:{i['name']}")]
        rows.append(row)
    rows.append([("🔄 Обновить", "wx:r")])
    lines.append("▶️ — запустить живым · ⏸ — пауза (тейки остаются) · ⛔ — закрыть позиции бота по рынку · ➖/➕ — ордер ≈$50")
    return "\n".join(lines), rows


def collect(state_fn=None, cfg_fn=None) -> list[dict]:
    """Сводки сеток пульта: конфиг — только чтение (peek_config, файл не создаётся), учёт — живой."""
    from services.weex_grid import engine as eg
    from services.weex_grid.loop import run_files
    cfg_fn = cfg_fn or eg.peek_config

    def _st(name):
        p = run_files(name, False)[0]
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except (OSError, ValueError):
            return {"halted": True}
    state_fn = state_fn or _st
    out = []
    for name in PANEL_GRIDS:
        cfg = cfg_fn(name)
        if cfg:
            out.append(grid_info(name, cfg, state_fn(name)))
    return out


def now() -> float:
    return time.time()
