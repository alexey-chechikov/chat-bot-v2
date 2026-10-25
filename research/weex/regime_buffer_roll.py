"""Полоса SMA100 по скользящим двухлетним окнам (25.10, вопрос оператора «чем плоха прибавка даже 2%»): реальный эффект
или удача периода 2024–26? Прокси regime_buffer_daily (держать лонг по режиму, 0.068% за смену), окна по 730 дней со
стартом каждые 30 дней с 2017 года; для полос 0.5/1/2 % — доля окон, где полоса лучше живого правила (0), медиана и
10/90% разницы в п.п. доходности и в просадке. Окна перекрываются — это распределение, а не независимые испытания."""
from __future__ import annotations

import numpy as np
import pandas as pd

from regime_buffer_daily import BANDS, COST, ROOT, regime  # noqa: E402

WIN, STEP = 730, 30


def curve(close: pd.Series, reg: pd.Series) -> tuple[pd.Series, pd.Series]:
    pos = reg.shift(1)
    flip = (pos.diff().abs() == 1).astype(float)
    return (pos * close.pct_change()).fillna(0.0) - flip * COST, pos.notna()


def main():
    for sym in ("BTCUSDT", "ETHUSDT"):
        d = pd.read_csv(ROOT / "data" / "historical" / f"daily_{sym}.csv")
        close = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["ts_ms"], unit="ms"))
        base_r, ok = curve(close, regime(close, 0.0))
        first = int(np.argmax(ok.to_numpy()))
        starts = range(first, len(close) - WIN, STEP)
        print(f"{sym}: окон {len(starts)} по {WIN} дн. (с {close.index[first].date()})")
        for b in BANDS[1:4]:
            r, _ = curve(close, regime(close, b))
            dp, ddd = [], []
            for s in starts:
                a, z = base_r.iloc[s:s + WIN], r.iloc[s:s + WIN]
                dp.append((z.sum() - a.sum()) * 100)
                ea, ez = a.cumsum(), z.cumsum()
                ddd.append(((ez - ez.cummax()).min() - (ea - ea.cummax()).min()) * 100)
            dp, ddd = np.array(dp), np.array(ddd)
            print(f"  полоса {b:g}%: лучше живого в {(dp > 0).mean():.0%} окон; разница доходности медиана {np.median(dp):+.1f} п.п."
                  f" (10–90% {np.quantile(dp, .1):+.1f}…{np.quantile(dp, .9):+.1f}); просадка глубже в {(ddd < 0).mean():.0%}"
                  f" окон, медиана {np.median(ddd):+.1f} п.п. (худшее {ddd.min():+.1f})")


if __name__ == "__main__":
    main()
