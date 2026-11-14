"""Исполнитель сигналов системы и 432 на любой бирже (интерфейс exchange.base).

Каждый шаг: (1) обновить свои заявки по cid; (2) по каждому слоту (system, 432) привести биржу к нужной позиции
движка (strategy.Desired): вход тактикой, добор стоп-ордером, цель шорта под жёлтой лимиткой reduceOnly, аварийный
стоп, выход по сигналу тактикой; (3) сверить позицию счёта со своим учётом; (4) сохранить учёт.

Правила живого ордерного кода (CLAUDE.md) и разбор GPT aadc2a4:
  * намерение (заявка SENDING) пишется на диск ДО отправки; один процесс на учёт (блокировка файла);
  * незавершённая заявка ищется в РЕЕСТРЕ по эпизоду и роли, а не в памяти процесса — после падения процесса новая
    копия не отправит вторую заявку той же работы (P1-1);
  * SENDING / UNKNOWN / UNRESOLVED — не конечные. Рыночная заявка, которую биржа «не знает» дольше grace, считается
    не вставшей (ABSENT), только если позиция счёта на этой стороне изменилась ровно на наши известные исполнения;
    иначе — UNRESOLVED: работа стоит, сообщение оператору (вопрос 2 разбора). Лимит и стоп в ABSENT ещё час
    перепроверяются — нашлась заявка, её исполнения идут в учёт;
  * исполнение аварийного стопа, пройденный аварийный уровень и закрытие позиции извне переводят эпизод в выход:
    увеличения нет, добор и цель снимаются, остаток — рыночным сразу (P1-3, P1-4); стоп стоит и во время входа;
  * потолок cap_usd: бронь = позиция + недобранный вход + недобранный добор до конца работы; каждая увеличивающая
    заявка пересчитывается по текущей цене стакана (P1-5); добор ставится на остаток goal_add − исполнено;
  * учёт по накопленному исполнению каждой заявки; учёт сохраняется до журнала; битый конфиг или учёт → Halt.
Позиция эпизода = Σ исполнено (вход, добор) − Σ исполнено (выход, цель, стоп, извне)."""
from __future__ import annotations

import fcntl
import re
import json
import logging
import math
import time
from pathlib import Path

from .exchange.base import BUY, FINAL, LONG, SELL, SHORT, Exchange, ExchangeError, Incomplete, OrderReq, Rejected, Unknown
from .strategy import Desired

log = logging.getLogger(__name__)

IN_ROLES = ("entry", "add")
OUT_ROLES = ("exit", "target", "stop", "external", "trim")
DONE = frozenset(FINAL | {"ABSENT"})
WAITING = frozenset({"SENDING", "UNKNOWN", "UNRESOLVED"})
SLOT_CODE = {"system": "s", "432": "q"}
SLOT_RE = re.compile(r"^(system|432|432w[0-9]{2})$")


def slot_code(slot: str) -> str:
    """Код слота в cid: system → s, 432 → q, часть ансамбля 432wNN → qNN."""
    return SLOT_CODE.get(slot) or ("q" + slot[4:])
ROLE_CODE = {"entry": "e", "add": "a", "exit": "x", "target": "t", "stop": "k", "trim": "r"}
MARKET_TAC = {"kind": "market"}

