"""22.10: риск-пинги сеток и сводка (services/grid_report.py) — без сети и без учёта: синтетические строки сеток."""
from __future__ import annotations

from datetime import datetime, timezone

from services import grid_report as gr

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def row(name, sym="BTCUSDT", bag=0.0, blocked="", lots=1, closed=0.0, error=""):
    return {"name": name, "sym": sym, "step": 0.1, "target": 0.34, "sides": ["LONG"], "lots": lots, "qty": 0.001,
            "bag": bag, "closed": closed, "total": closed + bag, "cost": 100.0 * lots, "blocked": blocked,
            "error": error}


def test_cap_ping_once_per_day_per_grid():
    rows = [row("B34", blocked="достигнут потолок позиции"), row("B49")]
    ev, st = gr.risk_events(rows, {}, {}, NOW)
    assert len(ev) == 1 and "B34 на потолке" in ev[0]
    ev2, st2 = gr.risk_events(rows, {}, st, NOW)
    assert ev2 == []                                            # тот же день — молчит
    ev3, _ = gr.risk_events(rows, {}, st2, NOW.replace(day=23))
    assert len(ev3) == 1                                        # новый день — снова


def test_bag_levels_with_hysteresis():
    ev, st = gr.risk_events([row("B34", bag=-120)], {}, {}, NOW)
    assert any("ниже −100" in e for e in ev) and st["bag"] == [100.0]
    ev, st = gr.risk_events([row("B34", bag=-90)], {}, st, NOW)          # выше уровня, но ниже половины — уровень держится
    assert ev == [] and st["bag"] == [100.0]
    ev, st = gr.risk_events([row("B34", bag=-120)], {}, st, NOW)
    assert ev == []                                             # повторно не пингует
    ev, st = gr.risk_events([row("B34", bag=-40)], {}, st, NOW)          # вернулся выше половины — уровень снят
    assert st["bag"] == []
    ev, st = gr.risk_events([row("B34", bag=-300)], {}, st, NOW)         # сразу два уровня — одно сообщение о худшем
    assert len(ev) == 1 and "ниже −250" in ev[0] and st["bag"] == [100.0, 250.0]


def test_unreadable_grid_not_counted_in_bag():
    ev, _ = gr.risk_events([row("B34", bag=-500, error="JSONDecodeError")], {}, {}, NOW)
    assert ev == []


def test_pause_after_cap_is_not_resume():
    """25.10 (аудит GPT G2): ушла с потолка на паузу — не «снова ставит входы»; входы разрешены — да."""
    from datetime import timedelta
    _, st = gr.risk_events([row("B34", blocked="достигнут потолок позиции")], {}, {}, NOW)
    ev, st = gr.risk_events([row("B34", blocked="выключено")], {}, st, NOW + timedelta(hours=2))
    assert not any("снова ставит входы" in e for e in ev)
    ev, _ = gr.risk_events([row("B34")], {}, st, NOW + timedelta(hours=3))
    assert any("снова ставит входы" in e for e in ev)


def test_unreadable_state_does_not_rearm_same_loss():
    """25.10 (аудит GPT G3): учёт на проход не прочитан — тот же убыток не даёт второго пинга."""
    from datetime import timedelta
    first, st = gr.risk_events([row("B34", bag=-150)], {}, {}, NOW)
    assert any("Мешок" in e for e in first)
    _, st = gr.risk_events([row("B34", error="JSONDecodeError")], {}, st, NOW + timedelta(minutes=5))
    again, _ = gr.risk_events([row("B34", bag=-150)], {}, st, NOW + timedelta(minutes=10))
    assert not any("Мешок" in e for e in again)


def test_threshold_levels_once_per_day():
    risk = {"BTCUSDT": {"thr": 79000.0, "px": 81000.0, "dist": -2.47, "bag": -400.0, "adds": 3}}
    ev, st = gr.risk_events([], risk, {}, NOW)
    assert len(ev) == 1 and "2.5% от порога выхода 79,000" in ev[0]
    ev, st = gr.risk_events([], risk, st, NOW)
    assert ev == []
    risk["BTCUSDT"]["dist"] = -1.2                              # ближе 1.5% — отдельное событие
    ev, _ = gr.risk_events([], risk, st, NOW)
    assert len(ev) == 1 and "1.2%" in ev[0]


