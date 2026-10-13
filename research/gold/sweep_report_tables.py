"""Таблицы отчёта из JSON-выводов sweep_backtest.py (--out=…) и sweep_lvn_controls.py (--out=…).

    .venv/bin/python3 research/gold/sweep_report_tables.py <paxg.json> <xau.json> [<paxg_s1.json> …] [<lvn_*.json> …]

Все R-колонки одной версии взяты из ОДНОГО ledger (капитал $3 000, после расходов): «до расходов» — те же сделки и тот же
qty без комиссий, проскальзывания и фандинга (разбор GPT 13.10, П7). Бюджетный R = PnL / R$ (0.25% капитала), ценовой R =
ход цены / (вход − стоп). ×2 проскальзывание — отдельный прогон.
"""
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone


def ts(x):
    return datetime.fromtimestamp(x / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def f3(x, sign=True):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:+.3f}" if sign else f"{x:.3f}"


def ci(c):
    return "—" if not c or c[0] is None else f"{c[0]:+.3f}…{c[1]:+.3f}"


def week_hist(tr) -> str:
    wk = Counter(tuple(datetime.fromtimestamp(t["entry_ts"] / 1000, timezone.utc).isocalendar()[:2]) for t in tr)
    return ",".join(str(v) for _, v in sorted(wk.items()))


