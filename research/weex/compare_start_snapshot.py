"""Старт недельного сравнения «4 бота против 1» (оператор 18.10): снимок конфигов, лотов, реализованного и цены.

Снимок — учёт ботов, в публичный репо НЕ идёт: пишется в state/grid_compare_start_<дата>.json, печатается его SHA256.
    .venv/bin/python3 research/weex/compare_start_snapshot.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.weex_grid import engine as eg  # noqa: E402
from services.weex_grid.loop import run_files  # noqa: E402

NAMES = ("BTC", "B34", "B49", "B89", "ETH")


def main() -> int:
    from services.weex_api.client import WeexClient
    c = WeexClient()
    now = datetime.now(timezone.utc)
    mids = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        bid, ask = c.book(sym)
        mids[sym] = (bid + ask) / 2
    grids = {}
    for n in NAMES:
        cfg_path, _, _ = eg.grid_files(n)
        st_path, jr_path = run_files(n, False)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
        first_live = None
        if jr_path.exists():
            for line in jr_path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("dry") is False:
                    first_live = r.get("ts")
                    break
        mid = mids[cfg["symbol"]]
        sides = {}
        for sd, d in (("LONG", 1), ("SHORT", -1)):            # 7ecda96 §3: все стороны и обязательства
            side = st.get(sd) or {}
            lots = [{"qty": l["qty"], "entry": l["entry"], "tp": l.get("tp"), "t": l.get("t"),
                     "tp_order_id": (l.get("tp_order") or {}).get("id")} for l in side.get("lots") or []]
            e = side.get("entry") or {}
            sides[sd] = {"lots": lots,
                         "lots_mtm_usd": sum(d * float(l["qty"]) * (mid - float(l["entry"])) for l in lots),
                         "realized_usd": side.get("realized"), "fees_usd": side.get("fees"),
                         "turnover_usd": side.get("turnover"),
                         "entry_order": {"id": e.get("id"), "price": e.get("price"), "qty": e.get("qty"),
                                         "filled": e.get("filled")} if e else None,
                         "pending": side.get("pending"), "strays": len(side.get("strays") or []),
                         "transfers": side.get("transfers") or [], "released": side.get("released")}
        grids[n] = {"config": cfg, "config_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
                    "config_mtime_utc": datetime.fromtimestamp(cfg_path.stat().st_mtime, timezone.utc).isoformat(),
                    "state_sha256": hashlib.sha256(st_path.read_bytes()).hexdigest() if st_path.exists() else None,
                    "first_live_journal_ts": first_live, "sides": sides,
                    "lots": sides["LONG"]["lots"], "lots_mtm_usd": sides["LONG"]["lots_mtm_usd"],
                    "realized_usd": sides["LONG"]["realized_usd"]}
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    snap = {"created_utc": now.isoformat(timespec="seconds"), "git_head": head, "mid": mids,
            "rules": {"mark": "WEEX bookTicker mid на момент снимка", "fees": "фактические из сделок (maker 0.016%)",
                      "funding": "фактические начисления по символу; делёж по лотам×времени — отчётная аллокация",
                      "old_btc_lots": "лоты BTC по 0.0036 оцениваются по mid на старте, их прибыль связке не засчитывается",
                      "versions": "смена параметров посреди недели = новая версия отрезка"},
            "grids": grids}
    # 7ecda96 §3: каждый снимок — новый файл с фактическим временем, прежние не перезаписываются; ссылка на предыдущие
    prev = sorted((ROOT / "state").glob("grid_compare_start_*.json"))
    snap["previous_snapshots"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in prev}
    snap["role"] = ("дополнение со старта недели: последняя смена параметров (B34/B49 30 ордеров, B89 20) — до него; "
                    "всё раньше — версии 0/1, отдельно") if prev else "первый снимок"
    out = ROOT / "state" / f"grid_compare_start_{now:%Y%m%dT%H%M%SZ}.json"
    if out.exists():
        sys.exit(f"{out.name} уже есть — не перезаписываю")
    blob = json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    with open(out, "xb") as f:                                 # x — ошибка, если файл появился между проверкой и записью
        f.write(blob)
    print(out.name, hashlib.sha256(blob).hexdigest(), "head", head[:7])
    for n, g in grids.items():
        print(f"  {n}: лотов {len(g['lots'])}, мешок {g['lots_mtm_usd']:+.2f}$, закрыто {g['realized_usd']}, "
              f"первая живая запись {g['first_live_journal_ts']}, конфиг {g['config_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
