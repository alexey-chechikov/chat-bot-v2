"""Отчёт по протоколу docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (b048207 + §7а 6ed43ad): читает out/summary.json
(и out/data_manifest.json — для раздела данных), пишет docs/TREND_4H_RECHECK_RESULTS_2026-10-15.md. Вердикт — первой
строкой, простым русским языком; затем таблицы.

  .venv/bin/python3 research/trend_recheck/report.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
DOC = ROOT / "docs" / "TREND_4H_RECHECK_RESULTS_2026-10-15.md"
SC = {"ETHUSDT": "ETH", "XRPUSDT": "XRP", "PORT": "ETH+XRP", "BTCUSDT": "BTC (вне решения)"}
KIND = {"close_exit": "выход по закрытию 4h", "emergency_stop": "аварийный стоп", "gap_through_stop": "гэп через стоп",
        "censored": "открыта на конец (censored)"}
GATE_SHORT = {1: "среднее R > 0 и при ×2", 2: "n ≥ 100, недель ≥ 30", 3: "низ 95% ДИ > 0", 4: "треть 3 P1 > 0 и P2 > 0",
              5: "4 соседа > 0", 6: "4 якоря > 0", 7: "ранг C1 ≤ 0.05"}

HONESTY = """**Честная оговорка (протокол §1).** P1 — период, на котором параметры правила (канал 30, Chandelier 3·ATR,
ADX ≥ 20) не подбирались, а не «никем не виденный период»: семейство 4h-пробоев (Дончиан 20/55) уже смотрела
лаборатория индикаторов TV 05.10 на спотовых 1h с 2017–2018.

Какие периоды видели прежние исследования (ответ шага данных; скрипта отбора 28.07 в git нет, период восстановлен
косвенно — по точному совпадению цифр ETH и BTC со `state/asset_profiles.json` из ec80ca1):
- `tools/trend_state.py`, коммит 00e66b1 (28.07) — параметры появились здесь и с тех пор не менялись (git log -G: только
  00e66b1 и ec80ca1, значения те же). Загрузчик того времени читал `backtests/frozen/<SYM>_1m_2y.csv` — спот Binance с
  2024-05-15. Цифры 28.07 ETH +109% PF 1.68 и BTC −3.5% PF 0.98 точно совпадают с asset_profiles (период «2024-05-15 →
  2026-07-29»); у XRP небольшое необъяснённое расхождение (+117%/1.51 против +112.6%/1.48). Развёртка 16 ячеек и
  сравнение выходов шли на том же периоде; ADX 20 не подбирался — был фиксирован.
- `tools/calibrate_assets.py` (29.07, перекалибровка 11.10) — параметры фиксированы, спот 1m_2y с 2024-05-15.
- `research/trend_expand/scan.py` (10.10) — спот 4h через API с 2024-10-10; отбирал монеты, не параметры.
- `research/weex/trend_risk_size.py` (11.10) — те же 4h с 2024-10-10, параметры 30/3 фиксированы.
- `research/weex/trend_sides.py` (10.10) — спот 1m_2y с 2024-05-15, параметры фиксированы.
- `tools/_regime_trend.py` (01.06) — только BTC, с 2024-05-15, другое правило (EMA + Дончиан, ADX 18/22/25/30).
- Аудит 29.09 (`docs/CONTEXT/REPLY_WIN_YT_AUDIT_2026-09-29.md`) — трети с 2024-05-15; walk-forward на старой трети
  выбирает ADX 20 — тоже только P2.
- Единственный контакт с данными до 2024-05-15 — `tools/tv_indicator_lab.py` (05.10, после выбора параметров): спот 1h
  с 2017-08 (BTC/ETH) и 2018-05 (XRP), периоды 2017-08…2020-09 и 2020-10…2023-09; там другие правила (Дончиан 20/55 со
  стопом ATR и тейком 2/3/5R, ADX/DMI-кросс при ADX > 20, Chandelier 22/3) — параметры 30/3/20 там не выбирались.
- Отбор шёл на СПОТЕ, P1 здесь — перпетуал UM.
- P1 начинается с первого месячного архива (формализация F0 шага данных): ETH и BTC с 2020-01-01 (REST знает минуты
  раньше — ETH с 2019-11-27, BTC с 2019-09-08, но архивов 1m за 2019 нет), XRP с 2020-01-06 08:21. Текст «с первой
  минуты UM-истории» буквально не выполнен для ETH (≈35 дней) и BTC (≈114 дней).
