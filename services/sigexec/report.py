"""Отчёт исполнителя по журналу: каждая сделка — цена сигнала против исполнения (б.п.), комиссии, задержка после
закрытия 4ч, итог в $ против итога движка (res × база). Это «живое против бэктеста» (ворота 5) по каждой сделке.

  python -m services.sigexec.report state/sigexec_<биржа>_journal.jsonl [--since 2026-11-12]"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def bps(side: int, px: float | None, ref: float | None, is_exit: bool) -> float | None:
    if not px or not ref:
        return None
    s = -side if is_exit else side
    return s * (px / ref - 1) * 10000            # плюс — хуже сигнала


def summary(path: Path, since: float = 0.0) -> str:
    R = [r for r in rows(path) if r.get("ts", 0) >= since]
    tr = [r for r in R if r["kind"] == "сделка" and r.get("qty")]
    opened = {(r["slot"], r["entry_t"]): r for r in R if r["kind"] == "вход исполнен"}
    missed = [r for r in R if r["kind"] == "сигнал пропущен"]
    errs = [r for r in R if r["kind"] in ("ошибка", "закрыто извне", "заявка не встала")]
    L = [f"📒 Исполнитель: сделок {len(tr)}, пропущено сигналов {len(missed)}, замечаний {len(errs)}"]
    tot = eng = fee = 0.0
    for r in tr:
        si = bps(r["side"], r["avg_in"], r["sig_in"], False)
        so = bps(r["side"], r["avg_out"], r.get("sig_out"), True)
        o = opened.get((r["slot"], r["entry_t"]), {})
        tot += r["pnl_usd"]
        fee += r["fee"]
        eng += r["engine_usd"] or 0.0
        when = datetime.fromtimestamp(r["entry_t"], timezone.utc).strftime("%d.%m %H:%M")
        L.append(f"  {r['slot']} {r['tag']} {when}: {r['pnl_usd']:+.2f}$ (движок {r['engine_usd']:+.2f}$)" if r["engine_usd"] is not None
                 else f"  {r['slot']} {r['tag']} {when}: {r['pnl_usd']:+.2f}$")
        L[-1] += (f", вход {si:+.1f} б.п." if si is not None else "") + (f", выход {so:+.1f} б.п." if so is not None else "") + \
            (f", вход через {o['delay_s']:.0f} с" if o.get("delay_s") is not None else "") + f", комиссии ${r['fee']:.2f}" + \
            (" (комиссия не дочитана)" if r.get("fee_incomplete") else "")
    if tr:
        L.append(f"Итого {tot:+.2f}$ против движка {eng:+.2f}$ (разница {tot - eng:+.2f}$), комиссии ${fee:.2f}")
    for r in missed:
        L.append(f"  пропущен {r['slot']} {datetime.fromtimestamp(r['entry_t'], timezone.utc):%d.%m %H:%M}: {r['why']}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    ap.add_argument("--since", default="")
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp() if a.since else 0.0
    print(summary(Path(a.journal), since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
