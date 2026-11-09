"""Сигналы системы BTC и 432 в Telegram. Запуск launchd раз в 10 минут (com.bot7.btc-signals); полный расчёт — только когда
в frozen-минутках закрылся новый час (их дописывает com.bot7.ohlcv-gapfill раз в час).

  run.py            — проверить новый час, отправить новые события (вход, добор, выход) системы и 432
  run.py --status   — отправить текущее положение (позиции, линии, последние сделки)
  run.py --weekly   — отправить недельную сверку сейчас (сама уходит раз в неделю, с понедельника 07:00 UTC)
  run.py --dry      — ничего не отправлять и не сохранять, печатать сообщения

Тень V2 (лонг закрывается и под синей, записки оператора 08.11) — только журнал state/btc_signals_shadow.jsonl, без отправки.
Состояние: state/btc_signals_state.json, журнал: state/btc_signals_journal.jsonl. Ничего не торгует."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research" / "chart_walk_20261105"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.btc_signals import engine as en  # noqa: E402
from services.btc_signals import features as fx  # noqa: E402

FROZEN = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
STATE = ROOT / "state" / "btc_signals_state.json"
JOURNAL = ROOT / "state" / "btc_signals_journal.jsonl"
SHADOW = ROOT / "state" / "btc_signals_shadow.jsonl"
FEATURES = ROOT / "state" / "btc_signals_features.jsonl"
BASE_USD = 1000.0
STALE_S = 3 * 3600
LATE_S = 2 * 3600
WEEK_S = 7 * 86400
MAIN_START = 1794092400  # 07.11.2026 23:00 UTC — первый час службы
WAW = ZoneInfo("Europe/Warsaw")
FOOT = "Binance BTCUSDT, по часам, без фандинга. Служба ничего не торгует."


def _now() -> int:
    return int(time.time())


def last_closed_hour(path: Path = FROZEN) -> int:
    """Время закрытия последнего полного часа в файле минуток (секунды UTC), по последней строке."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(size - 400, 0))
        tail = fh.read().decode("ascii", "replace")
    rows = [x for x in tail.split("\n") if x.strip()]
    if tail and not tail.endswith("\n"):
        rows = rows[:-1]
    last_min = int(rows[-1].split(",")[0]) // 1000
    return (last_min + 60) // 3600 * 3600