def test_far_from_threshold_silent():
    risk = {"ETHUSDT": {"thr": 2300.0, "px": 2400.0, "dist": -4.17, "bag": -40.0, "adds": 6}}
    ev, _ = gr.risk_events([], risk, {}, NOW)
    assert ev == []


def test_report_text_totals_and_cap_mark():
    rows = [row("BTC", bag=-9.0, closed=55.0, lots=6), row("B34", bag=-58.0, closed=39.0, lots=29,
                                                            blocked="достигнут потолок позиции")]
    data = {"now": NOW, "cap": 15000.0, "syms": {"BTCUSDT": {"grid": None, "day": None, "thr": None, "px": 81906.0}}}
    text = gr.report_text(now=NOW, rows=rows, data=data, eq=(3385.0, -163.0))
    assert "счёт $3,385" in text and "BTC 81,906" in text
    assert "B34 0.1/0.34: лотов 29 ⛔ на потолке" in text
    assert "Всего: мешок −67$ · итог +27$" in text and "занято $3,500 из $15,000" in text


def test_ping_symbols():
    rows = [row("BTC"), row("B34"), row("ETH", sym="ETHUSDT")]
    assert gr.ping_symbols(["⛔ B34 на потолке позиции"], rows) == ["BTCUSDT"]
    assert gr.ping_symbols(["🛑 ETH в 2.0% от порога"], rows) == ["ETHUSDT"]
    assert gr.ping_symbols(["📉 Мешок всех лонг-сеток −120$ — ниже −100$"], rows) == ["BTCUSDT"]


def test_resume_ping_after_long_cap_and_rate_limited():
    """24.10: «снова ставит входы» — после упора ≥1 ч, не чаще раза в 6 ч; короткое качание у потолка молчит."""
    from datetime import timedelta
    capped = [row("B34", blocked="достигнут потолок позиции", lots=31)]
    free = [row("B34", lots=30)]
    _, st = gr.risk_events(capped, {}, {}, NOW)
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(minutes=20))
    assert ev == []                                              # 20 мин на потолке — не событие
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(minutes=30))
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(hours=2))
    assert len(ev) == 1 and ev[0].startswith("✅ B34 снова ставит входы") and "стояла 1.5 ч" in ev[0]
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(hours=2, minutes=5))
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(hours=4))
    assert ev == []                                              # второй раз за 6 ч — молчит
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(hours=7))
    ev, _ = gr.risk_events(free, {}, st, NOW + timedelta(hours=9))
    assert len(ev) == 1                                         # прошло 6 ч — снова можно


# ---------------------------------------------------------------- G1 (аудит GPT 481385e): доставка пингов
CAPPED = [row("B34", blocked="достигнут потолок позиции")]
DATA = {"now": NOW, "cap": None, "syms": {"BTCUSDT": {"grid": None, "day": None, "thr": None, "px": 83000.0}}}


class Bot:
    """Telegram-заглушка: падения по получателю и по виду сообщения."""
    def __init__(self, fail_text=(), fail_photo=False):
        self.texts, self.photos, self.fail_text, self.fail_photo = [], [], set(fail_text), fail_photo

    def text(self, cid, t):
        if cid in self.fail_text:
            raise RuntimeError("telegram недоступен")
        self.texts.append((cid, t))

    def photo(self, cid, png, cap):
        if self.fail_photo:
            raise RuntimeError("send_photo упал")
        self.photos.append((cid, cap))


def _tick(bot, state, cids=(1,), now=NOW, render=lambda s, data=None: b"png", summary=lambda: "сводка", data=DATA):
    return gr.ping_tick(list(cids), bot.text, bot.photo, rows=CAPPED, data=data, state=state, now=now,
                        render=render, summary=summary)


def test_g1_map_failure_does_not_block_urgent_text():
    """impl до 25.10: карты рендерились ДО отправки — исключение render_map → текстов 0, состояние не записано."""
    def boom(sym, data=None):
        raise RuntimeError("matplotlib лёг")
    bot = Bot()
    st = _tick(bot, {}, render=boom)
    assert bot.texts[0] == (1, bot.texts[0][1]) and "B34 на потолке" in bot.texts[0][1]
    assert st is not None and "B34" in st["cap"]                # событие зафиксировано — повторно не придёт
    assert bot.photos == []


