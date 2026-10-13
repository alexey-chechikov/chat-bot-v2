"""Таблицы отчёта из JSON-выводов sweep_backtest.py (--out=…): версии × расходы, капиталы, кварталы, примеры.

    .venv/bin/python3 research/gold/sweep_report_tables.py <paxg.json> <xau.json> [<paxg_s1.json> <xau_s1.json>]
"""
import json
import sys
from datetime import datetime, timezone


def ts(x):
    return datetime.fromtimestamp(x / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    for path in sys.argv[1:]:
        d = json.load(open(path, encoding="utf-8"))
        name = path.split("/")[-1]
        print(f"\n### {name}: строк {d['info']['rows']}, sha256 {d['info']['sha256'][:16]}…, "
              f"{ts(d['info']['first'])} … {ts(d['info']['last'])} UTC, контрольная часть с {ts(d['split_ts'])[:10]}\n")
        print("| Версия | n | WR | Ожид. R до расходов | после | ×2 проскальз. | 95% ДИ (после) | разработка R (n) | "
              "контроль R (n) | PF | макс. просадка | серия убытков | выходы цель/стоп/время | статус |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for v, vv in d["versions"].items():
            g, n, n2 = vv["3000_gross"]["stats"], vv["3000_net"]["stats"], vv["3000_net_2slip"]["stats"]
            if not n.get("n"):
                print(f"| {v} | 0 | | | | | | | | | | | | {vv['status']} |")
                continue
            e = n["exits"]
            print(f"| {v} | {n['n']} | {n['wr']:.0%} | {g['exp_R']:+.3f} | {n['exp_R']:+.3f} | {n2['exp_R']:+.3f} | "
                  f"{n['ci_R'][0]:+.3f}…{n['ci_R'][1]:+.3f} | {n['dev']['exp_R']:+.3f} ({n['dev']['n']}) | "
                  f"{(n['holdout']['exp_R'] if n['holdout']['exp_R'] is not None else float('nan')):+.3f} "
                  f"({n['holdout']['n']}) | {n['pf']:.2f} | {n['max_dd']:.1%} | {n['max_loss_streak']} | "
                  f"{e['цель']}/{e['стоп']}/{e['время']} | {vv['status']} |")
        print("\nДеньги по капиталам (после расходов, сложный процент):\n")
        print("| Версия | Капитал | n | ожид. $/сделку | средний выигрыш R | средний проигрыш R | комиссии $ | "
              "проскальз. $ | оборот $ | итог капитала | пропущено (мин. размер) | урезано по номиналу |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for v, vv in d["versions"].items():
            for cap in ("1000", "3000", "5000"):
                r = vv[f"{cap}_net"]
                s = r["stats"]
                if not s.get("n"):
                    continue
                print(f"| {v} | ${int(cap):,} | {s['n']} | {s['exp_usd']:+.2f} | {s['avg_win_R']:+.2f} | "
                      f"{s['avg_loss_R']:+.2f} | {s['fees']:.0f} | {s['slip']:.0f} | {s['turnover']:,.0f} | "
                      f"${s['end_eq']:,.0f} | {r['skipped_min']} | {r['capped']} |")
        a = d["versions"]["A"]["3000_net"]
        if a["stats"].get("n"):
            print("\nA по кварталам (после расходов, сумма R):",
                  ", ".join(f"{k} {v['sum_R']:+.1f} ({v['n']})" for k, v in a["stats"]["by_quarter"].items()))
            tr = a["trades"]
            best = sorted(tr, key=lambda t: -t["R"])[:2]
            worst = sorted(tr, key=lambda t: t["R"])[:2]
            print("\nПримеры A (уровень известен до входа):")
            for t in best + worst:
                print(f"- сигнал {ts(t['sig_ts'])} UTC: уровень (минимум прошлого дня) {t['level']:.2f}, сигнальная "
                      f"свеча low {t['sig_low']:.2f} / high {t['sig_high']:.2f}; вход {ts(t['entry_ts'])} по "
                      f"{t['entry']:.2f}, стоп {t['stop']:.2f}, цель {t['target']:.2f}; выход {t['why']} "
                      f"{ts(t['exit_ts'])} по {t['exit']:.2f} → {t['R']:+.2f}R (${t['pnl']:+.2f})")


if __name__ == "__main__":
    main()