def px(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def when(ts: int) -> str:
    u = datetime.fromtimestamp(ts, timezone.utc)
    return f"{u:%d.%m %H:%M} UTC ({u.astimezone(WAW):%H:%M} Варшава)"


def short_when(ts: int) -> str:
    return f"{datetime.fromtimestamp(ts, timezone.utc):%d.%m %H:%M}"


def usd(w: float) -> str:
    return f"${w * BASE_USD:,.0f}".replace(",", " ")


def side_word(side: int, tag: str) -> str:
    return f"{'ЛОНГ' if side == 1 else 'ШОРТ'} {tag}"


def exit_rule(a: dict, i: int, side: int, tag: str) -> str:
    if side == 1:
        return f"2 закрытия 4ч подряд под красной (сейчас {px(a['f_R'][i])})"
    if tag == en.CS:
        return f"2 закрытия 4ч подряд над жёлтой (сейчас {px(a['f_Y'][i])})"
    return f"2 закрытия 4ч подряд над зелёной (сейчас {px(a['f_G'][i])})"


def exit_label(tag: str) -> str:
    return "Отмена" if tag == en.CS else "Выход"


def cs_target(a: dict, i: int) -> float:
    return float(a["B4p"][i]) * en.CS_TOL


def entry_text(a: dict, e: dict) -> str:
    p, i = e["pos"], e["i"]
    head = "🟢" if e["side"] == 1 else "🔴"
    lines = [f"{head} BTC: {side_word(e['side'], e['tag'])} — вход", f"Цена {px(e['px'])} (закрытие 4ч {when(e['t'])})"]
    if e["tag"] in en.MAIN:
        lines.append(f"Размер: вес {p['w']:.2f} → сейчас {usd(p['w'] * en.FIRST)} при базе {usd(1)} (первая половина)")
        lines.append(f"Добор: ещё {usd(p['w'] * en.ADD)} на {px(p['add_lv'])} (вход {'+' if e['side'] == 1 else '−'} 2×ATR 4ч {px(p['atr'])})")
    else:
        lines.append(f"Размер: вес {p['w']:.2f} → {usd(p['w'])} при базе {usd(1)}, целиком, без добора")
        lines.append(f"Цель: {px(cs_target(a, i))} (синяя прошлой свечи 4ч +0.5%, сдвигается каждые 4ч)")
    lines.append(f"{exit_label(e['tag'])}: {exit_rule(a, i, e['side'], e['tag'])}")
    return "\n".join(lines)


def entry432_text(e: dict) -> str:
    p = e["pos"]
    return "\n".join([
        "🟢 BTC: 432 ЛОНГ — вход (пробой 4ч)",
        f"Цена {px(e['px'])} (закрытие 4ч {when(e['t'])})",
        f"Пробой максимума 30 свечей 4ч {px(p['hi30'])} на {(e['px'] - p['hi30']) / p['atr']:.1f} ATR, ADX {p['adx']:.0f}, выше EMA200 4ч",
        f"Размер: {usd(1)} целиком, отдельно от системы, без добора",
        f"Выход: закрытие 4ч ниже минимума 30 свечей или через 20 свечей 4ч — не позже {when(p['exit_by_t'])}",
    ])


def add_text(a: dict, e: dict) -> str:
    p, i = e["pos"], e["i"]
    avg = (p["entry"] + p["add_px"]) / 2
    return "\n".join([
        f"➕ BTC: добор — {side_word(e['side'], e['tag'])}",
        f"Цена {px(e['px'])}: уровень {px(p['add_lv'])} достигнут в час до {short_when(e['t'])} UTC, ещё {usd(p['w'] * en.ADD)}",
        f"Средняя позиции {px(avg)}, всего {usd(p['w'])}",
        f"Выход общий: {exit_rule(a, i, e['side'], e['tag'])}",
    ])


def exit_text(e: dict) -> str:
    p = e["pos"]
    move = e["side"] * (e["px"] / p["entry"] - 1) * 100
    add = f", добор {px(p['add_px'])} взят" if p["add_done"] and e["tag"] in en.MAIN else (", добор не взят" if e["tag"] in en.MAIN else "")
    return "\n".join([
        f"⚪ BTC: {side_word(e['side'], e['tag']).lower()} закрыт — {e['why']}",
        f"Вход {px(p['entry'])} ({short_when(p['entry_t'])}) → выход {px(e['px'])} ({short_when(e['t'])} UTC){add}",
        f"Ход цены {pct(move)}, итог с весом и издержками {money(e['res'])} при базе {usd(1)}",
    ])


def pct(v: float) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v):.2f}%"


def money(res_pct: float) -> str:
    v = res_pct / 100 * BASE_USD
    return f"{'+' if v >= 0 else '−'}${abs(v):,.1f}".replace(",", " ")


REF = Path(__file__).with_name("feature_ref.json")


def fmt_feat(name: str, v: float) -> str:
    base = name.replace(", ATR", "").replace(", %", "")
    if name.endswith(", ATR"):
        return f"{base} {v:+.1f} ATR".replace("+-", "−").replace("-", "−")
    if name.endswith(", %"):
        return f"{base} {v:+.1f}%".replace("-", "−")
    if abs(v) >= 100 or float(v).is_integer():
        return f"{base} {v:.0f}".replace("-", "−")
    return f"{base} {v:.1f}".replace("-", "−") if abs(v) >= 10 else f"{base} {v:.2f}".replace("-", "−")


def describe(row: dict | None, ref: dict | None = None) -> list[str]:
    """5 признаков входа и их место среди таких же входов 2014–26 (feature_ref.json из trade_scan.export_ref). Описание, не прогноз."""
    if not row or not row.get("features"):
        return []
    if ref is None:
        try:
            ref = json.loads(REF.read_text())
        except Exception:  # noqa: BLE001
            return []
    typ = f"{'лонг' if row['side'] == 1 else 'шорт'} {row['tag']}"
    items = ref.get("types", {}).get(typ) or []
    out = []
    for it in items:
        v = row["features"].get(it["feat"])
        if v is None:
            continue
        q = it["q"]
        pc = int(round(sum(1 for x in q[1:-1] if x < v)))
        line = f"• {fmt_feat(it['feat'], v)} — больше, чем у {pc}% таких входов"
        out.append(line + (f" ({it['note']})" if it.get("note") else ""))
    if out:
        n = items[0]["n"]
        out.insert(0, f"Описание входа ({n} таких сделок 2014–26; описание, не прогноз):")
    return out


