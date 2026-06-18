"""Статус alt-momentum форвард-сбора для TG (/alt_momentum) — с разбивкой по режиму."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "alt_momentum_shadow.jsonl"


def _read():
    if not JOURNAL.exists():
        return []
    out = []
    for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def build_status_text() -> str:
    recs = _read()
    if not recs:
        return ("📈 ALT-MOMENTUM форвард-сбор\nРебалансов пока нет (первый — в ближайший "
                "день UTC). Long топ-4 / short низ-4 по excess vs BTC, холд 24ч, без денег.")
    L = ["📈 ALT-MOMENTUM (4ч-моментум, холд 24ч, market-neutral) — форвард"]
    last = recs[-1]
    L.append(f"─ ПОСЛЕДНИЙ ребаланс {last['date']} · режим: {last.get('regime','?')}"
             f" (BTC.D {last.get('btc_dominance','?')})")
    L.append("   лонг: " + ", ".join(f"{s[:-4]}(+{e:.1f}%)" for s, _p, e in last["longs"]))
    L.append("   шорт: " + ", ".join(f"{s[:-4]}({e:+.1f}%)" for s, _p, e in last["shorts"]))
    done = [r for r in recs if r.get("outcome")]
    if done:
        nets = [r["outcome"]["net_pct"] for r in done]
        wr = 100 * sum(1 for x in nets if x > 0) / len(nets)
        L.append(f"─ ЗАКРЫТО {len(done)} циклов: net Σ {sum(nets):+.1f}% · "
                 f"среднее {sum(nets)/len(nets):+.2f}%/цикл · win {wr:.0f}%")
        # разбивка по режиму (КЛЮЧ — Win: в доминансе моментум переворачивается)
        for tag in ("alt-active(моментум↑)", "dominance(моментум↓)"):
            sub = [r["outcome"]["net_pct"] for r in done if r.get("regime") == tag]
            if sub:
                L.append(f"   {tag}: n={len(sub)} среднее {sum(sub)/len(sub):+.2f}%/цикл")
    else:
        L.append("─ закрытых циклов ещё нет (холд 24ч) — копим")
    L.append("(бэктест Win: +70% при 10bp/300д, НО регим-условен; решение о деньгах — после cross-cycle)")
    return "\n".join(L)
