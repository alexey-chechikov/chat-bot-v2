"""Исполнитель сигналов системы и 432 на любой бирже (интерфейс exchange.base).

Каждый шаг: (1) обновить свои заявки по cid; (2) по каждому слоту (system, 432) привести биржу к нужной позиции
движка (strategy.Desired): вход тактикой, добор стоп-ордером, цель шорта под жёлтой лимиткой reduceOnly, аварийный
стоп, выход по сигналу тактикой; (3) сверить позицию счёта со своим учётом; (4) сохранить учёт.

Правила живого ордерного кода (CLAUDE.md):
  * намерение (заявка со статусом SENDING) пишется на диск ДО отправки;
  * Unknown/SENDING — не конечный: новой заявки той же работы нет, пока поиск по cid не дал конечный статус;
  * все заявки в одном реестре (state["orders"]); учёт — из НАКОПЛЕННОГО исполнения каждой заявки (повтор безопасен);
  * учёт сохраняется до записи в журнал; битый конфиг или учёт → Halt.
Позиция эпизода = Σ исполнено (вход, добор) − Σ исполнено (выход, цель, стоп, извне)."""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

from .exchange.base import BUY, FINAL, LONG, SELL, SHORT, Exchange, ExchangeError, Incomplete, OrderReq, Rejected, Unknown
from .strategy import Desired

log = logging.getLogger(__name__)

IN_ROLES = ("entry", "add")
OUT_ROLES = ("exit", "target", "stop", "external")
DONE = frozenset(FINAL | {"ABSENT"})
WAITING = frozenset({"SENDING", "UNKNOWN"})
SLOT_CODE = {"system": "s", "432": "q"}
ROLE_CODE = {"entry": "e", "add": "a", "exit": "x", "target": "t", "stop": "k"}

