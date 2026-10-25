"""Strategy 432 BTC 4h: риск одной сделки и серий (2017–2026) — для размера живого теста."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
from validate_432 import s432  # noqa: E402

df = R.bars(sys.argv[1])["4h"]
tr = R.evaluate(df, s432(tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))), R.funding("BTCUSDT"))
net = tr["net"].to_numpy()
worst = np.sort(net)[:5]
streak = cur = 0
for x in net:
    cur = cur + 1 if x < 0 else 0
    streak = max(streak, cur)
eq = np.cumsum(net)
dd = (eq - np.maximum.accumulate(eq)).min()
yrs = (tr["t"].iloc[-1] - tr["t"].iloc[0]).days / 365.25
print(f"сделок {len(net)} за {yrs:.1f} г ({len(net) / yrs:.1f}/год), средняя длительность {tr['bars'].mean():.1f} бара 4h, "
      f"доля времени в рынке {tr['bars'].sum() / len(df):.1%}")
print(f"худшие сделки: {', '.join(f'{100 * x:+.1f}%' for x in worst)}; серия убытков подряд до {streak}; "
      f"худшая просадка суммы {100 * dd:+.1f}% номинала")
for usd in (500, 1000, 2000):
    print(f"номинал ${usd}: в среднем ${usd * net.mean():+.0f}/сделку, ${usd * net.mean() * len(net) / yrs:+.0f}/год, "
          f"худшая сделка ${usd * worst[0]:+.0f}, худшая просадка ${usd * dd:+.0f}")
