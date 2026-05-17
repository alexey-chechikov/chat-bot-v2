# Regime-conditional grid performance — Phase 3.6 (2026-05-17)

**Цель:** определить когда volume-farm grid bot реально работает.
Если в TREND/HIGH vol он минусует — на эти периоды размер уменьшать или паузить.
Если RANGE/LOW — увеличивать.

**Method:** 2y BTC 1m данных, sweet-spot params (levels=120, size=$1000, cap=0.10 BTC). Каждый день классифицируется (regime × vol) и симулируется отдельно. Vol thresholds: LOW < 0.047% < MED < 0.073% < HIGH (daily ATR % of close).

## Avg daily net (USD) по cells

| Regime | LOW vol | MEDIUM | HIGH | all vols |
|---|---|---|---|---|
| RANGE | $+90 (n=204) | $+387 (n=138) | $+1,643 (n=89) | $+506 (n=431) |
| TREND_UP | $+184 (n=24) | $+458 (n=57) | $+1,796 (n=67) | $+1,020 (n=148) |
| TREND_DOWN | $+282 (n=14) | $+469 (n=54) | $+2,273 (n=86) | $+1,459 (n=154) |

## Size multiplier recommendation

Use as bot_brain rule R3.x param: при `regime=X, vol=Y` множитель base size на коэффициент.

| Regime | LOW | MEDIUM | HIGH |
|---|---|---|---|
| RANGE | 0.7 | 1.5 | 1.5 |
| TREND_UP | 1.0 | 1.5 | 1.5 |
| TREND_DOWN | 1.0 | 1.5 | 1.5 |

## Применение

`state/bot_brain_regime_grid_config.json` — машиночитаемая версия. Будущий R3.5_regime_resize правило consult'ит этот файл и предлагает resize action для testbed bot когда detect'ит regime/vol cell с multiplier ≠ 1.0.

## Caveats

- Classification одного дня — coarse. Реальный регайм меняется внутри дня.
- Sample sizes неравномерные: некоторые cells могут быть малыми.
- Sweet-spot params — те же что в sweep. Если базовые params поменяются, matrix нужно пересчитать.
- 0.0 multiplier = pause grid — НЕ паузит сам по себе. Это рекомендация operator decision-support layer.