def event_text(a: dict, e: dict, now: int, desc: list[str] | None = None) -> str:
    if e["tag"] == en.TAG432 and e["kind"] == "вход":
        txt = entry432_text(e)
    else:
        body = {"вход": entry_text, "добор": add_text}.get(e["kind"])
        txt = body(a, e) if body else exit_text(e)
    if desc:
        txt += "\n" + "\n".join(desc)
    if now - e["t"] > LATE_S:
        txt = f"⏰ с опозданием на {(now - e['t']) // 3600} ч\n" + txt
    return txt + "\n" + FOOT


def runs_word(r: float) -> str:
    r = int(r)
    return f"{abs(r)} {'над' if r > 0 else 'под'}" if r else "0"


def status432(R: dict) -> list[str]:
    p, lv = R["pos432"], R["lv432"]
    if p:
        mv = (lv["close"] / p["entry"] - 1) * 100
        return [f"432: ЛОНГ с {short_when(p['entry_t'])} UTC по {px(p['entry'])}, {usd(1)}, ход сейчас {pct(mv)}",
                f"432 выход: закрытие 4ч ниже {px(lv['next_lo30'])} или по времени {when(p['exit_by_t'])}"]
    trig = lv["next_hi30"] + en.BRK432 * lv["atr"]
    return [f"432: позиции нет. Вход — закрытие 4ч выше ≈{px(trig)} (максимум 30 свечей {px(lv['next_hi30'])} + 0.5 ATR), "
            f"ADX ≥22 (сейчас {lv['adx']:.0f}), выше EMA200 4ч ({px(lv['e200'])})"]


def status_text(R: dict) -> str:
    a, ev, pos = R["a"], R["ev"], R["pos"]
    i = len(a["t"]) - 1
    c, B = float(a["c"][i]), float(a["f_B"][i])
    L = [f"📊 BTC система: Простое+, шорт под жёлтой, добор — {when(int(a['t'][i]))}",
         f"Цена {px(c)}, {'выше' if c > B else 'ниже'} синей на {abs(c / B - 1) * 100:.1f}%",
         f"Линии 4ч: зелёная {px(a['f_G'][i])}, жёлтая {px(a['f_Y'][i])}, красная {px(a['f_R'][i])}, синяя {px(B)}",
         f"Закрытий 4ч подряд: зелёная {runs_word(a['f_run_G'][i])}, жёлтая {runs_word(a['f_run_Y'][i])}, красная {runs_word(a['f_run_R'][i])}"]
    if pos:
        now_move = pos["side"] * (c / pos["entry"] - 1) * 100
        L.append(f"Позиция: {side_word(pos['side'], pos['tag'])} с {short_when(pos['entry_t'])} UTC по {px(pos['entry'])}, вес {pos['w']:.2f}, ход цены сейчас {pct(now_move)}")
        if pos["tag"] in en.MAIN:
            L.append(f"Добор {usd(pos['w'] * en.ADD)}: " + (f"взят {px(pos['add_px'])}" if pos["add_done"] else f"на {px(pos['add_lv'])}, не взят"))
        else:
            L.append(f"Цель {px(cs_target(a, i))}")
        L.append(f"{exit_label(pos['tag'])}: {exit_rule(a, i, pos['side'], pos['tag'])}")
    else:
        L.append("Позиции нет")
    L += status432(R)
    closed = [e for e in ev if e["kind"] == "выход"]
    if closed:
        L.append("Последние сделки системы (сверка с индикатором):")
        for e in closed[-3:]:
            p = e["pos"]
            L.append(f"  {short_when(p['entry_t'])} → {short_when(e['t'])} {side_word(e['side'], e['tag']).lower()}: {money(e['res'])}")
    y25 = [e for e in closed if e["pos"]["entry_t"] >= 1735689600]
    if y25:
        s = sum(e["res"] for e in y25)
        L.append(f"С 01.01.2025 закрытых {len(y25)}, итог {s:+.1f}% базы, доборов {sum(1 for e in y25 if e['pos']['add_done'] and e['tag'] in en.MAIN)}")
    c432 = [e for e in R["ev432"] if e["kind"] == "выход" and e["pos"]["entry_t"] >= 1735689600]
    if c432:
        L.append(f"432 с 01.01.2025: закрытых {len(c432)}, итог {sum(e['res'] for e in c432):+.1f}% базы")
    return "\n".join(L) + "\n" + FOOT


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def stream_since(st: dict, tag: str) -> int:
    s = st.get("since", {})
    return int(s.get("432", 0)) if tag == en.TAG432 else int(s.get("main", 0))