DEFAULT_CFG = {
    "enabled": False,               # False: новых эпизодов нет, открытые сопровождаются и закрываются по сигналу
    "symbol": "BTCUSDT",
    "slots": ["system", "432"],
    "base_usd": 500.0,              # база: позиция = база × вес движка (× усиление 432, strategy.boost_432)
    "cap_usd": 1200.0,              # потолок номинала всех эпизодов (позиции + брони входа и добора), по цене исполнения
    "prefix": "b7x",
    "max_signal_age_s": 1800,       # сигнал старше — эпизод пропускается (с сообщением)
    "emergency_pct": 12.0,          # аварийный стоп от средней входа (за 3 года худший ход против: 10.6% / 9.5%)
    "add_follow_signal": True,      # движок засчитал добор, а стоп на бирже не сработал → добрать рыночным
    "unknown_grace_s": 180,         # заявка с потерянным ответом и «нет такой» дольше — решение ABSENT / UNRESOLVED
    "absent_recheck_s": 3600,       # лимит/стоп в ABSENT ещё столько перепроверяется
    "shared_account": False,        # True — на счёте чужие сделки (WEEX: сетки, ручные): потерянный рыночный → UNRESOLVED
    "allowed_sides": ["LONG", "SHORT"],  # WEEX: BTC SHORT передан оператору (release_sides) — там только ["LONG"]
    "max_rejects": 3,               # столько отказов биржи подряд на одну роль — пауза роли, сообщение раз в час
    "reject_backoff_s": 600,        # пауза роли после max_rejects отказов; потом одна новая попытка (стоп без паузы навсегда не остаётся)
    "entry": {"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20},
    "exit": {"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20},
    # Страховка лонг-сеток (14.11, research/grid_hedge_20261114, оператор «готовь код и давай на ревью GPT»):
    # sizing="hedge" — шорт системы размером hedge_k × HEDGE_LEG × позиция лонг-сеток счёта в $ (exposure() на входе
    # эпизода) на входе и столько же на доборе; вес движка и усиление 432 не применяются — как в замере. Только шорт и
    # только слот system; цель под жёлтой не ставится (use_target=false): выход по сигналу движка на закрытии часа, как в
    # замере, и на общем счёте нет второй reduceOnly рядом с аварийным стопом.
    "sizing": "base",
    "hedge_k": 1.0,
    "use_target": True,
    # добор стоп-ордером на бирже заранее (True) или только по сигналу движка рыночным (False). Страховка — False (разбор
    # ead2ca4: аварийный стоп закрыл шорт, а висящий стоп добора открыл его снова до следующего прохода; в замере добор —
    # по закрытию часа добора)
    "add_resting": True,
    # страховка на общей стороне (разбор GPT b056816): новый эпизод — только когда на стороне нет чужого объёма (ручных
    # шортов). В режиме COMBINED код не может гарантировать сохранность ручного объёма при гонках стопа и проходов
    "require_empty_side": False,
}
TACTICS = ("market", "chase", "limit")
SIZINGS = ("base", "hedge")
HEDGE_LEG = 0.5                     # доля страховки на вход и на добор (замер: 0.5 + 0.5 позиции сеток)
HEDGE_MIN_USD = 1.0                 # позиция сеток меньше — страховать нечего
TRIM_CHECK_S = 60.0                 # как часто сверять страховку с текущими лонгами (разбор ead2ca4)
TRIM_TOL = 0.05                     # урезать, если шорт больше предела больше чем на 5%


class Halt(RuntimeError):
    """Битый конфиг или учёт, второй экземпляр — исполнитель стоит, пока человек не разберётся."""


def validate_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(DEFAULT_CFG))
    for k, v in cfg.items():
        if k.startswith("_"):
            continue
        if k not in DEFAULT_CFG:
            raise Halt(f"конфиг: неизвестный ключ {k!r}")
        out[k] = v
    try:
        assert isinstance(out["enabled"], bool) and isinstance(out["shared_account"], bool)
        assert isinstance(out["symbol"], str) and out["symbol"]
        assert out["slots"] and all(isinstance(s, str) and SLOT_RE.match(s) for s in out["slots"]) and len(set(out["slots"])) == len(out["slots"]), "slots"
        for k in ("base_usd", "cap_usd", "emergency_pct", "max_signal_age_s", "unknown_grace_s", "absent_recheck_s", "reject_backoff_s"):
            assert isinstance(out[k], (int, float)) and math.isfinite(out[k]) and out[k] > 0, k
        assert 1.0 <= out["emergency_pct"] <= 50.0
        assert out["unknown_grace_s"] >= 60, "unknown_grace_s"
        assert out["prefix"].isalnum() and 1 <= len(out["prefix"]) <= 6
        assert out["allowed_sides"] and set(out["allowed_sides"]) <= {LONG, SHORT}, "allowed_sides"
        assert isinstance(out["max_rejects"], int) and 1 <= out["max_rejects"] <= 20, "max_rejects"
        for k in ("entry", "exit"):
            t = out[k]
            assert t["kind"] in TACTICS, f"{k}.kind"
            for kk in ("wait_s", "reprice_s", "max_orders", "offset_bps"):
                assert isinstance(t.get(kk, 1), (int, float)) and t.get(kk, 1) >= 0, f"{k}.{kk}"
        assert out["sizing"] in SIZINGS, "sizing"
        assert isinstance(out["use_target"], bool), "use_target"
        assert isinstance(out["add_resting"], bool) and isinstance(out["add_follow_signal"], bool), "add_resting / add_follow_signal"
        assert isinstance(out["require_empty_side"], bool), "require_empty_side"
        k = out["hedge_k"]
        assert isinstance(k, (int, float)) and not isinstance(k, bool) and math.isfinite(k) and 0 < k <= 2.0, "hedge_k (0; 2]"
        if out["sizing"] == "hedge":
            assert out["allowed_sides"] == [SHORT], "страховка: allowed_sides только [\"SHORT\"]"
            assert out["slots"] == ["system"], "страховка: slots только [\"system\"] (у 432 шортов нет)"
            assert out["use_target"] is False, "страховка: use_target=false (выход по сигналу, как в замере)"
            assert out["add_resting"] is False and out["add_follow_signal"] is True, "страховка: добор только по сигналу (add_resting=false)"
            assert out["exit"]["kind"] == "market", "страховка: выход рыночный (разбор ead2ca4: догон лимиткой держит шорт на росте)"
    except AssertionError as e:
        raise Halt(f"конфиг: неверное значение {e}") from None
    return out


class Executor:
    def __init__(self, ex: Exchange, cfg: dict, state_path: Path, journal_path: Path, notify=None, exposure=None):
        """exposure — для sizing="hedge": функция без аргументов → позиция лонг-сеток счёта в $ (services/sigexec/hedge.py);
        исключение или негодное число = «неизвестно» (не ноль): эпизод не начинается, повтор на следующем проходе."""
        self.ex = ex
        self.cfg = validate_config(cfg)
        if self.cfg["sizing"] == "hedge" and exposure is None:
            raise Halt("страховка: нет источника позиции сеток (exposure)")
        self.exposure = exposure
        self._doubt = {LONG: False, SHORT: False}      # сторона не сходится с учётом (общий счёт) — без увеличений
        self._side_pos: dict[str, float] = {}           # позиция стороны на начале прохода (_guard)
        self.block_increase = None                      # причина (str): увеличения запрещены снаружи (Runner: живая SB)
        self.sym = self.cfg["symbol"]
        self.state_path, self.journal_path = Path(state_path), Path(journal_path)
        self.notify = notify or (lambda text: None)
        self._lock_fd = self._lock()
        self.inst = ex.instrument(self.sym)
        self.st = self._load()

    # ------------------------------------------------------------------ один процесс на учёт
    def _lock(self):
        p = self.state_path.with_suffix(".lock")
        fd = open(p, "a+")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            raise Halt(f"учёт {self.state_path} уже ведёт другой процесс (блокировка {p})") from None
        return fd

    def close(self) -> None:
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            finally:
                self._lock_fd.close()
                self._lock_fd = None

    # ------------------------------------------------------------------ учёт
    def _load(self) -> dict:
        if not self.state_path.exists():
            if self.journal_path.exists() and self.journal_path.stat().st_size > 0:
                # журнал есть, учёта нет — учёт пропал: на бирже могут стоять наши заявки и позиция, начинать с нуля нельзя
                raise Halt(f"учёт {self.state_path} пропал при живом журнале {self.journal_path} — разобрать руками")
            return {"version": 1, "seq": 0, "orders": {}, "slots": {s: {"ep": None, "done": []} for s in self.cfg["slots"]},
                    "audit_bad": {LONG: 0, SHORT: 0}, "closing": False}
        try:
            st = json.loads(self.state_path.read_text())
            assert st.get("version") == 1 and isinstance(st["orders"], dict) and isinstance(st["slots"], dict)
            for s in self.cfg["slots"]:
                st["slots"].setdefault(s, {"ep": None, "done": []})
            if not isinstance(st.get("audit_bad"), dict):
                st["audit_bad"] = {LONG: 0, SHORT: 0}
            st.setdefault("closing", False)
        except Exception as e:  # noqa: BLE001
            raise Halt(f"учёт {self.state_path}: {e!r}") from None
        orphan = [s for s, S in st["slots"].items() if S.get("ep") and s not in self.cfg["slots"]]
        if orphan:
            # слот убран из конфига при открытом эпизоде — позиция осталась бы без стопа и выхода
            raise Halt(f"в учёте открыты эпизоды слотов {orphan}, а в конфиге их нет — вернуть слоты или закрыть эпизоды")
        return st

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
        return f"{self.cfg['prefix']}{slot_code(slot)}{ROLE_CODE[role]}{_b36(self.st['seq'])}{_b36(int(self.ex.now()) % 36 ** 5)}"

    def _eps(self) -> list[dict]:
        return [S["ep"] for S in self.st["slots"].values() if S["ep"]]

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

    def _side_own(self, pos_side: str) -> float:
        return sum(self.qty(e) for e in self._eps() if e["pos_side"] == pos_side)

    def _send(self, ep: dict, role: str, kind: str, side: str, qty: float, price: float | None = None, trigger: float | None = None,
              post_only: bool = False, reduce_only: bool = False) -> dict:
        req = OrderReq(cid=self._cid(ep["slot"], role), symbol=self.sym, side=side, pos_side=ep["pos_side"], kind=kind, qty=qty,
                       price=price, trigger=trigger, post_only=post_only, reduce_only=reduce_only)
        rec = {"cid": req.cid, "ep": ep["id"], "role": role, "kind": kind, "side": side, "pos_side": ep["pos_side"], "qty": qty, "price": price,
               "trigger": trigger, "status": "SENDING", "filled": 0.0, "avg": 0.0, "fee": 0.0, "oid": "", "t_sent": self.ex.now(), "t_done": None}
        if kind == "MARKET":                            # снимок для решения о потерянном ответе (вопрос 2 разбора)
            rec["own_before"] = self._side_own(ep["pos_side"])
            try:
                rec["pos_before"] = float(self.ex.position(self.sym).get(ep["pos_side"], 0.0))
            except Exception:  # noqa: BLE001
                rec["pos_before"] = None
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
        st, now = rec["status"], self.ex.now()
        if st in FINAL:
            return
        if st == "ABSENT":                              # лимит/стоп «не встал» — ещё час проверяем, не нашёлся ли
            if rec["kind"] == "MARKET" or now - (rec["t_done"] or now) > self.cfg["absent_recheck_s"] or now - rec.get("t_recheck", 0) < 60:
                return
            rec["t_recheck"] = now
        try:
            info = self.ex.order(self.sym, rec["cid"], rec["kind"], rec.get("oid", ""), rec["t_sent"])
        except (Incomplete, Unknown, ExchangeError, OSError) as e:
            rec["last_lookup_error"] = str(e)[:200]
            # разбор ead2ca4: неполный поиск — не «нет заявки»; работа стоит, человеку — раз в час
            if st in WAITING and now - rec["t_sent"] > self.cfg["unknown_grace_s"] and now - float(rec.get("t_unk_note") or 0) > 3600:
                rec["t_unk_note"] = now
                self._say(f"⛔ заявка {rec['cid']} ({rec['role']}, {rec['kind']} {rec['qty']:g}): исход неизвестен, поиск неполный "
                          f"({str(e)[:120]}). Новой такой заявки не ставлю — проверить на бирже"[:400])
            return
        if info is None:
            if st in WAITING and now - rec["t_sent"] > self.cfg["unknown_grace_s"]:
                if self._absent_verdict(rec):
                    rec.update(status="ABSENT", t_done=now)
                    self.save()                         # учёт до журнала
                    self._jr({"kind": "заявка не встала", "cid": rec["cid"], "role": rec["role"]})
                elif st != "UNRESOLVED":
                    rec["status"] = "UNRESOLVED"
                    self.save()
                    self._jr({"kind": "исход неизвестен", "cid": rec["cid"], "role": rec["role"], "pos_before": rec.get("pos_before")})
                    self._say(f"⛔ заявка {rec['cid']} ({rec['role']}, {rec['kind']} {rec['qty']:g}): биржа её не знает, а позиция "
                              f"изменилась — исход неизвестен. Работа стоит. Проверить на бирже и выполнить --resolve {rec['cid']} absent|filled")
            return
        if st == "ABSENT":
            self._jr({"kind": "заявка нашлась", "cid": rec["cid"], "role": rec["role"], "status": info.status, "filled": info.filled})
            self._say(f"⚠️ заявка {rec['cid']} ({rec['role']}) считалась не вставшей, но нашлась: {info.status}, исполнено {info.filled:g}")
        self._apply(rec, info)

    def _absent_verdict(self, rec: dict) -> bool:
        """True — заявки точно нет (можно ставить новую). Лимит и стоп: да (ещё час перепроверяются). Рыночная: да, только
        если позиция стороны изменилась ровно на наши известные исполнения (на общем счёте — никогда)."""
        if self.cfg["shared_account"]:
            # разбор b056816: на общем счёте «заявки нет» не выводится ни для какого типа — устаревший или неполный
            # снимок давал ABSENT, и второй стоп рядом с живым закрывал ручное. Решает человек (--resolve)
            return False
        if rec["kind"] != "MARKET":
            return True
        if rec.get("pos_before") is None:
            return False
        try:
            pos_now = float(self.ex.position(self.sym).get(rec["pos_side"], 0.0))
        except Exception:  # noqa: BLE001
            return False
        d_exch = pos_now - rec["pos_before"]
        d_own = self._side_own(rec["pos_side"]) - rec["own_before"]
        return abs(d_exch - d_own) < max(rec["qty"] / 2, self.inst.lot / 2)

    def resolve(self, cid: str, verdict: str, qty: float = 0.0, px: float = 0.0) -> None:
        """Решение оператора по UNRESOLVED: absent — заявки не было; filled — исполнилась qty по px (с биржи)."""
        rec = self.st["orders"].get(cid)
        if not rec or rec["status"] not in WAITING:
            raise Halt(f"{cid}: нет такой неразрешённой заявки")
        if verdict == "absent":
            rec.update(status="ABSENT", t_done=self.ex.now())
        elif verdict == "filled":
            if not (0 < qty <= rec["qty"] + 1e-12 and px > 0):
                raise Halt("filled: нужны объём (не больше заявки) и цена")
            rec.update(status="FILLED", filled=qty, avg=px, t_done=self.ex.now(), fee_incomplete=True)
        else:
            raise Halt(f"решение {verdict!r}: absent | filled")
        self.save()
        self._jr({"kind": "решение оператора", "cid": cid, "verdict": verdict, "qty": qty, "px": px})

    def _cancel(self, rec: dict) -> None:
        if rec["status"] in DONE or rec["status"] in WAITING:
            return
        if rec.get("cancel_sent") and self.ex.now() - rec["cancel_sent"] < 5:
            return
        rec["cancel_sent"] = self.ex.now()
        try:
            self.ex.cancel(self.sym, rec["cid"], rec["kind"], rec.get("oid", ""), placed_at=rec["t_sent"])
        except (Unknown, ExchangeError, OSError) as e:
            rec["cancel_error"] = str(e)[:200]
        self._refresh(rec)

    # ------------------------------------------------------------------ потолок
    def _reserved(self, ep: dict) -> float:
        """Позиция по себестоимости + недобранный вход (пока идёт вход) + недобранный добор (пока не закрыт)."""
        q = max(self.qty(ep), 0.0)
        r = q * (self._avg(ep, IN_ROLES) or ep["sig_px"])
        if ep["phase"] == "entering":
            r += max(ep["goal_main"] - self._filled(ep, ("entry",)), 0.0) * ep["sig_px"]
        if ep["phase"] != "exiting" and ep.get("goal_add") and not ep.get("add_closed"):
            r += max(ep["goal_add"] - self._filled(ep, ("add",)), 0.0) * (ep.get("add_lv") or ep["sig_px"])
        return r

    def _allowance(self, ep: dict, role: str) -> float:
        """Сколько номинала ещё можно добавить этой работе: потолок − брони других эпизодов − своя позиция − своя бронь добора
        (для входа)."""
        others = sum(self._reserved(e) for e in self._eps() if e["id"] != ep["id"])
        own = max(self.qty(ep), 0.0) * (self._avg(ep, IN_ROLES) or ep["sig_px"])
        if role == "entry" and ep.get("goal_add") and not ep.get("add_closed"):
            own += max(ep["goal_add"] - self._filled(ep, ("add",)), 0.0) * (ep.get("add_lv") or ep["sig_px"])
        return max(float(self.cfg["cap_usd"]) - others - own, 0.0)

    # ------------------------------------------------------------------ шаг
    def step(self, desired: dict | None, events: list[dict] | None = None) -> None:
        """desired: {слот: Desired|None} по свежим данным; None — данные несвежие: новых входов и выходов по сигналу нет,
        защита (стоп, последняя подтверждённая цель) и начатые работы продолжаются."""
        for rec in list(self.st["orders"].values()):
            self._refresh(rec)
        self._doubt = {LONG: False, SHORT: False}
        if self.cfg["shared_account"]:
            self._guard()
        for slot in self.cfg["slots"]:
            d = desired.get(slot) if desired is not None else None
            try:
                self._slot(slot, d, desired is not None, events or [])
            except Halt:
                raise
            except Exception as e:  # noqa: BLE001 — один слот не должен ронять второй
                log.exception("sigexec.slot_failed slot=%s", slot)
                self._jr({"kind": "ошибка", "slot": slot, "error": repr(e)[:300]})
        if not self.cfg["shared_account"]:
            self._audit()                                   # на общем счёте сверку ведёт _guard
        self._gc()
        self.save()

    # ------------------------------------------------------------------ общая сторона (разбор ead2ca4)
    def _guard(self) -> None:
        """Общий счёт (WEEX COMBINED: свои и ручные контракты одной стороны — одна позиция, reduceOnly режет общую сторону).
        На стороне — свой объём O (учёт) и чужой F = позиция − O. «Пол» чужого объёма base: закрывающие заявки исполнителя
        никогда не опускают сторону ниже base (_closable). Отклонение F от base — «сомнение»: увеличений нет (вход, добор,
        новый эпизод). То же отклонение два прохода подряд при отсутствии своих незавершённых заявок — подтверждено:
        рост — чужой объём вырос (base = F); падение — считается закрытием СВОЕГО объёма (ручной не трогаем никогда),
        эпизоды стороны уходят в выход остатком; что сверх своего — уменьшение чужого (base снижается)."""
        try:
            pos = self.ex.position(self.sym)
        except Exception as e:  # noqa: BLE001 — позиция не прочиталась: сомнение на обеих сторонах
            self._doubt = {LONG: True, SHORT: True}
            self._jr({"kind": "позиция не прочиталась", "error": repr(e)[:200]})
            return
        try:
            ids = self.ex.position_ids(self.sym) or None
        except Exception as e:  # noqa: BLE001 — номер позиции не прочитался: сомнение, эпоху не судим
            ids = None
            self._doubt = {LONG: True, SHORT: True}
            self._jr({"kind": "номер позиции не прочитался", "error": repr(e)[:200]})
        tol = self.inst.lot / 2
        fg = self.st.setdefault("foreign", {})
        self._side_pos = {}
        for side in (LONG, SHORT):
            S = float(pos.get(side, 0.0))
            O = self._side_own(side)
            F = S - O
            self._side_pos[side] = S
            G = fg.setdefault(side, {"base": None, "cand": None, "n": 0})
            waiting = any(r["status"] in WAITING for r in self.st["orders"].values() if r["pos_side"] == side)
            if ids is not None:
                pid = ids.get(side)
                if O > tol and G.get("pid") and pid != G["pid"] and not waiting:
                    # разбор b056816: сторону закрыли до нуля (и, может быть, открыли заново) между проходами — номер позиции
                    # другой. Свой объём прежней позиции закрыт вместе со стороной; всё, что на стороне сейчас, — чужое.
                    # Закрывающих заявок по нему нет; эпизод уходит в выход (стоп снимается — он резал бы чужое)
                    eps = [e for e in self._eps() if e["pos_side"] == side]
                    self._external(eps, side, O)
                    for ep in eps:
                        self._to_exit(ep, f"позиция {side} закрыта до нуля не мной (номер {G['pid']} → {pid}) — мой объём закрыт с ней",
                                      None, urgent=True)
                    G.update(base=round(max(S, 0.0), 12), cand=None, n=0, pid=pid)
                    self._say(f"⚠️ {side}: позицию закрыли до нуля не я (сейчас на стороне {S:g} — считаю всё чужим). "
                              f"Мой объём {O:g} считаю закрытым, свой стоп снимаю, ничего не закрываю.")
                    continue
                G["pid"] = pid
            if G["base"] is None:
                G["base"] = round(max(F, 0.0), 12)
                if F < -tol:                                # своего на бирже меньше учёта уже при первом взгляде
                    G["cand"], G["n"] = F, 0
            dev = F - G["base"]
            if abs(dev) <= tol:
                G["cand"], G["n"] = None, 0
                continue
            self._doubt[side] = True
            if waiting:
                continue                                    # свой исход неизвестен — подтверждать нечем
            if G["cand"] is not None and abs(F - G["cand"]) <= tol:
                G["n"] += 1
            else:
                G["cand"], G["n"] = F, 1
                self._jr({"kind": "сомнение на стороне", "side": side, "pos": S, "own": O, "foreign_base": G["base"], "foreign_now": F})
                continue
            if G["n"] < 2:
                continue
            if dev > 0:
                self._jr({"kind": "чужой объём вырос", "side": side, "from": G["base"], "to": F})
                G["base"] = round(F, 12)
                if self.cfg["require_empty_side"] and O > tol:
                    self._say(f"⚠️ {side}: при открытой страховке на стороне появился ручной объём {F:g}. Закрываю только своё "
                              f"(не ниже {F:g}), но между проходами стоп может задеть ручное — пока страховка открыта, ручные "
                              f"сделки на этой стороне лучше не делать.")
            else:
                short = G["base"] - F
                own_ext = min(short, O)
                if own_ext > tol:
                    eps = [e for e in self._eps() if e["pos_side"] == side]
                    self._external(eps, side, own_ext)
                    for ep in eps:
                        self._to_exit(ep, f"сторона {side} уменьшена не мной на {short:g} — считаю это своим объёмом, "
                                          f"ручной не трогаю; новых увеличений нет", None, urgent=True)
                    self._say(f"⚠️ {side}: сторона меньше ожидаемого на {short:g} — считаю, что закрыли МОЙ объём ({own_ext:g}); "
                              f"ручные {G['base']:g} не трогаю. Если закрывал свой ручной — на стороне на {own_ext:g} больше, "
                              f"чем ты думаешь. Эпизод закрываю остатком.")
                rest = short - own_ext
                if rest > tol:
                    G["base"] = round(max(G["base"] - rest, 0.0), 12)
                    self._jr({"kind": "чужой объём уменьшился", "side": side, "by": rest, "base": G["base"]})
            G["cand"], G["n"] = None, 0
            self._doubt[side] = False

    def _closable(self, side: str) -> float:
        """Сколько можно закрыть reduceOnly, не задев чужой объём: позиция стороны сейчас − пол чужого. Не общий счёт —
        без ограничения. Позиция не прочиталась — 0 (лучше подождать проход, чем закрыть ручное)."""
        if not self.cfg["shared_account"]:
            return float("inf")
        try:
            S = float(self.ex.position(self.sym).get(side, 0.0))
        except Exception:  # noqa: BLE001
            return 0.0
        base = (self.st.get("foreign", {}).get(side) or {}).get("base")
        return max(S - float(base or 0.0), 0.0)

    def _slot(self, slot: str, d: Desired | None, fresh: bool, events: list[dict]) -> None:
        S = self.st["slots"][slot]
        ep = S["ep"]
        if ep is None:
            if not (fresh and d and self.cfg["enabled"]) or self.st.get("closing") or d.entry_t in S["done"]:
                return
            side = LONG if d.side > 0 else SHORT
            if self._doubt.get(side):
                return                                      # разбор ead2ca4: сторона не сходится с учётом — эпизод позже
            if self.cfg["require_empty_side"] and self.cfg["shared_account"] and side in self.cfg["allowed_sides"]:
                foreign = (self._side_pos.get(side) if side in self._side_pos else None)
                if foreign is None or foreign - self._side_own(side) > self.inst.lot / 2:
                    now = self.ex.now()
                    if now - float(S.get("empty_note_t") or 0) > 3600:
                        S["empty_note_t"] = now
                        self._jr({"kind": "сторона не пустая — эпизод не начинаю", "slot": slot, "entry_t": d.entry_t, "side_pos": foreign})
                        self._say(f"ℹ️ {slot}: {d.tag} {d.sig_px:.0f} не открываю — на стороне {side} чужой объём "
                                  f"{foreign if foreign is not None else 'не прочитан'} (страховка только на пустой стороне)")
                    return                                  # не «сделано»: сторона опустеет, пока сигнал свежий, — войдём
            ep = self._start(slot, d)
            if ep is None:
                return
        if fresh and ep["phase"] in ("entering", "open") and (d is None or d.entry_t != ep["entry_t"]):
            ex_ev = next((e for e in events if e["slot"] == slot and e["kind"] == "выход" and e["entry_t"] == ep["entry_t"]), None)
            gone = ep["phase"] == "open" and self.qty(ep) <= self.inst.lot / 2
            head = "на бирже уже закрыто (цель или стоп), движок: " if gone else "сигнал выхода: "
            self._to_exit(ep, head + (ex_ev["why"] if ex_ev else "позиции нет"), ex_ev)
        if ep["phase"] in ("entering", "open") and self._filled(ep, ("stop",)) > 0:
            self._to_exit(ep, "аварийный стоп сработал", None, urgent=True)
        if ep["phase"] == "entering":
            if not self._protect_stop(ep):              # стоп на уже исполненный объём во время входа (P1-4)
                if self._work(ep, "entry", lambda: ep["goal_main"] - self._filled(ep, ("entry",)), self._open_side(ep), False, self.cfg["entry"]):
                    ep["phase"] = "open"
                    self._opened(ep)
        if ep["phase"] == "open":
            if self.qty(ep) <= self.inst.lot / 2:
                self._to_exit(ep, "позиция закрыта целью, стопом или извне", None, urgent=True)
            else:
                self._protect(ep, d if (fresh and d and d.entry_t == ep["entry_t"]) else None, fresh)
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
        if self.cfg["shared_account"] and self.cfg["use_target"] and (d.target is not None or d.tag == "под жёлтой"):
            # разбор aadc2a4: цель и аварийный стоп — две reduceOnly на одной стороне; на общем счёте вторая, исполнившись до
            # снятия, закроет чужие контракты. Без биржевого OCO такой эпизод только на отдельном счёте
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": "цель + стоп на общем счёте"})
            self._say(f"ℹ️ {slot}: {d.tag} не исполняю на общем счёте — цель и стоп могут закрыть чужое")
            return None
        hedge = None
        if self.cfg["sizing"] == "hedge":
            hedge = self._hedge_size(slot, d)
            if hedge is None:
                return None
            base, main_frac, add_frac = hedge["base_usd"], hedge["main_frac"], hedge["add_frac"]
        else:
            base, main_frac, add_frac = float(self.cfg["base_usd"]), d.main_frac, d.add_frac
        goal = self.inst.floor_qty(base * main_frac / d.sig_px)
        add = self.inst.floor_qty(base * add_frac / d.add_lv) if d.add_lv else 0.0
        room = float(self.cfg["cap_usd"]) - sum(self._reserved(e) for e in self._eps())
        if goal * d.sig_px + add * (d.add_lv or 0.0) > room:
            add = 0.0                                      # сначала без добора
            if goal * d.sig_px > room:
                goal = self.inst.floor_qty(max(room, 0.0) / d.sig_px)
        if goal < self.inst.min_qty:
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": f"объём {goal} меньше минимума или нет места под потолком (свободно ${room:.0f})"})
            self._say(f"⚠️ {slot}: вход {d.tag} пропущен — нет места под потолком (свободно ${room:.0f})")
            return None
        ep = {"id": f"{slot}:{d.entry_t}", "slot": slot, "entry_t": d.entry_t, "side": d.side, "tag": d.tag, "pos_side": side,
              "w": d.w, "boost": getattr(d, "boost", 1.0), "sig_px": d.sig_px, "goal_main": goal, "goal_add": add if add >= self.inst.min_qty else 0.0,
              "add_lv": d.add_lv, "phase": "entering", "work": None, "t_start": now, "exit_reason": None, "exit_sig_px": None, "engine_res": None}
        if hedge:
            ep["hedge"] = hedge                            # размер зафиксирован на входе: позже позиция сеток его не меняет
        S["ep"] = ep
        self.save()
        self._jr({"kind": "эпизод", "slot": slot, "entry_t": d.entry_t, "side": d.side, "tag": d.tag, "sig_px": d.sig_px, "goal_main": goal,
                  "goal_add": ep["goal_add"], "w": d.w, "boost": ep["boost"], "delay_s": round(now - d.entry_t, 1), "hedge": hedge})
        return ep

    def _hedge_size(self, slot: str, d: Desired) -> dict | None:
        """База страховки = hedge_k × позиция лонг-сеток счёта ($) сейчас; вход HEDGE_LEG базы, добор (если у тега он есть)
        ещё HEDGE_LEG. Неизвестная позиция — None без отметки «сделано» (повтор, пока сигнал свежий; сообщение раз в час);
        позиции нет — эпизод пропускается."""
        S = self.st["slots"][slot]
        now = self.ex.now()
        try:
            expo = self.exposure()
            if isinstance(expo, bool) or not isinstance(expo, (int, float)) or not math.isfinite(expo) or expo < 0:
                raise ValueError(f"позиция сеток {expo!r}")
            expo = float(expo)
        except Exception as e:  # noqa: BLE001 — любой сбой источника = «неизвестно», не ноль
            if now - float(S.get("hedge_err_t") or 0) > 3600:
                S["hedge_err_t"] = now
                self.save()
                self._jr({"kind": "размер страховки неизвестен", "slot": slot, "entry_t": d.entry_t, "error": repr(e)[:200]})
                self._say(f"⚠️ {slot}: шорт {d.tag} {d.sig_px:.0f} жду — позиция сеток не прочиталась ({e!r})"[:300])
            return None
        if expo < HEDGE_MIN_USD:
            S["done"].append(d.entry_t)
            self._jr({"kind": "сигнал пропущен", "slot": slot, "entry_t": d.entry_t, "why": f"страховать нечего: позиция сеток ${expo:.2f}"})
            self._say(f"ℹ️ {slot}: шорт {d.tag} {d.sig_px:.0f} не открываю — лонгов сеток нет")
            return None
        k = float(self.cfg["hedge_k"])
        return {"exposure_usd": round(expo, 2), "k": k, "base_usd": round(k * expo, 2), "main_frac": HEDGE_LEG,
                "add_frac": HEDGE_LEG if d.add_lv else 0.0}

    def _hedge_add_size(self, ep: dict) -> bool:
        """Добор страховки — от позиции сеток на часе добора (как overlay2, разбор ead2ca4: заранее заданный объём добора
        после тейков лонгов давал шорт без встречного лонга). Объём фиксируется один раз. False — позиция не прочиталась."""
        now = self.ex.now()
        try:
            expo = self.exposure()
            if isinstance(expo, bool) or not isinstance(expo, (int, float)) or not math.isfinite(expo) or expo < 0:
                raise ValueError(f"позиция сеток {expo!r}")
            bid, ask = self.ex.book(self.sym)
        except Exception as e:  # noqa: BLE001
            if now - float(ep.get("hedge_add_err_t") or 0) > 3600:
                ep["hedge_add_err_t"] = now
                self._jr({"kind": "размер добора страховки неизвестен", "slot": ep["slot"], "error": repr(e)[:200]})
                self._say(f"⚠️ {ep['slot']}: добор страховки жду — позиция сеток не прочиталась ({e!r})"[:300])
            return False
        px = bid if ep["side"] < 0 else ask
        h = ep["hedge"]
        goal = h["k"] * h["add_frac"] * float(expo) / px if px > 0 else 0.0
        room = h["k"] * float(expo) / px - self.qty(ep) if px > 0 else 0.0     # разбор b056816: с добором не больше предела
        goal = self.inst.floor_qty(max(min(goal, room), 0.0))
        ep["goal_add"] = goal if goal >= self.inst.min_qty else 0.0
        ep["add_sized"] = {"exposure_usd": round(float(expo), 2), "px": px, "goal_add": ep["goal_add"]}
        self.save()
        self._jr({"kind": "добор страховки рассчитан", "slot": ep["slot"], **ep["add_sized"]})
        return True

    def _open_side(self, ep: dict) -> str:
        return BUY if ep["side"] > 0 else SELL

    def _close_side(self, ep: dict) -> str:
        return SELL if ep["side"] > 0 else BUY

    def _to_exit(self, ep: dict, why: str, ev: dict | None, urgent: bool = False) -> None:
        if ep["phase"] == "exiting":
            ep["urgent"] = ep.get("urgent") or urgent
            return
        ep.update(phase="exiting", exit_reason=why, work=None, t_exit=self.ex.now(), urgent=urgent)
        if ev:
            ep.update(exit_sig_px=ev["px"], engine_res=ev.get("res"), exit_sig_t=ev["t"])
        self.save()
        self._jr({"kind": "выход начат", "slot": ep["slot"], "entry_t": ep["entry_t"], "why": why, "qty": self.qty(ep), "urgent": urgent})

    # ------------------------------------------------------------------ тактики
    def _work(self, ep: dict, role: str, remaining_fn, side: str, reduce: bool, tac: dict) -> bool:
        """Довести работу (вход, выход, рыночный добор) до конца: True — сделано. Одна живая заявка роли за раз — по реестру."""
        w = ep.get("work")
        now = self.ex.now()
        if not w or w["role"] != role:
            w = ep["work"] = {"role": role, "t0": now, "n": 0, "cur": None}
        urgent = role == "exit" and ep.get("urgent")
        live = self._orders(ep, (role,), live_only=True)   # из реестра: переживает падение процесса (P1-1)
        if any(r["status"] in WAITING for r in live):
            return False                                   # исход неизвестен — ждём поиска, новой заявки нет
        if live:
            for cur in live:
                if cur["kind"] != "LIMIT":
                    continue
                too_long = now - w["t0"] >= tac.get("wait_s", 0)
                stale = tac["kind"] == "chase" and now - cur["t_sent"] >= tac.get("reprice_s", 20) and self._off_best(cur)
                if urgent or too_long or stale:
                    self._cancel(cur)
            return False
        if role in IN_ROLES and (self._doubt.get(ep["pos_side"]) or self.block_increase):
            return False                                   # разбор ead2ca4: сторона не сходится с учётом — не увеличиваем
        rem = remaining_fn()
        q = self.inst.floor_qty(rem)
        if reduce and q >= self.inst.min_qty:
            lim = self._closable(ep["pos_side"])            # разбор ead2ca4: ниже пола чужого объёма не закрываем
            if lim < q:
                if not w.get("clamp_noted"):
                    w["clamp_noted"] = True
                    self._jr({"kind": "закрытие урезано полом чужого объёма", "slot": ep["slot"], "role": role, "want": q, "closable": lim})
                q = self.inst.floor_qty(lim)
                if q < self.inst.min_qty:
                    return False                           # ждём сверки стороны (_guard); ручное не закрываем
        px_now = None
        if role in IN_ROLES and q >= self.inst.min_qty:   # потолок по цене исполнения (P1-5)
            bid, ask = self.ex.book(self.sym)
            px_now = ask if side == BUY else bid
            allow = self.inst.floor_qty(self._allowance(ep, role) / px_now)
            if allow < q:
                self._jr({"kind": "потолок режет объём", "slot": ep["slot"], "role": role, "want": q, "allow": allow, "px": px_now})
                q = allow
        if q < self.inst.min_qty:
            if rem > self.inst.lot / 2:
                self._jr({"kind": "остаток меньше минимума или потолка", "slot": ep["slot"], "role": role, "qty": rem})
            ep["work"] = None
            return True
        market = urgent or tac["kind"] == "market" or now - w["t0"] >= tac.get("wait_s", 0) or w["n"] >= tac.get("max_orders", 20)
        if market and self._blocked(ep, role, ("MARKET",)):
            if role == "entry":                            # вход не берётся (маржа, лимиты) — эпизод закрываем тем, что налилось
                self._to_exit(ep, f"вход: биржа {self._rejected(ep, role, ('MARKET',))} раз отказала", None, urgent=True)
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
            if role in IN_ROLES:                           # разбор ead2ca4: потолок — по цене самой лимитки, не по стакану
                allow = self.inst.floor_qty(self._allowance(ep, role) / px)
                if allow < q:
                    self._jr({"kind": "потолок режет объём лимитки", "slot": ep["slot"], "role": role, "want": q, "allow": allow, "px": px})
                    q = allow
                if q < self.inst.min_qty:
                    return False
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
        """После max_rejects отказов подряд роль ждёт reject_backoff_s с последней попытки, потом одна новая попытка —
        без долбёжки биржи и без вечной блокировки (имитатор 12.11: при 30% сбоев цель вставала до конца эпизода); сообщение
        раз в час."""
        n = self._rejected(ep, role, kinds)
        if n < self.cfg["max_rejects"]:
            return False
        rs = [r for r in self._orders(ep, (role,)) if kinds is None or r["kind"] in kinds]
        if rs and self.ex.now() - max(r["t_sent"] for r in rs) >= self.cfg["reject_backoff_s"]:
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

    # ------------------------------------------------------------------ защита
    def _protect_stop(self, ep: dict) -> bool:
        """Аварийный стоп на фактически исполненный объём (и во время входа). True — уровень пройден, эпизод ушёл в выход."""
        q = self.qty(ep)
        stops = self._orders(ep, ("stop",), live_only=True)
        if q < self.inst.min_qty:
            for r in stops:
                if r["status"] not in WAITING:
                    self._cancel(r)
            return False
        avg = self._avg(ep, IN_ROLES) or ep["sig_px"]
        trg = self.inst.round_px(avg * (1 - ep["side"] * self.cfg["emergency_pct"] / 100), "down" if ep["side"] > 0 else "up")
        bid, ask = self.ex.book(self.sym)
        breached = (ep["side"] > 0 and bid <= trg) or (ep["side"] < 0 and ask >= trg)
        # объём стопа — не больше того, что можно закрыть, не задев чужое (разбор ead2ca4: стоп на прежний объём после
        # внешнего сокращения стороны закрывал ручной шорт)
        want = self.inst.floor_qty(min(q, self._closable(ep["pos_side"])))
        if stops:
            for r in stops:
                if r["status"] not in WAITING and (ep.get("trim_pending") or abs(r["qty"] - want) > self.inst.lot / 2
                                                   or abs((r["trigger"] or 0) - trg) > max(self.inst.tick, trg * 0.002)):
                    self._cancel(r)
            if self._filled(ep, ("stop",)) > 0:
                # разбор b056816: старый стоп исполнился во время замены — не ставить новый на прежний размер, а выходить
                self._to_exit(ep, "аварийный стоп сработал (при замене)", None, urgent=True)
                return True
            stops = self._orders(ep, ("stop",), live_only=True)
            if stops:
                return False                               # старый ещё жив или исход неизвестен — второй стоп не ставим
            # снят подтверждённо — новый в этом же проходе по ПЕРЕСЧИТАННОМУ объёму (разбор ead2ca4 / b056816)
            q = self.qty(ep)
            want = self.inst.floor_qty(min(q, self._closable(ep["pos_side"])))
        if ep.get("trim_pending"):
            return False                                   # урезание идёт без стопа рядом; новый стоп — после него
        if breached:
            # стопа нет, а уровень пройден (снят на замене, отказ, гэп) — стоп встал бы сразу: выходим сами, рыночным (P1-4)
            self._to_exit(ep, f"аварийный уровень {trg:.1f} пройден, стопа на бирже нет", None, urgent=True)
            return True
        if want >= self.inst.min_qty and not self._blocked(ep, "stop", ("STOP",)):
            self._send(ep, "stop", "STOP", self._close_side(ep), want, trigger=trg, reduce_only=True)
        return False

    def _trim_hedge(self, ep: dict) -> None:
        """Страховка не больше hedge_k × текущие лонги сеток (разбор ead2ca4: после тейков лонгов шорт оставался без
        встречного лонга). Раз в TRIM_CHECK_S читается позиция сеток; шорт больше предела на TRIM_TOL — урезается рыночным
        reduceOnly (пол чужого объёма соблюдается в _work), обратно не наращивается. Позиция не прочиталась — пропуск.
        Замер hedge_variants.py E: −$250 за 9 лет / −$23 за 2 года к страховке без предела, чистый шорт 4.9% часов → 0."""
        if ep.get("trim_pending"):
            # разбор b056816: урезание и стоящий стоп — две reduceOnly на общей стороне; стоп снимается и его конечный исход
            # подтверждается ДО урезания, новый стоп ставится после (_protect_stop ждёт, пока trim_pending)
            if self._orders(ep, ("stop",), live_only=True):
                return                                     # снятие стопа ещё не подтверждено
            self._trim_step(ep)
            return
        now = self.ex.now()
        if now - float(ep.get("trim_check_t") or 0) < TRIM_CHECK_S:
            return
        ep["trim_check_t"] = now
        try:
            expo = self.exposure()
            if isinstance(expo, bool) or not isinstance(expo, (int, float)) or not math.isfinite(expo) or expo < 0:
                raise ValueError(f"позиция сеток {expo!r}")
            bid, ask = self.ex.book(self.sym)
        except Exception as e:  # noqa: BLE001
            self._jr({"kind": "предел страховки не проверен", "slot": ep["slot"], "error": repr(e)[:200]})
            return
        px = ask if ep["side"] < 0 else bid
        lim = float(ep["hedge"]["k"]) * float(expo) / px
        q = self.qty(ep)
        if q <= lim * (1 + TRIM_TOL) + self.inst.lot / 2:
            return
        cut = self.inst.floor_qty(q - lim)
        if cut < self.inst.min_qty:
            return
        ep["trim_to_close"], ep["trim_base"], ep["trim_pending"] = cut, self._filled(ep, ("trim",)), True
        self.save()
        self._jr({"kind": "страховка больше лонгов — урезаю", "slot": ep["slot"], "qty": q, "limit": round(lim, 6), "cut": cut,
                  "exposure_usd": round(float(expo), 2)})
        for r in self._orders(ep, ("stop",), live_only=True):
            if r["status"] not in WAITING:
                self._cancel(r)                            # сначала снять стоп; урезание — со следующего прохода или сразу,
        if self._filled(ep, ("stop",)) > 0:                # если снятие подтвердилось
            self._to_exit(ep, "аварийный стоп сработал (перед урезанием)", None, urgent=True)
            return
        if not self._orders(ep, ("stop",), live_only=True):
            self._trim_step(ep)

    def _trim_step(self, ep: dict) -> None:
        """Рыночное урезание; исполнилось сразу — урезание закрыто и стоп на новый объём ставится в этом же проходе."""
        done = self._work(ep, "trim", lambda: ep["trim_to_close"] - self._filled_since(ep), self._close_side(ep), True, MARKET_TAC)
        if not done:
            for r in self._orders(ep, ("trim",), live_only=True):
                self._refresh(r)
            if not self._orders(ep, ("trim",), live_only=True):
                done = self._work(ep, "trim", lambda: ep["trim_to_close"] - self._filled_since(ep), self._close_side(ep), True, MARKET_TAC)
        if done:
            ep["trim_pending"] = False
            self.save()
            self._protect_stop(ep)

    def _filled_since(self, ep: dict) -> float:
        return self._filled(ep, ("trim",)) - float(ep.get("trim_base") or 0.0)

    def _protect(self, ep: dict, d: Desired | None, fresh: bool) -> None:
        if self._protect_stop(ep):
            return
        if ep.get("hedge"):
            self._trim_hedge(ep)
        # добор — остаток goal_add − исполнено (P1-5), в пределах потолка
        if ep["goal_add"] > 0 and not ep.get("add_closed"):
            got = self._filled(ep, ("add",))
            rem = ep["goal_add"] - got
            live = self._orders(ep, ("add",), live_only=True)
            waiting = any(r["status"] in WAITING for r in live)
            if rem < self.inst.min_qty and not live:
                ep["add_closed"] = True
            elif d is not None and d.add_done and self.cfg["add_follow_signal"]:
                stops = [r for r in live if r["kind"] == "STOP" and r["status"] not in WAITING]
                if stops:
                    for r in stops:
                        self._cancel(r)
                elif not waiting:
                    if ep.get("hedge") and not ep.get("add_sized") and not self._hedge_add_size(ep):
                        return                             # позиция сеток на часе добора не прочиталась — ждём
                    if ep["goal_add"] - self._filled(ep, ("add",)) < self.inst.min_qty:
                        ep["add_closed"] = True
                    else:
                        # разбор b056816: стоп мог исполниться после сверки в начале прохода — перед рыночным добором его
                        # состояние читается заново; исполнился — выход, не добор
                        for r in self._orders(ep, ("stop",), live_only=True):
                            self._refresh(r)
                        if self._filled(ep, ("stop",)) > 0:
                            self._to_exit(ep, "аварийный стоп сработал (перед добором)", None, urgent=True)
                            return
                        if self._work(ep, "add", lambda: ep["goal_add"] - self._filled(ep, ("add",)), self._open_side(ep), False, MARKET_TAC):
                            ep["add_closed"] = True
            elif not live and ep["add_lv"] and self.cfg["add_resting"] and not self._doubt.get(ep["pos_side"]) \
                    and not self._blocked(ep, "add", ("STOP",)):
                bid, ask = self.ex.book(self.sym)
                trg = self.inst.round_px(ep["add_lv"], "up" if ep["side"] > 0 else "down")
                beyond = (ep["side"] > 0 and ask >= trg) or (ep["side"] < 0 and bid <= trg)
                q = min(self.inst.floor_qty(rem), self.inst.floor_qty(self._allowance(ep, "add") / trg))
                if not beyond and q >= self.inst.min_qty:  # цена уже за уровнем — ждём решения движка на закрытии часа
                    self._send(ep, "add", "STOP", self._open_side(ep), q, trigger=trg)
        q = self.qty(ep)
        # цель шорта под жёлтой: при несвежих данных держится последняя подтверждённая (разбор: step(None) снимал цель)
        if fresh:
            use = self.cfg["use_target"] and d is not None and d.target
            ep["last_target"] = self.inst.round_px(d.target, "up" if ep["side"] < 0 else "down") if use else None
        want = ep.get("last_target")
        tg = self._orders(ep, ("target",), live_only=True)
        if tg:
            for r in tg:
                if r["status"] in WAITING:
                    continue
                if want is None or abs(r["price"] - want) >= self.inst.tick / 2 or abs(r["qty"] - (r["filled"] + q)) > self.inst.lot / 2:
                    self._cancel(r)
        elif want is not None and q >= self.inst.min_qty and not self._blocked(ep, "target", ("LIMIT",)):
            self._send(ep, "target", "LIMIT", self._close_side(ep), self.inst.floor_qty(q), price=want, reduce_only=True)

    # ------------------------------------------------------------------ выход
    def _exiting(self, ep: dict) -> None:
        for r in [r for r in self._orders(ep, live_only=True) if r["role"] != "exit"]:
            self._cancel(r)
        if [r for r in self._orders(ep, live_only=True) if r["role"] != "exit"]:
            return                                         # ждём, пока стопы, цель, вход и добор станут конечными
        q = self.qty(ep)
        if q > self.inst.lot / 2:
            self._work(ep, "exit", lambda: self.qty(ep), self._close_side(ep), True, MARKET_TAC if ep.get("urgent") else self.cfg["exit"])
            return
        if self._orders(ep, live_only=True):
            return
        self._finish(ep)

    def _opened(self, ep: dict) -> None:
        avg, q = self._avg(ep, ("entry",)), self._filled(ep, ("entry",))
        slip = ep["side"] * (avg / ep["sig_px"] - 1) * 10000 if avg else 0.0
        fee = sum(r["fee"] for r in self._orders(ep, ("entry",)))
        self._jr({"kind": "вход исполнен", "slot": ep["slot"], "entry_t": ep["entry_t"], "qty": q, "avg": avg, "sig_px": ep["sig_px"], "slip_bps": round(slip, 2),
                  "fee": fee, "boost": ep.get("boost", 1.0), "delay_s": round(self.ex.now() - ep["entry_t"], 1)})
        boost = f", усиление 432 ×{ep['boost']:g}" if ep.get("boost", 1.0) != 1.0 else ""
        if ep.get("hedge"):
            h = ep["hedge"]
            boost += f", страховка: позиция сеток ${h['exposure_usd']:,.0f} × {h['k']:g} × {h['main_frac']:g}" + (
                f", добор {ep['goal_add']:g} на {ep['add_lv']:.1f}" if ep.get("goal_add") else "")
        self._say(f"{'🟢' if ep['side'] > 0 else '🔴'} {ep['slot']} {ep['tag']}: вход {q:g} по {avg:.1f} (сигнал {ep['sig_px']:.1f}, {slip:+.1f} б.п.){boost}, "
                  f"комиссия ${fee:.2f}, через {int(self.ex.now() - ep['entry_t'])} с после закрытия 4ч")

    def _finish(self, ep: dict) -> None:
        S = self.st["slots"][ep["slot"]]
        ins, outs = self._orders(ep, IN_ROLES), self._orders(ep, OUT_ROLES)
        v_in = sum(r["filled"] * r["avg"] for r in ins)
        v_out = sum(r["filled"] * r["avg"] for r in outs)
        fee = sum(r["fee"] for r in ins + outs)
        q_in = sum(r["filled"] for r in ins)
        pnl = ep["side"] * (v_out - v_in) - fee
        rec = {"kind": "сделка", "slot": ep["slot"], "entry_t": ep["entry_t"], "tag": ep["tag"], "side": ep["side"], "qty": q_in, "boost": ep.get("boost", 1.0),
               "avg_in": v_in / q_in if q_in else None, "avg_out": v_out / q_in if q_in else None, "sig_in": ep["sig_px"], "sig_out": ep.get("exit_sig_px"),
               "fee": round(fee, 4), "pnl_usd": round(pnl, 4), "engine_res_pct": ep.get("engine_res"),
               "engine_usd": (round(ep["engine_res"] / 100 * self.cfg["base_usd"], 4)
                              if ep.get("engine_res") is not None and not ep.get("hedge") else None),   # у страховки размер не base_usd
               "hedge": ep.get("hedge"), "why": ep.get("exit_reason"), "fee_incomplete": any(r.get("fee_incomplete") for r in ins + outs),
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
        """Позиция стороны меньше своего учёта два прохода подряд (счётчик ПО СТОРОНЕ) — кто-то закрыл наши контракты: учёт
        уменьшается записью «извне» по текущей цене. Больше — чужие сделки: не наше дело."""
        if not getattr(self.ex, "hedge", True):
            return
        eps = self._eps()
        if not eps or any(r["status"] in WAITING for r in self.st["orders"].values()):
            return
        try:
            pos = self.ex.position(self.sym)
        except Exception:  # noqa: BLE001
            return
        bad = self.st["audit_bad"]
        for side in (LONG, SHORT):
            short = self._side_own(side) - float(pos.get(side, 0.0))
            if short > self.inst.lot / 2:
                bad[side] = bad.get(side, 0) + 1
                if bad[side] >= 2:
                    self._external(eps, side, short)
                    bad[side] = 0
            else:
                bad[side] = 0

    def _external(self, eps: list[dict], side: str, short: float) -> None:
        bid, ask = self.ex.book(self.sym)
        px = (bid + ask) / 2
        notes = []
        for ep in sorted((e for e in eps if e["pos_side"] == side), key=lambda e: -self.qty(e)):
            take = min(short, self.qty(ep))
            if take <= 0:
                continue
            self.st["seq"] += 1
            cid = f"ext{ep['slot'][0]}{_b36(self.st['seq'])}"
            self.st["orders"][cid] = {"cid": cid, "ep": ep["id"], "role": "external", "kind": "EXTERNAL", "side": self._close_side(ep), "pos_side": side,
                                      "qty": take, "price": px, "trigger": None, "status": "FILLED", "filled": take, "avg": px, "fee": 0.0, "oid": "",
                                      "t_sent": self.ex.now(), "t_done": self.ex.now()}
            short -= take
            notes.append((ep, take))
        self.save()                                         # учёт до журнала (разбор: _external писал журнал первым)
        for ep, take in notes:
            self._jr({"kind": "закрыто извне", "slot": ep["slot"], "qty": take, "px": px})
            self._say(f"⚠️ {ep['slot']}: на бирже {side} меньше учёта на {take:g} — закрыто не мной, учёт уменьшен по {px:.1f}")

    def _gc(self) -> None:
        """Конечные заявки закрытых эпизодов старше суток — из реестра (журнал хранит всё)."""
        live_eps = {e["id"] for e in self._eps()}
        now = self.ex.now()
        for cid in [c for c, r in self.st["orders"].items() if r["ep"] not in live_eps and r["status"] in DONE and now - (r["t_done"] or now) > 86400]:
            del self.st["orders"][cid]

    # ------------------------------------------------------------------ команды
    def close_all(self, why: str = "команда: закрыть всё") -> None:
        """Новые входы запрещены до reopen(); открытые эпизоды — в выход рыночным."""
        self.st["closing"] = True
        for ep in self._eps():
            self._to_exit(ep, why, None, urgent=True)
        self.save()
        self._jr({"kind": "закрыть всё", "why": why})

    def reopen(self) -> None:
        self.st["closing"] = False
        self.save()
        self._jr({"kind": "входы разрешены"})

    def flat(self) -> bool:
        """Эпизодов нет и ни одной незавершённой своей заявки."""
        return not self._eps() and not any(r["status"] not in DONE for r in self.st["orders"].values())

    def status(self) -> dict:
        out = {"closing": self.st.get("closing", False)}
        for slot, S in self.st["slots"].items():
            ep = S["ep"]
            if not ep:
                out[slot] = None
                continue
            out[slot] = {"phase": ep["phase"], "side": ep["side"], "tag": ep["tag"], "qty": self.qty(ep), "avg": self._avg(ep, IN_ROLES), "sig_px": ep["sig_px"],
                         "boost": ep.get("boost", 1.0), "hedge": ep.get("hedge"),
                         "live":[(r["role"], r["kind"], r["price"] or r["trigger"], r["status"]) for r in self._orders(ep, live_only=True)]}
        out["unresolved"] = [c for c, r in self.st["orders"].items() if r["status"] == "UNRESOLVED"]
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
