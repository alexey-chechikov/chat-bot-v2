"""Типичные сценарии суток: три формы пути цены по 9 годам истории.

Оператор 05.10.2026: «не предсказывать, а нарисовать 2–3 наиболее
распространённых по истории развития с описанием».

Путь за 24ч делится на σ пути (как в модели шансов), k-means на 3 кластера.
Замер 05.10 (26 401 путь на монету, шаг 3ч), доли одинаковы в обеих половинах:
  BTC: боковик 66% (конец +0.08σ, внутри ±0.45σ), вниз 18% (−1.34σ, по пути
       −1.74σ), вверх 15% (+1.66σ, по пути +2.0σ);
  ETH: боковик 64%, вниз 18% (−1.41σ), вверх 18% (+1.49σ).
Сценарий масштабируется на сегодняшний σ пути — поэтому в тихом рынке
линии ближе, в бурном дальше.

Какой сценарий будет — заранее не известно. Проверено 05.10 на 2023–2026
(аналоги ищутся только до 10.2023): похожие моменты по RSI(14), MACD,
EMA200, Боллинджеру (20,2), объёму и размаху угадывают сторону суток в
52.4% (BTC) и 50.9% (ETH); Brier хуже, чем у обычных суток. Касание +2% за
сутки аналоги прогнозируют хуже z-модели (0.217 против 0.203 BTC).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "state"
REFIT_DAYS = 7
NAMES = ("вниз", "боковик", "вверх")


@dataclass
class Scenario:
    name: str
    share: float
    path: list          # медианный путь, 24 точки, в единицах σ пути
    end: float          # медиана конца, σ
    max_: float         # медиана максимума по пути, σ
    min_: float         # медиана минимума по пути, σ


def _kmeans(X: np.ndarray, k: int = 3, iters: int = 60) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(X[:, -1])
    cent = np.stack([X[order[int(len(X) * q)]] for q in (0.15, 0.5, 0.85)])
    lab = np.zeros(len(X), dtype=int)
    for _ in range(iters):
        lab = ((X[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1)
        new = np.stack([X[lab == j].mean(0) for j in range(k)])
        if np.allclose(new, cent):
            break
        cent = new
    return lab, cent


def fit(sym: str) -> list[Scenario]:
    from services.grid_model import odds_intraday as oi

    m, d = oi.get_model(sym)
    s = np.asarray(m.profile)
    ds = oi.deseason_sigma(d, s)
    how = d["how"].to_numpy()
    c = d["close"].to_numpy()
    idx = np.array([i for i in range(24 * 30, len(d) - 25, 3) if np.isfinite(ds[i])])
    sp = np.array([ds[i] * float(oi.path_scale(s, how[i], 24)) for i in idx])
    P = np.stack([c[idx + k] / c[idx] - 1 for k in range(1, 25)], axis=1) / sp[:, None]
    lab, cent = _kmeans(P)
    out = []
    for name, j in zip(NAMES, np.argsort(cent[:, -1])):
        mk = lab == j
        med = np.median(P[mk], axis=0)
        out.append(Scenario(name, float(mk.mean()), [round(float(x), 4) for x in med],
                            float(med[-1]), float(np.median(P[mk].max(1))),
                            float(np.median(P[mk].min(1)))))
    return out


def get(sym: str) -> list[Scenario]:
    path = CACHE / f"odds_scenarios_{sym}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - raw["fitted_at"] < REFIT_DAYS * 86400:
            return [Scenario(**x) for x in raw["scenarios"]]
    except (OSError, ValueError, KeyError):
        pass
    sc = fit(sym)
    try:
        path.write_text(json.dumps({"fitted_at": time.time(),
                                    "scenarios": [x.__dict__ for x in sc]},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("odds_scenarios.cache_write_failed")
    return sc


def text(scen: list[Scenario], sigma_path: float) -> list[str]:
    """Блок карточки. sigma_path — σ пути на сутки (доля), из модели шансов."""
    out = ["🗺 ТИПИЧНЫЕ СЦЕНАРИИ СУТОК (9 лет истории, масштаб — сегодняшний размах):"]
    by = {x.name: x for x in scen}
    order = ("боковик", "вниз", "вверх")
    for name in order:
        x = by.get(name)
        if x is None:
            continue
        if name == "боковик":
            amp = max(abs(x.max_), abs(x.min_)) * sigma_path
            out.append(f"  ≈{x.share:.0%} — боковик: к концу суток около "
                       f"{x.end * sigma_path:+.1%}, ход внутри примерно ±{amp:.1%}")
        else:
            far = (x.min_ if name == "вниз" else x.max_) * sigma_path
            out.append(f"  ≈{x.share:.0%} — уход {name}: к концу суток около "
                       f"{x.end * sigma_path:+.1%}, по пути до {far:+.1%}")
    out.append("  Какой будет — заранее не известно: RSI, MACD, EMA200, Боллинджер и "
               "объём угадывают сторону в 51–52% (проверено на 2023–2026).")
    return out
