"""Помесячно: открытие/закрытие/минимум/максимум и средний дневной размах по минуткам из data/."""
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402

ts, o, h, l, c = fg.load(sys.argv[1])
months = OrderedDict()
days = {}
for t, hi, lo, cl in zip(ts, h, l, c):
    dt = datetime.fromtimestamp(int(t), timezone.utc)
    m = dt.strftime("%Y-%m")
    rec = months.setdefault(m, [cl, cl, hi, lo])
    rec[1] = cl
    rec[2] = max(rec[2], hi)
    rec[3] = min(rec[3], lo)
    d = dt.strftime("%Y-%m-%d")
    dd = days.setdefault(d, [hi, lo])
    dd[0], dd[1] = max(dd[0], hi), min(dd[1], lo)
rng = {}
for d, (hi, lo) in days.items():
    rng.setdefault(d[:7], []).append((hi / lo - 1) * 100)
print(f"{sys.argv[1]}: {c[0]:,.2f} → {c[-1]:,.2f} ({(c[-1] / c[0] - 1) * 100:+.1f}%), мин {l.min():,.2f} макс {h.max():,.2f}")
for m, (op, cl, hi, lo) in months.items():
    r = rng[m]
    print(f"{m}: {op:,.2f} → {cl:,.2f} ({(cl / op - 1) * 100:+.1f}%) мин {lo:,.2f} макс {hi:,.2f} "
          f"дневной размах {sum(r) / len(r):.2f}%")
