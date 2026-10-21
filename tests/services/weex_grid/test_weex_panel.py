"""Пульт сеток в Telegram (21.10): заряженные шорт-сетки SB/SE, закрытие позиций ботов по команде (тот же путь, что
закрытие по режиму), пауза всем, ордер ±, кнопки и подтверждения. Только имитатор биржи и временные файлы."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop
from services.weex_grid import panel


# ---------------------------------------------------------------- заряженные шорт-сетки
@pytest.fixture
def grid_files(tmp_path, monkeypatch):
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
    base = {**eg.DEFAULT, **eg.TEMPLATES.get(name, {}), "enabled": True, "dry_run": False, "order_qty": "0.0012",
            "stress_budget_frac": 0.0, "daily_loss_stop_usd": 0.0}
    if name in ("BTC",):
        base["sides"] = ["LONG"]
    (p / f"{name}_cfg.json").write_text(json.dumps({**base, **kw}), encoding="utf-8")


def write_state(p: Path, name: str, lots=(), side="LONG", entry=None) -> None:
    st = {"symbol": "BTCUSDT", "LONG": eg.new_side_state(), "SHORT": eg.new_side_state(), "halted": False}
    st[side]["lots"] = [{"entry": e, "qty": q, "tp": e * 1.014, "tp_order": None, "t": 1.0 + i, "parent": f"p{i}"}
                        for i, (e, q) in enumerate(lots)]
    st[side]["entry"] = entry
    (p / f"{name}_state.json").write_text(json.dumps(st), encoding="utf-8")


def test_short_presets_registered_disabled_without_regime(grid_files):
    for name, sym in (("SB", "BTCUSDT"), ("SE", "ETHUSDT")):
        assert name in eg.GRIDS
        cfg = eg.peek_config(name)                               # файла нет — шаблон, файл не создаётся
        assert cfg["symbol"] == sym and cfg["sides"] == ["SHORT"] and not cfg["regime_sma"]
        assert cfg["enabled"] is False and cfg["dry_run"] is True       # заряжена, но выключена
        assert not (grid_files / f"{name}_cfg.json").exists()
    tags = {n: eg.check_tag(n, eg.peek_config(n)) for n in eg.GRIDS}    # знаки ордеров не совпадают
    assert len({t.upper() for t in tags.values()}) == len(tags)


# ---------------------------------------------------------------- закрытие по команде в движке
class Px:
    def __init__(self, mid=100_000.0):
        self.mid = mid

    def __call__(self):
        return self.mid - 0.05, self.mid + 0.05


def make(tmp_path, px, **cfg):
    conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "stress_budget_frac": 0.0,
            "daily_loss_stop_usd": 0.0, "order_qty": "0.001", "step_pct": 1.0, "target_pct": 1.0, **cfg}
    clock = {"t": 1_800_000_000.0}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])

    def now():
        clock["t"] += 10
        return clock["t"]
    return eg.Grid(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now), ex


def _fill_two_lots(g, px):
    g.tick()
    for _ in range(120):                                         # плавно вниз через два входа
        px.mid -= 20
        g.tick()
        if len(g.st["LONG"]["lots"]) >= 2:
            break
    assert len(g.st["LONG"]["lots"]) == 2


def test_flatten_request_closes_bot_lots_only_and_places_no_new_entries(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)
    # ручная позиция оператора на той же стороне (UUID-клиентский id): её закрытие по команде не трогает
    ex.place_limit("BTCUSDT", "BUY", "LONG", "0.005", str(px.mid + 100), "5f0c2b8e-manual", post_only=False)
    ex.book("BTCUSDT")
    _fill_two_lots(g, px)
    bot_q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    g.cfg["enabled"] = False
    g.cfg["flatten_request"] = ["LONG"]
    g.tick()
    g.tick()
    mk = [o for o in ex.orders.values() if o.get("type") == "MARKET"]
    assert len(mk) == 1 and mk[0]["reduceOnly"] and mk[0]["side"] == "SELL"
    assert abs(float(mk[0]["origQty"]) - bot_q) < 1e-9                    # ровно лоты бота
    assert g.st["LONG"]["lots"] == [] and not g.st["LONG"].get("flatten")
    live = [o for o in ex.open_orders("BTCUSDT") if o["clientOrderId"].startswith(eg.PREFIX)]
    assert live == []                                                     # ни входа, ни тейков
    pos = {p["side"]: float(p["size"]) for p in ex.futures_positions()}
    assert abs(pos.get("LONG", 0.0) - 0.005) < 1e-9                       # ручная позиция цела
    for _ in range(3):                                                    # дальнейшие проходы ничего не ставят
        px.mid -= 500
        g.tick()
    assert g.st["LONG"]["lots"] == [] and not [o for o in ex.open_orders("BTCUSDT")
                                               if o["clientOrderId"].startswith(eg.PREFIX)]


@pytest.mark.parametrize("bad", ["LONG", ["UP"], {"LONG": 1}])
def test_bad_flatten_request_halts(tmp_path, bad):
    g, _ = make(tmp_path, Px(), flatten_request=bad)
    with pytest.raises(eg.ConfigError):
        g.tick()


def test_flatten_request_without_lots_does_nothing(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, enabled=False, flatten_request=["LONG"])
    g.tick()
    assert not [o for o in ex.orders.values() if o.get("type") == "MARKET"]


# ---------------------------------------------------------------- команды пульта (loop.command)
def test_close_grid_sets_request_and_disables(grid_files):
    write_cfg(grid_files, "BTC")
    write_state(grid_files, "BTC", lots=[(84000.0, "0.0012")])
    msg = loop.command("btc close")
    cfg = json.loads((grid_files / "BTC_cfg.json").read_text())
    assert cfg["enabled"] is False and cfg["flatten_request"] == ["LONG"] and "закрываю" in msg
    assert "Ручные позиции не трогаю" in msg


def test_close_grid_without_lots_just_disables(grid_files):
    write_cfg(grid_files, "B34")
    msg = loop.command("b34 close")
    cfg = json.loads((grid_files / "B34_cfg.json").read_text())
    assert cfg["enabled"] is False and cfg["flatten_request"] == [] and "позиций бота нет" in msg


def test_go_starts_live_and_clears_close_request(grid_files):
    write_cfg(grid_files, "SB", dry_run=True, enabled=False, flatten_request=["SHORT"])
    msg = loop.command("sb go")
    cfg = json.loads((grid_files / "SB_cfg.json").read_text())
    assert cfg["enabled"] is True and cfg["dry_run"] is False and "flatten_request" not in cfg
    assert "ЖИВАЯ" in msg


def test_pause_all_only_live_enabled(grid_files, monkeypatch):
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "B34", "XAU", "SB"))
    write_cfg(grid_files, "BTC")
    write_cfg(grid_files, "B34")
    write_cfg(grid_files, "XAU", dry_run=True)                           # холостая — не трогать
    write_cfg(grid_files, "SB", dry_run=True, enabled=False)
    msg = loop.command("pauseall")
    en = {n: json.loads((grid_files / f"{n}_cfg.json").read_text())["enabled"] for n in ("BTC", "B34", "XAU", "SB")}
    assert en == {"BTC": False, "B34": False, "XAU": True, "SB": False} and "Пауза" in msg


def test_close_all_only_live_grids_with_positions(grid_files, monkeypatch):
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "B34", "SB"))
    write_cfg(grid_files, "BTC")
    write_cfg(grid_files, "B34")
    write_cfg(grid_files, "SB")
    write_state(grid_files, "BTC", lots=[(84000.0, "0.0012")])
    write_state(grid_files, "SB", lots=[(85000.0, "0.0012")], side="SHORT")
    loop.command("closeall")
    req = {n: json.loads((grid_files / f"{n}_cfg.json").read_text()).get("flatten_request") for n in ("BTC", "B34", "SB")}
    assert req == {"BTC": ["LONG"], "B34": None, "SB": ["SHORT"]}


@pytest.mark.parametrize("name, start, sign, price, want", [
    ("BTC", "0.0012", 1, 84000.0, "0.0018"),      # +≈$50: 50/84000 = 0.0006
    ("BTC", "0.0012", -1, 84000.0, "0.0006"),
    ("BTC", "0.0003", -1, 84000.0, "0.0001"),     # не ниже шага объёма
    ("SE", "0.040", 1, 2500.0, "0.060"),          # ETH: 50/2500 = 0.020
])
def test_bump_qty_about_50_usd_within_limits(grid_files, name, start, sign, price, want):
    write_cfg(grid_files, name, order_qty=start)
    loop.bump_qty(name, sign, lambda: price)
    assert json.loads((grid_files / f"{name}_cfg.json").read_text())["order_qty"] == want


def test_bump_qty_at_max_is_refused(grid_files):
    write_cfg(grid_files, "BTC", order_qty="0.0100")
    msg = loop.bump_qty("BTC", 1, lambda: 84000.0)
    assert "границе" in msg and json.loads((grid_files / "BTC_cfg.json").read_text())["order_qty"] == "0.0100"


# ---------------------------------------------------------------- общая сверка позиции: сторона SB
def _g(sym, sides, release=(), lots=0.0, side="SHORT"):
    st = {side: {"lots": [{"qty": str(lots)}] if lots else []}}
    return {"symbol": sym, "sides": list(sides), "release_sides": list(release), "qty_step": 0.0001, "state": st}


def test_released_side_audited_when_short_grid_owns_it():
    btc = _g("BTCUSDT", ["LONG"], release=["SHORT"])
    sb = _g("BTCUSDT", ["SHORT"], lots=0.0024)
    gaps = loop.position_gaps([btc, sb], set(), [{"symbol": "BTCUSDT", "side": "SHORT", "size": "0.0024"}])
    assert gaps["BTCUSDT:SHORT"]["deficit"] is False
    gaps = loop.position_gaps([btc, sb], set(), [])                      # оператор закрыл всё руками
    assert gaps["BTCUSDT:SHORT"]["deficit"] is True
    gaps = loop.position_gaps([btc, sb], set(), [{"symbol": "BTCUSDT", "side": "SHORT", "size": "0.0100"}])
    assert gaps["BTCUSDT:SHORT"]["deficit"] is False                      # ручной шорт сверху — избыток, не блок
    assert "BTCUSDT:SHORT" not in loop.position_gaps([btc], set(), [])   # без SB сторона оператора не сверяется


# ---------------------------------------------------------------- кнопки
def _info(name, **kw):
    cfg = {**eg.DEFAULT, **eg.TEMPLATES.get(name, {}), **kw}
    return panel.grid_info(name, cfg, None)


def test_parse_and_command_strings():
    assert panel.parse("wx:a:go:SB") == {"kind": "a", "action": "go", "name": "SB"}
    assert panel.parse("wx:a:ca:ALL")["action"] == "ca"
    assert panel.parse("wx:y:cl:BTC:1792600000")["ts"] == 1792600000
    for bad in ("", "wx", "rh:x", "wx:a:xx:SB", "wx:a:go:XAU", "wx:y:go:SB:abc", "wx:a:go"):
        assert panel.parse(bad) is None, bad
    assert panel.command_for("go", "SB") == "sb go" and panel.command_for("pa", "ALL") == "pauseall"
    assert panel.command_for("q+", "BTC") == "btc qty+" and panel.command_for("ca", "ALL") == "closeall"
    for cmd in ("sb go", "btc qty+", "b34 close", "eth stop"):           # loop.command знает каждое имя
        assert cmd.split()[0] in loop.NAMES


def test_confirmation_needed_and_expires():
    for a in ("go", "st", "cl", "pa", "ca"):
        assert panel.needs_confirm(a)
    assert not panel.needs_confirm("q+") and not panel.needs_confirm("q-")
    d = panel.parse(panel.confirm_data("cl", "BTC", 1000.0))
    assert not panel.expired(d, 1000.0 + panel.CONFIRM_TTL) and panel.expired(d, 1000.0 + panel.CONFIRM_TTL + 1)
    assert panel.expired(d, 999.0)                                        # из будущего — нет


def test_build_rows_follow_state_and_fit_telegram():
    infos = [_info("BTC", enabled=True, dry_run=False, sides=["LONG"]),
             _info("SB")]                                                 # заряжена, выключена
    infos[0]["lots"]["LONG"] = 2
    text, rows = panel.build(infos, {"BTCUSDT": 84000.0})
    assert rows[0] == [("⏸ Пауза всем", "wx:a:pa:ALL"), ("⛔ Закрыть позиции ботов", "wx:a:ca:ALL")]
    btc, sb = rows[1], rows[2]
    assert btc[0] == ("⏸ BTC", "wx:a:st:BTC") and ("⛔ BTC", "wx:a:cl:BTC") in btc
    assert sb[0] == ("▶️ SB", "wx:a:go:SB") and not any(d.startswith("wx:a:cl") for _, d in sb)
    assert all(len(d.encode()) <= 64 for row in rows for _, d in row)
    assert "🟢 ЖИВАЯ" in text and "заряжена" in text and "≈$101" in text and "шорт" in text


def test_question_names_side_params_and_no_regime():
    q = panel.question("go", "SB", _info("SB"))
    assert "ЗАПУСТИТЬ ЖИВЫМ" in q and "шорт BTCUSDT" in q and "без режима SMA" in q and "$3,000" in q
    assert "ВСЕХ ботов" in panel.question("ca", "ALL", None)
