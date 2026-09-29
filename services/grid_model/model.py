"""Модель грид-бота: что даст конфигурация и чем за это платит инвентарь.

    итог = оборот × маржа(цель) × выживание

Каждый множитель замерен отдельно, ни один не подогнан под итог. Модель
воспроизводит все 12 замеренных ячеек с ошибкой ≤3% (см. тесты).

ОТКУДА КОЭФФИЦИЕНТЫ — прогоны оператора в GinArea, сентябрь 2026,
окно 25.09.2025–01.09.2026 (BTC 115k → 58.8k дно 30.06 → 84k).

1. МАРЖА С ОБОРОТА — зависит ТОЛЬКО от цели, не от шага.
   USDT: 0.502 × цель − 0.053 %.
     Точки: 0.29 → 0.0927% (замер 10.08.2026), 1.49 → 0.6985% (ETH, 15
     прогонов, разброс по шагам 0.1…0.8 всего 1.0%).
     Живьём: BTC-шорт цель 1.19 → 0.5564% против модели 0.5443% (102%);
     ETH цель 0.85 → 0.3487…0.3916% против 0.3737% (93…105%).
   Инверсные: (6.1612e-8 × цель − 0.3998e-8) BTC на 1 USD оборота.
     Фит по 7 прогонам, цели 0.7…2.5, ошибка ≤0.9%; вне выборки цели 2.0
     и 2.5 дали 0.35% и 0.56%. Живьём LONG COIN цель 0.74 → 116%.

2. ОБОРОТ ЗА ГОД = C × нотионал_ордера / (шаг% × цель%), где C — годовой
   «путь» инструмента. ETH C=4340 (5 шагов, разброс 3%), BTC C=2030
   (7 целей, разброс 1%). Другой год даст другое C: это мера волатильности.
   С включённым выходом по средней оборот падает — коэффициент TURN_ON.

3. ВЫЖИВАНИЕ = итог / реализованное: сколько доходит до низа после мешка.
   Замерено на ДВУХ РАЗНЫХ семьях, и ведёт себя в них по-разному:
     ETH Auto — зависит от ШАГА (цель везде 1.49);
     BTC односторонний — зависит от ЦЕЛИ (шаг везде 0.8 или 0.4).
   Поэтому модель калибрована посемейно и предупреждает вне семьи.

4. ВЫХОД ПО СРЕДНЕЙ поднимает выживание до 0.73…0.78 ТОЛЬКО на двусторонних
   (Auto). На односторонних он проиграл 5 падающих окон из 5 (BTC-лонг год,
   индикаторная сетка 08.12–08.03 и 01.04–01.07), поэтому бонуса не даёт.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WINDOW = "25.09.2025–01.09.2026"

USDT_SLOPE, USDT_FEE = 0.502, 0.053
INV_SLOPE, INV_FEE = 6.1612e-8, 0.3998e-8

PATH_C = {"ETH": 4450.0, "BTC": 2030.0}

# ── семья «ETH Auto» ─────────────────────────────────────────────────────
# ОБОРОТ на единицу экспозиции = оборот × шаг / нотионал. Замерено развёрткой
# по цели (шаг 0.1, ордер 0.01, 800 ордеров, окно →17.09.2026). Контрольные
# точки на шаге 0.4 с ордером 0.04 ложатся на ту же кривую (1441 против
# интерполированных 1503 и 3013 против 3045) — ШАГ НЕ ВЛИЯЕТ, подтверждено
# прямым замером при равной экспозиции (нотионал/шаг = 245 у обоих).
ETH_TURN_UNIT_ON = {0.6: 1933.0, 0.8: 1617.0, 1.1: 1568.0, 1.3: 1467.0,
                    1.4: 1503.0, 1.49: 1524.0, 1.69: 1381.0, 1.89: 1384.0,
                    2.0: 1366.0, 2.2: 1172.0, 2.5: 1255.0}
ETH_TURN_UNIT_OFF = {1.0: 3630.0, 1.3: 3252.0, 1.4: 3167.0, 1.49: 3045.0}
# Выживание с ВЫКЛЮЧЕННЫМ тумблером зависит от ШАГА: чем теснее сетка, тем
# глубже несбрасываемый мешок.
ETH_SURV_OFF = {0.1: 0.043, 0.2: 0.060, 0.3: 0.175, 0.4: 0.248, 0.8: 0.359}
# Выживание с ВКЛЮЧЁННЫМ тумблером от шага НЕ зависит (0.773 на шаге 0.1
# против 0.781 на 0.4), зато растёт с ЦЕЛЬЮ.
ETH_SURV_ON = {0.6: 0.696, 0.8: 0.713, 1.1: 0.786, 1.3: 0.802, 1.4: 0.819,
               1.49: 0.828, 1.69: 0.944, 1.89: 0.944, 2.0: 0.930,
               2.2: 0.840, 2.5: 0.868}
# Провалы развёртки — соседние ячейки по обе стороны, ворота №4. Оба раза
# причина одна: блок не разгружается, мешок втрое глубже соседей.
#   цель 1.0 — два прогона 621 и 636$ против 1026$ на 0.8 и 1529$ на 1.1,
#              мешок −1197$ против −420$, позиция 3.48 против 2.34 ETH.
#   цель 2.2 — 2516$ против 3010$ на 2.0 и 3198$ на 2.5, мешок −479$
#              против −227$, позиция 2.89 против 2.39 ETH.
ETH_TARGET_ISLANDS = (1.0, 2.2)
# Чистая зона: 1.69…2.0 — монотонный рост 2565→3010$, выживание 93-94%,
# мешок −153…−227$ (минимум по всей развёртке). Выше 2.0 поверхность рвётся.
ETH_TARGET_CLEAN = (1.69, 2.0)
AUTO_TARGET_RANGE = (0.6, 2.5)   # где мерили Auto по цели
# ТОЧНОСТЬ. Внутри одного окна и одной партии модель держит ~15%: шум
# движка 3.7%, разброс оборота по шагу до 11%.
TOLERANCE = 0.15
# Между окнами хуже. При одной цели 1.49 выживание вышло 0.828 в развёртке
# (800 ордеров, окно →17.09) против 0.729…0.779 в партии на 400 ордерах
# (окно →01.09) — расхождение 14%. Модель калибрована по развёртке, потому
# что там менялась ровно одна ось. Ранжировать разницы меньше 22% между
# конфигурациями из разных окон нельзя.
CROSS_WINDOW_TOLERANCE = 0.22

# ── семья «BTC односторонний ЛОНГ, инверсный»: выживание от ЦЕЛИ ──
BTC_SURV_OFF = {0.7: 0.239, 0.9: 0.274, 1.4: 0.297, 1.7: 0.303, 2.5: 0.325}

# ── семья «BTC-USDT ШОРТ» ────────────────────────────────────────────────
# Окно 17.09.2025→17.09.2026 (BTC ~115k → 84k), база 0.4/0.06, 9 прогонов.
# Шорт в ПАДАЮЩЕМ году: мешок работает на него, поэтому выживание втрое выше,
# чем у одностороннего лонга (0.65 против 0.24-0.33), и почти не зависит ни от
# шага, ни от цели — разброс всего 63.2…66.7% на шести прогонах.
# ⚠️ Это свойство ПАДАЮЩЕГО года, а не шорта вообще. Дневной гейт SMA100
# сейчас красный (+22.4% над средней); в ралли тот же шорт дал −$3 180
# против −$143 с гейтом. Модель считает доход, а не разрешение торговать.
BTC_SHORT_SURV = {False: 0.652, True: 0.570}   # ключ — выход по средней
# Выход по средней проиграл 3 пары из 3: −43%, −41%, −54%. Всего по односторонним
# теперь 8 опровержений из 8.
BTC_SHORT_TURN_BY_STEP = {0.1: 1055.0, 0.2: 1260.0, 0.8: 1469.0}   # при цели 1.39
BTC_SHORT_TURN_BY_TARGET = {1.3: 1.061, 1.39: 1.000, 1.5: 0.963,
                            1.7: 0.840, 1.9: 0.734}
# Кривая цели шорта ПЛОСКАЯ на всех трёх шагах — поднимать цель бессмысленно:
#   шаг 0.8 (в пересчёте на размер 0.001): 1.39 → 627$, 1.7 → 646$, 1.9 → 642$
#   шаг 0.2: 1.3 → 2075$, 1.39 → 2103$
#   шаг 0.1: 1.39 → 3709$, 1.5 → 3672$, 1.7 → 3791$
# Рост маржи ровно компенсируется падением оборота. В отличие от ETH Auto,
# где итог рос с 865$ при цели 0.6 до 3010$ при 2.0.
BTC_SHORT_TARGET_FLAT = (1.3, 1.9)
BTC_SHORT_TURN_ON_FACTOR = 0.758   # падение оборота от выхода по средней

ADVERSE = {"auto": 40.0, "one_sided": 64.0}   # ход против за то же окно, %

# СМЕЩЕНИЕ ГРАНИЦ на ETH Auto — замерено 26.09.2026, последняя нетронутая ось.
# Цель 2.0, шаг 0.1, 800×0.01, ВКЛ, конец 17.09:
#   база 0.75 / дин 0.10 → 2992$, позиция 2.39 ETH, мешок −227$, выживание 92.9%
#   база 0.40 / дин 0.06 → 2946$, позиция 3.17 ETH, мешок −537$, выживание 84.6%
# Деньги те же (−1.5%, внутри шума 0.6-3.7%), но инвентарь на 33% больше
# и мешок вдвое глубже. Широкое смещение лучше. Модель смещение не считает —
# это зафиксировано как настройка по умолчанию.
ETH_BORDER_OFFSET_BEST = (0.75, 0.10)

# ФАНДИНГ — структурная выплата, которой НЕТ ни в одном бэктесте GinArea.
# Замер по binance_funding_*.parquet, 2190 выплат 12.05.2024–11.05.2026:
#   BTC: 0.00484% за 8ч, положительный 82% времени → шорт +5.30%/год нотионала
#   ETH: 0.00504% за 8ч, 81% времени              → шорт +5.52%/год
# За последний год ставки ниже: BTC +3.64%, ETH +3.26%. Берём последний год
# как консервативную оценку. Шорт получает, лонг платит ровно столько же.
FUNDING_YEAR_PCT = {"BTC": 3.64, "ETH": 3.26, "XRP": 2.28}


def funding_year(coin: str, notional: float, short: bool) -> float:
    """Фандинг за год в долларах. Шорт получает, лонг платит."""
    rate = FUNDING_YEAR_PCT.get(coin.upper())
    if rate is None:
        return 0.0
    return (1.0 if short else -1.0) * notional * rate / 100.0


def _interp(table: dict[float, float], x: float) -> float:
    pts = sorted(table.items())
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def margin_pct(target_pct: float, inverse: bool = False,
               price: float = 0.0) -> float:
    """Маржа с оборота, %. Для инверсного контракта нужна цена монеты."""
    if target_pct <= 0:
        raise ValueError("цель должна быть > 0")
    if inverse:
        if price <= 0:
            raise ValueError("для инверсного контракта нужна цена")
        return (INV_SLOPE * target_pct - INV_FEE) * price * 100.0
    return USDT_SLOPE * target_pct - USDT_FEE


def turnover_year(coin: str, notional_per_order: float, step_pct: float,
                  target_pct: float, obap: bool = False,
                  auto: bool = True, short: bool = False) -> float:
    """Оборот за год = (оборот на единицу экспозиции) × нотионал / шаг.

    Три откалиброванных семьи: ETH Auto (развёртка по цели), BTC-USDT шорт
    (развёртка по шагу и цели) и BTC инверсный лонг, где оборот × цель
    постоянен (C с разбросом 1% на 7 целях) — там работает формула C/цель.
    """
    if step_pct <= 0 or target_pct <= 0:
        raise ValueError("шаг и цель должны быть > 0")
    if coin.upper() == "ETH" and auto:
        table = ETH_TURN_UNIT_ON if obap else ETH_TURN_UNIT_OFF
        return _interp(table, target_pct) * notional_per_order / step_pct
    if coin.upper() == "BTC" and short:
        unit = (_interp(BTC_SHORT_TURN_BY_STEP, step_pct)
                * _interp(BTC_SHORT_TURN_BY_TARGET, target_pct))
        if obap:
            unit *= BTC_SHORT_TURN_ON_FACTOR
        return unit * notional_per_order / step_pct
    c = PATH_C.get(coin.upper())
    if c is None:
        raise ValueError(f"нет замеренного C для {coin}; есть {sorted(PATH_C)}")
    return c * notional_per_order / (step_pct * target_pct)


def survival(obap: bool, step_pct: float, target_pct: float,
             auto: bool, short: bool = False) -> float:
    """Доля реализованного, доходящая до итога."""
    if auto:
        return (_interp(ETH_SURV_ON, target_pct) if obap
                else _interp(ETH_SURV_OFF, step_pct))
    if short:
        return BTC_SHORT_SURV[bool(obap)]
    return _interp(BTC_SURV_OFF, target_pct)


def max_inventory(notional_per_order: float, step_pct: float, max_orders: int,
                  auto: bool, border_pct: float | None = None) -> float:
    """border_pct — расстояние до жёсткой границы в %, если она задана.

    Граница режет набор раньше, чем ход рынка и чем число ордеров: выше неё
    бот новых ордеров не ставит (проверено на BTC-шорте, верх 86,500 не
    двигался с 21.09 ни разу).
    """
    adverse = ADVERSE["auto" if auto else "one_sided"]
    if border_pct is not None and border_pct > 0:
        adverse = min(adverse, border_pct)
    return min(notional_per_order * adverse / step_pct,
               notional_per_order * max_orders)


@dataclass
class Plan:
    coin: str
    step_pct: float
    target_pct: float
    notional_per_order: float
    max_orders: int
    auto: bool
    obap: bool
    deposit: float
    price: float
    inverse: bool = False
    border_pct: float | None = None
    short: bool = False
    step_multiplier: float = 1.0
    margin: float = field(init=False)
    turnover: float = field(init=False)
    realized: float = field(init=False)
    surv: float = field(init=False)
    net: float = field(init=False)
    inventory: float = field(init=False)
    warnings: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if abs(self.step_multiplier - 1.0) > 1e-9:
            raise ValueError(
                f"множитель шага сетки {self.step_multiplier}: опровергнут "
                f"замером 26.09.2026. На ETH Auto 1.05 срезал оборот в 4.0-7.7 "
                f"раза (43.5k против 334.7k при цели 2.0) и увёл итог в минус: "
                f"−76$ против +3010$. Модель такое не считает.")
        self.margin = margin_pct(self.target_pct, self.inverse, self.price)
        self.turnover = turnover_year(self.coin, self.notional_per_order,
                                      self.step_pct, self.target_pct,
                                      self.obap, self.auto, self.short)
        self.realized = self.turnover * self.margin / 100.0
        self.surv = survival(self.obap, self.step_pct, self.target_pct,
                             self.auto, self.short)
        self.net = self.realized * self.surv
        self.inventory = max_inventory(self.notional_per_order, self.step_pct,
                                       self.max_orders, self.auto,
                                       self.border_pct)
        if self.border_pct:
            self.warnings.append(
                f"инвентарь ограничен жёсткой границей в {self.border_pct:.1f}% "
                f"от цены — снимешь границу, вырастет в "
                f"{ADVERSE['auto' if self.auto else 'one_sided'] / self.border_pct:.1f}×")
            self.warnings.append(
                "ДОХОД ЗАВЫШЕН: все прогоны семьи сделаны БЕЗ границ, а она "
                "режет и набор, и оборот. Связка «граница → оборот» не мерена, "
                "поэтому доход на единицу риска у этого бота читать нельзя")
        if self.obap and not self.auto:
            self.warnings.append(
                "выход по средней на ОДНОСТОРОННЕМ боте: проиграл 8 замеров "
                "из 8 (5 падающих окон + 3 пары на BTC-шорте: −43%, −41%, −54%)")
        if self.short:
            self.warnings.append(
                "выживание 0.65 замерено в ПАДАЮЩЕМ году (BTC 115k→84k). "
                "Гейт SMA100 сейчас красный — модель считает доход, "
                "а не разрешение шортить")
        if self.leverage > 3:
            self.warnings.append(
                f"инвентарь {self.leverage:.1f}× депозита — выше безопасного 2-2.5×")
        if self.auto and not 0.1 <= self.step_pct <= 0.8:
            self.warnings.append(
                f"шаг {self.step_pct} вне замеренного диапазона 0.1…0.8")
        if not self.auto and not 0.7 <= self.target_pct <= 2.5:
            self.warnings.append(
                f"цель {self.target_pct} вне замеренного диапазона 0.7…2.5")
        if self.auto and not (AUTO_TARGET_RANGE[0] <= self.target_pct
                              <= AUTO_TARGET_RANGE[1]):
            self.warnings.append(
                f"цель {self.target_pct} вне замеренной развёртки "
                f"{AUTO_TARGET_RANGE[0]}…{AUTO_TARGET_RANGE[1]} — экстраполяция")
        for isl in ETH_TARGET_ISLANDS:
            if self.auto and self.obap and abs(self.target_pct - isl) < 0.06:
                self.warnings.append(
                    f"цель ≈{isl}: провал развёртки — блок не разгружается, "
                    f"мешок втрое глубже соседних ячеек. Не ставить.")
        if (self.auto and self.obap
                and self.target_pct > ETH_TARGET_CLEAN[1] + 1e-9):
            self.warnings.append(
                f"выше цели {ETH_TARGET_CLEAN[1]} поверхность рвётся "
                f"(провал на 2.2) и мешок растёт вдвое — чистая зона "
                f"{ETH_TARGET_CLEAN[0]}…{ETH_TARGET_CLEAN[1]}")

    @property
    def leverage(self) -> float:
        return self.inventory / self.deposit if self.deposit > 0 else 0.0

    @property
    def return_pct(self) -> float:
        return self.net / self.deposit * 100.0 if self.deposit > 0 else 0.0

    def death_price(self) -> float:
        """Цена, на которой мешок съедает депозит (линейно от средней входа)."""
        if self.inventory <= 0:
            return 0.0
        qty = self.inventory / self.price
        move = self.deposit / qty
        return self.price + move if self.auto else self.price - move


def plan(coin: str, step_pct: float, target_pct: float, order_size: float,
         price: float, max_orders: int = 400, auto: bool = True,
         obap: bool = True, deposit: float = 2530.0, inverse: bool = False,
         border_pct: float | None = None, short: bool = False,
         step_multiplier: float = 1.0) -> Plan:
    """order_size — в монете для USDT-контрактов, в USD для инверсных."""
    notional = order_size if inverse else order_size * price
    return Plan(coin=coin, step_pct=step_pct, target_pct=target_pct,
                notional_per_order=notional, max_orders=max_orders, auto=auto,
                obap=obap, deposit=deposit, price=price, inverse=inverse,
                border_pct=border_pct, short=short,
                step_multiplier=step_multiplier)


def fit_to_deposit(coin: str, step_pct: float, target_pct: float, price: float,
                   deposit: float, max_leverage: float = 2.5,
                   max_orders: int = 400, auto: bool = True, obap: bool = True,
                   inverse: bool = False) -> Plan:
    """Подобрать размер ордера под заданное плечо по худшему инвентарю."""
    adverse = ADVERSE["auto" if auto else "one_sided"]
    notional = deposit * max_leverage / min(adverse / step_pct,
                                            float(max_orders))
    size = notional if inverse else notional / price
    return plan(coin, step_pct, target_pct, size, price, max_orders, auto,
                obap, deposit, inverse)


def card(p: Plan) -> str:
    side = "Auto" if p.auto else "односторонний"
    cur = "BTC" if p.inverse else "$"
    unit = (lambda v: f"{v:,.5f} BTC") if p.inverse else (lambda v: f"${v:,.0f}")
    lines = [
        f"📐 ГРИД-МОДЕЛЬ — {p.coin.upper()} {side}",
        f"шаг {p.step_pct} · цель {p.target_pct} · ордер ${p.notional_per_order:,.0f}"
        f" × {p.max_orders} · выход по средней {'ВКЛ' if p.obap else 'ВЫКЛ'}",
        "",
        f"оборот за год     ${p.turnover:>12,.0f}",
        f"× маржа {p.margin:6.3f}%  {unit(p.realized):>16}  реализовано",
        f"× выживание {p.surv:4.2f}  {unit(p.net):>16}  ИТОГ",
        "",
        f"инвентарь худший  ${p.inventory:>12,.0f} = {p.leverage:.1f}× депозита",
        f"депозит           ${p.deposit:>12,.0f}",
        f"доходность               {p.return_pct:>7.0f}% годовых" if not p.inverse
        else f"итог в {cur}",
    ]
    for w in p.warnings:
        lines.append(f"⚠️ {w}")
    lines.append(f"\nкоэффициенты замерены на окне {WINDOW}")
    return "\n".join(lines)
