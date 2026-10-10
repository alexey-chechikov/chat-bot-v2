"""Трендовый бот ETH на WEEX — исполняет сигналы службы services/trend_signals.

Правила (валидированы на 2 годах 4ч баров, tools/trend_state.py; живые сигналы с 08.2026: ETH +3.9%,
XRP +32.4%):
  ВХОД   — пробой 5-дневного экстремума при ADX ≥ 20 (сторона и стоп — из trend_signals_state.json);
  ВЫХОД  — закрытие 4ч свечи за Chandelier-стопом (пик ± 3·ATR) — служба сигналов снимает состояние,
           бот закрывает позицию рыночным ордером. Это ОСНОВНОЙ выход, как в бэктесте;
  АВАРИЙНЫЙ СТОП — условный STOP_MARKET reduceOnly на самой бирже на emergency_buffer_pct дальше
           Chandelier, подтягивается за ним. Срабатывает, только если бот/мак лежат или цена
           проскакивает внутри свечи (известная цена отмены есть всегда).
  РАЗМЕР — риск / расстояние до Chandelier-стопа, не больше max_notional_usd.
  Вход только по СВЕЖЕМУ сигналу (не старше max_entry_age_sec): в старый эпизод не вскакиваем —
  стоп уже подтянут, риск/прибыль другие. Один эпизод — одна сделка: после аварийного стопа в тот же
  эпизод не входим.

Целостность — как у сетки (services/weex_grid): атомарная запись, битый конфиг/учёт → GridHalt, намерение
пишется до отправки (потерянный ответ ищется по clientOrderId), свои ордера — префикс b7t.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from services.weex_grid.engine import (ConfigError, GridHalt, StateCorrupt, atomic_write, fmt_px,  # noqa: F401
                                       round_tick)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "state" / "weex_trend_config.json"
STATE = ROOT / "state" / "weex_trend_state.json"
JOURNAL = ROOT / "state" / "weex_trend_journal.jsonl"
SIGNALS = ROOT / "state" / "trend_signals_state.json"
PREFIX = "b7t"
DIR = {"LONG": 1, "SHORT": -1}
OPEN_SIDE = {"LONG": "BUY", "SHORT": "SELL"}
CLOSE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}
LIVE = {"NEW", "PENDING", "CANCELING", "UNTRIGGERED", "UNACTIVATED", "PARTIALLY_FILLED"}
PENDING_TTL = 120.0
DEFAULT = {
    "enabled": False,               # новые входы; позиция ведётся до выхода и при enabled=false
    "dry_run": True,                # холостой: ордера не отправляются, исполнение по живым ценам
    "symbol": "ETHUSDT",
    "risk_usd": 33.0,               # потеря при выходе по Chandelier-стопу (~1% депозита $3 300)
    "max_notional_usd": 1500.0,     # потолок позиции
    "qty_step": 0.001,
    "price_tick": 0.01,
    "emergency_buffer_pct": 1.5,    # аварийный стоп на бирже — на столько дальше Chandelier
    "max_entry_age_sec": 4 * 3600,  # вход только по сигналу не старше одной 4ч свечи
    "stop_update_min_pct": 0.2,     # переставлять аварийный стоп, если Chandelier сдвинулся на ≥ этого
    "poll_sec": 60,
}


def load_config(path: Path = CONFIG) -> dict:
    path = Path(path)
    if not path.exists():
        atomic_write(path, json.dumps({"_note": "трендовый бот WEEX; enabled/dry_run меняет только оператор",
                                       **DEFAULT}, ensure_ascii=False, indent=1))
        return dict(DEFAULT)
    try:
        return {**DEFAULT, **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError) as exc:
        raise ConfigError(f"конфиг {path.name} не читается: {exc}") from exc


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    atomic_write(path, json.dumps(cfg, ensure_ascii=False, indent=1))


def read_signal(symbol: str, path: Path = SIGNALS) -> tuple[dict | None, bool]:
    """(сигнал по символу или None, файл прочитан). Файл службы сигналов пишется не атомарно —
    нечитаемый файл = «не знаю», бот в этот проход ничего не решает."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, True
    except (OSError, ValueError):
        return None, False
    return data.get(symbol), True


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