def weekly_due(now: int, st: dict) -> str | None:
    u = datetime.fromtimestamp(now, timezone.utc)
    if u.weekday() == 0 and u.hour < 7:
        return None
    label = f"{u:%G-W%V}"
    return None if st.get("weekly_for") == label else label


def closed_sum(ev: list[dict], t0: int, t1: int) -> tuple[int, float]:
    x = [e for e in ev if e["kind"] == "выход" and t0 < e["t"] <= t1]
    return len(x), sum(e["res"] for e in x)


def weekly_text(R: dict, st: dict, now: int) -> str:
    t0 = now - WEEK_S
    L = [f"📅 Сигналы BTC за неделю {short_when(t0)} – {short_when(now)} UTC"]
    for name, ev, pos in (("Система", R["ev"], R["pos"]), ("432", R["ev432"], R["pos432"])):
        n, s = closed_sum(ev, t0, now)
        op = f"; открыта: {side_word(pos['side'], pos['tag']).lower()} с {short_when(pos['entry_t'])} по {px(pos['entry'])}" if pos else "; позиции нет"
        L.append(f"{name}: закрыто {n}, итог {money(s)}{op}")
    exp = {ev_key(e): e for e in R["ev"] + R["ev432"] if e["t"] > max(t0, stream_since(st, e["tag"]))}
    got: dict[str, dict] = {}
    for r in read_rows(JOURNAL):
        if r["t"] > t0:
            k = ev_key(r)
            if k not in got or r.get("sent"):
                got[k] = r
    miss = [k for k in exp if k not in got]
    extra = [k for k in got if k not in exp]
    diff = [k for k in exp if k in got and abs(got[k]["px"] / exp[k]["px"] - 1) > 1e-4]
    unsent = [k for k, r in got.items() if not r.get("sent")]
    if not (miss or extra or diff or unsent):
        L.append(f"Сверка журнала с пересчётом: все {len(exp)} событий совпали")
    else:
        L.append(f"Сверка журнала с пересчётом: событий {len(exp)}, расхождения:")
        L += [f"  нет в журнале: {k}" for k in miss] + [f"  пересчёт не подтверждает: {k}" for k in extra]
        L += [f"  цена {k}: журнал {px(got[k]['px'])}, пересчёт {px(exp[k]['px'])}" for k in diff] + [f"  не отправлено: {k}" for k in unsent]
    s0 = int(st.get("since", {}).get("v2", now))
    n_m, s_m = closed_sum(R["ev"], s0, now)
    n_v, s_v = closed_sum(R["ev_v2"], s0, now)
    L.append(f"Тень «лонг закрывать и под синей» с {short_when(s0)}: закрыто {n_v}, итог {money(s_v)}; система за то же время: {n_m}, {money(s_m)}")
    sc = [r for r in read_rows(FEATURES) if r.get("kind") == "вход" and r["t"] > t0 and r.get("m2_score") is not None]
    if sc:
        L.append("Балл модели размера у входов недели (тень, 0–1, не доказан): " + ", ".join(f"{r['utc']} {r['tag']} {r['m2_score']:.2f}" for r in sc))
    m0 = int(st.get("since", {}).get("main", now))
    n1, v1 = closed_sum(R["ev"], m0, now)
    q0 = int(st.get("since", {}).get("432", now))
    n2, v2 = closed_sum(R["ev432"], q0, now)
    L.append(f"С начала службы: система {n1} сделок {money(v1)} (с {short_when(m0)}), 432 {n2} сделок {money(v2)} (с {short_when(q0)})")
    return "\n".join(L) + "\n" + FOOT


