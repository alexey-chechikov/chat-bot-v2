"""Текст статуса MA-cross для TG (/ma_cross): текущий уклон по символам + cross-to-cross PnL."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "ma_cross_shadow.jsonl"


def _read() -> list[dict]:
    if not JOURNAL.exists():
        return []
    out = []
    for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def _pf(xs: list[float]) -> float:
    loss = abs(sum(x for x in xs if x <= 0))
    return (sum(x for x in xs if x > 0) / loss) if loss else float("inf")


def build_status_text() -> str:
    recs = _read()
    if not recs:
        return ("📐 MA-CROSS H5 — форвард-сбор\nСигналов пока нет (кросс ~1.7/мес "
                "на символ). Появятся на первом переходе EMA14×77 4ч — придут сюда сами.")
    L = ["📐 MA-CROSS H5 — форвард-сбор (EMA14/77 4ч)"]
    # текущий уклон по символу = последний сигнал
    by_sym: dict[str, dict] = {}
    for r in recs:
        by_sym[r["symbol"]] = r
    L.append("─ ТЕКУЩИЙ directional-СИГНАЛ (НЕ уклон книги — gate=TEMA):")
    for sym, r in by_sym.items():
        s = sym.replace("USDT", "")
        if r["passed_h5"]:
            lean = f"{r['dir']} (H5✅)"
        else:
            lean = f"НЕЙТРАЛ ({r['dir']}-кросс не прошёл)"
        # EW только на BTC (на альтах не переносится — Win)
        ew = (("имп" if r.get("ew_impulse") else "корр") if sym == "BTCUSDT" else "—(BTC-only)")
        L.append(f"   {s}: {lean} · MA100:{r['ma100_lean']} · EW:{ew}")
    # cross-to-cross итоги
    passed = [r["outcome_cross"] for r in recs if r.get("passed_h5") and r.get("outcome_cross") is not None]
    allx = [r["outcome_cross"] for r in recs if r.get("outcome_cross") is not None]
    L.append("─ НАКОПЛЕНО (cross-to-cross):")
    if passed:
        wr = 100 * sum(1 for x in passed if x > 0) / len(passed)
        L.append(f"   H5: n={len(passed)} net {sum(passed):+.1f}пп win {wr:.0f}% PF {_pf(passed):.2f}")
    else:
        L.append("   H5: закрытых пока нет (нога ~10 дней)")
    L.append(f"   (бенчмарк бэктеста: +117пп / PF 2.5; n<20 — рано судить)")
    L.append(f"всего сигналов в журнале: {len(recs)} · решение о встройке ~26.06")
    return "\n".join(L)
