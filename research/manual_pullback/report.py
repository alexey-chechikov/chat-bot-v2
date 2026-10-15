"""Отчёт docs/PULLBACK_4H_RESULTS_2026-10-15.md из research/manual_pullback/out/summary.json (+ audit.json).
Диагностика ширины стопа у подтверждений пересчитывается теми же функциями replay.py.

    .venv/bin/python3 research/manual_pullback/report.py "<строка итога полного _run_tests.py>" <число тестов research_manual>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay as rp  # noqa: E402

OUT = HERE / "out"
DOC = rp.ROOT / "docs" / "PULLBACK_4H_RESULTS_2026-10-15.md"
SCOPES = [("PORT", "Портфель ETH+XRP"), ("ETH", "ETH отдельно"), ("XRP", "XRP отдельно"), ("BTC", "BTC отдельно (вне решения)")]


def r3(x):
    return "—" if x is None else f"{x:+.3f}"


def usd(x):
    return "—" if x is None else f"{x:+.2f}"


def pct(x, d=0):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def ci(c):
    return "—" if not c else f"[{c[0]:+.3f}; {c[1]:+.3f}]"


def width_diag() -> dict:
    names = ["ETHUSDT", "XRPUSDT", "BTCUSDT"]
    raw = {nm: rp.read_minutes(nm) for nm in names}
    end = min(int(raw[nm]["ts"][-1]) for nm in names) + rp.MIN
    out = {}
    for nm in names:
        s = rp.make_sym(nm, raw[nm], None, rp.START, end)
        ws = []
        for T, side, i4 in rp.detect_events(s, True):
            p = rp.Pending("d", nm, side, T, int((T - s.start) // rp.M15), float(s.b4["l"][i4]), float(s.b4["h"][i4]))
            for j in range(p.k1, p.k1 + 16):
                r = rp.step(p, s, j)
                if r is None:
                    continue
                if r == "confirm":
                    o = rp.order_from_confirm(p, s, j, rp.BASE)
                    if isinstance(o, dict) or o == "skip_width":
                        i0 = rp.minute_index(s, int(s.b15["t"][j] + rp.M15))
                        E = float(rp.entry_price(s.o[i0], side, rp.BASE))
                        ws.append(side * (E - (p.ext - side * 0.1 * p.A)) / E)
                break
        w = np.array(ws)
        out[nm] = {"n": len(w), "narrow": int((w < 0.007).sum()), "ok": int(((w >= 0.007) & (w <= 0.02)).sum()),
                   "wide": int((w > 0.02).sum()), "median": float(np.median(w)) if len(w) else None}
    return out


def main() -> None:
    suite = sys.argv[1] if len(sys.argv) > 1 else "—"
    n_tests = sys.argv[2] if len(sys.argv) > 2 else "—"
    S = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    A = json.loads((OUT / "audit.json").read_text(encoding="utf-8")) if (OUT / "audit.json").exists() else {}
    runs, c3, stt, man = S["runs"], S["c3"], S["status"], S["manifest"]
    P, P2 = runs["S_PORT_base"], runs["S_PORT_slip2"]
    C1, C2 = runs["C1_PORT_base"], runs["C2_PORT_base"]
    wd = width_diag()
    L = []
    a = L.append

    a("# Первый откат после нового 4h тренда — результат (15.10.2026)")
    a("")
    a(f"**Вердикт: нет. Стратегия не квалифицирована, карточки сделки нет.** Портфель ETH+XRP по протоколу "
      f"`docs/PULLBACK_4H_PROTOCOL_2026-10-15.md` (коммит {rp.PROTOCOL_COMMIT}, опубликован до расчётов) — "
      f"**«{stt['PORT']['label']}»**: среднее после расходов **{r3(P['mean_R'])}R** на **{P['n']}** сделках "
      f"(нужно > 0 и не меньше 100), при ×2 проскальзывании {r3(P2['mean_R'])}R, до расходов {r3(P['mean_R_gross'])}R. "
      f"Случайный вход той же стороны, в то же время суток и ту же волатильность с тем же стопом (C3) не хуже: ранг "
      f"**{c3['PORT']['rank']:.3f}** (нужно ≤ 0.05). Оба исполнимых контроля лучше стратегии: прямой вход на 4h-пробое "
      f"(C1) {r3(C1['mean_R'])}R, тот же откат без ADX (C2) {r3(C2['mean_R'])}R. На $3 000 портфель за 2 года 5 месяцев: "
      f"**{usd(P['sum_pnl'])} $**, макс. просадка {usd(P['max_dd_usd'])} $.")
    a("")
    a(f"- **ETH отдельно:** «{stt['ETH']['label']}» — {r3(runs['S_ETH_base']['mean_R'])}R, n {runs['S_ETH_base']['n']}.")
    a(f"- **XRP отдельно:** «{stt['XRP']['label']}» — {r3(runs['S_XRP_base']['mean_R'])}R, n {runs['S_XRP_base']['n']}.")
    a(f"- **BTC отдельно (в решение не входит):** «{stt['BTC']['label']}» — {r3(runs['S_BTC_base']['mean_R'])}R, "
      f"n {runs['S_BTC_base']['n']}.")
    a("")
    cnt = P["counts"]
    ev = cnt.get("events", 0)
    a(f"**По-простому.** Правило почти не торгует: из {ev} 4h-пробоев ETH+XRP за 2 года 5 месяцев вышло {P['n']} сделок "
      f"(≈1 в месяц). В {pct(cnt.get('expire_touch', 0) / ev)} событий откат не дошёл до EMA20 за свечи №4…16, в "
      f"{pct(cnt.get('cancel_new_extreme', 0) / ev)} после касания цена ушла за минимум отката (максимум для шорта), в "
      f"{pct(cnt.get('expire_confirm', 0) / ev)} не было подтверждения; из {cnt.get('confirm', 0)} подтверждений "
      f"{cnt.get('skip_width', 0)} отсеяны шириной стопа. Оставшиеся сделки "
      f"{'в минусе и до комиссий' if P['mean_R_gross'] < 0 else 'в плюсе до комиссий, но не после'}. Свежие 30% "
      f"периода в плюсе ({r3(P['holdout']['mean_R'])}R на {P['holdout']['n']} сделках), первые 70% — "
      f"{r3(P['dev']['mean_R'])}R на {P['dev']['n']}: шесть сделок ничего не доказывают, а протокол отказывает по всему "
      f"периоду. Параметры после результата не менялись и меняться не будут — другая геометрия = новый протокол.")
    a("")

    a("## Итог по прогонам (базовые расходы: тейкер 0.048% + проскальзывание 0.02% на ногу, цель — мейкер 0.016%)")
    a("")
    a("| Прогон | Статус | n | WR | R после расходов | R ×2 проскальз. (n) | R до расходов | ДИ 95% среднего R "
      "(ISO-недели) | первые 70%: n / R | последние 30%: n / R | итог $ на $3 000 | макс. просадка $ | фандинг $ |")
    a("|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|")
    for sc, name in SCOPES:
        r, r2 = runs[f"S_{sc}_base"], runs[f"S_{sc}_slip2"]
        a(f"| {name} | {stt[sc]['label']} | {r['n']} | {pct(r['WR'])} | {r3(r['mean_R'])} | {r3(r2['mean_R'])} "
          f"({r2['n']}) | {r3(r['mean_R_gross'])} | {ci(r['weekly_ci'].get('all'))} | {r['dev']['n']} / "
          f"{r3(r['dev']['mean_R'])} | {r['holdout']['n']} / {r3(r['holdout']['mean_R'])} | {usd(r['sum_pnl'])} | "
          f"{usd(r.get('max_dd_usd'))} | {usd(r.get('funding_total'))} |")
    a("")
    a("R = net PnL / риск позиции (q × (|E − S*| + комиссия входа × E + комиссия выхода × S*)); стоп без гэпа = −1R. "
      "Фандинг: «+» — заплачено, «−» — получено. ×2 проскальзывание — полный повторный прогон (меняются E, ширина, цель и "
      "набор сделок), а не вычитание из готовых. Разрез 70/30 — по календарю, граница "
      f"{rp.iso(P['split_cut'])} UTC; эти данные проект уже видел, это не непросмотренная проверка.")
    a("")

    a("## Ворота протокола — портфель ETH+XRP")
    a("")
    a("| Ворота | Значение | Пройдены |")
    a("|---|---|:-:|")
    for g in stt["PORT"]["gates"]:
        v = g["value"]
        v = ci(v) if isinstance(v, list) else ((f"{v:.3f}" if "C3" in g["gate"] else r3(v)) if isinstance(v, float) else v)
        a(f"| {g['gate']} | {v} | {'да' if g['pass'] else '**нет**'} |")
    a("")
    a(f"Квалификация требует всех {len(stt['PORT']['gates'])} ворот; не пройдено {len(stt['PORT']['failed'])}. "
      + ("Статус «Отвергнута» — по правилу «среднее после расходов ≤ 0 на всём периоде»; одновременно выполнено и условие "
         "«Недостаточно данных» (n < 100)." if stt["PORT"]["label"].startswith("Отвергнута") else ""))
    a("")

    a("## Контроли (тот же цикл исполнения, тот же риск)")
    a("")
    a("| Прогон | Стратегия: R (n) | C1 прямой 4h-вход: R (n) | C2 откат без ADX: R (n) | C3: ранг | C3: среднее случайных | "
      "C3: 95-й перцентиль |")
    a("|---|---:|---:|---:|---:|---:|---:|")
    for sc, name in SCOPES:
        r, k1, k2, k3 = runs[f"S_{sc}_base"], runs[f"C1_{sc}_base"], runs[f"C2_{sc}_base"], c3[sc]
        a(f"| {name} | {r3(r['mean_R'])} ({r['n']}) | {r3(k1['mean_R'])} ({k1['n']}) | {r3(k2['mean_R'])} ({k2['n']}) | "
          f"{k3['rank']:.3f} | {r3(k3['random_mean_R'])} | {r3(k3['random_p95_R'])} |")
    a("")
    a("C3: для каждой сделки — случайная 15m-свеча той же монеты и стороны, той же 6-часовой корзины UTC и терциля "
      "ATR14/close, та же ширина стопа в %, цель 2R, 8 ч; 999 повторов, seed 20261015; ранг = (k+1)/1000, k — повторов со "
      "средним ≥ стратегии." + (" Ни C1, ни C2 ни в одном прогоне не в плюсе: 4h-пробой сам по себе на этих монетах в "
      "этой геометрии денег не дал, и откат его не улучшил." if all(
          (runs[f"{v}_{sc}_base"]["mean_R"] or 0) <= 0 for v in ("C1", "C2") for sc, _ in SCOPES) else "")
      + " Это согласуется с прежними отказами в той же семье: пробой ETH/XRP 2R/8 ч (+$0.85 за 152 дня, CLAUDE.md "
      "«WEEX 09–12.10 — не повторять») и пилот P1 GPT (−0.40…−0.53R, `docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_"
      "2026-10-15.md` §5).")
    a("")

    a("## Выходы по типам")
    a("")
    a("| Прогон | Стоп: n / R | Цель: n / R | 8 ч: n / R | Гэп через стоп: n | Медиана ширины стопа | Среднее удержание, мин |")
    a("|---|---|---|---|---:|---:|---:|")
    for sc, name in SCOPES:
        r = runs[f"S_{sc}_base"]
        e, em = r.get("exits", {}), r.get("exits_mean_R", {})
        cell = lambda k: f"{e.get(k, 0)} / {r3(em.get(k))}"            # noqa: E731
        a(f"| {name} | {cell('SL')} | {cell('TP')} | {cell('TIME')} | {e.get('SL_GAP', 0)} | {pct(r.get('median_width'), 2)} | "
          f"{r.get('mean_hold_min', 0):.0f} |")
    a("")

    a("## Воронка событий")
    a("")
    keys = [("events", "4h-события"), ("ignored_in_position", "во время позиции"), ("expire_touch", "нет касания EMA20 в №4…16"),
            ("cancel_new_extreme", "новый экстремум за low_p/high_p"), ("expire_confirm", "нет подтверждения"),
            ("cancel_close_beyond_4h", "close за экстремумом 4h-пробоя"), ("confirm", "подтверждений"),
            ("cancel_drift", "дрейф > 0.1A"), ("skip_width", "ширина вне 0.7–2.0%"), ("skip_busy", "слот занят другой монетой"),
            ("skip_daily_limit", "дневной лимит"), ("entered", "входов")]
    a("| | " + " | ".join(n for _, n in SCOPES) + " |")
    a("|---|" + "---:|" * len(SCOPES))
    for k, nm in keys:
        a(f"| {nm} | " + " | ".join(str(runs[f'S_{sc}_base']['counts'].get(k, 0)) for sc, _ in SCOPES) + " |")
    a("")
    a("Ширина стопа у подтверждений (до фильтра): " + "; ".join(
        f"{nm[:3]} — {d['n']}: уже 0.7% {d['narrow']}, в коридоре {d['ok']}, шире 2% {d['wide']}, медиана {pct(d['median'], 2)}"
        for nm, d in wd.items()) + ". Дрейф входа ни разу не превысил 0.1A: open следующей минуты на перпетуале почти "
      "равен close подтверждения.")
    a("")

    a("## LONG / SHORT")
    a("")
    a("| Прогон | LONG: n / R / $ | SHORT: n / R / $ |")
    a("|---|---|---|")
    for sc, name in SCOPES:
        r = runs[f"S_{sc}_base"]
        f = lambda b: f"{b['n']} / {r3(b['mean_R'])} / {usd(b['sum_pnl'])}"   # noqa: E731
        a(f"| {name} | {f(r['long'])} | {f(r['short'])} |")
    a("")
    if (P["short"]["mean_R"] or 0) > 0 or (P["long"]["mean_R"] or 0) > 0:
        a(f"Плюс одной стороны в портфеле (LONG {r3(P['long']['mean_R'])}R на {P['long']['n']}, SHORT "
          f"{r3(P['short']['mean_R'])}R на {P['short']['n']}) — выбор стороны по результату; протокол проверяет обе "
          "стороны вместе, отдельная «односторонняя версия» была бы новой гипотезой на уже просмотренных данных.")
    a("")

    a("## По месяцам — портфель ETH+XRP (по времени входа)")
    a("")
    mon = P["monthly"]
    a("| Месяц | n | R | $ |")
    a("|---|---:|---:|---:|")
    for m, b in mon.items():
        a(f"| {m} | {b['n']} | {r3(b['mean_R'])} | {usd(b['sum_pnl'])} |")
    a("")
    a(f"Месяцев с хотя бы одной сделкой — {len(mon)} из 30 (май 2024 — октябрь 2026); непустых ISO-недель — "
      f"{P['weekly_ci']['weeks_nonempty']} из {P['weekly_ci']['weeks_all']}. Помесячно по каждой монете — в ledger.")
    a("")

    a("## Карточка сделки")
    a("")
    if stt["PORT"]["label"].startswith("Кандидат"):
        a("(квалифицирована — см. правила протокола)")
    else:
        a("**Нет.** Стратегия не прошла ворота протокола, поэтому карточки для ручной торговли нет — ни в бумажный "
          "forward, ни живьём. Если хочется дальше искать в этой семье, это новая гипотеза со своим протоколом и новым "
          "календарным периодом, а не подстройка этой.")
    a("")

    a("## Данные и проверка кода")
    a("")
    a(f"Период: {man['start']} — {man['end_exclusive']} UTC (исключительно), общий конец — последняя закрытая минута "
      "самого короткого файла (BTC).")
    a("")
    a("| Файл | sha256 | Строк | Пропусков минут / дублей / дефектов OHLC | Свечей 15m / 4h (дыр) |")
    a("|---|---|---:|---|---|")
    for nm, d in man["inputs"].items():
        a(f"| `{d['minutes']}` | `{d['sha256']}` | {d['rows']} | {d['missing_minutes']} / {d['duplicates_or_unsorted']} / "
          f"{d['ohlc_defects']} | {d['bars15']} / {d['bars4']} ({d['bars15_holes']} / {d['bars4_holes']}) |")
    for nm, d in man["funding"].items():
        a(f"| `{d['file']}` | `{d['sha256']}` | {d['rows']} | начислений в периоде {d['in_period']}, интервалы ч "
          f"{d['interval_hours']}, без mark {d['missing_mark']}, сдвиг метки ≤ {d['jitter_ms_max']} мс | {d['first']} — "
          f"{d['last']} |")
    a("")
    a("Фандинг — публичный `GET https://fapi.binance.com/fapi/v1/fundingRate` (без ключей), "
      "`research/manual_pullback/fetch_funding.py`. Минутки — `research/atlas_data/fetch_binance_um_1m.py` (только закрытые).")
    a("")
    if A:
        ok = all(v["outcome_mismatches"] == 0 and not v["trade_mismatches"] and v["events_audit"] == v["events_replay"]
                 and v["trades_audit"] == v["trades_replay"] for v in A.values())
        tot_ev = sum(v["events_audit"] for v in A.values())
        tot_tr = sum(v["trades_audit"] for v in A.values())
        mx = max(v["max_abs_R_diff"] for v in A.values())
        a(f"**Независимая сверка** (`research/manual_pullback/audit.py`: свечи через pandas.resample, ADX/ATR — сглаживание "
          f"суммами, своя машина отката, построчный выход по минутам, фандинг перебором): прогоны S и C2 по каждой монете — "
          f"{tot_ev} событий и {tot_tr} сделок, {'исходы всех событий и все сделки совпали' if ok else 'ЕСТЬ РАСХОЖДЕНИЯ'} "
          f"(вид и время выхода, цены, номера свечей касания/подтверждения), max |ΔR| = {mx:.1e}.")
        a("")
    a(f"**Тесты:** `tests/research_manual/` — {n_tests} синтетических тестов (seed ADX Уайлдера, окно 30 без текущей, "
      "«впервые выше», окно №4…16, касание EMA20, приоритет отмен, подтверждение по двум high, дрейф ≤ 0.1A, ширина "
      "стопа, мейкер-цель от TP + тик, стоп раньше цели в минуте, гэп по open, выход через 8 ч, знак фандинга LONG/SHORT, "
      "округление размера вниз, одна позиция на портфель, дневной лимит, сквозной вход стратегии). Добавлены в "
      f"`scripts/_run_tests.py`. Полный набор: {suite}.")
    a("")

    a("## Отклонения от протокола и формализации")
    a("")
    a("Отклонения:")
    a("")
    lasts = {nm: d["last"] for nm, d in man["inputs"].items()}
    a("1. Конец данных общий для трёх монет — по самому короткому файлу; последние минуты выгрузок: "
      + ", ".join(f"{nm} {t}" for nm, t in lasts.items()) + " UTC. Протокол говорит «до последней закрытой минуты "
      "выгрузки» — у ETH/XRP отрезано до 2.5 ч хвоста; закрытий 4h в нём нет (последнее учтённое — 20:00 14.10, "
      "следующее — 00:00 15.10, его нет ни в одном файле), незавершённых сделок и ожидающих событий на конце — "
      f"{sum(runs[f'S_{sc}_base']['censored'] for sc, _ in SCOPES)} и "
      f"{sum(runs[f'S_{sc}_base']['counts'].get('pending_at_end', 0) for sc, _ in SCOPES)}.")
    a("2. Протокол не задаёт приоритет статусов; при среднем ≤ 0 и n < 100 пишу «Отвергнута (и n < 100)».")
    a("3. Вне пакета, чтобы полный набор проходил: `tests/services/range_hunter/test_signal.py::"
      "test_signal_buy_sell_levels_correct` падал от живого `state` (свежие VAL/VAH рядом с ценой теста подменяли "
      "симметричные уровни) — тест изолирован подменой `services.manual_levels.get_levels`; код службы не тронут.")
    a("4. Все параметры — из протокола; ничего не подбиралось по результатам. Неоднозначности решены до расчёта "
      "(записаны в `replay.py`, FORMALIZATIONS) и проверены тестами:")
    a("")
    for f in S["formalizations"]:
        a(f"   - {f}")
    a("")
    a("## Файлы")
    a("")
    a("- `research/manual_pullback/replay.py` — реплей (единый цикл исполнения `simulate()` для стратегии и C1/C2/C3), "
      "`stats.py` — статистика и статусы, `audit.py` — независимая сверка, `report.py` — этот отчёт, "
      "`fetch_funding.py` — фандинг.")
    a("- `research/manual_pullback/out/` — `summary.json`, `manifest.json` (sha256 входов, кода и протокола), "
      "`ledger_<вариант>_<прогон>_<расходы>.csv` (каждая сделка: уровни, размер, комиссии, фандинг, R), "
      "`events_*.csv` (исход каждого 4h-события), `audit.json`.")
    a(f"- sha256 протокола `{man['protocol_sha256']}`, replay.py `{man['replay_sha256']}`, stats.py `{man['stats_sha256']}`.")
    a("")
    DOC.write_text("\n".join(L), encoding="utf-8")
    print(DOC)


if __name__ == "__main__":
    main()