def test_g1_photo_failure_does_not_resend_text():
    """impl до 25.10: текст ушёл, send_photo упал → sent=0, состояние не записано → тот же текст через 5 мин снова."""
    bot = Bot(fail_photo=True)
    st = _tick(bot, {})
    assert st is not None
    again = _tick(bot, st, now=NOW.replace(minute=5))
    urgent = [t for _, t in bot.texts if "на потолке" in t]
    assert len(urgent) == 1 and again is None


def test_g1_summary_failure_keeps_urgent_text():
    def boom():
        raise ValueError("котировки недоступны")
    bot = Bot()
    st = _tick(bot, {}, summary=boom)
    assert "на потолке" in bot.texts[0][1] and bot.texts[1][1] == "сводка не собрана: ValueError" and st is not None


def test_g1_failed_recipient_is_retried_alone():
    bot = Bot(fail_text={2})
    st = _tick(bot, {}, cids=(1, 2))
    assert [c for c, t in bot.texts if "на потолке" in t] == [1]
    assert [(q["cid"], q["attempts"]) for q in st["undelivered"]] == [(2, 1)]
    bot.fail_text = set()
    st2 = _tick(bot, st, cids=(1, 2), now=NOW.replace(minute=5))
    assert [c for c, t in bot.texts if "на потолке" in t] == [1, 2]          # второму — дослали, первому — не повтор
    assert st2["undelivered"] == [] and st2["cap"] == st["cap"]


def test_g1_retry_gives_up_after_max_attempts():
    bot = Bot(fail_text={2})
    st = _tick(bot, {}, cids=(1, 2))
    for i in range(gr.RETRY_MAX):
        nxt = _tick(bot, st, cids=(1, 2), now=NOW.replace(minute=5 + i))
        st = nxt if nxt is not None else st
    assert st["undelivered"] == []


def test_g1_nobody_got_it_means_no_state():
    bot = Bot(fail_text={1})
    assert _tick(bot, {}) is None                                # повтор события в следующий проход


def test_g1_no_quotes_still_sends_cap_event():
    bot = Bot()
    st = _tick(bot, {}, data=None)
    assert "на потолке" in bot.texts[0][1] and st is not None and bot.photos == []


def test_g5_stalled_grid_loop_pings_once_and_recovers():
    """25.10 (аудит GPT 481385e G5): задача сеток упала/застряла — приложение живо, пинг один на эпизод с причиной;
    снова пошла — парный пинг. Без ok_ts (старый учёт) — молчит, не выдумывает."""
    t = NOW.timestamp()
    old = dict(row("B34"), ok_ts=t - 900, tick_err={"ts": t - 890, "phase": "open_orders", "err": "HTTP 521"})
    fresh = dict(row("B49"), ok_ts=t - 30)
    ev, st = gr.risk_events([old, fresh], {}, {}, NOW)
    assert len(ev) == 1 and "B34" in ev[0] and "15 мин" in ev[0] and "open_orders — HTTP 521" in ev[0]
    assert "B49" not in ev[0] and st["stale"] == ["B34"]
    ev, st = gr.risk_events([old, fresh], {}, st, NOW)
    assert ev == []                                                       # тот же эпизод — молчит
    dead = dict(row("B34"), ok_ts=t - 900, tick_err=None)
    ev, _ = gr.risk_events([dead], {}, {}, NOW)
    assert "цикл, похоже, стоит" in ev[0]
    ev, st = gr.risk_events([dict(old, ok_ts=t - 20), fresh], {}, st, NOW)
    assert ev == ["✅ Сетки B34 снова проходят цикл"] and st["stale"] == []
    assert gr.risk_events([row("B34")], {}, {}, NOW)[0] == []             # нет ok_ts — неизвестно, не «стоит»


def test_g3_report_total_excludes_unreadable():
    rows = [row("B34", bag=-50.0, closed=10.0), row("B49", error="JSONDecodeError")]
    text = gr.report_text(now=NOW, rows=rows, data=DATA, eq=None)
    assert "Всего (без 1 непрочитанных — итог неполный): мешок −50$ · итог −40$" in text