DEFAULT_CFG = {
    "enabled": False,               # False: новых эпизодов нет, открытые сопровождаются и закрываются по сигналу
    "symbol": "BTCUSDT",
    "slots": ["system", "432"],
    "base_usd": 500.0,              # база: позиция = база × вес движка
    "cap_usd": 1200.0,              # потолок номинала всех эпизодов исполнителя
    "prefix": "b7x",
    "max_signal_age_s": 1800,       # сигнал старше — эпизод пропускается (с сообщением)
    "emergency_pct": 12.0,          # аварийный стоп от средней входа (за 3 года худший ход против: 10.6% / 9.5%)
    "add_follow_signal": True,      # движок засчитал добор, а стоп на бирже не сработал → добрать рыночным
    "unknown_grace_s": 120,         # заявка с потерянным ответом и «нет такой» дольше — считается не вставшей
    "allowed_sides": ["LONG", "SHORT"],  # WEEX: BTC SHORT передан оператору (release_sides) — там только ["LONG"]
    "max_rejects": 3,               # столько отказов биржи подряд на одну роль — роль встаёт, сообщение
    "entry": {"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20},
    "exit": {"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20},
}
TACTICS = ("market", "chase", "limit")


class Halt(RuntimeError):
    """Битый конфиг или учёт — исполнитель стоит, пока человек не разберётся."""


def validate_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(DEFAULT_CFG))
    for k, v in cfg.items():
        if k.startswith("_"):
            continue
        if k not in DEFAULT_CFG:
            raise Halt(f"конфиг: неизвестный ключ {k!r}")
        out[k] = v
    try:
        assert isinstance(out["enabled"], bool)
        assert isinstance(out["symbol"], str) and out["symbol"]
        assert set(out["slots"]) <= {"system", "432"} and out["slots"]
        for k in ("base_usd", "cap_usd", "emergency_pct", "max_signal_age_s", "unknown_grace_s"):
            assert isinstance(out[k], (int, float)) and math.isfinite(out[k]) and out[k] > 0, k
        assert 1.0 <= out["emergency_pct"] <= 50.0
        assert out["prefix"].isalnum() and 1 <= len(out["prefix"]) <= 6
        assert out["allowed_sides"] and set(out["allowed_sides"]) <= {LONG, SHORT}, "allowed_sides"
        assert isinstance(out["max_rejects"], int) and 1 <= out["max_rejects"] <= 20, "max_rejects"
        for k in ("entry", "exit"):
            t = out[k]
            assert t["kind"] in TACTICS, f"{k}.kind"
            for kk in ("wait_s", "reprice_s", "max_orders"):
                assert isinstance(t.get(kk, 1), (int, float)) and t.get(kk, 1) >= 0, f"{k}.{kk}"
    except AssertionError as e:
        raise Halt(f"конфиг: неверное значение {e}") from None
    return out


class Executor:
    def __init__(self, ex: Exchange, cfg: dict, state_path: Path, journal_path: Path, notify=None):
        self.ex = ex
        self.cfg = validate_config(cfg)
        self.sym = self.cfg["symbol"]
        self.inst = ex.instrument(self.sym)
        self.state_path, self.journal_path = Path(state_path), Path(journal_path)
        self.notify = notify or (lambda text: None)
        self.st = self._load()

    # ------------------------------------------------------------------ учёт
    def _load(self) -> dict:
        if not self.state_path.exists():
            if self.journal_path.exists() and self.journal_path.stat().st_size > 0:
                # журнал есть, учёта нет — учёт пропал: на бирже могут стоять наши заявки и позиция, начинать с нуля нельзя
                raise Halt(f"учёт {self.state_path} пропал при живом журнале {self.journal_path} — разобрать руками")
            return {"version": 1, "seq": 0, "orders": {}, "slots": {s: {"ep": None, "done": []} for s in ("system", "432")}, "audit_bad": 0}
        try:
            st = json.loads(self.state_path.read_text())
            assert st.get("version") == 1 and isinstance(st["orders"], dict) and isinstance(st["slots"], dict)
            for s in ("system", "432"):
                st["slots"].setdefault(s, {"ep": None, "done": []})
            return st
        except Exception as e:  # noqa: BLE001
            raise Halt(f"учёт {self.state_path}: {e!r}") from None

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, ensure_ascii=False, indent=1))
        tmp.replace(self.state_path)

    def _jr(self, rec: dict) -> None:
        rec = {"ts": round(self.ex.now(), 3), **rec}
        with open(self.journal_path, "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _say(self, text: str) -> None:
        try:
            self.notify(text)
        except Exception:  # noqa: BLE001 — сообщение не должно ломать исполнение
            log.exception("sigexec.notify_failed")

    # ------------------------------------------------------------------ заявки
    def _cid(self, slot: str, role: str) -> str:
        self.st["seq"] += 1
        return f"{self.cfg['prefix']}{SLOT_CODE[slot]}{ROLE_CODE[role]}{_b36(self.st['seq'])}{_b36(int(self.ex.now()) % 36 ** 5)}"

    def _orders(self, ep: dict, roles=None, live_only=False) -> list[dict]:
        out = [r for r in self.st["orders"].values() if r["ep"] == ep["id"] and (roles is None or r["role"] in roles)]
        return [r for r in out if r["status"] not in DONE] if live_only else out

    def _filled(self, ep: dict, roles) -> float:
        return sum(r["filled"] for r in self._orders(ep, roles))

    def qty(self, ep: dict) -> float:
        return round(self._filled(ep, IN_ROLES) - self._filled(ep, OUT_ROLES), 12)

    def _avg(self, ep: dict, roles) -> float:
        rs = [r for r in self._orders(ep, roles) if r["filled"] > 0]
        q = sum(r["filled"] for r in rs)
        return sum(r["filled"] * r["avg"] for r in rs) / q if q else 0.0

    def _send(self, ep: dict, role: str, kind: str, side: str, qty: float, price: float | None = None, trigger: float | None = None,
              post_only: bool = False, reduce_only: bool = False) -> dict:
        req = OrderReq(cid=self._cid(ep["slot"], role), symbol=self.sym, side=side, pos_side=ep["pos_side"], kind=kind, qty=qty,
                       price=price, trigger=trigger, post_only=post_only, reduce_only=reduce_only)
        rec = {"cid": req.cid, "ep": ep["id"], "role": role, "kind": kind, "side": side, "qty": qty, "price": price, "trigger": trigger,
               "status": "SENDING", "filled": 0.0, "avg": 0.0, "fee": 0.0, "oid": "", "t_sent": self.ex.now(), "t_done": None}
        self.st["orders"][req.cid] = rec
        self.save()                                     # намерение на диск до отправки
        try:
            self._apply(rec, self.ex.place(req))
        except Rejected as e:
            rec.update(status="REJECTED", t_done=self.ex.now(), note=str(e)[:200])
        except (Unknown, ExchangeError, OSError) as e:
            rec.update(status="UNKNOWN", note=str(e)[:200])
        self.save()
        self._jr({"kind": "заявка", "cid": rec["cid"], "slot": ep["slot"], "role": role, "type": kind, "side": side, "qty": qty, "price": price,
                  "trigger": trigger, "status": rec["status"], "note": rec.get("note")})
        return rec

    def _apply(self, rec: dict, info) -> None:
        if info is None:
            return
        if info.filled + 1e-12 < rec["filled"]:
            raise Halt(f"заявка {rec['cid']}: исполнено уменьшилось {rec['filled']} → {info.filled}")
        rec.update(status=info.status, filled=float(info.filled), avg=float(info.avg or rec["avg"]), fee=float(info.fee), oid=info.oid or rec["oid"])
        if not info.fee_known:
            rec["fee_incomplete"] = True
        if info.final and rec["t_done"] is None:
            rec["t_done"] = self.ex.now()

    def _refresh(self, rec: dict) -> None:
        if rec["status"] in DONE:
            return
        try:
            info = self.ex.order(self.sym, rec["cid"], rec["kind"], rec.get("oid", ""), rec["t_sent"])
        except (Incomplete, Unknown, ExchangeError, OSError) as e:
            rec["last_lookup_error"] = str(e)[:200]
            return
        if info is None:
            if rec["status"] in WAITING and self.ex.now() - rec["t_sent"] > self.cfg["unknown_grace_s"]:
                rec.update(status="ABSENT", t_done=self.ex.now())   # биржа точно не знает заявку — не встала
                self.save()                                          # учёт до журнала
                self._jr({"kind": "заявка не встала", "cid": rec["cid"], "role": rec["role"]})
            return
        self._apply(rec, info)

    def _cancel(self, rec: dict) -> None:
        if rec["status"] in DONE or rec["status"] in WAITING:
            return
        if rec.get("cancel_sent") and self.ex.now() - rec["cancel_sent"] < 5:
            return
        rec["cancel_sent"] = self.ex.now()
        try:
            self.ex.cancel(self.sym, rec["cid"], rec["kind"], rec.get("oid", ""))
        except (Unknown, ExchangeError, OSError) as e:
            rec["cancel_error"] = str(e)[:200]
        self._refresh(rec)

    # ------------------------------------------------------------------ шаг
    def step(self, desired: dict | None, events: list[dict] | None = None) -> None:
        """desired: {слот: Desired|None} по свежим данным; None — данные несвежие: новых входов и выходов по сигналу нет,
        защита и начатые работы продолжаются."""
        for rec in list(self.st["orders"].values()):
            self._refresh(rec)
        for slot in self.cfg["slots"]:
            d = desired.get(slot) if desired is not None else None
            try:
                self._slot(slot, d, desired is not None, events or [])
            except Halt:
                raise
            except Exception as e:  # noqa: BLE001 — один слот не должен ронять второй
                log.exception("sigexec.slot_failed slot=%s", slot)
                self._jr({"kind": "ошибка", "slot": slot, "error": repr(e)[:300]})
        self._audit()
        self._gc()
        self.save()

    def _slot(self, slot: str, d: Desired | None, fresh: bool, events: list[dict]) -> None:
        S = self.st["slots"][slot]
        ep = S["ep"]
        if ep is None:
            if not (fresh and d and self.cfg["enabled"]) or d.entry_t in S["done"]:
                return
            ep = self._start(slot, d)
            if ep is None:
                return
        if fresh and ep["phase"] in ("entering", "open") and (d is None or d.entry_t != ep["entry_t"]):
            ex_ev = next((e for e in events if e["slot"] == slot and e["kind"] == "выход" and e["entry_t"] == ep["entry_t"]), None)
            gone = ep["phase"] == "open" and self.qty(ep) <= self.inst.lot / 2
            head = "на бирже уже закрыто (цель или стоп), движок: " if gone else "сигнал выхода: "
            self._to_exit(ep, head + (ex_ev["why"] if ex_ev else "позиции нет"), ex_ev)
        if ep["phase"] == "entering":
            if self._work(ep, "entry", lambda: ep["goal_main"] - self._filled(ep, ("entry",)), self._open_side(ep), False, self.cfg["entry"]):
                ep["phase"] = "open"
                self._opened(ep)
        if ep["phase"] == "open":
            if self.qty(ep) <= self.inst.lot / 2 and not self._orders(ep, IN_ROLES, live_only=True):
                self._to_exit(ep, "позиция закрыта стопом, целью или извне", None)
            else:
                self._protect(ep, d if (fresh and d and d.entry_t == ep["entry_t"]) else None)
        if ep["phase"] == "exiting":
            self._exiting(ep)

    def _start(self, slot: str, d: Desired) -> dict | None:
        S = self.st["slots"][slot]
        now = self.ex.now()
        if now - d.entry_t > self.cfg["max_signal_age_s"]:
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": f"старше {self.cfg['max_signal_age_s']} с"})
            self._say(f"⚠️ {slot}: вход {d.tag} {d.sig_px:.0f} пропущен — сигнал старше {int((now - d.entry_t) // 60)} мин")
            return None
        side = LONG if d.side > 0 else SHORT
        if side not in self.cfg["allowed_sides"]:
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": f"сторона {side} не разрешена конфигом"})
            self._say(f"ℹ️ {slot}: {d.tag} {d.sig_px:.0f} не исполняю — сторона {side} не разрешена (allowed_sides)")
            return None
        base = float(self.cfg["base_usd"])
        goal = self.inst.floor_qty(base * d.main_frac / d.sig_px)
        add = self.inst.floor_qty(base * d.add_frac / d.add_lv) if d.add_lv else 0.0
        # занято = позиции эпизодов + всё, что ещё может исполниться на вход (входы, доборы, неясные постановки)
        used = sum(self.qty(e) * (self._avg(e, IN_ROLES) or e["sig_px"]) + self._live_in_notional(e) + self._pending_add_notional(e)
                   for e in (self.st["slots"][s]["ep"] for s in self.st["slots"]) if e)
        room = float(self.cfg["cap_usd"]) - used
        if goal * d.sig_px + add * (d.add_lv or 0.0) > room:
            add = 0.0                                      # сначала без добора
            if goal * d.sig_px > room:
                goal = self.inst.floor_qty(max(room, 0.0) / d.sig_px)
        if goal < self.inst.min_qty:
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": f"объём {goal} меньше минимума или нет места под потолком (свободно ${room:.0f})"})
            self._say(f"⚠️ {slot}: вход {d.tag} пропущен — нет места под потолком (свободно ${room:.0f})")
            return None
        ep = {"id": f"{slot}:{d.entry_t}", "slot": slot, "entry_t": d.entry_t, "side": d.side, "tag": d.tag, "pos_side": LONG if d.side > 0 else SHORT,
              "w": d.w, "sig_px": d.sig_px, "goal_main": goal, "goal_add": add if add >= self.inst.min_qty else 0.0, "add_lv": d.add_lv,
              "phase": "entering", "work": None, "t_start": now, "exit_reason": None, "exit_sig_px": None, "engine_res": None}
        S["ep"] = ep
        self.save()
        self._jr({"kind": "эпизод", "slot": slot, "entry_t": d.entry_t, "side": d.side, "tag": d.tag, "sig_px": d.sig_px, "goal_main": goal,
                  "goal_add": ep["goal_add"], "w": d.w, "delay_s": round(now - d.entry_t, 1)})
        return ep

    def _live_in_notional(self, ep: dict) -> float:
        return sum((r["qty"] - r["filled"]) * (r["price"] or r["trigger"] or ep["sig_px"]) for r in self._orders(ep, IN_ROLES, live_only=True))

    def _pending_add_notional(self, ep: dict) -> float:
        """Добор, который ещё может встать (стоп не выставлен или ждёт решения движка) — место держится заранее."""
        if not ep.get("goal_add") or ep.get("add_closed") or ep["phase"] == "exiting":
            return 0.0
        done = self._filled(ep, ("add",)) + sum(r["qty"] - r["filled"] for r in self._orders(ep, ("add",), live_only=True))
        return max(ep["goal_add"] - done, 0.0) * (ep.get("add_lv") or ep["sig_px"])

    def _rejected(self, ep: dict, role: str, kinds: tuple | None = None) -> int:
        """Отказы биржи подряд по роли (с последней заявки, которая встала или исполнилась). kinds — учитывать только эти
        типы (у тактики догона отказ post-only при пересечении стакана — норма, считаются только рыночные)."""
        n = 0
        rs = [r for r in self._orders(ep, (role,)) if kinds is None or r["kind"] in kinds]
        for r in sorted(rs, key=lambda r: r["t_sent"], reverse=True):
            if r["status"] in ("REJECTED", "ABSENT") and not r["filled"]:
                n += 1
            else:
                break
        return n

    def _blocked(self, ep: dict, role: str, kinds: tuple | None = None) -> bool:
        """Роль встала после max_rejects отказов подряд — без бесконечных повторов; сообщение раз в час."""
        n = self._rejected(ep, role, kinds)
        if n < self.cfg["max_rejects"]:
            return False
        last = ep.setdefault("alerts", {}).get(role, 0)
        if self.ex.now() - last > 3600:
            ep["alerts"][role] = self.ex.now()
            note = next((r.get("note") for r in sorted(self._orders(ep, (role,)), key=lambda r: -r["t_sent"]) if r.get("note")), "")
            self._jr({"kind": "роль встала", "slot": ep["slot"], "role": role, "rejects": n, "note": note})
            what = {"stop": "АВАРИЙНОГО СТОПА НЕТ", "exit": "ВЫХОД НЕ ИСПОЛНЯЕТСЯ", "entry": "вход отменён", "add": "добора не будет",
                    "target": "цели на бирже нет"}.get(role, role)
            self._say(f"⛔ {ep['slot']} {ep['tag']}: биржа {n} раз отказала ({role}) — {what}. {note}"[:400])
        return True

    def _open_side(self, ep: dict) -> str:
        return BUY if ep["side"] > 0 else SELL

    def _close_side(self, ep: dict) -> str:
        return SELL if ep["side"] > 0 else BUY

    def _to_exit(self, ep: dict, why: str, ev: dict | None) -> None:
        ep.update(phase="exiting", exit_reason=why, work=None, t_exit=self.ex.now())
        if ev:
            ep.update(exit_sig_px=ev["px"], engine_res=ev.get("res"), exit_sig_t=ev["t"])
        self._jr({"kind": "выход начат", "slot": ep["slot"], "entry_t": ep["entry_t"], "why": why, "qty": self.qty(ep)})

    # ------------------------------------------------------------------ тактики
    def _work(self, ep: dict, role: str, remaining_fn, side: str, reduce: bool, tac: dict) -> bool:
        """Довести работу (вход, выход, рыночный добор) до конца: True — сделано. Одна живая заявка на работу за раз."""
        w = ep.get("work")
        now = self.ex.now()
        if not w or w["role"] != role:
            w = ep["work"] = {"role": role, "t0": now, "n": 0, "cur": None}
        cur = self.st["orders"].get(w["cur"]) if w["cur"] else None
        if cur and cur["status"] not in DONE:
            if cur["status"] in WAITING:
                return False                               # исход неизвестен — ждём поиска, новой заявки нет
            if cur["kind"] == "LIMIT":
                too_long = now - w["t0"] >= tac.get("wait_s", 0)
                stale = tac["kind"] == "chase" and now - cur["t_sent"] >= tac.get("reprice_s", 20) and self._off_best(cur)
                if too_long or stale:
                    self._cancel(cur)
            return False
        rem = remaining_fn()
        q = self.inst.floor_qty(rem)
        if q < self.inst.min_qty:
            if rem > self.inst.lot / 2:
                self._jr({"kind": "остаток меньше минимума", "slot": ep["slot"], "role": role, "qty": rem})
            ep["work"] = None
            return True
        market = tac["kind"] == "market" or now - w["t0"] >= tac.get("wait_s", 0) or w["n"] >= tac.get("max_orders", 20)
        if market and self._blocked(ep, role, ("MARKET",)):
            if role == "entry":                            # вход не берётся (маржа, лимиты) — эпизод закрываем тем, что налилось
                self._to_exit(ep, f"вход: биржа {self._rejected(ep, role, ('MARKET',))} раз отказала", None)
                return False
            if role == "add":
                ep["add_closed"] = True
                ep["work"] = None
                return True
            last = max(r["t_sent"] for r in self._orders(ep, (role,)))
            if now - last < 60:                            # выход: повтор раз в минуту, сообщение раз в час
                return False
        if market:
            rec = self._send(ep, role, "MARKET", side, q, reduce_only=reduce)
        else:
            bid, ask = self.ex.book(self.sym)
            px = bid if side == BUY else ask
            if tac["kind"] == "limit":                     # лучше сигнала на offset б.п., не через стакан
                ref = ep["sig_px"] if role == "entry" else (ep.get("exit_sig_px") or px)
                off = tac.get("offset_bps", 0) / 10000
                px = min(px, ref * (1 - off)) if side == BUY else max(px, ref * (1 + off))
            px = self.inst.round_px(px, "down" if side == BUY else "up")
            rec = self._send(ep, role, "LIMIT", side, q, price=px, post_only=True, reduce_only=reduce)
        w["n"] += 1
        w["cur"] = rec["cid"]
        return False

    def _off_best(self, rec: dict) -> bool:
        try:
            bid, ask = self.ex.book(self.sym)
        except Exception:  # noqa: BLE001
            return False
        best = bid if rec["side"] == BUY else ask
        return abs(best - rec["price"]) >= self.inst.tick / 2

    # ------------------------------------------------------------------ защита открытого эпизода
    def _protect(self, ep: dict, d: Desired | None) -> None:
        q = self.qty(ep)
        cs = self._close_side(ep)
        # добор
        if ep["goal_add"] > 0:
            got = self._filled(ep, ("add",))
            live = self._orders(ep, ("add",), live_only=True)
            waiting = any(r["status"] in WAITING for r in live)
            if got >= ep["goal_add"] - self.inst.lot / 2 or ep.get("add_closed"):
                pass
            elif d is not None and d.add_done and self.cfg["add_follow_signal"]:
                stops = [r for r in live if r["kind"] == "STOP"]
                if stops:
                    for r in stops:
                        self._cancel(r)
                elif not waiting:
                    if self._work(ep, "add", lambda: ep["goal_add"] - self._filled(ep, ("add",)), self._open_side(ep), False, {"kind": "market"}):
                        ep["add_closed"] = True
            elif not live and ep["add_lv"] and not self._blocked(ep, "add", ("STOP",)):
                bid, ask = self.ex.book(self.sym)
                trg = self.inst.round_px(ep["add_lv"], "up" if ep["side"] > 0 else "down")
                beyond = (ep["side"] > 0 and ask >= trg) or (ep["side"] < 0 and bid <= trg)
                if not beyond:                             # цена уже за уровнем — ждём решения движка на закрытии часа
                    self._send(ep, "add", "STOP", self._open_side(ep), ep["goal_add"], trigger=trg)
        q = self.qty(ep)
        # аварийный стоп на весь объём эпизода
        stops = self._orders(ep, ("stop",), live_only=True)
        avg = self._avg(ep, IN_ROLES) or ep["sig_px"]
        trg = self.inst.round_px(avg * (1 - ep["side"] * self.cfg["emergency_pct"] / 100), "down" if ep["side"] > 0 else "up")
        if stops:
            for r in stops:
                if r["status"] not in WAITING and (abs(r["qty"] - q) > self.inst.lot / 2 or abs((r["trigger"] or 0) - trg) > max(self.inst.tick, trg * 0.002)):
                    self._cancel(r)
        elif q >= self.inst.min_qty:
            bid, ask = self.ex.book(self.sym)
            if (ep["side"] > 0 and bid <= trg) or (ep["side"] < 0 and ask >= trg):
                # аварийный уровень уже пройден (стоп снят на замене, пропуск, гэп) — стоп встал бы сразу: выходим сами
                self._to_exit(ep, f"аварийный уровень {trg:.1f} пройден, стопа на бирже нет", None)
                return
            if not self._blocked(ep, "stop", ("STOP",)):
                self._send(ep, "stop", "STOP", cs, self.inst.floor_qty(q), trigger=trg, reduce_only=True)
        # цель шорта под жёлтой
        tg = self._orders(ep, ("target",), live_only=True)
        want = self.inst.round_px(d.target, "up" if ep["side"] < 0 else "down") if (d is not None and d.target) else None
        if tg:
            for r in tg:
                if r["status"] in WAITING:
                    continue
                if want is None or abs(r["price"] - want) >= self.inst.tick / 2 or abs(r["qty"] - (r["filled"] + q)) > self.inst.lot / 2:
                    self._cancel(r)
        elif want is not None and q >= self.inst.min_qty and not self._blocked(ep, "target", ("LIMIT",)):
            self._send(ep, "target", "LIMIT", cs, self.inst.floor_qty(q), price=want, reduce_only=True)

    # ------------------------------------------------------------------ выход
    def _exiting(self, ep: dict) -> None:
        live_other = [r for r in self._orders(ep, live_only=True) if r["role"] != "exit"]
        for r in live_other:
            self._cancel(r)
        if [r for r in self._orders(ep, live_only=True) if r["role"] != "exit"]:
            return                                         # ждём, пока стопы, цель и вход станут конечными
        q = self.qty(ep)
        if q > self.inst.lot / 2:
            self._work(ep, "exit", lambda: self.qty(ep), self._close_side(ep), True, self.cfg["exit"])
            return
        if self._orders(ep, live_only=True):
            return
        self._finish(ep)

    def _opened(self, ep: dict) -> None:
        avg, q = self._avg(ep, ("entry",)), self._filled(ep, ("entry",))
        slip = ep["side"] * (avg / ep["sig_px"] - 1) * 10000 if avg else 0.0
        fee = sum(r["fee"] for r in self._orders(ep, ("entry",)))
        self._jr({"kind": "вход исполнен", "slot": ep["slot"], "entry_t": ep["entry_t"], "qty": q, "avg": avg, "sig_px": ep["sig_px"], "slip_bps": round(slip, 2),
                  "fee": fee, "delay_s": round(self.ex.now() - ep["entry_t"], 1)})
        self._say(f"{'🟢' if ep['side'] > 0 else '🔴'} {ep['slot']} {ep['tag']}: вход {q:g} по {avg:.1f} (сигнал {ep['sig_px']:.1f}, {slip:+.1f} б.п.), "
                  f"комиссия ${fee:.2f}, через {int(self.ex.now() - ep['entry_t'])} с после закрытия 4ч")

    def _finish(self, ep: dict) -> None:
        S = self.st["slots"][ep["slot"]]
        ins, outs = self._orders(ep, IN_ROLES), self._orders(ep, OUT_ROLES)
        v_in = sum(r["filled"] * r["avg"] for r in ins)
        v_out = sum(r["filled"] * r["avg"] for r in outs)
        fee = sum(r["fee"] for r in ins + outs)
        q_in = sum(r["filled"] for r in ins)
        pnl = ep["side"] * (v_out - v_in) - fee
        rec = {"kind": "сделка", "slot": ep["slot"], "entry_t": ep["entry_t"], "tag": ep["tag"], "side": ep["side"], "qty": q_in,
               "avg_in": v_in / q_in if q_in else None, "avg_out": v_out / q_in if q_in else None, "sig_in": ep["sig_px"], "sig_out": ep.get("exit_sig_px"),
               "fee": round(fee, 4), "pnl_usd": round(pnl, 4), "engine_res_pct": ep.get("engine_res"),
               "engine_usd": round(ep["engine_res"] / 100 * self.cfg["base_usd"], 4) if ep.get("engine_res") is not None else None,
               "why": ep.get("exit_reason"), "fee_incomplete": any(r.get("fee_incomplete") for r in ins + outs),
               "orders": [r["cid"] for r in ins + outs]}
        S["done"] = (S["done"] + [ep["entry_t"]])[-50:]
        S["ep"] = None
        self.save()                                         # учёт до журнала
        self._jr(rec)
        if q_in > 0:
            eng = f", движок {rec['engine_usd']:+.2f}$" if rec["engine_usd"] is not None else ""
            self._say(f"⚪ {ep['slot']} {ep['tag']} закрыт: {pnl:+.2f}$ (комиссии ${fee:.2f}){eng} — {ep.get('exit_reason')}")

    # ------------------------------------------------------------------ сверка и уборка
    def _audit(self) -> None:
        """Позиция счёта меньше своего учёта два прохода подряд — кто-то закрыл наши контракты: учёт уменьшается
        записью «извне» по текущей цене, сообщение. Больше — чужие сделки (ручные, другие боты): не наше дело."""
        if not getattr(self.ex, "hedge", True):
            return
        eps = [S["ep"] for S in self.st["slots"].values() if S["ep"]]
        if not eps or any(r["status"] in WAITING for r in self.st["orders"].values()):
            return
        try:
            pos = self.ex.position(self.sym)
        except Exception:  # noqa: BLE001
            return
        bad = False
        for side in (LONG, SHORT):
            own = sum(self.qty(e) for e in eps if e["pos_side"] == side)
            short = own - float(pos.get(side, 0.0))
            if short > self.inst.lot / 2:
                bad = True
                if self.st.get("audit_bad", 0) >= 1:
                    self._external(eps, side, short)
        self.st["audit_bad"] = self.st.get("audit_bad", 0) + 1 if bad else 0

    def _external(self, eps: list[dict], side: str, short: float) -> None:
        bid, ask = self.ex.book(self.sym)
        px = (bid + ask) / 2
        for ep in sorted((e for e in eps if e["pos_side"] == side), key=lambda e: -self.qty(e)):
            take = min(short, self.qty(ep))
            if take <= 0:
                continue
            cid = f"ext{ep['slot'][0]}{_b36(self.st['seq'] + 1)}"
            self.st["seq"] += 1
            self.st["orders"][cid] = {"cid": cid, "ep": ep["id"], "role": "external", "kind": "EXTERNAL", "side": self._close_side(ep), "qty": take, "price": px,
                                      "trigger": None, "status": "FILLED", "filled": take, "avg": px, "fee": 0.0, "oid": "", "t_sent": self.ex.now(),
                                      "t_done": self.ex.now()}
            short -= take
            self._jr({"kind": "закрыто извне", "slot": ep["slot"], "qty": take, "px": px})
            self._say(f"⚠️ {ep['slot']}: на бирже {side} меньше учёта на {take:g} — закрыто не мной, учёт уменьшен по {px:.1f}")
        self.st["audit_bad"] = 0

    def _gc(self) -> None:
        """Конечные заявки закрытых эпизодов старше суток — из реестра (журнал хранит всё)."""
        live_eps = {S["ep"]["id"] for S in self.st["slots"].values() if S["ep"]}
        now = self.ex.now()
        for cid in [c for c, r in self.st["orders"].items() if r["ep"] not in live_eps and r["status"] in DONE and now - (r["t_done"] or now) > 86400]:
            del self.st["orders"][cid]

    # ------------------------------------------------------------------ команды
    def close_all(self, why: str = "команда: закрыть всё") -> None:
        for S in self.st["slots"].values():
            if S["ep"] and S["ep"]["phase"] != "exiting":
                self._to_exit(S["ep"], why, None)
        self.save()

    def status(self) -> dict:
        out = {}
        for slot, S in self.st["slots"].items():
            ep = S["ep"]
            if not ep:
                out[slot] = None
                continue
            out[slot] = {"phase": ep["phase"], "side": ep["side"], "tag": ep["tag"], "qty": self.qty(ep), "avg": self._avg(ep, IN_ROLES), "sig_px": ep["sig_px"],
                         "live": [(r["role"], r["kind"], r["price"] or r["trigger"], r["status"]) for r in self._orders(ep, live_only=True)]}
        return out


def _b36(n: int) -> str:
    s, n = "", int(n)
    while True:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
        if n == 0:
            return s


def now_s() -> float:
    return time.time()