- §7а (дыры XRP): черновой прогон этой реализации 15.10 в 10:00 UTC уже содержал цифры XRP; дополнение §7а закоммичено
  в 14:02 UTC (6ed43ad). По тексту дополнения его автор видел только базовые цифры ETH независимой реализации. Основной
  расчёт дополнение не меняет — оно лишь добавляет чувствительность."""


def f(x, nd=3, sign=True):
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def usd(x):
    return "—" if x is None else f"{'−' if x < 0 else '+'}${abs(x):,.0f}".replace(",", " ")


def pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def pos(x) -> bool:
    return x is not None and x > 0


def _why(gate: int, g: dict) -> str:
    ci = g["ci_all"] or [None, None]
    bad_off = [f"{k}:00 UTC — {f(v)}R" for k, v in g["offsets"].items() if not pos(v)]
    bad_nb = [f"{k} {f(v)}R" for k, v in g["neighbors"].items() if not pos(v)]
    return {1: f"после расходов или при ×2 проскальзывании не в плюсе ({f(g['mean_R'])} / {f(g['mean_R_slip2'])}R)",
            2: f"мало данных (сделок {g['n']}, непустых недель {g['weeks_nonempty']})",
            3: f"ноль не исключён: 95% интервал среднего от {f(ci[0])} до {f(ci[1])}R",
            4: f"не в плюсе свежая часть (последняя треть P1 {f(g['third3_mean_R'])}R, P2 {f(g['p2_mean_R'])}R)",
            5: "соседние настройки в минусе: " + ", ".join(bad_nb),
            6: "результат зависит от того, с какого часа UTC начинаются 4h-свечи: при начале в " + ", ".join(bad_off),
            7: f"не лучше случайного входа с тем же выходом (ранг C1 {f(g['c1_rank'], 3, False)})"}[gate]


def verdict(s: dict) -> str:
    g = s["gate_values"]
    st = s["status"]
    failed = [r["gate"] for r in s["gates"] if not r["pass"]]
    P1 = s["summary"]["base"]["PORT"]["P1"]
    head = {"Квалифицирована": "да — правило прошло проверку",
            "Не квалифицирована": "нет — правило не прошло проверку",
            "Отвергнута": "нет — правило отвергнуто"}
    key = next((k for k in head if st.startswith(k)), st)
    body = (f"На 2020-01 … 2024-05, где его параметры не подбирались, тренд 4h ETH+XRP дал в среднем "
            f"{f(P1['mean_R'])}R на сделку после комиссий, проскальзывания и фандинга ({P1['n']} сделок, "
            f"{usd(P1['sum_net'])} при риске $50)")
    if failed:
        body += ", но " + "; ".join(_why(x, g) for x in failed) + f" (не пройдены ворота {', '.join(map(str, failed))} из 7)."
    else:
        body += "; все 7 ворот пройдены."
    ind = s.get("c1_independent_diag", {}).get("ranks", {}).get("PORT_P1", {})
    if 7 not in failed and ind.get("rank") is not None and ind["rank"] > 0.05:
        body += (f" Ворота 7 пройдены только формально: принятая до расчёта схема контроля «одна позиция» отбирает "
                 f"короткие, убыточные случайные сделки; без неё случайный вход с тем же выходом даёт в среднем "
                 f"{f(ind.get('control_mean_of_means'))}R, ранг стратегии {f(ind['rank'], 3, False)} — сам сигнал "
                 f"входа не лучше случайного.")
    return f"**Вердикт: {head.get(key, st)} (статус «{st}»).** {body}"


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def base_table(s: dict, vname: str = "base") -> str:
    rows = []
    for scope in ("ETHUSDT", "XRPUSDT", "PORT", "BTCUSDT"):
        for p in ("P1", "P2", "full"):
            b = s["summary"][vname][scope][p]
            dd = s["equity_dd"].get(f"{vname}_{scope}_{p}", {}).get("max_dd")
            rows.append([SC[scope], p, b["n"], b["censored"], f(b["mean_R"]), f(b["median_R"]), pct(b["WR"]),
                         f(b["PF"], 2, False), usd(b["sum_net"]), usd(b["R50"]), usd(-b["fees"]) if b["n"] else "—",
                         usd(b["funding"]) if b["n"] else "—", usd(dd)])
    return table(["монета", "период", "n", "cens", "ср. R", "медиана R", "WR", "PF", "$ net", "50·ΣR", "комиссии",
                  "фандинг", "макс. просадка"], rows)


def anchors(s: dict, sym: str) -> dict:
    return {h: s["summary"][n][sym]["P1"]["mean_R"] for h, n in
            (("00", "base"), ("01", "offset_01"), ("02", "offset_02"), ("03", "offset_03"))}


def anchor_phrase(s: dict, sym: str) -> str:
    a = anchors(s, sym)
    plus = [h for h, v in a.items() if pos(v)]
    vals = ", ".join(f"{h}: {f(v)}" for h, v in a.items())
    if len(plus) == 4:
        return f"в плюсе при всех четырёх ({vals}R)"
    if not plus:
        return f"в минусе при всех четырёх ({vals}R)"
    return f"в плюсе только при {', '.join(h + ':00' for h in plus)} UTC ({vals}R)"


def section_7a(s: dict, A: list) -> None:
    F = s["xrp_filled_7a"]
    fr = F["fill_report"]
    dif = F["xrp_trade_diff"]
    A("## §7а — чувствительность: XRP с 5 днями из дневных архивов (ворота — по основному расчёту)")
    A("")
    ck = fr["check_vs_monthly"]
    A(f"Вставлено {fr['inserted_minutes']} минут ({', '.join(fr['fill_days'])}) из дневных архивов Binance UM 1m, "
      f"каждый сверен с `.CHECKSUM`; ни одна минута не наложилась на имеющиеся, пропусков в P1 XRP после вставки "
      f"{fr['p1_missing_after']}, невалидных минут {fr['invalid_inserted_minutes']}. Контроль: соседние дни "
      f"{', '.join(ck)} из дневных архивов совпали с минутами месячных архивов по OHLCV — "
      f"{', '.join(str(v['numeric_equal_ohlcv']) for v in ck.values())} из 1440. Скачки на стыках с имеющимися "
      f"минутами — не больше {max(abs(x['jump_pct']) for x in fr['seams']):.3f}% (один тик). Ряд — только в памяти, "
      f"frozen-файлы не менялись. 4h-свечей XRP: {s['data']['XRPUSDT']['bars']} → {F['data']['XRPUSDT']['bars']}.")
    A("")
    A(f"Сделки базы XRP: те же {dif['same']}, изменились {len(dif['changed'])}, только в основном "
      f"{len(dif['only_primary'])}, только в §7а {len(dif['only_filled'])}.")
    if dif["changed"] or dif["only_primary"] or dif["only_filled"]:
        A("")
        rows = []
        for c in dif["changed"]:
            a, b = c["primary"], c["filled"]
            rows.append(["изменилась", a["side"], a["entry_utc"], f"{a['exit_utc']} {KIND.get(a['kind'], a['kind'])} "
                         f"{f(a['R'], 2)}R", f"{b['exit_utc']} {KIND.get(b['kind'], b['kind'])} {f(b['R'], 2)}R"])
        for a in dif["only_primary"]:
            rows.append(["только в основном", a["side"], a["entry_utc"],
                         f"{a['exit_utc']} {KIND.get(a['kind'], a['kind'])} {f(a['R'], 2)}R", "—"])
        for b in dif["only_filled"]:
            rows.append(["только в §7а", b["side"], b["entry_utc"], "—",
                         f"{b['exit_utc']} {KIND.get(b['kind'], b['kind'])} {f(b['R'], 2)}R"])
        A(table(["", "сторона", "вход", "основной: выход, тип, R", "§7а: выход, тип, R"], rows))
    A("")
    rows = []
    for scope in ("XRPUSDT", "PORT"):
        for p in ("P1", "P2", "full"):
            a, b = s["summary"]["base"][scope][p], F["summary"]["base"][scope][p]
            rows.append([SC[scope], p, f"{f(a['mean_R'])} (n {a['n']}, {usd(a['sum_net'])})",
                         f"{f(b['mean_R'])} (n {b['n']}, {usd(b['sum_net'])})"])
    A(table(["монета", "период", "основной: ср. R (n, $)", "§7а: ср. R (n, $)"], rows))
    A("")
    rows = []
    for ra, rb in zip(s["gates"], F["gates"]):
        rows.append([ra["gate"], GATE_SHORT[ra["gate"]], ra["value"], "да" if ra["pass"] else "**нет**", rb["value"],
                     "да" if rb["pass"] else "**нет**"])
    A(table(["№", "ворота", "основной", "пройдено", "§7а (для сведения)", "прошло бы"], rows))
    A("")
    same = F["status"] == s["status"]
    A(f"Статус по основному расчёту — «{s['status']}». На ряду §7а ворота дали бы «{F['status']}» — "
      + ("вывод от заполнения дыр не зависит." if same else "ДРУГОЙ итог; решение всё равно по основному расчёту (§7а).")
      + f" C1 без запрета наложения (диагностика) на ряду §7а: ранг "
        f"{f(F['c1_independent_diag']['ranks']['PORT_P1']['rank'], 3, False)}.")
    A("")


def write(s: dict) -> Path:
    L: list[str] = []
    A = L.append
    A(verdict(s))
    A("")
    g, P = s["gate_values"], s["summary"]["base"]
    qualified = s["status"].startswith("Квалифицирована")
    A(f"Протокол: `{s['protocol']}` (commit {s['protocol_commit']}, дополнение §7а — {s['addendum_commit']}), правила и "
      f"параметры не менялись. Расчёт {s['generated_utc']} UTC, основная реализация `research/trend_recheck/` (тесты "
      f"`tests/research_trend/`).")
    A("")
    A("## Коротко")
    A("")
    A(f"- **P1 (решение):** ETH+XRP {f(P['PORT']['P1']['mean_R'])}R на сделку, n {P['PORT']['P1']['n']}, "
      f"{usd(P['PORT']['P1']['sum_net'])}; ETH {f(P['ETHUSDT']['P1']['mean_R'])}R (n {P['ETHUSDT']['P1']['n']}), "
      f"XRP {f(P['XRPUSDT']['P1']['mean_R'])}R (n {P['XRPUSDT']['P1']['n']}).")
    A(f"- **P2 (просмотренный период отбора):** ETH+XRP {f(P['PORT']['P2']['mean_R'])}R, n {P['PORT']['P2']['n']}, "
      f"{usd(P['PORT']['P2']['sum_net'])} — уже с аварийным стопом внутри свечи, расходами WEEX и фандингом.")
    A(f"- **BTC (отрицательный контроль, вне решения):** P1 {f(P['BTCUSDT']['P1']['mean_R'])}R "
      f"(n {P['BTCUSDT']['P1']['n']}), P2 {f(P['BTCUSDT']['P2']['mean_R'])}R (n {P['BTCUSDT']['P2']['n']}). "
      + ("Отрицательный контроль не отрицательный: BTC, не прошедший отбор 28.07, на P1 не хуже ETH+XRP — отбор "
         "монет по P2 на P1 не подтверждается."
         if pos(P['BTCUSDT']['P1']['mean_R']) and P['BTCUSDT']['P1']['mean_R'] >= (P['PORT']['P1']['mean_R'] or 0)
         else ""))
    c1 = s["c1"]["ranks"]["PORT_P1"]
    ci1 = s["c1_independent_diag"]["ranks"]["PORT_P1"]
    du = s["c1"]["duration_bars_mean"]["PORT_P1"], s["c1_independent_diag"]["duration_bars_mean"]["PORT_P1"]
    A(f"- **Случайный вход с тем же выходом (C1):** по объявленной схеме R16 ранг {f(c1['rank'], 3, False)} (контроль "
      f"{f(c1.get('control_mean_of_means'))}R против {f(c1['strategy_mean'])}R у стратегии), но R16 смещена: запрет "
      f"наложения пропускает длинные контрольные сделки (средняя длина {du[0]:.1f} против {du[1]:.1f} свечей без "
      f"запрета), а длинные в тренде — прибыльные. Без запрета наложения контроль {f(ci1.get('control_mean_of_means'))}R, "
      f"ранг {f(ci1['rank'], 3, False)}"
      + (": сигнал пробоя с ADX не лучше случайного входа той же стороны с тем же выходом. " if ci1["rank"] > 0.05
         else ". ")
      + "Найдено после расчёта; ворота 7 формально пройдены, статус от этого не зависит.")
    failed = [r for r in s["gates"] if not r["pass"]]
    if failed:
        A("- **Не пройдено:** " + "; ".join(f"ворота {r['gate']} ({r['value']})" for r in failed) + ".")
    A(f"- **Начало 4h-свечей (якорь), P1:** ETH {anchor_phrase(s, 'ETHUSDT')}; XRP {anchor_phrase(s, 'XRPUSDT')}.")
    ex = s["exits"]["PORT"]["P1"]
    n_st = ex["emergency_stop"]["n"] + ex["gap_through_stop"]["n"]
    n_all = n_st + ex["close_exit"]["n"]
    ne = s["summary"]["no_emergency"]["PORT"]["P1"]["mean_R"]
    A(f"- **Аварийный стоп внутри свечи** (как у живого бота, храповик только в пользу) закрыл {n_st} из {n_all} "
      f"сделок P1; без него на P1 было бы {f(ne)}R против {f(P['PORT']['P1']['mean_R'])}R. Это заранее объявленная "
      f"чувствительность, не основание менять правило: другая геометрия — новый протокол.")
    l0 = s["last365"]["base"]
    A(f"- **Последние 365 дней P2** (с {l0['from_utc'][:10]}): n {l0['n']}, {f(l0['mean_R'])}R, {usd(l0['sum_net'])}.")
    F = s["xrp_filled_7a"]
    A(f"- **§7а, XRP с заполненными 5 днями:** ETH+XRP P1 {f(F['summary']['base']['PORT']['P1']['mean_R'])}R "
      f"(n {F['summary']['base']['PORT']['P1']['n']}); ворота дали бы «{F['status']}» "
      f"({'тот же итог' if F['status'] == s['status'] else 'другой итог'}). Решение — по основному расчёту.")
    A("- **Исход по протоколу:** " + ("квалифицируется → отдельным шагом карточка ручной сделки и Pine-алерт; живой "
                                      "бот остаётся холостым до R1–R4, R6, R7 и слова оператора."
                                      if qualified else "тренд 4h ETH/XRP убирается из «что держится»."))
    A("")
    A(HONESTY)
    A("")
    A("## Ворота (портфель ETH+XRP, P1)")
    A("")
    ind = s["c1_independent_diag"]["ranks"]["PORT_P1"]["rank"]

    def mark(r):
        if r["gate"] == 7 and r["pass"] and ind is not None and ind > 0.05:
            return f"пройдено формально (R16 смещена; без запрета наложения ранг {f(ind, 3, False)})"
        return "пройдено" if r["pass"] else "**не пройдено**"

    A(table(["№", "ворота", "значение", "итог"], [[r["gate"], r["text"], r["value"], mark(r)] for r in s["gates"]]))
    A("")
    A(f"**Статус: {s['status']}.**")
    A("")
    section_7a(s, A)
    A("## Базовая ячейка (канал 30, Chandelier 3·ATR, ADX ≥ 20, аварийный стоп 1.5%, тейкер 0.048% + 0.02% на ногу)")
    A("")
    A("Отнесение к периоду — по времени входа; censored в n и средние не входят. «$ net» — сумма net PnL при риске $50 "
      "до аварийного стопа и потолке $3 000; «50·ΣR» — то же в единицах риска. Просадка — по совместной кривой на "
      "закрытиях 4h с плавающим результатом (R17).")
    A("")
    A(base_table(s))
    A("")
    ci = s["ci"]
    A("Бутстрап блоками по ISO-неделям (9 999, seed 20261015), 95% ДИ среднего R:")
    A("")
    rows = []
    for k in ("PORT_P1", "ETHUSDT_P1", "XRPUSDT_P1", "PORT_P2", "PORT_full", "BTCUSDT_P1", "slip2_PORT_P1"):
        c = ci.get(k)
        if not c:
            continue
        rows.append([k.replace("PORT", "ETH+XRP").replace("USDT", ""), c["weeks_all"], c["weeks_nonempty"],
                     f"[{f(c['all'][0])}; {f(c['all'][1])}]" if c.get("all") else "—",
                     f"[{f(c['nonempty'][0])}; {f(c['nonempty'][1])}]" if c.get("nonempty") else "—"])
    A(table(["выборка", "недель всего", "непустых", "ДИ (все недели)", "ДИ (только непустые)"], rows))
    A("")
    A("## ×2 проскальзывание (0.04% на ногу, полный повторный прогон)")
    A("")
    rows = []
    for scope in ("ETHUSDT", "XRPUSDT", "PORT", "BTCUSDT"):
        for p in ("P1", "P2"):
            b0, b2 = P[scope][p], s["summary"]["slip2"][scope][p]
            rows.append([SC[scope], p, b2["n"], f(b0["mean_R"]), f(b2["mean_R"]), usd(b2["sum_net"])])
    A(table(["монета", "период", "n", "ср. R база", "ср. R ×2", "$ net ×2"], rows))
    A("")
    A("## Время: трети P1 по календарю (по 532 дня)")
    A("")
    rows = []
    for scope in ("PORT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
        th = s["thirds"][scope]
        rows.append([SC[scope]] + [f"{f(x['mean_R'])} (n {x['n']}, {usd(x['sum_net'])})" for x in th])
    th2 = s["thirds_slip2_PORT"]
    rows.append(["ETH+XRP ×2 проск."] + [f"{f(x['mean_R'])} (n {x['n']})" for x in th2])
    b = s["thirds_bounds_utc"]
    A(table(["монета", f"1: {b[0][0][:10]} … {b[0][1][:10]}", f"2: … {b[1][1][:10]}", f"3: … {b[2][1][:10]}"], rows))
    A("")
    A("Границы — полночь UTC, правая не включается (вход 2022-11-29 23:59 — вторая треть).")
    A("")
    A("## C1 — случайный вход, тот же выход (999 повторов, seed 20261015)")
    A("")
    A("Страта: та же монета, сторона, период, час закрытия 4h-свечи, терциль ATR14/close; одна позиция по символу "
      "(R16). Ранг = (k+1)/1000, k — повторы со средним R ≥ стратегии.")
    A("")
    rows = []
    for key in ("PORT_P1", "ETHUSDT_P1", "XRPUSDT_P1", "PORT_P2", "BTCUSDT_P1", "BTCUSDT_P2"):
        r, rl, ri = (s["c1"]["ranks"][key], s["c1_literal_diag"]["ranks"][key],
                     s["c1_independent_diag"]["ranks"][key])
        sd = s["strategy_duration_bars_mean"][key]
        rows.append([key.replace("PORT", "ETH+XRP").replace("USDT", ""), f(r["strategy_mean"]),
                     f"{f(r.get('control_mean_of_means'))} / {f(r.get('control_p95'))}", f(r["rank"], 3, False),
                     f"{f(ri.get('control_mean_of_means'))} / {f(ri.get('control_p95'))}", f(ri["rank"], 3, False),
                     f"{f(rl['rank'], 3, False) if rl.get('rank') is not None else '—'} "
                     f"({s['c1_literal_diag']['trades_mean'][key]:.1f})",
                     f"{sd:.1f} / {s['c1']['duration_bars_mean'][key]:.1f} / "
                     f"{s['c1_independent_diag']['duration_bars_mean'][key]:.1f}" if sd else "—"])
    A(table(["выборка", "стратегия ср. R", "R16: контроль ср. / 95-й перц.", "R16: ранг (ворота 7)",
             "без запрета наложения: контроль ср. / 95-й перц.", "его ранг (диагностика)",
             "буквальный: ранг (сделок на повтор)", "длина сделки, свечей: стратегия / R16 / без запрета"], rows))
    A("")
    ci1 = s["c1_independent_diag"]["ranks"]["PORT_P1"]
    A(f"**Смещение R16 (найдено после расчёта, правила не менялись).** Схема «одна позиция» R16 ставит контрольную "
      f"сделку только туда, где она целиком помещается между уже поставленными, — длинная сделка помещается реже. "
      f"В тренде длинные сделки — прибыльные, поэтому контроль R16 занижен: средняя длина "
      f"{s['c1']['duration_bars_mean']['PORT_P1']:.1f} свечей против "
      f"{s['c1_independent_diag']['duration_bars_mean']['PORT_P1']:.1f} без запрета наложения (у стратегии "
      f"{s['strategy_duration_bars_mean']['PORT_P1']:.1f}), среднее R {f(s['c1']['ranks']['PORT_P1']['control_mean_of_means'])} "
      f"против {f(ci1.get('control_mean_of_means'))}. Без запрета наложения (каждый вход стратегии получает "
      f"независимую случайную свечу из своей страты) ранг ETH+XRP на P1 — {f(ci1['rank'], 3, False)}; буквальный "
      f"последовательный вариант — {f(s['c1_literal_diag']['ranks']['PORT_P1']['rank'], 3, False)}. "
      + ("Ни один вариант без смещения по длине не отделяет стратегию от случайного входа с тем же выходом. "
         if ci1["rank"] > 0.05 and (s["c1_literal_diag"]["ranks"]["PORT_P1"]["rank"] or 1) > 0.05 else "")
      + (f"Пул всех кандидатов (таблица ниже): на P1 случайный лонг с этим выходом в среднем "
         f"{f(s['c1_pool_diag']['PORT_P1_LONG']['mean_R'])}R после расходов, шорт "
         f"{f(s['c1_pool_diag']['PORT_P1_SHORT']['mean_R'])}R — плюс даёт рост рынка 2020–2024 и выход, а не момент "
         f"пробоя. " if pos(s["c1_pool_diag"]["PORT_P1_LONG"]["mean_R"]) else "")
      + "Тест смещения — `tests/research_trend/test_tr_stats_data.py::"
        "test_c1_nonoverlap_prefers_short_trades_independent_does_not`.")
    A("")
    c = s["c1"]
    cl = s["c1_literal_diag"]
    A("Выпавшие контрольные входы (нет допустимого кандидата), среднее на повтор: " +
      ", ".join(f"{k[:3]} {c['dropped_mean'][k]:.1f} из {c['templates'][k]} (макс. {c['dropped_max'][k]})"
                for k in c["templates"]) +
      ". Буквальный последовательный вариант (кандидат только после выхода предыдущей контрольной позиции в порядке "
      "входов стратегии): " + ", ".join(f"{k[:3]} {cl['dropped_mean'][k]:.1f}" for k in cl["templates"]) +
      " выпавших на повтор — первый случайный вход уводит позицию в середину периода, и почти всё остальное выпадает; "
      "его средние — по горстке сделок, поэтому ворота 7 считаются по R16.")
    A("")
    lit_status, ind_status = s.get("status_if_c1_literal_diag"), s.get("status_if_c1_independent_diag")
    if lit_status is not None and ind_status is not None:
        same = lit_status == s["status"] and ind_status == s["status"]
        A(f"От схемы C1 зависят только ворота 7. По буквальному варианту статус был бы «{lit_status}», без запрета "
          f"наложения — «{ind_status}»: {'тот же итог' if same else 'ИТОГ МЕНЯЕТСЯ — см. выше'}.")
        A("")
    pool = s["c1_pool_diag"]
    rows = []
    for scope in ("PORT", "BTCUSDT"):
        for p in ("P1", "P2"):
            row = [SC[scope], p]
            for dn in ("both", "LONG", "SHORT"):
                x = pool[f"{scope}_{p}_{dn}"]
                row.append(f"{f(x['mean_R'])} / {f(x['mean_R_gross'])} (n {x['n']})")
            rows.append(row)
    A("Пул всех кандидатов C1 (каждая полная свеча после прогрева, обе стороны, тот же цикл исполнения, без страт и "
      "без запрета наложения), среднее R после расходов / до расходов и фандинга:")
    A("")
    A(table(["монета", "период", "обе стороны", "LONG", "SHORT"], rows))
    A("")
    A("## C2 — пробой без фильтра ADX")
    A("")
    rows = []
    for scope in ("ETHUSDT", "XRPUSDT", "PORT", "BTCUSDT"):
        for p in ("P1", "P2"):
            b0, b2 = P[scope][p], s["summary"]["c2_no_adx"][scope][p]
            rows.append([SC[scope], p, b0["n"], f(b0["mean_R"]), b2["n"], f(b2["mean_R"]), usd(b2["sum_net"])])
    A(table(["монета", "период", "n с ADX", "ср. R с ADX", "n без ADX", "ср. R без ADX", "$ без ADX"], rows))
    A("")
    A("## Чувствительность (объявлена заранее, не для выбора)")
    A("")
    A("**16 ячеек на P1, портфель ETH+XRP: среднее R (n).** Базовая — (30, 3); соседи ворот 5 — (20,3), (45,3), "
      "(30,2.5), (30,4).")
    A("")
    rows = []
    for lb in (20, 30, 45, 60):
        row = [lb]
        for k in ("2", "2.5", "3", "4"):
            bb = s["summary"][f"cell_lb{lb}_k{k}"]["PORT"]["P1"]
            row.append(f"{f(bb['mean_R'])} ({bb['n']})")
        rows.append(row)
    A(table(["канал \\ K", "K 2", "K 2.5", "K 3", "K 4"], rows))
    A("")
    rows = []
    for lb in (20, 30, 45, 60):
        row = [lb]
        for k in ("2", "2.5", "3", "4"):
            e = s["summary"][f"cell_lb{lb}_k{k}"]["ETHUSDT"]["P1"]["mean_R"]
            x = s["summary"][f"cell_lb{lb}_k{k}"]["XRPUSDT"]["P1"]["mean_R"]
            row.append(f"{f(e)} / {f(x)}")
        rows.append(row)
    A("По монетам (ETH / XRP), P1:")
    A("")
    A(table(["канал \\ K", "K 2", "K 2.5", "K 3", "K 4"], rows))
    A("")
    A("**Смещение якоря 4h-свечей (с какого часа UTC начинаются свечи), P1:**")
    A("")
    rows = []
    for h, name in ((0, "base"), (1, "offset_01"), (2, "offset_02"), (3, "offset_03")):
        sm = s["summary"][name]
        rows.append([f"{h:02d}:00 UTC", f"{f(sm['PORT']['P1']['mean_R'])} ({sm['PORT']['P1']['n']})",
                     f(sm["ETHUSDT"]["P1"]["mean_R"]), f(sm["XRPUSDT"]["P1"]["mean_R"]),
                     f"{f(sm['PORT']['P2']['mean_R'])} ({sm['PORT']['P2']['n']})", f(sm["BTCUSDT"]["P1"]["mean_R"])])
    A(table(["якорь", "ETH+XRP P1 (n)", "ETH P1", "XRP P1", "ETH+XRP P2 (n)", "BTC P1"], rows))
    A("")
    A("**Задержка входа +5 мин и вариант без аварийного стопа:**")
    A("")
    rows = []
    for name, label in (("base", "база"), ("delay5", "вход +5 мин"), ("no_emergency", "без аварийного стопа"),
                        ("slip2", "×2 проскальзывание")):
        sm = s["summary"][name]
        rows.append([label] + [f"{f(sm['PORT'][p]['mean_R'])} (n {sm['PORT'][p]['n']}, {usd(sm['PORT'][p]['sum_net'])})"
                               for p in ("P1", "P2", "full")])
    A(table(["вариант", "ETH+XRP P1", "ETH+XRP P2", "весь ряд"], rows))
    A("")
    l0, l1 = s["last365"]["base"], s["last365"]["no_emergency"]
    d0, d1 = s["equity_dd"]["base_PORT_P2"]["max_dd"], s["equity_dd"]["no_emergency_PORT_P2"]["max_dd"]
    A(f"Сверка с прежним бэктестом (спот, без аварийного стопа: +$1 867 за 2 года, последний год +$209, просадка "
      f"−$624): здесь на перпе P2 без аварийного стопа {usd(s['summary']['no_emergency']['PORT']['P2']['sum_net'])}, "
      f"последние 365 дней (с {l1['from_utc'][:10]}) {usd(l1['sum_net'])}, просадка {usd(d1)}; с аварийным стопом — "
      f"{usd(P['PORT']['P2']['sum_net'])}, {usd(l0['sum_net'])}, {usd(d0)}. Расходы и фандинг здесь включены; прежний "
      f"расчёт — другой ряд (спот) и другой учёт, поэтому сверка приблизительная.")
    A("")
    A("## Как закрывались сделки (база)")
    A("")
    rows = []
    for scope in ("PORT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
        for p in ("P1", "P2"):
            exs = s["exits"][scope][p]
            rows.append([SC[scope], p] + [f"{exs[k]['n']} / {f(exs[k]['mean_R'])} / {usd(exs[k]['sum_net'])}"
                                          for k in ("close_exit", "emergency_stop", "gap_through_stop", "censored")])
    A(table(["монета", "период"] + [f"{KIND[k]}: n / ср. R / $" for k in
                                    ("close_exit", "emergency_stop", "gap_through_stop", "censored")], rows))
    A("")
    A("## Воронка (база)")
    A("")
    rows = []
    for sym in ("ETHUSDT", "XRPUSDT", "BTCUSDT"):
        fu = s["funnel"][sym]
        fp = s["funnel_by_period"][sym]
        re = s["reentry_inside_live_episode"][sym]
        rows.append([SC[sym], fu["signals"], f"{fp['P1']['entry']} / {fp['P2']['entry']}", fu["skip_beyond_chandelier"],
                     fu["skip_qty0"], fu["skip_data_end"], fu["signal_on_incomplete_bar"], fu["incomplete_bars_total"],
                     fu["deferred_close_exits"], fu["trades_with_incomplete_bars"], f"{re['P1']} / {re['P2']}"])
    A(table(["монета", "сигналов", "входов P1 / P2", "пропуск: цена за стопом", "пропуск: qty 0",
             "пропуск: конец данных", "сигнал на неполной свече", "неполных свечей в ряду", "отложенных выходов",
             "сделок с неполной свечой", "входов внутри живого эпизода P1 / P2 (R1)"], rows))
    A("")
    re = s["reentry_inside_live_episode"]
    wr = s["without_reentry_diag"]["PORT"]["P1"]
    A("Входы внутри ещё живого эпизода сервиса сигналов (R1: после аварийного стопа или пропуска бэктест ищет вход "
      "со следующей свечи, живой сервис — только после своего выхода по закрытию), среднее R на P1: " +
      ", ".join(f"{k[:3]} {f(v['mean_R_P1'])} (n {v['P1']})" for k, v in re.items()) +
      f". Без них ETH+XRP на P1 — {f(wr['mean_R'])}R (n {wr['n']}; приближённо: выход оставшихся сделок не "
      f"пересчитан). Диагностика, не ворота.")
    A("")
    inc = []
    for name in ("offset_01", "offset_02", "offset_03", "delay5", "no_emergency"):
        fv = s["funnel_variants"][name]
        inc.append(f"{name}: " + ", ".join(
            f"{sym[:3]} неполных {fv[sym]['incomplete_bars_total']}, сигналов на неполной {fv[sym]['signal_on_incomplete_bar']}, "
            f"отложенных выходов {fv[sym]['deferred_close_exits']}, пропусков «за стопом» {fv[sym]['skip_beyond_chandelier']}"
            for sym in ("ETHUSDT", "XRPUSDT", "BTCUSDT")))
    A("Неполные свечи и пропуски в вариантах: " + "; ".join(inc) + ".")
    A("")
    A("## Живое против бэктеста (диагностика, не ворота)")
    A("")
    lv = s["live"]
    cnt = lv["counts"]
    bys = cnt.get("journal_by_symbol", {})
    pre_all = sum(v["pre_fix"] for v in bys.values())
    other = {k: v for k, v in bys.items() if k not in ("ETHUSDT", "XRPUSDT")}
    A(f"Живой журнал `state/trend_signals.jsonl` (только чтение): входов ETH/XRP {cnt['live_entries']}, из них до "
      f"исправления 17.09 — {cnt['pre_fix']} (совпало {cnt['pre_fix_matched']}, фантомов по незакрытой свече "
      f"{cnt['pre_fix_phantom']}); после 17.09 внутри данных — {cnt['post_fix_in_data']} (совпало "
      f"{cnt['post_fix_matched']}); после конца данных — {cnt['after_data_end']}. Окно сверки "
      f"{cnt['window_from_utc']} … {cnt['window_to_utc']}, допуск ±4 ч, та же сторона. Объяснения — по машине сигналов "
      f"на закрытых свечах спота (ряд живого сервиса, снимок `1m_2y`) и перпа (ряд бэктеста).")
    if other:
        A("")
        others = ", ".join(f"{k} — {v['entries']}" for k, v in other.items())
        A(f"В журнале есть и другие символы (входов: {others}) — вне проверки. Протокол называет «9 фантомов из 20» до "
          f"17.09; по журналу до 17.09 входов {pre_all} по всем символам, из них ETH/XRP {cnt['pre_fix']} — счёт "
          f"протокола в точности не воспроизводится. Здесь по ETH/XRP: фантомов {cnt['pre_fix_phantom']} из "
          f"{cnt['pre_fix']}.")
    A("")
    rows = []
    for r in lv["live"]:
        rows.append([r["symbol"][:3], r["side"], r["live_ts"], "до 17.09" if r["pre_fix_17_09"] else "после",
                     r["bt_entry_utc"] or "—", "—" if r["dt_h"] is None else f"{r['dt_h']:+.1f}",
                     f(r["bt_R"], 2) if r["bt_R"] is not None else "—",
                     "—" if r["live_pnl_pct"] is None else f"{r['live_pnl_pct']:+.2f}%", r["explanation"]])
    A(table(["монета", "сторона", "живой вход (UTC)", "до/после фикса", "вход бэктеста", "Δ ч", "R бэктеста",
             "живой итог", "объяснение"], rows))
    A("")
    if lv["bt_unmatched"]:
        A("Сделки бэктеста P2 в окне живого журнала без живого входа:")
        A("")
        A(table(["монета", "сторона", "вход", "выход", "тип выхода", "R", "объяснение"],
                [[r["symbol"][:3], r["side"], r["bt_entry_utc"], r["bt_exit_utc"], KIND.get(r["bt_exit_kind"], r["bt_exit_kind"]),
                  f(r["bt_R"], 2), r["explanation"]] for r in lv["bt_unmatched"]]))
        A("")
    else:
        A("Сделок бэктеста P2 в окне живого журнала без живого входа нет.")
        A("")
    sc = s.get("selfcheck")
    if sc:
        A("## Самопроверка основной реализации")
        A("")
        A("`research/trend_recheck/selfcheck.py` (не замена независимой реализации §7): свечи и ATR/ADX против pandas "
          "resample + dropna живого кода — побитово; машина сигналов — отдельным циклом; выход КАЖДОЙ сделки базы — "
          "поминутным перебором против быстрого пути по 4h (порядок: аварийный стоп по минутам, потом закрытие, "
          "храповик на закрытии); кандидаты C1 на свечах сигналов стратегии — те же сделки; фандинг — перебором строк "
          "файла; net, R, проскальзывание и qty — по формулам протокола; заглядывание вперёд — ряд, обрезанный в трёх "
          "точках, даёт те же закрытые до обрезки сделки до последнего знака. Расхождений: "
          f"**{sc['mismatches']}** ({sc['generated_utc']} UTC; " +
          ", ".join(f"{k.replace('USDT', '')}: сделок {v['trades']}, эпизодов {v['episodes']}, при обрезке сверено "
                    f"{v.get('truncation_trades_checked', '—')}" for k, v in sc["per_symbol"].items()) + ").")
        A("")
    A("## Найдено после расчёта (правила и параметры не менялись)")
    A("")
    A(f"- C1, схема «одна позиция» R16 смещена в пользу стратегии (см. раздел C1): ворота 7 засчитаны формально; без "
      f"запрета наложения ранг {f(s['c1_independent_diag']['ranks']['PORT_P1']['rank'], 3, False)}. Статус от этого "
      f"не зависит.")
    A("- R13: в тексте формализации была опечатка в границе второй трети (2022-11-29 вместо 2022-11-30 00:00 UTC); "
      "расчёт с самого начала шёл по правильной границе (532 дня), исправлен только текст.")
    A("- «9 фантомов из 20» протокола по журналу в точности не воспроизводится (см. «Живое против бэктеста»).")
    A("")
    A("## Формализации (записаны до расчёта)")
    A("")
    for x in s["formalizations"]:
        A(f"- {x}")
    A("- Данные: формализации F0–F10 шага подготовки — `research/trend_recheck/out/data_manifest.json` (F0: P1 с "
      "первого месячного архива; F7: целые значения части архивов дополнены нулями без изменения значения).")
    A("")
    A("## Данные")
    A("")
    rows = []
    for sym, d in s["data"].items():
        rows.append([sym, d["first_minute_utc"], d["data_end_utc"], f"{d['p1_rows']:,} + {d['p2_rows']:,}".replace(",", " "),
                     d["bars"], d["incomplete_bars"], d["funding_settlements_used"], d["funding_mark_from_close"]])
    A(table(["символ", "первая минута", "конец (последняя полная 4h)", "минут P1 + P2", "4h-свечей",
             "неполных", "начислений фандинга", "из них mark = close"], rows))
    A("")
    dm_path = OUT / "data_manifest.json"
    if dm_path.exists():
        dm = json.loads(dm_path.read_text(encoding="utf-8"))
        parts = []
        for sym, fd in dm["funding"].items():
            mm = dm["minutes"][sym]["P1_early"]
            parts.append(f"{sym[:3]}: фандинг {fd['rows']} начислений с {fd['first_utc'][:10]}, интервалы 8 ч — "
                         f"{sum(fd['intervals_hours'].values())}, других {fd['intervals_other']}, пропусков "
                         f"{fd['gaps_over_8h']}; минут P1 пропущено {mm['missing_minutes']}, нулевой объём "
                         f"{mm['zero_volume_minutes']}")
        A("Из `data_manifest.json`: " + "; ".join(parts) + ". Шов P1/P2 (15–31.05.2024): все общие минуты совпали, "
          "расхождений 0.")
        A("")
    A("## Файлы")
    A("")
    A("- Ledger базовой ячейки (вход/выход UTC, сторона, E, цена выхода, тип выхода, qty, R, PnL, фандинг): "
      "`research/trend_recheck/out/ledger_base_ETHUSDT.csv`, `…_XRPUSDT.csv`, `…_BTCUSDT.csv`; §7а — "
      "`out/ledger_base_XRPUSDT_filled7a.csv`.")
    A("- Все варианты: `out/ledger_variants.csv` (§7а XRP — `out/ledger_variants_XRPUSDT_filled7a.csv`); события и "
      "воронка: `out/events_base_<SYM>.csv`; повторы C1: `out/c1_reps.csv`, `out/c1_reps_filled7a.csv`; живое против "
      "бэктеста: `out/live_vs_backtest.csv`, `out/backtest_unmatched_live_window.csv`.")
    A("- Сводка: `out/summary.json`; sha256 входов (и дневных архивов §7а), скриптов и выходов: "
      "`out/results_manifest.json`; данные: `out/data_manifest.json`, `out/um_daily_fetch.json`.")
    A("- Повторить: `.venv/bin/python3 -I research/trend_recheck/fetch_um_daily.py` (дневные архивы §7а, один раз), "
      "затем `.venv/bin/python3 research/trend_recheck/selfcheck.py` и `.venv/bin/python3 research/trend_recheck/run.py` "
      "(≈ 2 минуты, сеть не нужна).")
    A("")
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    return DOC


if __name__ == "__main__":
    print(write(json.loads((OUT / "summary.json").read_text(encoding="utf-8"))))