def backtest(d: dict, name: str) -> None:
    info = d["info"]
    print(f"\n### {name}: строк {info['rows']}, sha256 {info['sha256'][:16]}…, {ts(info['first'])} … {ts(info['last'])} "
          f"UTC, контрольная часть с {ts(d['split_ts'])[:10]}{', только пн–пт' if d.get('s1') else ''}\n")
    fi = d.get("funding_info")
    if fi:
        print(f"Фандинг: {fi['rows']} начислений {ts(fi['first'])} … {ts(fi['last'])} UTC, интервалы (ч: число) "
              f"{fi['intervals_h']}, без markPrice {fi['mark_missing']}, sha256 {fi['sha256'][:16]}…\n")
    print("| Версия | n | WR | бюдж. R после | бюдж. R до расходов (тот же ledger) | ×2 проскальз. | 95% ДИ бюдж. после | "
          "ценовой R до | 95% ДИ ценовой до | ценовой R после | разработка R (n) | контроль R (n) | PF | макс. просадка | "
          "серия убытков | выходы цель/стоп/время/конец | недель (сделок по неделям) | статус |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v, vv in d["versions"].items():
        n, n2 = vv["3000_net"]["stats"], vv["3000_net_2slip"]["stats"]
        if not n.get("n"):
            print(f"| {v} | 0 |" + " |" * 16 + f" {vv['status']} |")
            continue
        e = n["exits"]
        weeks = f"{n['n_weeks']}" + (f" ({week_hist(vv['3000_net']['trades'])})" if n["n"] < 30 else "")
        print(f"| {v} | {n['n']} | {n['wr']:.0%} | {f3(n['exp_R'])} | {f3(n['exp_R_gross'])} | {f3(n2['exp_R'])} | "
              f"{ci(n['ci_R'])} | {f3(n['exp_pR_gross'])} | {ci(n['ci_pR_gross'])} | {f3(n['exp_pR'])} | "
              f"{f3(n['dev']['exp_R'])} ({n['dev']['n']}) | {f3(n['holdout']['exp_R'])} ({n['holdout']['n']}) | "
              f"{n['pf']:.2f} | {n['max_dd']:.1%} | {n['max_loss_streak']} | "
              f"{e['цель']}/{e['стоп']}/{e['время']}/{e['конец данных']} | {weeks} | {vv['status']} |")
    bma = d.get("b_minus_a")
    if bma and bma["net_R"]["diff"] is not None:
        a_, g_ = bma["net_R"], bma["gross_pR"]
        print(f"\nB−A (парный бутстрап по общим ISO-неделям, недель {a_['weeks']}): бюджетный R после {f3(a_['diff'])} "
              f"[95% ДИ {ci(a_['ci'])}]; ценовой R до расходов {f3(g_['diff'])} [95% ДИ {ci(g_['ci'])}]")
    print("\nСчётчики и чувствительности (капитал $3 000, после расходов):\n")
    print("| Версия | вход ниже low сигнальной (ТЗ отменило бы) | отмена по ТЗ «до входа»: n / отменено / R / статус | "
          "выходов по времени позже 4 ч 5 мин (дыра в данных) | сигналов обрезано концом данных | вход ниже стопа "
          "(ценовой R не определён) | урезано по номиналу | без фандинга: R / статус |")
    print("|---|---|---|---|---|---|---|---|")
    for v, vv in d["versions"].items():
        n = vv["3000_net"]["stats"]
        sens = vv.get("sens", {})
        sc = sens.get("spec_cancel", {})
        nf = sens.get("no_funding")
        sc_s = f"{sc.get('n', 0)} / {sc.get('cancelled', 0)} / {f3(sc.get('exp_R'))} / {sc.get('status', '—')}"
        nf_s = f"{f3(nf.get('exp_R'))} / {nf.get('status')}" if nf else "спот — фандинга нет"
        print(f"| {v} | {n.get('entry_below_sig_low', 0)} | {sc_s} | {n.get('late_time_exits', 0)} | "
              f"{vv['3000_net']['censored']} | {n.get('entry_below_stop', 0)} | {vv['3000_net']['capped']} | {nf_s} |")
    if fi:
        print("\nФандинг LONG (−qty × mark × ставка в каждый момент начисления внутри позиции; $3 000, после расходов):\n")
        print("| Версия | часть | n | пересечений | фандинг $ | фандинг, сумма R | на сделку R |")
        print("|---|---|---|---|---|---|---|")
        for v, vv in d["versions"].items():
            n = vv["3000_net"]["stats"]
            if not n.get("n"):
                continue
            for part, lab in (("dev", "разработка"), ("holdout", "контроль"), ("all", "весь период")):
                p = n[part]
                per = p["funding_R"] / p["n"] if p["n"] else float("nan")
                print(f"| {v} | {lab} | {p['n']} | {p['funding_crossings']} | {p['funding_usd']:+.2f} | "
                      f"{p['funding_R']:+.2f} | {f3(per)} |")
    print("\nДеньги по капиталам (после расходов, сложный процент):\n")
    print("| Версия | Капитал | n | ожид. $/сделку | средний выигрыш R | средний проигрыш R | комиссии $ | "
          "проскальз. $ | фандинг $ | оборот $ | итог капитала | пропущено (мин. размер) | урезано по номиналу |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v, vv in d["versions"].items():
        for cap in ("1000", "3000", "5000"):
            r = vv[f"{cap}_net"]
            s = r["stats"]
            if not s.get("n"):
                continue
            print(f"| {v} | ${int(cap):,} | {s['n']} | {s['exp_usd']:+.2f} | {s['avg_win_R']:+.2f} | "
                  f"{s['avg_loss_R']:+.2f} | {s['fees']:.0f} | {s['slip']:.0f} | {s['funding']['usd']:+.2f} | "
                  f"{s['turnover']:,.0f} | ${s['end_eq']:,.0f} | {r['skipped_min']} | {r['capped']} |")
    a = d["versions"]["A"]["3000_net"]
    if a["stats"].get("n"):
        print("\nA по кварталам (после расходов, сумма бюджетного R):",
              ", ".join(f"{k} {v['sum_R']:+.1f} ({v['n']})" for k, v in a["stats"]["by_quarter"].items()))
        tr = a["trades"]
        best = sorted(tr, key=lambda t: -t["R"])[:2]
        worst = sorted(tr, key=lambda t: t["R"])[:2]
        print("\nПримеры A (уровень известен до входа):")
        for t in best + worst:
            print(f"- сигнал {ts(t['sig_ts'])} UTC: уровень (минимум прошлого дня) {t['level']:.2f}, сигнальная "
                  f"свеча low {t['sig_low']:.2f} / high {t['sig_high']:.2f}; вход {ts(t['entry_ts'])} по "
                  f"{t['entry']:.2f}, стоп {t['stop']:.2f} (шаг {t['tick']:g}), цель {t['target']:.2f}; выход "
                  f"{t['why']} {ts(t['exit_ts'])} по {t['exit']:.2f} → {t['R']:+.2f}R бюдж. / {t['pR']:+.2f}R цен. "
                  f"(${t['pnl']:+.2f}" + (f", фандинг ${t['funding']:+.2f}" if t.get("n_funding") else "") + ")")


def lvn(d: dict, name: str) -> None:
    c = d["lvn_control"]
    print(f"\n### {name}: контроль LVN ({d['inst']}, данные sha256 {str(d.get('data_sha256'))[:16]}…, seed {d['seed']})\n")
    print(f"E (окно 2 дня, $3 000, после расходов): n {c['real_n']}, ожидание {f3(c['real_mean_R'])}R. Повторов "
          f"{c['done']} из {d['n_requested']}; невалидных {c['invalid_reps']} (дней без допустимого размещения "
          f"{c['invalid_days']}), без сделок {c['empty_reps']}, валидных {c['valid']}; медиана контроля "
          f"{f3(c['ctl_median_R'])}R (5–95%: {ci(c['ctl_q05_q95_R'])}), сделок в контроле медиана "
          f"{c['ctl_median_n'] if c['ctl_median_n'] is not None else '—'}; не хуже настоящего "
          f"{c['k'] if c['k'] is not None else '—'}/{c['valid']}, ранг {c['rank']}")
    w = d["windows"]
    print("Окна LVN (E заново): " + "; ".join(f"{k} дн. n {v['n']}, {f3(v['mean_R'])}R" for k, v in w.items()))
    m = d["mgc_proxy"]
    print("MGC-прокси (бюджетный фильтр ширины стопа на прокси, не стратегия MGC): "
          + "; ".join(f"${int(k):,}: {v['fit']} из {v['n']}" for k, v in m.items())
          + f"; медиана риска контракта на прокси ${next(iter(m.values()))['median_risk']:.0f}")


def main() -> None:
    for path in sys.argv[1:]:
        d = json.load(open(path, encoding="utf-8"))
        name = path.split("/")[-1]
        if "lvn_control" in d:
            lvn(d, name)
        else:
            backtest(d, name)


if __name__ == "__main__":
    main()
