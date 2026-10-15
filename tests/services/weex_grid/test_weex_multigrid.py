"""Несколько сеток на ОДНОМ символе (15.10: живая BTC + B34/B49/B89 на BTCUSDT для недельного сравнения).

До правки свои ордера сетки определялись префиксом b7g и буквой символа — у всех сеток BTCUSDT это b7gB…: сетка
усыновляла входы соседки, снимала их как «лишние», путала одинаковые clientOrderId. Теперь у сетки свой знак (cid_tag;
по умолчанию буква символа — формат живых BTC/ETH прежний), своими считаются только b7g+знак.

Стенд: одна поддельная биржа BTCUSDT (общая позиция LONG хедж-режима, PARTIALLY_FILLED в открытых, потеря ответа на
постановку, частичный market), каждый проход каждой сетки — новый Grid с диска (как loop.py). Кто ставил и кто снимал
ордер, биржа записывает сама (по сетке, чей проход идёт), а не по clientOrderId — проверка не зависит от формата cid.
Биржа — имитатор, это проверка логики, не замер реального WEEX."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.weex_api.client import WeexIncomplete
from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from services.weex_grid import portfolio

TAGS = {"BTC": None, "B34": "3", "B49": "4", "B89": "8"}         # None — без cid_tag (живая BTC, прежний формат)
OWN = {"BTC": "b7gB", "B34": "b7g3", "B49": "b7g4", "B89": "b7g8"}
STEP = {"BTC": 0.6, "B34": 0.1, "B49": 0.1, "B89": 0.1}
TARGET = {"BTC": 1.4, "B34": 0.34, "B49": 0.49, "B89": 0.89}


class Px:
    def __init__(self, mid=100_000.0):
        self.mid = mid

    def __call__(self):
        return round(self.mid - 0.05, 2), round(self.mid + 0.05, 2)


class SharedEx(eg.DryExchange):
    """Одна биржа на все сетки символа. actor — сетка, чей проход идёт: биржа помнит, кто поставил (placer) и кто снял
    (cancels) каждый ордер. PARTIALLY_FILLED — в открытых; lose='after' — ордер принят, ответ потерян; первый market
    reduceOnly исполняется наполовину (остаток добивает тест)."""

    def __init__(self, px, clock):
        super().__init__(px, now_fn=lambda: clock["t"])
        self.actor = None
        self.placer: dict[str, str | None] = {}
        self.cancels: list[tuple[str | None, str]] = []
        self.lose = None
        self.half_market = True

    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] in eg.LIVE]

    def cancel(self, oid):
        self.cancels.append((self.actor, str(oid)))
        o = self.orders.get(str(oid))
        if o and o["status"] in ("NEW", "PARTIALLY_FILLED"):
            o["status"] = "CANCELED"
        return {"success": True, "orderId": oid}

    def place_limit(self, *a, **kw):
        mode, self.lose = self.lose, None
        r = super().place_limit(*a, **kw)
        if r.get("success"):
            self.placer[r["orderId"]] = self.actor
            self.orders[r["orderId"]]["time"] = int(self.now_fn() * 1000)
        if mode == "after" and r.get("success"):
            raise TimeoutError("synthetic: order accepted, response lost")
        return r

    def place_market(self, symbol, side, position_side, qty, cid, reduce_only=False):
        r = super().place_market(symbol, side, position_side, qty, cid, reduce_only)
        if r.get("success"):
            oid = r["orderId"]
            self.placer[oid] = self.actor
            o = self.orders[oid]
            o["time"] = int(self.now_fn() * 1000)
            if reduce_only and self.half_market:
                self.half_market = False
                half = float(o["origQty"]) / 2
                o.update(status="PARTIALLY_FILLED", executedQty=f"{half:.4f}")
                self.trades[oid][0].update(qty=f"{half:.4f}", commission=str(half * float(o["price"]) * 0.00048))
        return r

    def fill(self, oid: str, qty: str | None = None) -> None:
        """Исполнить ордер (частично — qty) по его цене, сделка с комиссией мейкера."""
        o = self.orders[oid]
        done = float(o["executedQty"])
        q = float(o["origQty"]) - done if qty is None else float(qty)
        px = float(o["price"])
        new = done + q
        o.update(executedQty=f"{new:.4f}", avgPrice=o["price"],
                 status="FILLED" if new >= float(o["origQty"]) - 1e-12 else "PARTIALLY_FILLED")
        fee = q * px * (0.00048 if o.get("type") == "MARKET" else self.maker_fee)
        book = self.trades.setdefault(oid, [])
        book.append({"id": f"t{oid}-{len(book)}", "orderId": oid, "commission": str(fee), "maker": True,
                     "price": o["price"], "qty": f"{q:.4f}", "time": int(self.now_fn() * 1000)})

    def bot_orders(self, name: str) -> dict[str, dict]:
        return {k: v for k, v in self.orders.items() if self.placer.get(k) == name}


def cfg_for(name: str, **extra) -> dict:
    c = {**eg.DEFAULT, "enabled": True, "dry_run": False, "symbol": "BTCUSDT", "sides": ["LONG"], "regime_sma": 100,
         "order_qty": "0.0012", "stress_budget_frac": 0.0, "daily_loss_stop_usd": 0.0, "max_notional_usd": 4000.0,
         "step_pct": STEP[name], "target_pct": TARGET[name], **extra}
    if TAGS[name]:
        c["cid_tag"] = TAGS[name]
    return c


class Stand:
    """Несколько сеток на одной бирже; round() — проход каждой сетки (новый Grid с диска) + проверка инвариантов."""

    def __init__(self, tmp: Path, names, cls=SharedEx, named: bool = False):
        self.tmp, self.names, self.named = tmp, list(names), named
        self.px, self.clock = Px(), {"t": 1_800_000_000.0}
        self.ex = cls(self.px, self.clock)
        self.regime = {n: True for n in names}
        self.sends = {n: [] for n in names}
        self.cfg = {n: cfg_for(n) for n in names}
        self.g: dict[str, eg.Grid] = {}

    def paths(self, n):
        return self.tmp / f"{n}_st.json", self.tmp / f"{n}_journal.jsonl"

    def build(self, n):
        """named — как цикл (имя сетки: проверка знака по всем сеткам и имя в сообщениях); без имени — как на b3f92ca."""
        st, jr = self.paths(n)
        kw = {"name": n} if self.named else {}
        return eg.Grid(self.ex, self.cfg[n], state_path=st, journal_path=jr, now_fn=lambda: self.clock["t"],
                       regime_fn=lambda *a, n=n: self.regime[n], send_fn=self.sends[n].append, **kw)

    def round(self, lose_for=None):
        self.clock["t"] += 10
        for n in self.names:
            self.ex.actor = n
            if n == lose_for:
                self.ex.lose = "after"
            self.g[n] = self.build(n)
            self.g[n].tick()
            self.ex.lose = None
        self.ex.actor = None
        self.check()

    # ---------- инварианты после каждого прохода
    def refs(self, n) -> dict[str, str]:
        """Ордера, которые учёт сетки ведёт: {orderId: роль}."""
        out = {}
        for side in ("LONG", "SHORT"):
            s = self.g[n].st[side]
            if s.get("entry"):
                out[str(s["entry"]["id"])] = f"{side} вход"
            for lot in s["lots"]:
                if lot.get("tp_order"):
                    out[str(lot["tp_order"]["id"])] = f"{side} тейк"
            for x in s["strays"]:
                out[str(x["id"])] = f"{side} лишний"
            if s.get("flatten") and s["flatten"].get("id"):
                out[str(s["flatten"]["id"])] = f"{side} market"
        return out

    def check(self):
        for actor, oid in self.ex.cancels:
            owner = self.ex.placer.get(oid)
            assert owner in (None, actor), f"сетка {actor} сняла ордер {oid} сетки {owner}"
        for n in self.names:
            for oid, role in self.refs(n).items():
                owner = self.ex.placer.get(oid)
                assert owner == n, f"сетка {n} ведёт как свой ({role}) ордер {oid} сетки {owner}"
            for side in ("LONG", "SHORT"):
                assert not self.g[n].st[side]["strays"], f"у сетки {n} лишние ордера: {self.g[n].st[side]['strays']}"
                p = self.g[n].st[side].get("pending")
                if p:
                    hit = [k for k, v in self.ex.orders.items() if v["clientOrderId"] == p["cid"]]
                    assert all(self.ex.placer.get(k) == n for k in hit), f"намерение {n} совпало с чужим ордером"

    # ---------- деньги сетки по бирже (только её ордера — по placer)
    def exchange_view(self, n, mid):
        cash = net = fees = 0.0
        for oid, o in self.ex.bot_orders(n).items():
            for t in self.ex.trades.get(oid, []):
                q, p = float(t["qty"]), float(t["price"])
                sgn = 1 if o["side"] == "BUY" else -1
                net += sgn * q
                cash -= sgn * q * p
                fees += float(t["commission"])
        return cash + net * mid, net, fees

    def lots_qty(self, n):
        return sum(float(l["qty"]) for l in self.g[n].st["LONG"]["lots"])

    def position(self):
        return next(float(p["size"]) for p in self.ex.futures_positions() if p["side"] == "LONG")


def run_scenario(st: Stand) -> None:
    """Входы, частичный вход, потерянный ответ на тейк, частичный тейк, тейк, закрытие одной сетки по режиму."""
    names = st.names
    news = [n for n in names if n != "BTC"]
    lost = news[0]
    part = news[-1] if len(news) > 1 else "BTC"              # частичный вход — не у той же сетки, что теряет ответ
    st.round()                                               # входы: BTC 99 400, новые 99 900
    for n in names:
        e = st.g[n].st["LONG"]["entry"]
        assert e and st.ex.placer[e["id"]] == n
    # частичное исполнение входа одной сетки
    pe = st.g[part].st["LONG"]["entry"]["id"]
    st.ex.fill(pe, "0.0006")
    st.round()
    assert st.lots_qty(part) == pytest.approx(0.0006) and st.g[part].st["LONG"]["entry"]["id"] == pe
    # цена вниз: входы всех сеток исполняются; у сетки lost ответ на постановку тейка потерян
    st.ex.fill(pe)
    st.px.mid = 99_390.0
    st.round(lose_for=lost)
    assert st.g[lost].st["LONG"]["pending"] and st.g[lost].st["LONG"]["pending"]["kind"] == "t"
    st.round()                                               # тейк с потерянным ответом найден по cid и привязан
    assert not st.g[lost].st["LONG"]["pending"]
    tp = st.g[lost].st["LONG"]["lots"][0]["tp_order"]
    assert st.ex.placer[tp["id"]] == lost
    for n in names:
        assert st.lots_qty(n) == pytest.approx(0.0012), n
    # частичный тейк, затем цена вверх и тейк целиком
    st.ex.fill(tp["id"], "0.0006")
    st.round()
    assert st.lots_qty(lost) == pytest.approx(0.0006)
    st.px.mid = 100_300.0
    st.ex.fill(tp["id"])
    st.round()
    st.round()
    assert st.lots_qty(lost) == pytest.approx(0.0) and st.g[lost].st["LONG"]["n_tps"] == 1
    assert st.g[lost].st["LONG"]["realized"] == pytest.approx(0.0012 * (100_239.7 - 99_900.0), abs=1e-6)
    # закрытие по режиму ОДНОЙ сетки (живой BTC): чужие лоты и ордера не тронуты, её market соседи не трогают
    before = {n: (json.dumps(st.g[n].st["LONG"]["lots"], sort_keys=True),
                  {k for k, v in st.ex.bot_orders(n).items() if v["status"] in eg.LIVE}) for n in news}
    cancels0 = len(st.ex.cancels)
    st.regime["BTC"] = False
    st.round()                                               # market отправлен, исполнен наполовину (в открытых)
    fl = st.g["BTC"].st["LONG"]["flatten"]
    assert fl and st.ex.orders[fl["id"]]["status"] == "PARTIALLY_FILLED"
    st.round()
    st.ex.fill(fl["id"])
    st.round()
    st.round()
    assert not st.g["BTC"].st["LONG"]["lots"] and not st.g["BTC"].st["LONG"].get("flatten")
    for n in news:
        lots, live = before[n]
        assert json.dumps(st.g[n].st["LONG"]["lots"], sort_keys=True) == lots, n
        assert {k for k, v in st.ex.bot_orders(n).items() if v["status"] in eg.LIVE} == live, n
    assert all(st.ex.placer.get(oid) == "BTC" for _, oid in st.ex.cancels[cancels0:])
    if len(news) > 1:                                        # вторая сетка закрывается по режиму — остальные целы
        flat2 = news[1]
        keep = [n for n in news if n != flat2]
        before = {n: json.dumps(st.g[n].st["LONG"]["lots"], sort_keys=True) for n in keep}
        st.regime[flat2] = False
        for _ in range(3):
            st.round()
        assert not st.g[flat2].st["LONG"]["lots"]
        assert {n: json.dumps(st.g[n].st["LONG"]["lots"], sort_keys=True) for n in keep} == before


@pytest.mark.parametrize("names", [("BTC", "B34"), ("BTC", "B34", "B49", "B89")], ids=["2grids", "4grids"])
def test_grids_on_one_symbol_never_touch_each_other(tmp_path, names):
    """Две и четыре сетки на одной бирже BTCUSDT: ни одна не усыновляет, не снимает и не записывает в лишние ордер
    соседки; у каждой закрытое, комиссии и лоты — ровно по её собственным ордерам на бирже; сумма лотов = общая позиция;
    закрытие по режиму одной сетки оставляет лоты и ордера остальных. На b3f92ca: соседка усыновляет вход живой BTC
    (у всех сеток префикс b7gB)."""
    st = Stand(tmp_path, names)
    run_scenario(st)
    mid = st.px.mid
    for n in names:
        s = st.g[n].st["LONG"]
        bag = sum(float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
        exch, net, fees = st.exchange_view(n, mid)
        assert st.lots_qty(n) == pytest.approx(net, abs=1e-9), n
        assert s["realized"] + bag == pytest.approx(exch, abs=1e-6), n
        assert s["fees"] == pytest.approx(fees, abs=1e-9), n
    assert sum(st.lots_qty(n) for n in names) == pytest.approx(st.position(), abs=1e-9)
    # общий потолок: каждый лот и каждый стоящий вход — ровно один раз
    used = portfolio.used_usd([st.paths(n)[0] for n in names], [])
    lots_cost = sum(float(l["qty"]) * l["entry"] for n in names for l in st.g[n].st["LONG"]["lots"])
    entries = sum((float(o["origQty"]) - float(o["executedQty"])) * float(o["price"]) for o in st.ex.orders.values()
                  if o["status"] in eg.LIVE and not o["reduceOnly"] and o.get("type") != "MARKET")
    assert used == pytest.approx(lots_cost + entries, abs=1e-6)
    assert sum(portfolio.used_usd([st.paths(n)[0]], []) for n in names) == pytest.approx(used, abs=1e-9)


def test_cid_prefix_is_per_grid_and_legacy_format_unchanged(tmp_path):
    """Каждая сетка ставит ордера только со своим префиксом; у BTC без cid_tag — прежний b7gB…, у ETH — b7gE…"""
    st = Stand(tmp_path, ("BTC", "B34", "B49", "B89"))
    st.round()
    for oid, o in st.ex.orders.items():
        assert o["clientOrderId"].startswith(OWN[st.ex.placer[oid]])
    assert re.fullmatch(r"b7gBLe\d+", st.g["BTC"].st["LONG"]["entry"]["cid"])
    for side in ("LONG", "SHORT"):
        ex = eg.DryExchange(lambda: (2599.99, 2600.01), symbol="ETHUSDT")
        cfg = {**eg.DEFAULT, **eg.TEMPLATES["ETH"], "enabled": True, "sides": [side]}
        g = eg.Grid(ex, cfg, state_path=tmp_path / f"eth_{side}.json", journal_path=tmp_path / f"eth_{side}.jsonl",
                    now_fn=lambda: 1_800_000_000.0)
        g.tick()
        assert re.fullmatch(rf"b7gE{side[0]}e\d+", g.st[side]["entry"]["cid"])


def live_shaped_state(t0: float) -> dict:
    """Учёт формы живого state/weex_grid_state.json (лоты LONG с тейками b7gBLt…, вход b7gBLe…, курсоры, переданный
    SHORT) — фикстура, живой файл тестом не читается."""
    lots = []
    for i, entry in enumerate((99_800.0, 99_200.0, 98_600.0)):
        tp = eg.round_tick(entry * 1.014, 0.1, up=True)
        lots.append({"entry": entry, "qty": "0.0036", "tp": tp, "t": t0 + i, "parent": f"e{i}",
                     "tp_order": {"id": f"tp{i}", "cid": f"b7gBLt{int(t0) + i}{10 + i}", "price": tp, "qty": "0.0036"}})
    long = {**eg.new_side_state(), "lots": lots, "ref": 98_600.0, "seq": 40, "n_entries": 3, "realized": 12.5,
            "fees": 0.4, "entry": {"id": "e3", "cid": f"b7gBLe{int(t0)}39", "price": 98_008.4, "qty": "0.0036"},
            "order_fills": {f"e{i}": {"filled": 0.0036, "val": 0.0036 * lots[i]["entry"], "t": t0} for i in range(3)}}
    short = {**eg.new_side_state(), "transferred_mtm": -3.2,
             "transfers": [{"ts": "2026-10-12T13:00:00+00:00", "qty": "0.0024", "mtm": -3.2, "lots": 2}]}
    return {"symbol": "BTCUSDT", "LONG": long, "SHORT": short, "halted": False, "day": None, "day_start_pnl": 0.0}


def test_legacy_btc_still_owns_live_shaped_state_next_to_new_grids(tmp_path):
    """Живая BTC (без cid_tag) с учётом формы живого: её тейки b7gBLt… и вход b7gBLe… остаются её (ни сирот, ни лишних,
    ни снятий, ни второго тейка), а ордера B34 (b7g3…) на той же бирже она не видит. На b3f92ca: ордера B34 для неё
    «свои сироты» — вход B34 уходит в лишние и снимается."""
    t0 = 1_800_000_000.0
    px, clock = Px(99_000.0), {"t": t0 + 100}
    ex = SharedEx(px, clock)
    st = live_shaped_state(t0)
    for lot in st["LONG"]["lots"]:
        o = lot["tp_order"]
        ex.orders[o["id"]] = {"clientOrderId": o["cid"], "side": "SELL", "positionSide": "LONG", "price": str(o["price"]),
                              "origQty": "0.0036", "status": "NEW", "executedQty": "0", "avgPrice": "0",
                              "reduceOnly": True}
        ex.placer[o["id"]] = "BTC"
        ex.orders[lot["parent"]] = {"clientOrderId": f"b7gBLe{lot['parent']}", "side": "BUY", "positionSide": "LONG",
                                    "price": str(lot["entry"]), "origQty": "0.0036", "status": "FILLED",
                                    "executedQty": "0.0036", "avgPrice": str(lot["entry"]), "reduceOnly": False}
        ex.placer[lot["parent"]] = "BTC"
    e = st["LONG"]["entry"]
    ex.orders["e3"] = {"clientOrderId": e["cid"], "side": "BUY", "positionSide": "LONG", "price": str(e["price"]),
                       "origQty": "0.0036", "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": False}
    ex.placer["e3"] = "BTC"
    for oid, cid, side, price, reduce in (("n1", "b7g3Le18000000501", "BUY", "98900.0", False),
                                          ("n2", "b7g3Lt18000000502", "SELL", "99300.0", True),
                                          ("m1", "6b1f0c9e-manual", "BUY", "95000.0", False)):
        ex.orders[oid] = {"clientOrderId": cid, "side": side, "positionSide": "LONG", "price": price, "origQty": "0.0012",
                          "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": reduce}
        ex.placer[oid] = "B34" if cid.startswith("b7g3") else "manual"
    sp = tmp_path / "weex_grid_state.json"
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"], "release_sides": ["SHORT"],
           "step_pct": 0.6, "target_pct": 1.4, "order_qty": "0.0036", "max_notional_usd": 12000.0,
           "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0, "regime_sma": 100}
    ids0 = set(ex.orders)
    for _ in range(3):
        clock["t"] += 10
        ex.actor = "BTC"
        g = eg.Grid(ex, cfg, state_path=sp, journal_path=tmp_path / "j.jsonl", now_fn=lambda: clock["t"],
                    regime_fn=lambda *a: True)
        g.tick()
    s = g.st["LONG"]
    assert [l["tp_order"]["id"] for l in s["lots"]] == ["tp0", "tp1", "tp2"]
    assert s["entry"]["id"] == "e3" and not s["strays"] and not s["pending"]
    assert ex.cancels == []                                   # ни своих тейков, ни чужих ордеров не снимала
    assert all(ex.orders[k]["status"] == "NEW" for k in ("n1", "n2", "m1", "tp0", "tp1", "tp2", "e3"))
    assert set(ex.orders) == ids0                             # ничего нового не ставила (второго тейка нет)
    assert g.st["SHORT"]["transferred_mtm"] == pytest.approx(-3.2)


# ---------- знак сетки: годность и уникальность
@pytest.fixture
def grid_files(tmp_path, monkeypatch):
    """Файлы сеток во временной папке; BTC — через CONFIG/STATE/JOURNAL (как живые weex_grid_config.json …)."""
    btc = tmp_path / "BTC_cfg.json"
    monkeypatch.setattr(eg, "CONFIG", btc)
    monkeypatch.setattr(eg, "STATE", tmp_path / "BTC_state.json")
    monkeypatch.setattr(eg, "JOURNAL", tmp_path / "BTC_journal.jsonl")
    monkeypatch.setattr(eg.load_config, "__defaults__", (btc, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (btc,))

    def gf(name="BTC"):
        return tmp_path / f"{name}_cfg.json", tmp_path / f"{name}_state.json", tmp_path / f"{name}_journal.jsonl"
    monkeypatch.setattr(eg, "grid_files", gf)
    return tmp_path


def write_cfg(p: Path, name: str, **kw) -> None:
    (p / f"{name}_cfg.json").write_text(json.dumps({**eg.DEFAULT, "enabled": True, "dry_run": False,
                                                     "sides": ["LONG"], "order_qty": "0.0012", "stress_budget_frac": 0.0,
                                                     "daily_loss_stop_usd": 0.0, **kw}), encoding="utf-8")


@pytest.mark.parametrize("dup", ["B", "b"], ids=["same", "case"])
def test_duplicate_tag_halts_both_grids_and_places_nothing(grid_files, monkeypatch, dup):
    """Новая сетка получила знак живой BTC (или тот же без учёта регистра): ОБЕ встают с понятным сообщением, ни одного
    ордера, ни одного запроса к бирже от них. На b3f92ca: проверки нет — обе ставят входы с одним префиксом."""
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "B34"))
    write_cfg(grid_files, "BTC")
    write_cfg(grid_files, "B34", cid_tag=dup)
    px, clock = Px(), {"t": 1_800_000_000.0}
    ex = SharedEx(px, clock)
    sends = []
    r = lp.Runner(send_fn=lambda m: sends.append(m) or True)
    monkeypatch.setattr(r, "_client", lambda: ex)
    monkeypatch.setattr(r, "_portfolio_free", lambda: None)
    r.trend = SimpleNamespace(tick=lambda portfolio_free=None: None)
    r.tick()
    assert ex.orders == {}
    assert len(sends) == 2 and all("совпадает" in m for m in sends)
    assert any("BTC" in m for m in sends) and any("B34" in m for m in sends)
    for n in ("BTC", "B34"):
        with pytest.raises(eg.ConfigError, match="совпадает"):
            r.tick_one(n)
    assert ex.orders == {}


@pytest.mark.parametrize("bad", [None, "", "33", "-", "Б", 3], ids=["null", "empty", "two", "dash", "cyr", "int"])
def test_invalid_tag_halts_without_default(grid_files, monkeypatch, bad):
    """Негодный cid_tag — сетка встаёт (ConfigError), знак по умолчанию не подставляется, ордеров нет."""
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "B34"))
    write_cfg(grid_files, "BTC")
    write_cfg(grid_files, "B34", cid_tag=bad)
    ex = SharedEx(Px(), {"t": 1_800_000_000.0})
    r = lp.Runner()
    monkeypatch.setattr(r, "_client", lambda: ex)
    with pytest.raises(eg.ConfigError, match="cid_tag"):
        r.tick_one("B34")
    with pytest.raises(eg.ConfigError):
        eg.Grid(ex, {**eg.DEFAULT, "cid_tag": bad}, state_path=grid_files / "x.json", journal_path=grid_files / "x.j")
    r.tick_one("BTC")                                          # живая BTC с прежним знаком работает
    assert ex.orders and all(o["clientOrderId"].startswith("b7gB") for o in ex.orders.values())


def test_tag_collision_across_symbols_and_unreadable_peer(grid_files, monkeypatch):
    """Знаки уникальны по ВСЕМ сеткам (и других символов); сетка с нечитаемым конфигом в сравнение не входит (стоит сама)."""
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "ETH", "B34"))
    write_cfg(grid_files, "BTC")
    write_cfg(grid_files, "ETH", symbol="ETHUSDT", cid_tag="3")
    write_cfg(grid_files, "B34", cid_tag="3")
    with pytest.raises(eg.ConfigError, match="ETH"):
        eg.check_tag("B34", lp.grid_config("B34"))
    (grid_files / "ETH_cfg.json").write_text("{битый", encoding="utf-8")
    assert eg.check_tag("B34", lp.grid_config("B34")) == "3"
    with pytest.raises(eg.ConfigError):
        lp.grid_config("ETH")


# ---------- новые сетки: шаблоны, команды, карточка
def test_new_grids_created_off_dry_with_template(grid_files):
    for name, tag, target in (("B34", "3", 0.34), ("B49", "4", 0.49), ("B89", "8", 0.89)):
        assert name in eg.GRIDS
        cfg = lp.grid_config(name)
        assert cfg["enabled"] is False and cfg["dry_run"] is True
        assert (cfg["symbol"], cfg["sides"], cfg["regime_sma"], cfg["step_pct"], cfg["target_pct"]) == \
            ("BTCUSDT", ["LONG"], 100, 0.1, target)
        assert (cfg["order_qty"], cfg["qty_step"], cfg["price_tick"], cfg["qty_max"]) == ("0.0012", 0.0001, 0.1, 0.01)
        assert (cfg["max_lots_per_side"], cfg["max_notional_usd"], cfg["daily_loss_stop_usd"]) == (15, 1500.0, 0.0)
        assert (cfg["stress_budget_frac"], cfg["trail_min_move_pct"], cfg["poll_sec"]) == (0.0, 0.05, 10)
        assert cfg["cid_tag"] == tag and "release_sides" not in cfg
        assert json.loads((grid_files / f"{name}_cfg.json").read_text())["cid_tag"] == tag
    tags = eg.grid_tags()
    assert tags == {"BTC": "B", "ETH": "E", "XAU": "X", "B34": "3", "B49": "4", "B89": "8"}
    assert len({t.upper() for t in tags.values()}) == len(tags)
    assert len({lp.run_files(n, False)[0] for n in eg.GRIDS}) == len(eg.GRIDS)      # у каждой свой учёт


class FakeBook:
    """WeexClient для /weex set: только стакан (сеть в тесте не нужна)."""

    def __init__(self, *a, **k):
        pass

    def book(self, symbol):
        return 80_999.95, 81_000.05


def test_commands_for_new_grids(grid_files, monkeypatch):
    import services.weex_api.client as wc
    monkeypatch.setattr(wc, "WeexClient", FakeBook)
    write_cfg(grid_files, "BTC", order_qty="0.0036", step_pct=0.6, target_pct=1.4)
    out = lp.command("b34 live")
    assert "B34 BTCUSDT" in out and "/weex b34 start" in out
    assert json.loads((grid_files / "B34_cfg.json").read_text())["dry_run"] is False
    assert "B34 BTCUSDT" in lp.command("b34 start")
    assert json.loads((grid_files / "B34_cfg.json").read_text())["enabled"] is True
    lp.command("b49 live")
    lp.command("b89 dry")
    assert json.loads((grid_files / "B49_cfg.json").read_text())["dry_run"] is False
    assert json.loads((grid_files / "B89_cfg.json").read_text())["dry_run"] is True
    assert "B34 BTCUSDT" in lp.command("b34 stop")
    assert json.loads((grid_files / "B34_cfg.json").read_text())["enabled"] is False
    out = lp.set_params("цель 0.4", lambda: 81_000.0, "B49")
    assert "B49 BTCUSDT" in out and json.loads((grid_files / "B49_cfg.json").read_text())["target_pct"] == 0.4
    # живая BTC не тронута ни одной командой новых сеток; её ордер — /weex set qty 0.0012
    btc = json.loads((grid_files / "BTC_cfg.json").read_text())
    assert (btc["order_qty"], btc["dry_run"], btc["enabled"], btc["target_pct"]) == ("0.0036", False, True, 1.4)
    out = lp.command("set qty 0.0012")                              # /weex set qty 0.0012 — ордер живой BTC
    assert "Сетка WEEX BTCUSDT" in out and "0.0012" in out
    btc = json.loads((grid_files / "BTC_cfg.json").read_text())
    assert (btc["order_qty"], btc["dry_run"], btc["enabled"]) == ("0.0012", False, True)
    write_cfg(grid_files, "BTC", order_qty="0.0036")
    lp.command("set ордер 100")                                     # $100 / 81 000 = 0.00123 → вниз до 0.0012
    assert json.loads((grid_files / "BTC_cfg.json").read_text())["order_qty"] == "0.0012"
    for n in ("B34", "B49", "B89"):                                 # команды BTC не трогают новые сетки
        assert json.loads((grid_files / f"{n}_cfg.json").read_text())["order_qty"] == "0.0012"


def test_compact_card_and_long_message_split(grid_files):
    st = Stand(grid_files, ("BTC", "B34"), named=True)
    st.round()
    card = st.g["B34"].card(st.px.mid)
    assert card.startswith("🕸 B34 BTCUSDT — ЖИВАЯ") and len(card.splitlines()) <= 3, card
    assert st.g["BTC"].card(st.px.mid).startswith("🕸 СЕТКА WEEX BTCUSDT")       # карточка живой BTC прежняя
    off = eg.Grid(st.ex, {**cfg_for("B49"), "enabled": False}, state_path=grid_files / "off.json",
                  journal_path=grid_files / "off.jsonl", name="B49")
    assert len(off.card(st.px.mid).splitlines()) == 1
    text = "\n\n".join(["x" * 1500] * 6)
    parts = lp.split_message(text)
    assert all(len(p) <= 4096 for p in parts) and "\n\n".join(parts) == text
    huge = lp.split_message("y" * 9000)
    assert all(len(p) <= 4096 for p in huge) and "".join(huge) == "y" * 9000


def test_new_grid_messages_name_the_grid(grid_files):
    """Сообщения сеток одного символа различимы: у новой — «B34 BTCUSDT», у живой BTC — прежнее «BTCUSDT»."""
    st = Stand(grid_files, ("BTC", "B34"), named=True)
    st.round()
    st.px.mid = 99_850.0
    st.round()
    st.regime["B34"] = False
    st.round()
    st.round()
    assert any("Сетка WEEX B34 BTCUSDT" in m for m in st.sends["B34"])
    assert not st.sends["BTC"]
    assert eg.grid_label("BTC", "BTCUSDT") == "BTCUSDT" and eg.grid_label("ETH", "ETHUSDT") == "ETHUSDT"


# ---------- потерянный ответ в плотном окне соседей: история без листания, сделки делением окна
class RealisticHistoryEx(SharedEx):
    """История как у WEEX (проверено 15.10): page игнорируется — любая страница = новейшие 100 окна; окно startTime/
    endTime работает; сделки — новейшие 100 окна."""

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [{"orderId": k, **v} for k, v in self.orders.items()
                if (start_ms is None or v.get("time", 0) >= start_ms) and (end_ms is None or v.get("time", 0) <= end_ms)]
        rows.sort(key=lambda r: -r.get("time", 0))
        return rows[:limit]


def crowd(ex: SharedEx, t_ms: int, n: int, prefix: str = "b7g4") -> None:
    """n исполненных ордеров соседней сетки ПОСЛЕ t_ms в пределах окна +10 мин (BUY и SELL вперемешку): новейшие 100
    окна — все соседские."""
    for i in range(n):
        oid = f"c{i}"
        side = "BUY" if i % 2 else "SELL"
        at = t_ms + 1_000 + i * (588_000 // n)
        ex.orders[oid] = {"clientOrderId": f"{prefix}L{'e' if side == 'BUY' else 't'}{i}", "side": side,
                          "positionSide": "LONG", "price": "99000.0", "origQty": "0.0012", "status": "FILLED",
                          "executedQty": "0.0012", "avgPrice": "99000.0", "reduceOnly": side == "SELL", "time": at}
        ex.placer[oid] = "B49"
        ex.trades[oid] = [{"id": f"t{oid}", "orderId": oid, "commission": "0.019", "maker": True, "price": "99000.0",
                           "qty": "0.0012", "time": at, "side": side, "positionSide": "LONG"}]


def test_lost_entry_found_in_crowded_window_of_neighbour_grids(tmp_path):
    """Ответ на вход B34 потерян, вход сразу исполнился (в открытых его нет), а в окне ±10 мин — 150 ордеров соседней
    сетки (история без листания отдаёт одни и те же 100). Ордер находится (деление окна истории), исполнение учтено
    лотом, второго входа нет. На b3f92ca: 10 одинаковых страниц → «история слишком плотная», сторона стоит, лота нет."""
    st = Stand(tmp_path, ("B34",), cls=RealisticHistoryEx)
    st.round()
    e = st.g["B34"].st["LONG"]["entry"]
    st.px.mid = 100_400.0                                    # вход отстал — переставится; ответ на новый потерян
    st.round(lose_for="B34")
    p = st.g["B34"].st["LONG"]["pending"]
    assert p and p["kind"] == "e" and st.ex.orders[e["id"]]["status"] == "CANCELED"
    lost = next(k for k, v in st.ex.orders.items() if v["clientOrderId"] == p["cid"])
    crowd(st.ex, st.ex.orders[lost]["time"], 150)
    st.ex.fill(lost)                                          # исполнился сразу — в открытых его нет
    for _ in range(int(eg.PENDING_TTL // 10) + 8):
        st.round()
    s = st.g["B34"].st["LONG"]
    assert not s["pending"] and [l["parent"] for l in s["lots"]] == [lost]
    entries = [k for k, v in st.ex.bot_orders("B34").items() if not v["reduceOnly"] and v["status"] in ("NEW", "FILLED")]
    assert len(entries) == 2                                  # найденный (исполнен) + следующий уровень, не дубль
    assert not any("слишком плотная" in m for m in st.sends["B34"])


def test_lost_filled_entry_found_by_trades_past_twenty_neighbour_orders(tmp_path):
    """История ордер так и не показала (годный пустой список), в сделках окна — 60 ордеров соседней сетки: сделки другого
    направления отсеиваются без детали, прочитанные чужие запоминаются в намерении — поиск доходит до своего ордера за
    несколько попыток. На b3f92ca: каждые 30 с те же 20 деталей, поиск неполон навсегда — исполнение без учёта и тейка."""
    st = Stand(tmp_path, ("B34",), cls=RealisticHistoryEx)
    st.round()
    st.px.mid = 100_400.0
    st.round(lose_for="B34")
    p = st.g["B34"].st["LONG"]["pending"]
    lost = next(k for k, v in st.ex.orders.items() if v["clientOrderId"] == p["cid"])
    t_ms = st.ex.orders[lost]["time"]
    crowd(st.ex, t_ms, 120)
    st.ex.fill(lost)
    st.ex.trades[lost][0]["time"] = t_ms - 590_000                # самая старая в окне: новейшие 100 — соседи
    st.ex.order_history = lambda *a, **kw: []
    for _ in range(int(eg.PENDING_TTL // 10) + 60):
        st.round()
        if not st.g["B34"].st["LONG"]["pending"]:
            break
    s = st.g["B34"].st["LONG"]
    assert not s["pending"] and [l["parent"] for l in s["lots"]] == [lost]


class CidlessDetailEx(RealisticHistoryEx):
    """Деталь ордеров из hide приходит без clientOrderId (иначе годная: тот же orderId, статус, объёмы)."""

    def __init__(self, px, clock):
        super().__init__(px, clock)
        self.hide: set[str] = set()

    def order_info(self, oid):
        r = super().order_info(oid)
        return {k: v for k, v in r.items() if k != "clientOrderId"} if str(oid) in self.hide else r


def test_lost_entry_detail_without_cid_keeps_intent(tmp_path):
    """Ответ на вход B34 потерян, ордер исполнился; история пуста, а деталь ордера из сделок окна пришла без clientOrderId.
    Владелец не установлен — намерение остаётся, второго входа нет, оператору одно сообщение. На b3f92ca: деталь без cid
    = «не наш», поиск «полон» → «не дошёл» → второй вход поверх неучтённой позиции."""
    st = Stand(tmp_path, ("B34",), cls=CidlessDetailEx)
    st.round()
    st.px.mid = 100_400.0
    st.round(lose_for="B34")
    p = st.g["B34"].st["LONG"]["pending"]
    lost = next(k for k, v in st.ex.orders.items() if v["clientOrderId"] == p["cid"])
    st.ex.fill(lost)
    st.ex.hide.add(lost)
    st.ex.order_history = lambda *a, **kw: []
    for _ in range(int(eg.PENDING_TTL // 10) + 20):
        st.round()
    s = st.g["B34"].st["LONG"]
    assert s["pending"] and s["pending"]["cid"] == p["cid"] and not s["lots"]
    live_entries = [k for k, v in st.ex.bot_orders("B34").items() if not v["reduceOnly"] and v["status"] == "NEW"]
    assert live_entries == []                                 # нового входа поверх неясного нет
    assert sum(1 for m in st.sends["B34"] if "поиск по сделкам неполон" in m) == 1


class FlakyEx(SharedEx):
    """Ответы-ошибки в проход ОДНОЙ сетки: bad_open — объект ошибки вместо списка открытых, empty_info — {} на деталь."""

    def __init__(self, px, clock):
        super().__init__(px, clock)
        self.bad_open = self.empty_info = None

    def open_orders(self, symbol):
        if self.actor is not None and self.actor == self.bad_open:
            return {"code": "40001", "msg": "system busy"}
        return super().open_orders(symbol)

    def order_info(self, oid):
        if self.actor is not None and self.actor == self.empty_info:
            return {}
        return super().order_info(oid)


def test_error_and_empty_answers_of_one_grid_touch_no_neighbour(tmp_path):
    """Входы трёх сеток BTCUSDT исполнились. В проход B34 биржа отдала объект ошибки вместо списка открытых, в проход B49 —
    пустые детали: эти сетки ничего не ставят, не снимают и не теряют учёт; живая BTC в том же проходе учитывает только
    свой вход. Следующий нормальный проход — у каждой ровно свой лот и свой тейк, сумма лотов = общая позиция."""
    st = Stand(tmp_path, ("BTC", "B34", "B49"), cls=FlakyEx)
    st.round()
    st.px.mid = 99_390.0                                      # входы всех трёх исполняются
    st.ex.bad_open, st.ex.empty_info = "B34", "B49"
    placed0, cancels0 = dict(st.ex.placer), len(st.ex.cancels)
    disk34 = json.loads(st.paths("B34")[0].read_text())
    st.clock["t"] += 10
    for n in st.names:
        st.ex.actor = n
        st.g[n] = st.build(n)
        if n == "B34":
            with pytest.raises(WeexIncomplete):
                st.g[n].tick()
        else:
            st.g[n].tick()
    st.ex.actor = None
    st.check()
    new = {k: v for k, v in st.ex.placer.items() if k not in placed0}
    assert set(new.values()) <= {"BTC"} and all(a == "BTC" for a, _ in st.ex.cancels[cancels0:])
    after34 = json.loads(st.paths("B34")[0].read_text())
    assert after34["LONG"] == disk34["LONG"] and after34["last_tick_error"]["fatal"] is True
    assert st.g["B49"].st["LONG"]["entry"] and not st.g["B49"].st["LONG"]["lots"]
    assert st.lots_qty("BTC") == pytest.approx(0.0012)
    st.ex.bad_open = st.ex.empty_info = None
    st.round()
    st.round()
    for n in st.names:
        lots = st.g[n].st["LONG"]["lots"]
        assert st.lots_qty(n) == pytest.approx(0.0012) and lots[0]["tp_order"], n
        assert st.ex.placer[lots[0]["tp_order"]["id"]] == n
    assert sum(st.lots_qty(n) for n in st.names) == pytest.approx(st.position(), abs=1e-9)


class LostMarketEx(RealisticHistoryEx):
    """Рыночное закрытие принимается, ответ теряется; до lag_until биржа не показывает его ни в истории, ни в сделках окна
    (запаздывание). Счётчик запросов поиска: история и сделки окна."""

    def __init__(self, px, clock):
        super().__init__(px, clock)
        self.clock, self.lag_until = clock, 0.0
        self.calls = {"history": 0, "window_trades": 0}
        self.half_market = False

    def place_market(self, *a, **kw):
        super().place_market(*a, **kw)
        raise TimeoutError("synthetic: market accepted, response lost")

    def order_history(self, *a, **kw):
        self.calls["history"] += 1
        return [] if self.clock["t"] < self.lag_until else super().order_history(*a, **kw)

    def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
        if order_id is None:
            self.calls["window_trades"] += 1
            if self.clock["t"] < self.lag_until:
                return []
        return super().user_trades(symbol, order_id, start_ms, end_ms)


def test_regime_flip_four_grids_lost_market_answers_search_throttled(tmp_path):
    """Режим сменился у всех четырёх сеток BTC сразу, ответы на все четыре market потеряны, биржа минуту их не показывает.
    Поиск потерянного market — не чаще раза в 30 с на сетку (а не каждый проход: иначе 4 тяжёлых поиска за проход упрутся
    в лимит веса WEEX); второго market нет; когда биржа показала ордера — каждая сетка закрыла ровно свои лоты."""
    names = ("BTC", "B34", "B49", "B89")
    st = Stand(tmp_path, names, cls=LostMarketEx)
    st.round()
    st.px.mid = 99_390.0
    st.round()
    st.round()
    assert all(st.lots_qty(n) == pytest.approx(0.0012) for n in names)
    for n in names:
        st.regime[n] = False
    st.ex.lag_until = st.clock["t"] + 10 + 65                 # биржа «видит» market только через 65 с после отправки
    st.round()                                                 # 4 market отправлены, ответы потеряны
    assert all(st.g[n].st["LONG"]["flatten"] and not st.g[n].st["LONG"]["flatten"].get("id") for n in names)
    st.ex.calls = {"history": 0, "window_trades": 0}
    for _ in range(7):                                         # 70 с: поиск на 10-й, 40-й и 70-й секунде
        st.round()
    assert st.ex.calls["history"] <= 3 * len(names) and st.ex.calls["window_trades"] <= 3 * len(names), st.ex.calls
    for n in names:
        s = st.g[n].st["LONG"]
        assert not s["lots"] and not s.get("flatten"), n
        markets = [k for k, v in st.ex.bot_orders(n).items() if v.get("type") == "MARKET"]
        assert len(markets) == 1, (n, markets)
    assert st.position() == pytest.approx(0.0, abs=1e-9)


# ---------- режим: одна выборка дневок на все сетки символа
def test_regime_fetched_once_for_four_btc_grids_and_failure_backs_off(monkeypatch):
    calls = []
    today = 20_000
    now = {"t": today * 86400 + 600.0}

    def rows(sym, n):
        calls.append(sym)
        return [[d * 86_400_000, 0, 0, 0, str(1000.0 + d - today), 0, (d + 1) * 86_400_000 - 1]
                for d in range(today - n, today)]
    monkeypatch.setattr(eg, "_REGIME_CACHE", {})
    for _ in range(3):                                         # 3 прохода × 4 сетки BTC
        for _ in range(4):
            assert eg.regime_up("BTCUSDT", 100, now=now["t"], fetch=rows) is True
        now["t"] += 10
    assert len(calls) == 1
    monkeypatch.setattr(eg, "_REGIME_CACHE", {})
    calls.clear()

    def boom(sym, n):
        calls.append(sym)
        raise TimeoutError("binance timeout")
    for _ in range(3):
        for _ in range(4):
            assert eg.regime_up("BTCUSDT", 100, now=now["t"], fetch=boom) is None
        now["t"] += 10
    assert len(calls) == 1                                     # не 12 таймаутов
    now["t"] += eg.REGIME_RETRY
    assert eg.regime_up("BTCUSDT", 100, now=now["t"], fetch=rows) is True and len(calls) == 2