def load_state() -> dict:
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_state(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def journal(row: dict, path: Path | None = None) -> None:
    with open(path or JOURNAL, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ev_key(e: dict) -> str:
    return f"{e['kind']}|{e['t']}|{e['tag']}"


def pos_brief(p: dict | None) -> dict | None:
    if not p:
        return None
    return {k: p[k] for k in ("side", "tag", "entry", "entry_t", "w", "atr", "add_lv", "add_done", "add_px", "add_t")}


def ev_row(e: dict, ok: bool, now: int) -> dict:
    return {"kind": e["kind"], "t": e["t"], "utc": short_when(e["t"]), "side": e["side"], "tag": e["tag"], "px": e["px"], "res": e.get("res"), "why": e.get("why"),
            "pos": pos_brief(e["pos"]), "sent": ok, "sent_at": now}


def compute() -> dict:
    """Загрузка и линии — код разбора research/chart_walk_20261105 (у него имена модулей вроде pos, journal — путь только здесь)."""
    sys.path.insert(0, str(RESEARCH))
    import plus as pl
    import state_card as sc
    a, _, h4f = sc.load_coin("BTC")
    lay = pl.layer(a)
    ev, pos = en.simulate(a, lay)
    ev432, pos432, lv432 = en.simulate432(a)
    ev_v2, pos_v2 = en.simulate(a, lay, lx_blue=True)
    return {"a": a, "lay": lay, "h4f": h4f, "ev": ev, "pos": pos, "ev432": ev432, "pos432": pos432, "lv432": lv432, "ev_v2": ev_v2, "pos_v2": pos_v2}


def closed_hist(ev: list[dict]) -> list[tuple[int, int, int, float]]:
    return [(e["pos"]["entry_t"], e["t"], e["side"], e["res"]) for e in ev if e["kind"] == "выход"]


def feature_rows(R: dict, events: list[dict], now: int) -> list[dict]:
    """Строка таблицы сделок на каждое событие: вход — ~120 признаков (features.py) и балл M2 (тень, только система),
    выход — итог и путь сделки (MFE, MAE, отдача), добор — цена. Ошибка признаков не мешает сигналам: пишется в строку."""
    a, lay = R["a"], R.get("lay")
    rows, P, err = [], None, None
    try:
        P = fx.prepare(a, lay, R.get("h4f"))
    except Exception as exc:  # noqa: BLE001 — признаки не должны останавливать сигналы
        err = f"prepare: {exc!r}"
    hist = {"система": closed_hist(R["ev"]), "432": closed_hist(R["ev432"])}
    try:
        model = fx.m2_load()
    except Exception:  # noqa: BLE001
        model = None
    for e in events:
        strat = "432" if e["tag"] == en.TAG432 else "система"
        p = e["pos"]
        r = {"key": ev_key(e), "kind": e["kind"], "strategy": strat, "tag": e["tag"], "side": e["side"], "t": e["t"], "utc": short_when(e["t"]), "px": e["px"], "written_at": now}
        try:
            if e["kind"] == "вход":
                if P is None:
                    raise RuntimeError(err)
                f = fx.row(P, a, e["i"])
                f.update(fx.history(hist[strat], e["t"], e["side"]))
                r["features"] = f
                if strat == "система" and model:
                    try:
                        prev = [x for x in hist["система"] if x[1] <= e["t"]]
                        r["m2_score"] = fx.m2_score(model, fx.m2_vector(a, lay, e["i"], e["side"], e["tag"], prev[-1][3] if prev else 0.0))
                    except Exception as exc:  # noqa: BLE001
                        r["m2_error"] = repr(exc)
            elif e["kind"] == "выход":
                r.update({"res": e["res"], "why": e["why"], "entry_t": p["entry_t"], "entry": p["entry"], "path": fx.path(a, p["entry_i"], e["i"], e["side"], p["entry"], e["px"])})
            else:
                r["add_px"] = e["px"]
        except Exception as exc:  # noqa: BLE001
            r["error"] = repr(exc)
        rows.append(r)
    return rows


def sender(dry: bool):
    if dry:
        return lambda text: (print(text, "\n---", flush=True), True)[1]
    from services.telegram_alert_client import TelegramAlertClient
    cl = TelegramAlertClient.instance()
    if not cl.is_enabled():
        raise SystemExit("Telegram не настроен (BOT_TOKEN/CHAT_ID)")
    return cl.send


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    now = _now()
    st = load_state()
    hour = last_closed_hour()
    if not (args.status or args.weekly) and st.get("last_hour", 0) >= hour:
        if now - hour > STALE_S and st.get("stale_warned_for") != hour:
            send = sender(args.dry)
            ok = send(f"⚠️ Сигналы BTC: минутки не обновлялись с {when(hour)}, сигналов нет. Проверить com.bot7.ohlcv-gapfill.")
            if ok and not args.dry:
                st["stale_warned_for"] = hour
                save_state(st)
        return 0
    R = compute()
    a = R["a"]
    send = sender(args.dry)
    t_last = int(a["t"][-1])
    first_run = "last_hour" not in st
    since = st.setdefault("since", {})
    if first_run:
        since.update({"main": t_last, "432": t_last, "v2": t_last})
    else:
        since.setdefault("main", MAIN_START)
        since.setdefault("432", int(st["last_hour"]))
        since.setdefault("v2", int(st["last_hour"]))
    sent_ok = True
    keys = list(st.get("sent_keys", []))
    ran_events = not first_run and not (args.status or args.weekly)
    journaled: list[dict] = []
    fkeys = list(st.get("feature_keys", []))
    frows: dict[str, dict] = {}
    if ran_events:
        new = [x for x in R["ev"] if x["t"] > st["last_hour"]] + [x for x in R["ev432"] if x["t"] > max(st["last_hour"], since["432"])]
        new = [x for x in sorted(new, key=lambda x: x["t"]) if ev_key(x) not in keys]
        if new:
            try:
                frows = {r["key"]: r for r in feature_rows(R, new, now)}
            except Exception as exc:  # noqa: BLE001 — признаки не должны останавливать сигналы
                print(f"признаки не посчитаны: {exc!r}", flush=True)
        for e in new:
            ok = bool(send(event_text(a, e, now, describe(frows.get(ev_key(e))) if e["kind"] == "вход" else None)))
            sent_ok = sent_ok and ok
            if not args.dry:
                journal(ev_row(e, ok, now))
                journaled.append(e)
                if ok:
                    keys.append(ev_key(e))
                    st["sent_keys"] = keys[-80:]
                    save_state(st)
    todo = [e for e in journaled if ev_key(e) not in fkeys]
    if todo:
        for e in todo:
            r = frows.get(ev_key(e))
            if r is None:
                continue
            journal(r, FEATURES)
            fkeys.append(r["key"])
        st["feature_keys"] = fkeys[-80:]
    if not args.dry:
        skeys = list(st.get("shadow_keys", []))
        for e in R["ev_v2"]:
            if e["t"] > since["v2"] and ev_key(e) not in skeys:
                journal(ev_row(e, False, now), SHADOW)
                skeys.append(ev_key(e))
        st["shadow_keys"] = skeys[-80:]
    if args.status or first_run:
        sent_ok = bool(send(status_text(R))) and sent_ok
    label = weekly_due(now, st)
    if args.weekly or (label and not first_run and not args.status):
        ok = bool(send(weekly_text(R, st, now)))
        sent_ok = sent_ok and ok
        if ok and label and not args.dry:
            st["weekly_for"] = label
    if args.dry:
        return 0
    if not sent_ok:
        save_state(st)
        print("отправка не удалась, час не отмечен — повтор при следующем запуске", flush=True)
        return 1
    if not (first_run or ran_events):
        save_state(st)
        return 0
    st.update({"last_hour": t_last, "pos": pos_brief(R["pos"]), "pos432": pos_brief(R["pos432"]), "pos_v2": pos_brief(R["pos_v2"]), "checked_at": now})
    st.pop("stale_warned_for", None)
    save_state(st)
    print(f"{short_when(now)} час {short_when(t_last)} событий отправлено, позиция {pos_brief(R['pos'])}, 432 {pos_brief(R['pos432'])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