class Trend:
    def __init__(self, client, cfg: dict, state_path: Path = STATE, journal_path: Path = JOURNAL,
                 signals_path: Path = SIGNALS, send_fn=None, now_fn=time.time):
        self.c = client
        self.cfg = cfg
        self.state_path = Path(state_path)
        self.journal_path = Path(journal_path)
        self.signals_path = Path(signals_path)
        self.send = send_fn
        self.now = now_fn
        self.st = self._load()

    # ---------- состояние
    def _load(self) -> dict:
        if not self.state_path.exists():
            st = {}
        else:
            try:
                st = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(st, dict):
                    raise ValueError("не объект")
            except (OSError, ValueError) as exc:
                raise StateCorrupt(f"учёт {self.state_path.name} не читается: {exc}") from exc
        if st.get("symbol") and st["symbol"] != self.cfg["symbol"]:
            raise StateCorrupt(f"учёт {self.state_path.name} от {st['symbol']}, а бот {self.cfg['symbol']}")
        st["symbol"] = self.cfg["symbol"]
        for k, v in {"episode": None, "pending": None, "last_episode": None, "realized": 0.0, "fees": 0.0,
                     "n_trades": 0, "n_wins": 0, "seq": 0, "last_tick": 0.0}.items():
            st.setdefault(k, v)
        return st

    def save(self) -> None:
        atomic_write(self.state_path, json.dumps(self.st, ensure_ascii=False, indent=1))

    def _journal(self, rec: dict) -> None:
        rec = {"ts": datetime.fromtimestamp(self.now(), timezone.utc).isoformat(timespec="seconds"),
               "dry": bool(self.cfg["dry_run"]), "symbol": self.cfg["symbol"], **rec}
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _notify(self, text: str) -> None:
        if self.send:
            try:
                self.send(text)
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_trend.send_failed")

    # ---------- помощники
    def _cid(self, kind: str) -> str:
        self.st["seq"] += 1
        return f"{PREFIX}{self.cfg['symbol'][0]}{kind}{int(self.now())}{self.st['seq']}"

    def _step(self) -> float:
        return float(self.cfg["qty_step"])

    def _qty_str(self, q: float) -> str:
        step = self._step()
        dec = max(0, -int(math.floor(math.log10(step) + 1e-9)))
        return f"{math.floor(q / step + 1e-9) * step:.{dec}f}"

    def _emergency(self, side: str, chand: float) -> float:
        d = DIR[side]
        buf = float(self.cfg["emergency_buffer_pct"]) / 100
        return round_tick(chand * (1 - d * buf), float(self.cfg["price_tick"]), up=d < 0)

    def _fee(self, order_id) -> float:
        try:
            return sum(float(t.get("commission") or 0) for t in (self.c.user_trades(self.cfg["symbol"], order_id) or []))
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_trend.trades_failed")
            return 0.0

    def _position(self, side: str) -> float:
        pos = self.c.futures_positions() or []
        return sum(float(p.get("size") or 0) for p in pos
                   if p.get("symbol") == self.cfg["symbol"] and p.get("side") == side)

    def _srv_now(self) -> float:
        return self.now() + float(getattr(self.c, "_offset_ms", 0) or 0) / 1000

    # ---------- постановка с намерением на диске
    def _send(self, kind: str, fn, **kw) -> dict | None:
        """kind: entry / exit / stop. Намерение пишется ДО отправки; исключение = исход неизвестен."""
        cid = self._cid({"entry": "E", "exit": "X", "stop": "S"}[kind])
        self.st["pending"] = {"cid": cid, "kind": kind, "t": self.now(), "srv": self._srv_now(), **{
            k: v for k, v in kw.items() if k in ("trigger", "qty")}}
        self.save()
        try:
            r = fn(cid=cid, **kw)
        except Exception as exc:                                # noqa: BLE001
            logger.warning("weex_trend.send_failed kind=%s err=%s", kind, exc)
            return None
        if not r or not r.get("success", False) or not r.get("orderId"):
            if r and r.get("success"):
                return None                                     # «успех» без номера — исход неизвестен
            self.st["pending"] = None
            self.save()
            logger.warning("weex_trend.rejected kind=%s resp=%s", kind, r)
            return {"rejected": True, "resp": r}
        self.st["pending"] = None
        self.save()
        return {"id": str(r["orderId"]), "cid": cid}

    def _resolve_pending(self) -> bool:
        p = self.st.get("pending")
        if not p:
            return True
        sym = self.cfg["symbol"]
        found = None
        try:
            if p["kind"] == "stop":
                rows = list(self.c.open_algo_orders(sym) or [])
                srv = p.get("srv") or p["t"]
                rows += list(self.c.algo_history(sym, int((srv - 600) * 1000), int((srv + 600) * 1000)) or [])
                o = next((x for x in rows if x.get("clientAlgoId") == p["cid"]), None)
                if o is not None:
                    found = {"id": str(o.get("algoId")), "cid": p["cid"]}
            else:
                srv = p.get("srv") or p["t"]
                rows = list(self.c.open_orders(sym) or [])
                for page in range(5):
                    rows += list(self.c.order_history(sym, limit=100, page=page,
                                                      start_ms=int((srv - 600) * 1000),
                                                      end_ms=int((srv + 600) * 1000)) or [])
                o = next((x for x in rows if x.get("clientOrderId") == p["cid"]), None)
                if o is not None:
                    found = {"id": str(o.get("orderId")), "cid": p["cid"]}
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_trend.pending_lookup_failed")
            return False
        ep = self.st.get("episode")
        if found is None:
            if self.now() - p["t"] < PENDING_TTL:
                return False
            logger.warning("weex_trend.pending_not_found kind=%s cid=%s", p["kind"], p["cid"])
            self.st["pending"] = None
            if p["kind"] == "entry" and ep and ep.get("status") == "opening" and not ep.get("entry_order"):
                self.st["episode"] = None                       # вход не дошёл — эпизод не начался
            self.save()
            return True
        if p["kind"] == "entry" and ep:
            ep["entry_order"] = found
        elif p["kind"] == "exit" and ep:
            ep["exit_order"] = found
        elif p["kind"] == "stop" and ep:
            old = ep.get("stop")
            ep["stop"] = {**found, "trigger": p.get("trigger")}
            if old and old.get("id") != found["id"]:
                self._cancel_algo(old)
        self.st["pending"] = None
        self.save()
        return True

    def _cancel_algo(self, algo: dict | None) -> None:
        if not algo:
            return
        try:
            self.c.cancel_algo(algo["id"])
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_trend.cancel_algo_failed id=%s", algo.get("id"))

    # ---------- проход
    def tick(self) -> None:
        if self.now() - float(self.st.get("last_tick") or 0) < float(self.cfg["poll_sec"]):
            return
        self.st["last_tick"] = self.now()
        sig, ok = read_signal(self.cfg["symbol"], self.signals_path)
        if not ok:
            return                                              # файл сигналов пишется — решим в следующий раз
        if not self._resolve_pending():
            return
        bid, ask = self.c.book(self.cfg["symbol"])
        mid = (bid + ask) / 2
        ep = self.st.get("episode")
        if ep is None:
            self._maybe_open(sig, mid)
        elif ep["status"] == "opening":
            self._on_opening(ep, sig, mid)
        elif ep["status"] == "open":
            self._on_open(ep, sig, mid)
        elif ep["status"] == "closing":
            self._on_closing(ep, mid)
        self.save()

    def _maybe_open(self, sig: dict | None, mid: float) -> None:
        cfg = self.cfg
        if not cfg["enabled"] or not sig or not sig.get("side") or not sig.get("entry_ts"):
            return
        if sig["entry_ts"] == self.st.get("last_episode"):
            return                                              # этот эпизод уже обработан (вход или пропуск)
        side, chand = sig["side"], float(sig["stop"])
        d = DIR[side]
        age = self.now() - _ts(sig["entry_ts"])
        self.st["last_episode"] = sig["entry_ts"]
        if age > float(cfg["max_entry_age_sec"]):
            self._journal({"kind": "пропуск: сигнал старый", "side": side, "age_h": round(age / 3600, 1)})
            return
        dist = d * (mid - chand)
        if dist <= 0:
            self._journal({"kind": "пропуск: цена уже за стопом", "side": side, "mid": mid, "stop": chand})
            return
        qty = min(float(cfg["risk_usd"]) / dist, float(cfg["max_notional_usd"]) / mid)
        free = cfg.get("portfolio_free_usd")                # общий потолок счёта (сетки + тренд)
        if free is not None:
            qty = min(qty, max(float(free), 0.0) / mid)
        q = self._qty_str(qty)
        if float(q) < self._step():
            why = "общий потолок счёта" if free is not None and float(free) / mid < self._step() else "объём меньше минимального"
            self._journal({"kind": f"пропуск: {why}", "side": side, "qty": qty})
            return
        self.st["episode"] = {"status": "opening", "sig_entry_ts": sig["entry_ts"], "side": side, "qty": q,
                              "chand": chand, "t_open": self.now()}
        self.save()
        r = self._send("entry", self.c.place_market, symbol=cfg["symbol"], side=OPEN_SIDE[side],
                       position_side=side, qty=q)
        if r and r.get("rejected"):
            self.st["episode"] = None
            self._journal({"kind": "вход отклонён биржей", "side": side, "resp": r.get("resp")})
            return
        if r:
            self.st["episode"]["entry_order"] = r

    def _on_opening(self, ep: dict, sig: dict | None, mid: float) -> None:
        o = ep.get("entry_order")
        if not o:
            return                                              # ответ потерян — ждёт _resolve_pending
        info = self.c.order_info(o["id"])
        exq = float(info.get("executedQty") or 0)
        if info.get("status") in LIVE:
            return
        if exq < self._step() / 2:
            self.st["episode"] = None
            self._journal({"kind": "вход не исполнился", "side": ep["side"], "status": info.get("status")})
            return
        px = float(info.get("avgPrice") or 0) or mid
        fee = self._fee(o["id"])
        ep.update(status="open", qty=self._qty_str(exq), entry_px=px, entry_fee=fee)
        self.st["fees"] += fee
        self._journal({"kind": "вход", "side": ep["side"], "price": px, "qty": ep["qty"], "fee": fee,
                       "chand": ep["chand"], "order_id": o["id"]})
        risk = abs(px - ep["chand"]) * exq
        self._notify(f"🟢 Тренд {self.cfg['symbol'].replace('USDT', '')} {ep['side']} {ep['qty']} по {px:,.2f} "
                     f"({'холостой' if self.cfg['dry_run'] else 'ЖИВОЙ'}). Отмена — закрытие 4ч за "
                     f"{ep['chand']:,.2f} (риск ${risk:.0f}); аварийный стоп на бирже "
                     f"{self._emergency(ep['side'], ep['chand']):,.2f}.")
        self._place_stop(ep, ep["chand"])

    def _place_stop(self, ep: dict, chand: float) -> None:
        trig = self._emergency(ep["side"], chand)
        r = self._send("stop", self.c.place_stop_market, symbol=self.cfg["symbol"], side=CLOSE_SIDE[ep["side"]],
                       position_side=ep["side"], qty=ep["qty"], trigger=fmt_px(trig, float(self.cfg["price_tick"])))
        if r and not r.get("rejected"):
            old = ep.get("stop")
            ep["stop"] = {**r, "trigger": trig}
            ep["chand"] = chand
            self._cancel_algo(old)                              # новый стоит — старый снимаем
        elif r and r.get("rejected"):
            self._notify(f"⚠️ Тренд {self.cfg['symbol']}: биржа не приняла аварийный стоп {trig:,.2f} — "
                         f"позиция под основным выходом (закрытие 4ч за {chand:,.2f}).")

    def _on_open(self, ep: dict, sig: dict | None, mid: float) -> None:
        side, d, q = ep["side"], DIR[ep["side"]], float(ep["qty"])
        held = self._position(side)
        if held < q - self._step() / 2:
            self._closed_outside(ep, held, mid)                 # аварийный стоп или ручное закрытие
            return
        same = sig and sig.get("entry_ts") == ep["sig_entry_ts"] and sig.get("side") == side
        if not same:                                            # служба сигналов сняла эпизод — основной выход
            ep["status"] = "closing"
            ep["exit_reason"] = "закрытие 4ч за стопом"
            self.save()
            r = self._send("exit", self.c.place_market, symbol=self.cfg["symbol"], side=CLOSE_SIDE[side],
                           position_side=side, qty=ep["qty"], reduce_only=True)
            if r and not r.get("rejected"):
                ep["exit_order"] = r
            elif r and r.get("rejected"):
                ep["status"] = "open"                           # повторим в следующий проход
                self._notify(f"⚠️ Тренд {self.cfg['symbol']}: биржа не приняла закрытие — повторю.")
            return
        chand = float(sig["stop"])                              # трейл: двигаем аварийный стоп только в плюс
        if d * (chand - ep["chand"]) / ep["chand"] * 100 >= float(self.cfg["stop_update_min_pct"]) or not ep.get("stop"):
            self._place_stop(ep, chand)

    def _on_closing(self, ep: dict, mid: float) -> None:
        o = ep.get("exit_order")
        if not o:
            return
        info = self.c.order_info(o["id"])
        if info.get("status") in LIVE:
            return
        exq = float(info.get("executedQty") or 0)
        if exq < self._step() / 2:
            ep["status"] = "open"                               # не исполнилось — следующий проход повторит
            ep.pop("exit_order", None)
            return
        px = float(info.get("avgPrice") or 0) or mid
        self._finish(ep, px, self._fee(o["id"]), ep.get("exit_reason", "выход"))

    def _closed_outside(self, ep: dict, held: float, mid: float) -> None:
        """Позиции на бирже меньше нашей: сработал аварийный стоп (цена из истории условных ордеров)
        либо закрыто вручную (оценка по текущей цене)."""
        px, reason, fee = mid, "закрыто не ботом (оценка по текущей цене)", 0.0
        stop = ep.get("stop")
        if stop:
            try:
                hist = self.c.algo_history(self.cfg["symbol"], int((ep["t_open"] - 60) * 1000),
                                           int((self._srv_now() + 60) * 1000)) or []
            except Exception:                                   # noqa: BLE001
                hist = []
            h = next((x for x in hist if str(x.get("algoId")) == stop["id"]), None)
            if h and (h.get("algoStatus") == "FILLED" or int(h.get("triggerTime") or 0) > 0):
                px = float(h.get("actualPrice") or 0) or float(stop["trigger"])
                reason = "аварийный стоп на бирже"
                if h.get("actualOrderId"):
                    fee = self._fee(h["actualOrderId"])
        self._finish(ep, px, fee, reason, cancel_stop=reason != "аварийный стоп на бирже")

    def _finish(self, ep: dict, px: float, fee: float, reason: str, cancel_stop: bool = True) -> None:
        d, q = DIR[ep["side"]], float(ep["qty"])
        pnl = d * q * (px - ep["entry_px"])
        self.st["realized"] += pnl
        self.st["fees"] += fee
        self.st["n_trades"] += 1
        self.st["n_wins"] += 1 if pnl - fee - float(ep.get("entry_fee") or 0) > 0 else 0
        if cancel_stop:
            self._cancel_algo(ep.get("stop"))
        net = pnl - fee - float(ep.get("entry_fee") or 0)
        self._journal({"kind": "выход", "reason": reason, "side": ep["side"], "price": px, "qty": ep["qty"],
                       "entry": ep["entry_px"], "pnl": pnl, "fee": fee, "net": net})
        self._notify(f"{'✅' if net > 0 else '🛑'} Тренд {self.cfg['symbol'].replace('USDT', '')} {ep['side']} закрыт по "
                     f"{px:,.2f} ({reason}): вход {ep['entry_px']:,.2f}, итог ${net:+.2f}.")
        self.st["episode"] = None

    def card(self, mid: float | None = None) -> str:
        cfg = self.cfg
        if mid is None:
            b, a = self.c.book(cfg["symbol"])
            mid = (b + a) / 2
        mode = "ВЫКЛ" if not cfg["enabled"] else ("ХОЛОСТОЙ" if cfg["dry_run"] else "ЖИВОЙ")
        lines = [f"📈 ТРЕНД {cfg['symbol']} — {mode} · риск ${cfg['risk_usd']:.0f}, потолок ${cfg['max_notional_usd']:,.0f}"]
        ep = self.st.get("episode")
        if ep and ep.get("entry_px"):
            d = DIR[ep["side"]]
            un = d * float(ep["qty"]) * (mid - ep["entry_px"])
            lines.append(f"позиция {ep['side']} {ep['qty']} по {ep['entry_px']:,.2f}, сейчас {mid:,.2f} → ${un:+.2f}; "
                         f"отмена: закрытие 4ч за {ep['chand']:,.2f}, аварийный стоп "
                         f"{(ep.get('stop') or {}).get('trigger', 0):,.2f}")
        elif ep:
            lines.append(f"позиция открывается/закрывается ({ep['status']})")
        else:
            sig, _ = read_signal(cfg["symbol"], self.signals_path)
            if sig:
                lines.append(f"позиции нет; сигнал {sig.get('side')} с {str(sig.get('entry_ts'))[:16]} — старый, жду "
                             f"следующий вход")
            else:
                lines.append("позиции нет; жду сигнал входа (пробой 5 дней при ADX ≥ 20)")
        n, w = self.st["n_trades"], self.st["n_wins"]
        lines.append(f"сделок {n}, в плюсе {w}, итог ${self.st['realized'] - self.st['fees']:+.2f}")
        return "\n".join(lines)


