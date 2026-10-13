"""Общая обвязка: поддельная биржа, файлы сетки во временной папке, запуск скрипта как из консоли (runpy, __main__),
код выхода и stdout. Скрипт берёт WeexClient из services.weex_api.client и пути из engine.grid_files — оба
подменяются; ордера ставить/снимать поддельная биржа не даёт (проверочные скрипты — только чтение)."""
from __future__ import annotations

import contextlib
import io
import json
import runpy
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import services.weex_api.client as wc
from services.weex_grid import engine as eg

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "research" / "weex"
DAY_MS = 86_400_000


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def side_state(**kw) -> dict:
    s = eg.new_side_state()
    s.update(kw)
    return s


def trade(tid, oid, pos="SHORT", side="SELL", price=100.0, qty=1.0, at: float | None = None, commission="0") -> dict:
    """Сделка в форме /capi/v3/userTrades; at — epoch секунды."""
    at = time.time() - 3600 if at is None else at
    return {"id": str(tid), "orderId": str(oid), "positionSide": pos, "side": side, "price": str(price),
            "qty": str(qty), "commission": str(commission), "time": int(at * 1000)}


def daily_rows(last_closed_days_ago: int = 1, n: int = 105, drop: int | None = None, rising: bool = True) -> list:
    """Дневки Binance [open_ms, o, h, l, close, v, close_ms]; последняя закрытая — last_closed_days_ago дней назад."""
    today = int(time.time() // 86400)
    days = list(range(today - last_closed_days_ago - n + 1, today - last_closed_days_ago + 1))
    if drop is not None:
        del days[drop]
    rows = []
    for i, d in enumerate(days):
        close = 100.0 + i if rising else 300.0 - i
        rows.append([d * DAY_MS, "0", "0", "0", str(close), "0", (d + 1) * DAY_MS - 1])
    return rows


class FakeClient:
    """trades: список сделок (фильтр по окну), None — биржа вернула null, иное — отдаётся как есть.
    infos: orderId → ответ order_info (Exception — бросить)."""

    def __init__(self, trades=(), infos=None, opens=(), algos=(), positions=(), book=(100.0, 100.0)):
        self.trades = list(trades) if isinstance(trades, (list, tuple)) else trades
        self.infos = infos or {}
        self.opens = list(opens)
        self.algos = list(algos)
        self.positions = list(positions)
        self._book = book
        self.info_calls: list[str] = []

    def sync_time(self):
        return 0

    def book(self, symbol):
        return self._book

    def futures_balance(self):
        return [{"asset": "USDT", "balance": "1", "availableBalance": "1"}]

    def futures_positions(self):
        return self.positions

    def open_orders(self, symbol):
        return list(self.opens)

    def open_algo_orders(self, symbol):
        return list(self.algos)

    def order_info(self, oid):
        self.info_calls.append(str(oid))
        r = self.infos.get(str(oid), {})
        if isinstance(r, Exception):
            raise r
        return r

    def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
        if not isinstance(self.trades, list):
            return self.trades
        rows = [t for t in self.trades if (start_ms is None or int(t["time"]) >= start_ms)
                and (end_ms is None or int(t["time"]) <= end_ms)]
        return rows[:100]

    def _forbidden(self, *a, **k):
        raise AssertionError("проверочный скрипт не должен ставить/снимать ордера")

    place_limit = place_market = place_stop_market = cancel = cancel_algo = _forbidden


def make_grid(tmp_path: Path, monkeypatch, cfg: dict | None = None, st: dict | None = None,
              journal: list | None = None) -> tuple[Path, Path, Path]:
    cp, sp, jp = tmp_path / "cfg.json", tmp_path / "state.json", tmp_path / "journal.jsonl"
    config = {"symbol": "BTCUSDT", "dry_run": False, "enabled": True, "sides": ["LONG"],
              "release_sides": ["SHORT"], **(cfg or {})}
    state = st if st is not None else {"symbol": "BTCUSDT", "LONG": side_state(), "SHORT": side_state(),
                                       "halted": False}
    cp.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    sp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    jp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in (journal or [])), encoding="utf-8")
    monkeypatch.setattr(eg, "GRIDS", ("BTC",))
    monkeypatch.setattr(eg, "grid_files", lambda name: (cp, sp, jp))
    return cp, sp, jp


def run_script(name: str, client: FakeClient, monkeypatch, argv=()) -> tuple[int, str]:
    """Запуск research/weex/<name> как `python <name>`: (код выхода, stdout)."""
    path = SCRIPTS / name
    monkeypatch.setattr(wc, "WeexClient", lambda *a, **k: client)
    monkeypatch.setattr(sys, "argv", [str(path), *argv])
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return code, out.getvalue()
