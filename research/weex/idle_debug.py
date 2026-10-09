"""Откуда в прогоне 28 сут простой 234 ч: состояние сетки в начале и середине самого долгого простоя."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refill_compare as rc  # noqa: E402

from services.weex_grid import engine as eg  # noqa: E402


def snap(g, mid, ts):
    out = [datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M"), f"цена {mid:,.0f}",
           f"halted={g.st['halted']}"]
    for s in ("LONG", "SHORT"):
        st = g.st[s]
        lots = st["lots"]
        lo = min((l["entry"] for l in lots), default=None)
        hi = max((l["entry"] for l in lots), default=None)
        out.append(f"{s}: лотов {len(lots)} [{lo}..{hi}] ref {st['ref']} вход {st['entry'] and st['entry']['price']} "
                   f"блок '{st['blocked']}'")
    return " | ".join(out)


ks = rc.klines(rc.DAYS)
cfg = {**eg.load_config(), "enabled": True, "dry_run": True}
px = rc.Px()
px.mid = float(ks[0][1])
ex = eg.DryExchange(px)
clock = {"t": ks[0][0] / 1000}
import tempfile  # noqa: E402
tmp = Path(tempfile.mkdtemp())
g = eg.Grid(ex, cfg, state_path=tmp / "st.json", journal_path=tmp / "j.jsonl", now_fn=lambda: clock["t"])
g.save = lambda: None
last_n, run, best, best_start, snaps = 0, 0, 0, None, {}
for i, k in enumerate(ks):
    for p in rc.path6(k):
        px.mid = p
        clock["t"] += 10
        g.tick()
    n = sum(g.st[s]["n_entries"] + g.st[s]["n_tps"] for s in ("LONG", "SHORT"))
    if n == last_n:
        run += 1
        if run == 1:
            snaps["start"] = snap(g, float(k[4]), clock["t"])
        if run == 60 * 24:
            snaps["day"] = snap(g, float(k[4]), clock["t"])
        if run > best:
            best, best_start = run, dict(snaps)
    else:
        run = 0
    last_n = n
print(f"самый долгий простой {best / 60:.1f} ч")
for k, v in best_start.items():
    print(k, "→", v)