class DryTrendExchange:
    """Имитатор для холостого режима и тестов: рыночный ордер исполняется сразу по лучшей цене стороны
    (комиссия тейкера), условный стоп срабатывает, когда цена его пересекает."""

    def __init__(self, book_fn, symbol: str = "ETHUSDT", taker_fee: float = 0.00048, now_fn=time.time):
        self.book_fn = book_fn
        self.symbol = symbol
        self.fee = taker_fee
        self.now_fn = now_fn
        self.orders: dict[str, dict] = {}
        self.algos: dict[str, dict] = {}
        self.pos = {"LONG": 0.0, "SHORT": 0.0}
        self.trades: dict[str, list] = {}
        self.n = 0

    def _fill(self, oid, side, ps, qty, px, reduce):
        q = float(qty)
        self.pos[ps] += -q if reduce else q
        self.pos[ps] = max(self.pos[ps], 0.0)
        self.orders[oid].update(status="FILLED", executedQty=qty, avgPrice=str(px))
        self.trades[oid] = [{"orderId": oid, "commission": str(q * px * self.fee), "price": str(px), "qty": qty}]

    def book(self, symbol):
        bid, ask = self.book_fn()
        for aid, a in self.algos.items():
            if a["algoStatus"] != "UNTRIGGERED":
                continue
            trig = float(a["triggerPrice"])
            hit = (a["side"] == "SELL" and bid <= trig) or (a["side"] == "BUY" and ask >= trig)
            if hit:
                self.n += 1
                oid = f"dt{self.n}"
                q = min(float(a["quantity"]), self.pos[a["positionSide"]])
                self.orders[oid] = {"clientOrderId": f"algo-{aid}", "status": "NEW"}
                px = bid if a["side"] == "SELL" else ask
                self._fill(oid, a["side"], a["positionSide"], f"{q}", px, True)
                a.update(algoStatus="FILLED", actualOrderId=oid, actualPrice=str(px),
                         triggerTime=int(self.now_fn() * 1000))
        return bid, ask

    def place_market(self, symbol, side, position_side, qty, cid, reduce_only=False):
        bid, ask = self.book_fn()
        self.n += 1
        oid = f"dt{self.n}"
        self.orders[oid] = {"clientOrderId": cid, "side": side, "positionSide": position_side, "origQty": qty,
                            "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": reduce_only,
                            "time": int(self.now_fn() * 1000)}
        self._fill(oid, side, position_side, qty, ask if side == "BUY" else bid, reduce_only)
        return {"success": True, "orderId": oid}

    def place_stop_market(self, symbol, side, position_side, qty, trigger, cid):
        self.n += 1
        aid = f"da{self.n}"
        self.algos[aid] = {"algoId": aid, "clientAlgoId": cid, "side": side, "positionSide": position_side,
                           "quantity": qty, "triggerPrice": trigger, "algoStatus": "UNTRIGGERED",
                           "triggerTime": 0, "createTime": int(self.now_fn() * 1000)}
        return {"success": True, "orderId": aid}

    def open_algo_orders(self, symbol):
        return [a for a in self.algos.values() if a["algoStatus"] == "UNTRIGGERED"]

    def algo_history(self, symbol, start_ms=None, end_ms=None):
        return list(self.algos.values())

    def cancel_algo(self, aid):
        a = self.algos.get(str(aid))
        if a and a["algoStatus"] == "UNTRIGGERED":
            a["algoStatus"] = "CANCELED"
        return {"success": True}

    def order_info(self, oid):
        return {"orderId": oid, **self.orders[str(oid)]}

    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] == "NEW"]

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [{"orderId": k, **v} for k, v in self.orders.items()]
        return rows[page * limit:(page + 1) * limit]

    def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
        return self.trades.get(str(order_id), []) if order_id is not None else []

    def futures_positions(self):
        return [{"symbol": self.symbol, "side": k, "size": f"{v:.6f}"} for k, v in self.pos.items()]
