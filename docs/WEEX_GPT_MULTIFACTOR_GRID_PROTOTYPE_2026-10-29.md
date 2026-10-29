# Офлайн-прототип сетки с запуском и завершением по нескольким факторам

Это исполняемый исследовательский прототип. Статус результата: `RETROSPECTIVE_HOURLY_ENGINEERING_DEMO_ONLY`.
Параметры условные, не настройки живого бота; суммы ниже — результаты моделирования в USDT, не данные счёта.

В решения о запуске, прекращении новых входов и завершении цикла входят OI, funding, поток покупок/продаж,
стакан, ликвидации, L/S, WI2, цена/объём и их связи. SMA — самостоятельный вариант сравнения.
Получились 93 признака, а не 93 доказанных сигналов. При отсутствии исходного ряда признак остаётся неизвестным.

## Запуск

Python 3.10.12; проверенные версии зависимостей перечислены в requirements.txt.
Из каталога прототипа:

```sh
python -m pytest --noconftest -c pytest.ini test_features.py test_controller.py test_prototype.py test_sma_baseline.py
python fetch_daily.py
python prototype.py --html /path/to/metrics_20261029_0802.html --daily-dir daily_public --out output
```

`fetch_daily.py` делает только два публичных запроса дневных свечей Binance, без ключей и аккаунтных методов.
Если дневные JSON уже сохранены, этот шаг не нужен. Сам prototype.py работает офлайн.
Исходный HTML не входит в пакет. SHA-256: `a2502aec14a6fb05d203a33193503eb1624808f6d28ed3d4c1f79723c5f6fe65`.

## Что получилось

Общий интервал сравнения: **21.10.2026 18:00 — 29.10.2026 07:00 UTC**, 181 час.
Для факторов доступно 336 часов; ранняя часть используется для прогрева и появления завершённых обучающих исходов.
Одинаковая геометрия: шаг 0.6%, цель лота 1.4%, условный номинал заявки 100 USDT, потолок номинала 1000 USDT.
Maker 0.016%, taker 0.048%, проскальзывание рыночного выхода 0.02%. Это фиксированные исследовательские допущения.
Циклы: цель net +5, ограничение потери −30, срок 24 часа, ожидание после завершения 2 часа.
Постоянная сетка и SMA не используют цель/срок цикла, но сохраняют общий лимит потерь и ожидание.

| Вариант | BTC, net с оценкой закрытия остатка | ETH, net с оценкой закрытия остатка |
|---|---:|---:|
| Постоянная сетка + общий лимит потерь | -30.56 | -32.45 |
| SMA100 дневная, гистерезис ±2% | -30.56 | -32.45 |
| Циклы: только цена/волатильность | -13.73 | -41.31 |
| Много факторов, без блока корреляций | -4.00 | -21.22 |
| Много факторов + корреляции | -8.71 | -30.13 |

Сравнивается закрытый результат минус комиссии/funding плюс стоимость остатка с оценкой расходов на его закрытие.
Остаток не объявляется закрытым: в журнале он остаётся открытым. Последняя переоценка не гарантирует цену будущего исполнения.
Таблица не доказывает доходность и не обосновывает отключение SMA. Добавление корреляций здесь ухудшило оба результата
относительно версии без блока корреляций. Это наблюдение на коротком отрезке, а не выбор готовой торговой стратегии.

На всём доступном 336-часовом отрезке SMA разрешала LONG обоим активам: переключений режима **0**.
Поэтому совпадение SMA и постоянной сетки здесь ожидаемо и **не проверяет пользу самого отсечения**.
Для такого вывода нужны общие данные факторов и исполнения, включающие реальные смены режима SMA.
Публичные дневные закрытия совпали с агрегацией HTML точно на всех 13 полных общих днях.

## Как устроены решения

1. Используются только закрытые часы. Решение по часу t исполняется на open t+2: час закрылся и прошёл ещё час запаса.
2. Для каждой прошлой точки отдельно посчитан исход одной фиксированной сетки из пустой позиции.
   Такой исход допускается в обучение лишь после закрытия всего его горизонта. Пересекающиеся исходы зависимы.
3. После минимум 48 зрелых примеров выбираются 20 похожих прошлых состояний; шкалы IQR считаются только по зрелому прошлому.
   Семейства факторов имеют равный вес в расстоянии. Пропуски не заменяются нулём.
4. Новый переход оценки среднего net из неположительной в положительную разрешает запуск. Неположительная/неизвестная
   оценка прекращает новые входы до конца текущего цикла. Два последовательных значения ниже −5 дают команду выхода.
5. Отдельно действует учёт текущих лотов: полный net, расходы, лимит потерь, цель, срок, остаток, ожидание перед новым входом.
   Повторный вход требует нового положительного перехода; старый сигнал не перезапускает сетку бесконечно.

**Ограничение модели выхода:** аналоговый прогноз обучен на запуске новой сетки с пустой позицией. Его применение
к завершению уже накопленной позиции — явно заданная эвристика. Это ещё не модель, сравнивающая ценность
«продолжать / прекратить добор / закрыть сейчас» для конкретного текущего остатка.

## Факторы и корреляции

Есть уровни, изменения, нормированные отклонения, ликвидации лонгов/шортов и их доля, совместные направления цены/потока/OI.
Корреляции рассчитываются на доходностях и изменениях, а не на растущих уровнях цен.
Предварительно заданы окна 24/72 часа; присутствуют прошлые сдвиги потока/OI/стакана относительно доходности.
Межфакторные пары: поток–изменение OI; поток–изменение стакана; поток–изменение log1p(ликвидаций);
изменение funding–изменение OI; изменение log(L/S)–изменение funding.

Ряд net taker flow из HTML используется. Но отдельных рядов taker_buy/taker_sell в HTML нет:
D6/относительный дисбаланс не восстанавливается выдуманным знаменателем. Покрытие каждого признака сохраняется отдельно.
Отсутствующий ряд ликвидаций тоже не превращается в нулевые ликвидации.

## Значения во флете и возле разворотов

Флет размечен по прошлому ER24 < 0.3. Разворот — движение прошлого 6-часового окна больше 1 ATR и последующее
противоположное 6-часовое движение больше 1 ATR. Вторая разметка известна лишь задним числом и не поступает в модель.
Окна могут пересекаться между собой и с флетом; строки ниже нельзя считать независимыми событиями.

| Актив / состояние | Часов, не независимых событий | Медиана net-flow z72 | Медиана corr(доходность, поток), 24ч |
|---|---:|---:|---:|
| BTCUSDT / флет ER24 < 0.3 | 212 | 0.003 | 0.806 |
| BTCUSDT / ретроспективный разворот вверх | 22 | -0.933 | 0.827 |
| BTCUSDT / ретроспективный разворот вниз | 21 | 1.051 | 0.821 |
| ETHUSDT / флет ER24 < 0.3 | 219 | 0.110 | 0.864 |
| ETHUSDT / ретроспективный разворот вверх | 27 | -1.236 | 0.922 |
| ETHUSDT / ретроспективный разворот вниз | 20 | 1.243 | 0.852 |

У отдельных медиан число известных значений меньше числа часов группы; точные known-count сохранены в JSON.
Высокая одновременная корреляция потока и цены встречается и во флете, и у разворотов. Само по себе это не доказывает
предсказание следующего движения. Полный набор медиан OI/funding/ликвидаций/стакана/межфакторных связей есть в results.json.

## Чего эти результаты ещё не устанавливают

- HTML выгружен 29.10; время первой доступности каждого исторического значения CoinGlass неизвестно.
  Задержка исполнения и тесты причинности не восстанавливают отсутствующий архив публикаций/пересмотров.
- Исполнение на H1 — условный путь из четырёх OHLC-точек с полным исполнением касаний. Нет очереди, частичных исполнений,
  биржевых округлений, гонок отмены/исполнения, перезапуска и маржинальной ликвидации. Это не точная модель WEEX.
- Просадка измерена по закрытиям часов и может пропустить более глубокую внутрисвечную просадку.
- Funding берётся из 42 платёжных событий на актив в исходном HTML. Процент переведён в долю; полнота истории отдельно не подтверждена.
- SMA100 использует настоящие публичные дневки Binance, полосу ±2% и час запаса после закрытия дня.
  Незакрытая дневка 29.10 исключена. Это сравнение правила SMA в том же условном движке, а не подтверждённая копия живого исполнения.
- 181 час сравнения, 93 признака и перекрывающиеся обучающие исходы недостаточны для вывода об устойчивости.
  Независимого длинного теста, подбора на отдельном обучающем периоде и проверки на нетронутом периоде пока нет.

## Проверка и артефакты

**47 тестов прошли**: календарь и пропуски, доступность часов, единицы funding, нормализация только по прошлому,
зрелость меток, неизменность старых прогнозов после добавления будущего, задержка решений, SMA/гистерезис,
сохранение количества стоящей заявки, остаток, комиссии/funding, выход на следующем open и гэп после цели,
ожидание нового сигнала, общий лимит потерь. Тесты проверяют описанный прототип, не паритет с биржей.
Предупреждения NumPy в синтетике вызваны медианами намеренно полностью отсутствующих факторов; неизвестность сохранена.

`output/results.json` содержит сравнение, покрытие, допущения, SHA исходников и диагностику режимов.
Рядом лежат признаки, отдельные будущие обучающие исходы, решения, оценки аналогов, журнал циклов и кривая капитала каждого варианта.
Результаты диагностического прогона не являются рекомендацией менять торговые настройки.

## Что передать Клоду для следующей проверяемой стадии

Использовать этот пакет как проверяемый исходный прототип; торговые процессы не менять.
Нужны непрерывная история исполнения WEEX и архив факторов CoinGlass с временем получения, отдельными buy/sell и явными пропусками.
На общей истории воспроизвести действующее SMA-правило, постоянную сетку и циклы в одном проверенном движке.
Для модели выхода добавить состояние остатка и контрфактические исходы трёх действий, затем выделить независимый тестовый период
и проверить устойчивость по неперекрывающимся режимам. Отдельно проверить, даёт ли блок корреляций добавочную пользу.
Текущий результат не позволяет ни объявить многофакторную модель готовой, ни признать SMA бесполезной.

## Самодостаточный пакет кода и тестов для Claude

В соответствии с поручением пользователя публикация состоит из одного Markdown-файла и одного коммита.
Ниже исходники и тесты встроены целиком; сырые аккаунтные данные, ключи и исходный HTML не включены.
Их можно извлечь в новый отдельный каталог этим скриптом (путь к Markdown задаётся первым аргументом):

```python
import hashlib, json, pathlib, re, sys
document = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
out = pathlib.Path("research/multifactor_grid_20261029_from_report")
out.mkdir(parents=True, exist_ok=False)
parts = re.findall(r"^### FILE: ([a-z0-9_.]+)\n```[a-z]*\n(.*?)^```$", document, re.M | re.S)
assert len(parts) == 12, len(parts)
for name, content in parts:
    (out / name).write_bytes(content.encode("utf-8"))
manifest = json.loads(re.search(r"<!-- BUNDLE_SHA256\n(.*?)\nBUNDLE_SHA256 -->", document, re.S)[1])
assert set(manifest) == {name for name, _ in parts}
for name, digest in manifest.items():
    assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest, name
print(out)
```

После извлечения использовать команды запуска из раздела выше. Для полностью офлайн-повтора нужны исходный HTML
и ранее сохранённые публичные daily JSON. Сравнение SHA исходников и входов обязательно при сопоставлении результатов.

<!-- BUNDLE_SHA256
{
  "features.py": "489d3150f287458f61e7a2c3e263e1f6c55bb0048220897238690c903cf0c5db",
  "controller.py": "0322bbe548769d598b7a99123f9954134ff3b16fdd65b15af76ea4183fa28d14",
  "prototype.py": "ef4e44a8a0bf264745766f8cac76ab74afb360c7fbd7056de1e00dfb37aa6ae8",
  "sma_baseline.py": "412093b5e61d3bdd4b612164d93e5b95c0e83c631c1ed288f61259e9374440a8",
  "fetch_daily.py": "36535074cfb779ebef69d7fb791207ca5984f7dfe334cc51cf394985f5652ee7",
  "test_features.py": "75ed38143484434a5feefef660f45bfcf975616ccdf1c9d5094b27d56c130057",
  "test_controller.py": "a27771899cea17378b250bbb9e376bf2bddadf10725f781afcd12f5f687c2fb1",
  "test_prototype.py": "6c27af2e1ad863995fa9fb1132b9b32713bd4b04381bd1d0cf254166950b879b",
  "test_sma_baseline.py": "97b750644c4f3fa2acac8c4751f9284268a81f720576ed221872056ff8c59527",
  "pytest.ini": "8250d20f42b419af40706490ead78aabab9feba93eab09a3f626e3de5256e1f4",
  "requirements.txt": "2a2be18af5116e8b9b0c0ddbfe884467772fed0affe4fb057a4f42aa7bd840ae",
  "result_summary.json": "a15f0f3a37379655f036cf6a3616907e7d0577445e1e2cf2be9ff73cd7ad120a"
}
BUNDLE_SHA256 -->

### FILE: features.py
```python
"""Causal hourly features for an offline grid-cycle research prototype.

The index is the UTC START of an hour. A row is available only after that hour
closes and its source has actually arrived. The caller must supply closed bars;
optionally set ``df.attrs['asof']`` to exclude bars not closed at that instant.
This module cannot reconstruct the historical publication time of a revised
export. It neither labels future reversals nor asserts that a feature predicts
anything. Missing observations remain NaN, with separate availability flags.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES_VERSION = "mf-grid-features-1"
HOUR = pd.Timedelta(hours=1)
FEATURES_METADATA: dict[str, dict] = {}


def _meta(name: str, family: str, description: str, window: str) -> str:
    FEATURES_METADATA[name] = {
        "family": family, "description": description,
        "causal_window": window, "available": "after bar close and source arrival",
    }
    return name


# A fixed feature contract; unavailable input columns still produce NaN columns.
for h in (1, 6, 24, 72):
    _meta(f"price_ret_{h}h", "price", f"Log return over {h} complete calendar hours", f"t-{h}..t")
for name, desc, win in (
    ("atr14_pct", "Mean true range / close", "t-14..t"),
    ("price_move_6h_atr", "Six-hour close change / ATR14", "t-14..t"),
    ("er24", "Absolute 24h change / sum of absolute hourly changes; zero for a constant price", "t-24..t"),
    ("range_position24", "Close location in 24h high-low range; 0.5 for a zero-width range", "t-23..t"),
    ("range_width24_pct", "24h high-low range / close", "t-23..t"),
    ("distance_prior_high24_atr", "Distance from current close to PRIOR 24h high / ATR", "t-24..t"),
    ("distance_prior_low24_atr", "Distance from current close to PRIOR 24h low / ATR", "t-24..t"),
):
    _meta(name, "price", desc, win)

LEVELS = {
    "oi": ("oi_coins", "oi"),
    "funding": ("fr_pct", "funding"),
    "funding_oiw": ("fr_oiw_pct", "funding"),
    "ls_accounts": ("ls_acc", "positioning"),
    "ls_top": ("ls_top_pos", "positioning"),
    "wi2": ("wi2", "positioning"),
}
for name, (_column, family) in LEVELS.items():
    # Raw OI is scale-dependent, so expose relative changes and historical z only.
    if name != "oi":
        _meta(f"{name}_level", family, "Observed level in original source units", "t")
    for h in (6, 24):
        change = "log change" if name in ("oi", "ls_accounts", "ls_top") else "level change"
        _meta(f"{name}_change_{h}h", family, f"{h}h {change}; funding changes are percentage points", f"t-{h}..t")
    _meta(f"{name}_z72", family, "Current level relative to mean/std of preceding 72 hours", "baseline t-72..t-1; observation t")

for h in (6, 24):
    _meta(f"flow_net_{h}h", "flow", "Sum of signed taker delta in source coin units", f"t-{h-1}..t")
    _meta(f"flow_imbalance_{h}h", "flow", "(sum buy - sum abs(sell)) / sum gross; needs paired buy/sell", f"t-{h-1}..t")
for name, desc, win in (
    ("flow_net6_z24", "6h net delta standardized against preceding 24 values", "observation t-5..t; baseline sums ending t-24..t-1"),
    ("flow_net6_z72", "6h net delta standardized against preceding 72 values", "observation t-5..t; baseline sums ending t-72..t-1"),
    ("flow_imbalance_change6", "Current 6h relative imbalance minus preceding non-overlapping 6h imbalance", "t-11..t"),
    ("book_mean6", "Mean signed bid-ask delta; orders rather than executed flow", "t-5..t"),
    ("book_positive_share6", "Share of strictly positive bid-ask observations, zero is not positive", "t-5..t"),
    ("book_mean6_z72", "6h mean order imbalance versus preceding 72 observations", "baseline ends t-1"),
    ("volume_sum6_z24", "6h reported volume versus preceding 24 observations", "baseline ends t-1"),
    ("volume_sum6_z72", "6h reported volume versus preceding 72 observations", "baseline ends t-1"),
):
    _meta(name, "book" if name.startswith("book") else "volume" if name.startswith("volume") else "flow", desc, win)

LIQUIDATIONS = ("liq_all_long", "liq_all_short", "liq_coin_long", "liq_coin_short")
for source in LIQUIDATIONS:
    _meta(f"{source}_sum6", "liquidations", "Sum of absolute liquidation USD over six fully observed hours", "t-5..t")
    _meta(f"{source}_sum6_z72", "liquidations", "6h liquidation sum versus preceding 72 sums", "baseline ends t-1")
_meta("liq_long_share6", "liquidations", "Long liquidation share of total; NaN if total is zero or any side unknown", "t-5..t")

# Correlate returns with changes/flows, never the nonstationary price level.
CORRELATION_INPUTS = {
    "oi_change": "hourly log OI change",
    "funding_change": "hourly funding level change",
    "net_flow": "hourly signed taker flow",
    "book_change": "hourly signed order-book delta change",
    "liquidation_change": "hourly change in log1p total observed liquidation USD",
    "positioning_change": "hourly log account L/S change",
}
CROSS_FACTOR_PAIRS = {
    "flow_oi": ("net_flow", "oi_change"),
    "flow_book": ("net_flow", "book_change"),
    "flow_liquidations": ("net_flow", "liquidation_change"),
    "funding_oi": ("funding_change", "oi_change"),
    "positioning_funding": ("positioning_change", "funding_change"),
}
for name, desc in CORRELATION_INPUTS.items():
    for h in (24, 72):
        _meta(f"corr_return_{name}_{h}h", "relations", f"Pearson correlation of hourly log return with {desc}", f"{h} paired calendar hours ending t")
for name in ("net_flow", "oi_change", "book_change"):
    _meta(f"corr_prior_{name}_return24", "relations", "Correlation of metric at u-1 with return at u; retrospective association only", "24 paired hours u ending t, metric lagged one hour")
for name, (left, right) in CROSS_FACTOR_PAIRS.items():
    for h in (24, 72):
        _meta(f"corr_cross_{name}_{h}h", "relations", f"Cross-factor Pearson correlation: {CORRELATION_INPUTS[left]} with {CORRELATION_INPUTS[right]}", f"{h} fully observed paired calendar hours ending t")

for name, desc in (
    ("price_flow_alignment6", "Sign of six-hour price return times sign of net flow; -1 means observed disagreement"),
    ("flow_book_alignment6", "Sign of net executed flow times sign of mean order imbalance"),
    ("price_oi_interaction6", "Six-hour log price return times six-hour log OI change; not an initiator-side label"),
    ("price_liquidation_interaction6", "Six-hour log price return times (2 * long-liquidation share - 1)"),
):
    _meta(name, "interactions", desc, "through t only; both inputs required")

GROUPS = {
    "price": ("open", "high", "low", "close"),
    "flow": ("taker_delta",),
    "paired_flow": ("taker_buy", "taker_sell"),
    "book": ("bid_ask_delta",),
    "oi": ("oi_coins",),
    "funding": ("fr_pct", "fr_oiw_pct"),
    "liquidations": ("liq_all_long", "liq_all_short"),
    "coin_liquidations": ("liq_coin_long", "liq_coin_short"),
    "positioning": ("ls_acc", "ls_top_pos", "wi2"),
}
for group in GROUPS:
    _meta(f"missing_{group}", "availability", "1 if any source in group is unknown this hour, else 0", "t")


def _complete_change(s: pd.Series, hours: int) -> pd.Series:
    return s.diff(hours).where(s.rolling(hours + 1, min_periods=hours + 1).count() == hours + 1)


def _past_z(s: pd.Series, hours: int) -> pd.Series:
    past = s.shift(1).rolling(hours, min_periods=hours)
    mean, std = past.mean(), past.std(ddof=0)
    z = (s - mean) / std.where(std > 0)
    # A known zero/constant source is not a missing source. A new deviation from
    # an exactly constant baseline has undefined z, not an invented infinity.
    return z.mask(std.eq(0) & s.eq(mean), 0.0)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator > 0)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return the fixed numeric feature contract on a full hourly UTC calendar.

    Missing hours are inserted as NaN rather than compressed away. No source is
    forward/back-filled. The optional ``attrs['asof']`` is a closure cutoff, not
    proof that historical source values were available at the time. Input is
    never mutated. Features at row t are NOT available at the opening of t.
    """
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("Expected a timezone-aware DatetimeIndex of hourly bar starts")
    if not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError("Bar starts must be unique and increasing")
    work = df.copy()
    work.index = work.index.tz_convert("UTC")
    if not work.index.equals(work.index.floor("1h")):
        raise ValueError("Expected exact hourly bar starts")
    if df.attrs.get("asof") is not None:
        asof = pd.Timestamp(df.attrs["asof"])
        if asof.tzinfo is None:
            raise ValueError("attrs['asof'] must be timezone-aware")
        work = work.loc[work.index + HOUR <= asof.tz_convert("UTC")]
    if work.empty:
        return pd.DataFrame(index=work.index, columns=list(FEATURES_METADATA), dtype=float)
    work = work.reindex(pd.date_range(work.index[0], work.index[-1], freq="1h", tz="UTC"))

    def series(name: str) -> pd.Series:
        if name not in work:
            return pd.Series(np.nan, index=work.index, dtype=float)
        return pd.to_numeric(work[name], errors="coerce").astype(float).replace([np.inf, -np.inf], np.nan)

    raw = {c: series(c) for c in set(sum((list(v) for v in GROUPS.values()), [])) | {"volume_usd"}}
    for c in ("open", "high", "low", "close", "oi_coins", "ls_acc", "ls_top_pos"):
        raw[c] = raw[c].where(raw[c] > 0)
    # Signed sells are accepted (CoinGlass often plots them below zero).
    raw["taker_buy"] = raw["taker_buy"].where(raw["taker_buy"] >= 0)
    raw["taker_sell"] = raw["taker_sell"].abs()
    raw["volume_usd"] = raw["volume_usd"].where(raw["volume_usd"] >= 0)
    for c in LIQUIDATIONS:
        raw[c] = raw[c].abs()

    out: dict[str, pd.Series] = {}
    c, high, low = raw["close"], raw["high"], raw["low"]
    log_price = np.log(c)
    for h in (1, 6, 24, 72):
        out[f"price_ret_{h}h"] = _complete_change(log_price, h)
    tr = pd.concat([high - low, (high - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1, skipna=False)
    tr = tr.where(high >= low)
    atr = tr.rolling(14, min_periods=14).mean()
    out["atr14_pct"] = 100 * _safe_ratio(atr, c)
    out["price_move_6h_atr"] = _safe_ratio(_complete_change(c, 6), atr)
    path = c.diff().abs().rolling(24, min_periods=24).sum()
    move = _complete_change(c, 24).abs()
    out["er24"] = _safe_ratio(move, path).mask(path.eq(0) & move.eq(0), 0.0)
    hi24, lo24 = high.rolling(24, min_periods=24).max(), low.rolling(24, min_periods=24).min()
    width = hi24 - lo24
    out["range_position24"] = _safe_ratio(c - lo24, width).mask(width.eq(0) & c.eq(lo24), 0.5)
    out["range_width24_pct"] = 100 * _safe_ratio(width, c)
    out["distance_prior_high24_atr"] = _safe_ratio(c - high.shift().rolling(24, min_periods=24).max(), atr)
    out["distance_prior_low24_atr"] = _safe_ratio(c - low.shift().rolling(24, min_periods=24).min(), atr)

    for name, (column, _family) in LEVELS.items():
        value = raw[column]
        transformed = np.log(value) if name in ("oi", "ls_accounts", "ls_top") else value
        if name != "oi":
            out[f"{name}_level"] = value
        for h in (6, 24):
            out[f"{name}_change_{h}h"] = _complete_change(transformed, h)
        out[f"{name}_z72"] = _past_z(transformed, 72)

    buy, sell = raw["taker_buy"], raw["taker_sell"]
    for h in (6, 24):
        out[f"flow_net_{h}h"] = raw["taker_delta"].rolling(h, min_periods=h).sum()
        gross = (buy + sell).rolling(h, min_periods=h).sum()
        net = (buy - sell).rolling(h, min_periods=h).sum()
        out[f"flow_imbalance_{h}h"] = _safe_ratio(net, gross)
    for h in (24, 72):
        out[f"flow_net6_z{h}"] = _past_z(out["flow_net_6h"], h)
        out[f"volume_sum6_z{h}"] = _past_z(raw["volume_usd"].rolling(6, min_periods=6).sum(), h)
    out["flow_imbalance_change6"] = out["flow_imbalance_6h"].diff(6)
    out["book_mean6"] = raw["bid_ask_delta"].rolling(6, min_periods=6).mean()
    out["book_positive_share6"] = raw["bid_ask_delta"].gt(0).astype(float).where(raw["bid_ask_delta"].notna()).rolling(6, min_periods=6).mean()
    out["book_mean6_z72"] = _past_z(out["book_mean6"], 72)
    for source in LIQUIDATIONS:
        total = raw[source].rolling(6, min_periods=6).sum()
        out[f"{source}_sum6"] = total
        out[f"{source}_sum6_z72"] = _past_z(total, 72)
    out["liq_long_share6"] = _safe_ratio(out["liq_all_long_sum6"], out["liq_all_long_sum6"] + out["liq_all_short_sum6"])

    relation_inputs = {
        "oi_change": np.log(raw["oi_coins"]).diff(),
        "funding_change": raw["fr_pct"].diff(),
        "net_flow": raw["taker_delta"],
        "book_change": raw["bid_ask_delta"].diff(),
        "liquidation_change": np.log1p(raw["liq_all_long"] + raw["liq_all_short"]).diff(),
        "positioning_change": np.log(raw["ls_acc"]).diff(),
    }
    returns = out["price_ret_1h"]
    for name, value in relation_inputs.items():
        for h in (24, 72):
            out[f"corr_return_{name}_{h}h"] = returns.rolling(h, min_periods=h).corr(value).clip(-1, 1)
    for name in ("net_flow", "oi_change", "book_change"):
        out[f"corr_prior_{name}_return24"] = returns.rolling(24, min_periods=24).corr(relation_inputs[name].shift()).clip(-1, 1)
    for name, (left, right) in CROSS_FACTOR_PAIRS.items():
        for h in (24, 72):
            out[f"corr_cross_{name}_{h}h"] = relation_inputs[left].rolling(h, min_periods=h).corr(relation_inputs[right]).clip(-1, 1)

    ret6 = out["price_ret_6h"]
    out["price_flow_alignment6"] = np.sign(ret6) * np.sign(out["flow_net_6h"])
    out["flow_book_alignment6"] = np.sign(out["flow_net_6h"]) * np.sign(out["book_mean6"])
    out["price_oi_interaction6"] = ret6 * out["oi_change_6h"]
    out["price_liquidation_interaction6"] = ret6 * (2 * out["liq_long_share6"] - 1)
    for group, columns in GROUPS.items():
        out[f"missing_{group}"] = pd.concat([raw[col] for col in columns], axis=1).isna().any(axis=1).astype(float)

    result = pd.DataFrame(out, index=work.index).reindex(columns=list(FEATURES_METADATA))
    result = result.replace([np.inf, -np.inf], np.nan).astype(float)
    result.attrs.update({
        "features_version": FEATURES_VERSION,
        "decision_time_rule": "index + 1h plus actual source publication/collection latency",
        "historical_availability_not_verified": True,
        "asof": df.attrs.get("asof"),
    })
    return result
```

### FILE: controller.py
```python
"""Pure offline long-grid cycle prototype; never connects to a trading service.

Grid geometry is adapted from 2c90cf5 research/weex/exec_calib/matrix.py:
peak/lowest-lot reference, TP before entry, at most one new entry per OHLC point.
This is NOT production/WEEX parity. Touches fill completely, with no queue,
partial fills, lot-size rounding, asynchronous cancellation, or exchange restart.
The default parameters are illustrative research inputs, not trading settings.

Input bars have UTC bar-start timestamps. Decision rows are already aligned to
their EXECUTION bar by the caller; this module neither shifts nor manufactures
signals. All market observations used by a decision must precede that bar.
Net targets, risk and time limits inspected at close execute on the next open.
The final observation does not liquidate or discard an unfinished position.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Config:
    step_pct: float = 0.6
    target_pct: float = 1.4
    order_notional: float = 100.0
    capital_cap: float = 1000.0
    maker_fee: float = 0.00016
    taker_fee: float = 0.00048
    slippage: float = 0.0002
    profit_target: float = 5.0
    loss_limit: float = 30.0
    max_cycle_bars: int = 24
    cooldown_bars: int = 2

    def __post_init__(self):
        for name in ("step_pct", "target_pct", "order_notional", "capital_cap",
                     "profit_target", "loss_limit"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.step_pct >= 100 or self.order_notional > self.capital_cap:
            raise ValueError("invalid step or order notional above capital cap")
        for name in ("maker_fee", "taker_fee", "slippage"):
            if not 0 <= getattr(self, name) < 1:
                raise ValueError(f"{name} must be in [0,1)")
        if self.max_cycle_bars < 1 or self.cooldown_bars < 0:
            raise ValueError("invalid bar limits")


@dataclass
class Lot:
    entry: float
    qty: float
    tp: float


@dataclass
class PendingEntry:
    price: float
    qty: float


@dataclass
class GridBook:
    """One cycle's accounting. A standing order retains its own quantity."""
    config: Config
    lots: list[Lot] = field(default_factory=list)
    pending: PendingEntry | None = None
    reference: float | None = None
    realized: float = 0.0
    fees: float = 0.0
    funding: float = 0.0  # positive means paid; negative means received
    turnover: float = 0.0
    entries: int = 0
    takes: int = 0
    max_lots: int = 0

    @property
    def qty(self) -> float:
        return sum(x.qty for x in self.lots)

    @property
    def cost(self) -> float:
        return sum(x.qty * x.entry for x in self.lots)

    def net(self, price: float) -> float:
        return self.realized - self.fees - self.funding + self.qty * price - self.cost

    def liquidation_net(self, price: float) -> float:
        px = price * (1 - self.config.slippage)
        return self.net(px) - self.qty * px * self.config.taker_fee

    def settle_funding(self, price: float, rate: float) -> None:
        self.funding += self.qty * price * rate

    def cancel_entry(self) -> None:
        self.pending = None

    def point(self, price: float, allow_new: bool = True) -> None:
        """Process a synthetic OHLC path point; immediate full fills only."""
        keep = []
        took = False
        for lot in self.lots:
            if price >= lot.tp:
                self.realized += lot.qty * (lot.tp - lot.entry)
                self.fees += lot.qty * lot.tp * self.config.maker_fee
                self.turnover += lot.qty * lot.tp
                self.takes += 1
                took = True
            else:
                keep.append(lot)
        self.lots = keep
        if not allow_new:
            self.cancel_entry()
            return
        # A TP changes the anchor. Explicit synthetic cancel/replace is immediate.
        if took:
            self.pending = None
        if self.lots:
            self.reference = min(x.entry for x in self.lots)
        elif self.reference is None or price > self.reference:
            self.reference = price
            self.pending = None  # trailing the empty-book entry is a replacement
        if self.pending is None:
            level = self.reference * (1 - self.config.step_pct / 100)
            qty = self.config.order_notional / level
            if max(self.cost, self.qty * level) + qty * level <= self.config.capital_cap + 1e-9:
                self.pending = PendingEntry(level, qty)
        order = self.pending
        if order is not None and price <= order.price:
            # Recheck cap using the standing order's quantity, never a new size.
            if max(self.cost, self.qty * order.price) + order.qty * order.price <= self.config.capital_cap + 1e-9:
                self.lots.append(Lot(order.price, order.qty,
                                     order.price * (1 + self.config.target_pct / 100)))
                self.fees += order.qty * order.price * self.config.maker_fee
                self.turnover += order.qty * order.price
                self.entries += 1
                self.max_lots = max(self.max_lots, len(self.lots))
                self.pending = None

    def flatten(self, open_price: float) -> None:
        self.cancel_entry()
        px = open_price * (1 - self.config.slippage)
        self.realized += self.qty * px - self.cost
        self.fees += self.qty * px * self.config.taker_fee
        self.turnover += self.qty * px
        self.lots = []


def _flag(row: pd.Series, name: str) -> bool:
    value = row.get(name, False)
    return bool(value) if pd.notna(value) else False


def _validate(bars: pd.DataFrame, decisions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("bars require a timezone-aware DatetimeIndex")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("bars must have strictly increasing timestamps")
    if len(bars) > 2 and len(set(np.diff(bars.index.asi8))) != 1:
        raise ValueError("bars must be a complete regular grid; gaps cannot be invented")
    bars = bars.copy()
    bars.index = bars.index.tz_convert("UTC")
    values = bars[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("OHLC must be positive and finite")
    if len(values):
        o, h, l, c = values.T
        if ((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l)).any():
            raise ValueError("invalid OHLC geometry")
    if "funding_rate" in bars and not np.isfinite(bars["funding_rate"].to_numpy(float)).all():
        raise ValueError("funding_rate must explicitly contain finite event rates or zero")
    if len(decisions):
        if not isinstance(decisions.index, pd.DatetimeIndex) or decisions.index.tz is None:
            raise ValueError("decisions require a timezone-aware execution index")
        if decisions.index.has_duplicates or not decisions.index.is_monotonic_increasing:
            raise ValueError("decisions must have strictly increasing execution timestamps")
        decisions = decisions.copy()
        decisions.index = decisions.index.tz_convert("UTC")
    return bars, decisions


def replay(bars: pd.DataFrame, decisions: pd.DataFrame, config: Config | None = None,
           policy: str = "cycles") -> dict[str, Any]:
    """Replay already-lagged decisions; an absent row means no new instruction.

    ``continuous`` ignores discretionary decisions and cycles' profit/time exit;
    the same loss limit and cooldown still apply. ``cycles`` uses start/stop_new/
    exit plus profit/time exits. ``gated`` uses those discretionary decisions but
    has no profit/time exit, for a regime baseline with its own exit rule.
    stop_new enters DRAIN for the remainder of that cycle; its TP orders remain
    eligible. start is only accepted when flat and cooldown has elapsed.
    """
    config = config or Config()
    if policy not in {"cycles", "continuous", "gated"}:
        raise ValueError("policy must be cycles, continuous or gated")
    controlled = policy in {"cycles", "gated"}
    bars, decisions = _validate(bars, decisions)
    bar_duration = (bars.index[1] - bars.index[0]) if len(bars) > 1 else (
        pd.Timedelta(bars.index.freq.nanos, unit="ns") if bars.index.freq is not None else None)
    curve, cycles = [], []
    book: GridBook | None = None
    cycle_id = 0
    active: dict[str, Any] | None = None
    pending_exit: dict[str, Any] | None = None
    state = "WAIT"
    closed_net = 0.0
    cooldown_until = 0
    peak = max_dd = 0.0
    no_instruction = pd.Series(dtype=object)

    def record(status: str, at: pd.Timestamp, mark: float, exit_reason: str | None = None) -> dict:
        assert book is not None and active is not None
        return {**active, "status": status, "end": at.isoformat(), "exit_reason": exit_reason,
                "net_pnl": book.net(mark), "estimated_liquidation_net": book.liquidation_net(mark),
                "realized_gross": book.realized, "fees": book.fees, "funding": book.funding,
                "open_qty": book.qty, "open_cost": book.cost, "turnover": book.turnover,
                "entries": book.entries, "takes": book.takes, "max_lots": book.max_lots,
                "successful": status == "closed" and book.entries > 0 and book.net(mark) > 0}

    for i, (at, row) in enumerate(bars.iterrows()):
        observed_at = (at + bar_duration).isoformat() if bar_duration is not None else None
        o, h, l, c = (float(row[x]) for x in ("open", "high", "low", "close"))
        decision = decisions.loc[at] if at in decisions.index else no_instruction
        closed_this_bar = False
        if book is not None:
            # Existing inventory pays funding before any exit at this bar's open.
            book.settle_funding(o, float(row.get("funding_rate", 0.0)))
            if pending_exit is None and controlled and _flag(decision, "exit"):
                pending_exit = {"reason": str(decision.get("reason", "signal_exit")),
                                "intent_at": at.isoformat(), "trigger_estimate": None}
            if pending_exit is not None:
                state = "EXIT"
                active.update({"exit_intent_at": pending_exit["intent_at"],
                               "exit_trigger_estimate": pending_exit["trigger_estimate"]})
                book.flatten(o)
                state = "RECONCILE"  # deterministic fills are known in this prototype
                result = record("closed", at, o, pending_exit["reason"])
                cycles.append(result)
                closed_net += result["net_pnl"]
                book, active, pending_exit = None, None, None
                cooldown_until = i + config.cooldown_bars + 1
                state = "COOLDOWN"
                closed_this_bar = True
            elif controlled and _flag(decision, "stop_new"):
                book.cancel_entry()
                state = "DRAIN"

        if book is None and not closed_this_bar:
            state = "COOLDOWN" if i < cooldown_until else "WAIT"
            allowed = policy == "continuous" or (_flag(decision, "start") and
                        not _flag(decision, "exit") and not _flag(decision, "stop_new"))
            if state == "WAIT" and allowed:
                cycle_id += 1
                book = GridBook(config)
                active = {"cycle_id": cycle_id, "start": at.isoformat(), "start_bar": i,
                          "reason": "continuous" if policy == "continuous" else str(decision.get("reason", "signal")),
                          "bars": 0, "min_mtm": 0.0, "min_liquidation": 0.0}
                state = "RUN"

        if book is not None:
            path = (o, l, h, c) if c >= o else (o, h, l, c)
            for price in path:
                book.point(price, allow_new=state == "RUN")
            active["bars"] += 1
            mtm = book.net(c)
            liquid = book.liquidation_net(c)
            active["min_mtm"] = min(active["min_mtm"], mtm)
            active["min_liquidation"] = min(active["min_liquidation"], liquid)
            why = None
            if liquid <= -config.loss_limit:
                why = "loss_limit"
            elif policy == "cycles" and book.entries and liquid >= config.profit_target:
                why = "net_profit_target"
            elif policy == "cycles" and active["bars"] >= config.max_cycle_bars:
                why = "max_cycle_bars"
            elif controlled and state == "DRAIN" and not book.lots:
                why = "drain_complete"
            if why is not None:
                pending_exit = {"reason": why, "intent_at": observed_at,
                                "trigger_estimate": liquid}
                state = "EXIT_PENDING"
            equity = closed_net + mtm
            liq_equity = closed_net + liquid
            qty, cycle = book.qty, cycle_id
        else:
            equity = liq_equity = closed_net
            qty, cycle = 0.0, None
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append({"time": at.isoformat(), "observed_at": observed_at, "equity": equity,
                      "estimated_liquidation_equity": liq_equity, "drawdown": peak - equity,
                      "state": state, "cycle_id": cycle, "open_qty": qty})

    if book is not None:
        at = bars.index[-1]
        mark = float(bars.iloc[-1]["close"])
        open_record = record("open", at, mark)
        open_record["pending_exit_reason"] = pending_exit["reason"] if pending_exit else None
        cycles.append(open_record)
    closed = [x for x in cycles if x["status"] == "closed"]
    open_cycles = [x for x in cycles if x["status"] == "open"]
    return {"equity_curve": curve, "cycles": cycles,
            "summary": {"policy": policy, "bars": len(bars), "cycles": len(cycles),
                        "closed_cycles": len(closed), "open_cycles": len(open_cycles),
                        "profitable_closed_cycles": sum(x["successful"] for x in closed),
                        "net_pnl": curve[-1]["equity"] if curve else 0.0,
                        "estimated_liquidation_net": curve[-1]["estimated_liquidation_equity"] if curve else 0.0,
                        "net_liquidation": curve[-1]["estimated_liquidation_equity"] if curve else 0.0,
                        "max_drawdown": max_dd, "turnover": sum(x["turnover"] for x in cycles),
                        "drawdown_sampling": "bar_close",
                        "fees": sum(x["fees"] for x in cycles),
                        "funding": sum(x["funding"] for x in cycles),
                        "open_qty": book.qty if book else 0.0,
                        "funding_rates_supplied": "funding_rate" in bars,
                        "config": asdict(config)},
            "assumptions": ["Prototype, not validated WEEX/production execution parity",
                            "Fixed O-L-H-C path for up bars; O-H-L-C for down bars",
                            "Full limit fills at touches; no queue, partials, tick/qty rounding",
                            "One new entry per synthetic point; immediate cancel/replace and TP",
                            "Decisions are caller-lagged to execution; close exits execute next open",
                            "End-of-data inventory remains open; no synthetic terminal liquidation",
                            "Funding absent from input is not modeled; supplied event rates use existing inventory",
                            "No exchange restart, asynchronous cancel/fill race or live connectivity"]}
```

### FILE: prototype.py
```python
"""Offline, retrospective hourly demonstration. No trading clients or network.

Historical publication times are NOT recoverable from an HTML snapshot. Results
are engineering diagnostics, not an as-of backtest or a validated WEEX strategy.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from controller import Config, replay
from features import build_features, FEATURES_METADATA

VERSION = "multifactor-grid-demo-1"
HORIZON = 24
EXECUTION_DELAY = 2  # source hour closes, then one more complete hour before execution
MIN_TRAIN = 48
NEIGHBORS = 20
WARMUP = 80


def load_html(path):
    raw = Path(path).read_bytes()
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', raw.decode("utf-8"), re.S)
    if not match:
        raise ValueError("No embedded metrics data")
    payload = json.loads(match.group(1))
    frames = {}
    for sym, p in payload.items():
        ix = pd.to_datetime(p["t"], utc=True)
        df = pd.DataFrame({k: p["ohlc"][k] for k in ("open", "high", "low", "close")}, index=ix)
        for k, values in p["s"].items():
            if len(values) == len(ix):
                df[k] = values
        built = pd.Timestamp(p["built"])
        df = df.loc[df.index + pd.Timedelta(hours=1) <= built].copy()
        if df.index.duplicated().any() or not df.index.is_monotonic_increasing:
            raise ValueError("Invalid hourly calendar")
        expected = pd.date_range(df.index.min(), df.index.max(), freq="h")
        if not df.index.equals(expected):
            raise ValueError("Missing price hours; no synthetic fills permitted")
        if df[["open", "high", "low", "close"]].isna().any().any():
            raise ValueError("Missing OHLC")
        df["funding_rate"] = 0.0
        paid = p.get("paid") or {}
        for stamp, pct in zip(paid.get("t", []), paid.get("v", [])):
            stamp = pd.Timestamp(stamp, tz="UTC") if pd.Timestamp(stamp).tzinfo is None else pd.Timestamp(stamp).tz_convert("UTC")
            if stamp in df.index and pct is not None:
                df.loc[stamp, "funding_rate"] += float(pct) / 100.0
        df.attrs.update(asof=built.isoformat(), historical_availability_verified=False)
        frames[sym] = df
    return frames, {"source_sha256": hashlib.sha256(raw).hexdigest(), "source_file": Path(path).name,
                    "publication_times_verified": False, "execution_data": "hourly OHLC from snapshot",
                    "funding": "embedded Binance paid events, percent converted to decimal; completeness not independently verified"}


def cycle_labels(bars, cfg):
    """Same fixed grid policy from empty inventory at every eligible time.

Future labels stay outside the feature frame and can enter training only after
their entire observation interval has closed. Overlapping starts are dependent.
"""
    y = pd.Series(np.nan, index=bars.index, name="cycle_net_label")
    for i in range(WARMUP, len(bars) - EXECUTION_DELAY - HORIZON):
        future = bars.iloc[i + EXECUTION_DELAY:i + EXECUTION_DELAY + HORIZON + 1]
        dec = pd.DataFrame(False, index=future.index, columns=["start", "stop_new", "exit"])
        dec.iloc[0, dec.columns.get_loc("start")] = True
        dec["reason"] = "fixed label policy"
        result = replay(future, dec, cfg, "cycles")
        y.iloc[i] = result["summary"]["estimated_liquidation_net"]
    return y


def neighbors_at(features, labels, i, columns):
    # A label for j observes through close(j + delay + horizon). By decision
    # close(i), that label is mature only when j + delay + horizon <= i.
    last_mature = i - EXECUTION_DELAY - HORIZON
    pool = labels.iloc[:max(0, last_mature + 1)].dropna()
    if len(pool) < MIN_TRAIN:
        return None
    train = features.loc[pool.index, columns]
    current = features.iloc[i][columns]
    scale = train.quantile(.75) - train.quantile(.25)
    usable = current.notna() & scale.gt(1e-12) & train.notna().mean().ge(.5)
    names = usable.index[usable].tolist()
    if len(names) < 3:
        return None
    train = train[names]
    delta = ((train - current[names]) / scale[names]).clip(-10, 10).pow(2)
    family_scores = []
    for family in sorted({FEATURES_METADATA[k]["family"] for k in names}):
        members = [k for k in names if FEATURES_METADATA[k]["family"] == family]
        part = delta[members]
        score = part.mean(axis=1).where(part.notna().sum(axis=1) >= max(1, int(np.ceil(len(members) / 2))))
        family_scores.append(score)
    distances = pd.concat(family_scores, axis=1)
    score = distances.mean(axis=1).where(distances.notna().sum(axis=1) == len(family_scores))
    nearest = score.dropna().sort_values(kind="mergesort").head(NEIGHBORS)
    if len(nearest) < NEIGHBORS:
        return None
    outcomes = pool.loc[nearest.index]
    return {"mean": float(outcomes.mean()), "q20": float(outcomes.quantile(.2)),
            "neighbors": len(nearest), "training_cases": len(pool), "features_used": len(names),
            "latest_training_bar": str(nearest.index.max()), "families_used": len(family_scores)}


def decisions_from_history(features, labels, cfg, variant):
    names = [k for k in features if variant != "price_cycles" or FEATURES_METADATA[k]["family"] == "price"]
    if variant == "multifactor_without_correlations":
        names = [k for k in names if FEATURES_METADATA[k]["family"] != "relations"]
    estimates = []
    for i in range(len(features)):
        estimate = neighbors_at(features, labels, i, names)
        estimates.append(estimate or {})
    estimates = pd.DataFrame(estimates, index=features.index)
    mean = estimates.get("mean", pd.Series(np.nan, index=features.index))
    positive = mean.gt(0)
    adverse = mean.lt(-cfg.profit_target)
    dec = pd.DataFrame(index=features.index)
    dec["start"] = positive & ~positive.shift(fill_value=False)  # re-arm only on a fresh positive transition
    dec["stop_new"] = mean.le(0) | mean.isna()
    dec["exit"] = adverse & adverse.shift(fill_value=False)
    dec["reason"] = "historical fixed-cycle net estimate; heuristic environment gate"
    # A negative fresh-start estimate is NOT a proven optimal exit for the
    # current inventory. Exit uses this explicit research heuristic plus ledger guards.
    delayed = dec.shift(EXECUTION_DELAY)
    for key in ("start", "stop_new", "exit"):
        delayed[key] = delayed[key].eq(True)
    delayed["reason"] = delayed["reason"].fillna("warmup/no mature evidence")
    return delayed, estimates


def regime_diagnostics(bars, feats):
    """Descriptive future reversal labels are NEVER model inputs."""
    atr = feats["atr14_pct"] * bars["close"] / 100
    previous = feats["price_move_6h_atr"]
    following = (bars["close"].shift(-6) - bars["close"]) / atr
    flat = feats["er24"].lt(.3)
    groups = {"causal_flat_er24_below_0_3": flat,
              "retrospective_down_to_up_6h": previous.lt(-1) & following.gt(1),
              "retrospective_up_to_down_6h": previous.gt(1) & following.lt(-1)}
    selected = ["oi_change_6h", "funding_level", "funding_change_6h", "flow_net6_z72",
                "book_mean6_z72", "liq_long_share6", "ls_accounts_change_6h", "wi2_change_6h",
                "corr_return_oi_change_24h", "corr_return_net_flow_24h",
                "corr_return_book_change_24h", "corr_return_liquidation_change_24h",
                "corr_cross_flow_oi_24h", "corr_cross_flow_book_24h",
                "corr_cross_flow_liquidations_24h", "corr_cross_funding_oi_24h",
                "corr_cross_positioning_funding_24h"]
    result = {}
    for group, mask in groups.items():
        mask = mask & feats["price_ret_72h"].notna()
        result[group] = {"hours": int(mask.sum()), "independent_events": None,
                         "feature_medians": {name: {"known": int(feats.loc[mask, name].notna().sum()),
                                                     "median": finite(feats.loc[mask, name].median())}
                                             for name in selected}}
    return {"definitions": {"flat": "ER24 < .3 from past data, descriptive only",
                             "reversal": "prior 6h move >1 ATR and opposite following 6h move >1 ATR; hindsight label only"},
            "groups": result, "predictive_significance_established": False}


def finite(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def json_default(obj):
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return str(obj)
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    raise TypeError(type(obj).__name__)


def run(path, out, daily_dir=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frames, provenance = load_html(path)
    cfg = Config()
    result = {"version": VERSION, "status": "RETROSPECTIVE_HOURLY_ENGINEERING_DEMO_ONLY", "provenance": provenance,
              "feature_count": len(FEATURES_METADATA),
              "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("features.py", "controller.py", "prototype.py")},
              "config": asdict(cfg), "parameters": {"horizon": HORIZON, "delay": EXECUTION_DELAY,
                   "minimum_train": MIN_TRAIN, "neighbors": NEIGHBORS, "warmup": WARMUP},
              "sma100_daily_benchmark": {"status": "NOT_RUN", "reason": "No daily directory supplied; no hourly substitution"},
              "symbols": {}}
    if daily_dir is not None:
        from sma_baseline import build_sma_decisions
        result["source_code_sha256"]["sma_baseline.py"] = hashlib.sha256(Path(__file__).with_name("sma_baseline.py").read_bytes()).hexdigest()
        result["sma100_daily_benchmark"] = {"status": "HOURLY_ENGINEERING_COMPARISON", "band": 0.02,
                                          "production_execution_parity": False}
    # Common chronological comparison slice; no tuning after seeing outcomes.
    evaluation_start = WARMUP + EXECUTION_DELAY + HORIZON + MIN_TRAIN - 1 + EXECUTION_DELAY
    for sym, bars in frames.items():
        feats = build_features(bars)
        labels = cycle_labels(bars, cfg)
        feats.to_csv(out / f"{sym}_features.csv")
        labels.to_csv(out / f"{sym}_retrospective_cycle_labels.csv")
        entry = {"hours": len(bars), "evaluation_start": str(bars.index[evaluation_start]),
                 "evaluation_end_exclusive": str(bars.index[-1] + pd.Timedelta(hours=1)),
                 "coverage": {k: float(feats[k].notna().mean()) for k in feats},
                 "missing_inputs": [k for k in ("taker_buy", "taker_sell") if k not in bars],
                 "regime_diagnostics": regime_diagnostics(bars, feats), "policies": {}}
        common_bars = bars.iloc[evaluation_start:]
        variants = ["continuous", "price_cycles", "multifactor_without_correlations", "multifactor"]
        if daily_dir is not None:
            variants.insert(1, "sma100_daily")
        for variant in variants:
            if variant == "continuous":
                dec = pd.DataFrame({"start": True, "stop_new": False, "exit": False, "reason": "continuous benchmark"}, index=bars.index)
                estimates = pd.DataFrame(index=bars.index)
            elif variant == "sma100_daily":
                dec, metadata = build_sma_decisions(bars, Path(daily_dir) / f"{sym}.json")
                entry["sma100_daily_diagnostics"] = metadata
                estimates = pd.DataFrame(index=bars.index)
            else:
                dec, estimates = decisions_from_history(feats, labels, cfg, variant)
            policy = "continuous" if variant == "continuous" else "gated" if variant == "sma100_daily" else "cycles"
            sim = replay(common_bars, dec.loc[common_bars.index], cfg, policy)
            entry["policies"][variant] = sim["summary"]
            result["execution_assumptions"] = sim["assumptions"]
            pd.DataFrame(sim["equity_curve"]).to_csv(out / f"{sym}_{variant}_equity.csv", index=False)
            pd.DataFrame(sim["cycles"]).to_csv(out / f"{sym}_{variant}_cycles.csv", index=False)
            dec.to_csv(out / f"{sym}_{variant}_decisions.csv")
            estimates.to_csv(out / f"{sym}_{variant}_historical_estimates.csv")
        result["symbols"][sym] = entry
    (out / "feature_metadata.json").write_text(json.dumps(FEATURES_METADATA, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=json_default, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "symbols": {s: {"hours": v["hours"], "evaluation_start": v["evaluation_start"],
          "policies": v["policies"]} for s, v in result["symbols"].items()}}, indent=2, default=json_default))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    parser.add_argument("--daily-dir", help="Optional public daily JSON directory for SMA100 benchmark")
    args = parser.parse_args()
    run(args.html, args.out, args.daily_dir)
```

### FILE: sma_baseline.py
```python
"""Offline SMA100 daily hysteresis comparator with an explicit execution lag.

No network, execution clients, hourly-SMA substitutions or future daily closes.
The fixed 2% band and initial state reproduce the stated matrix comparator;
hourly decisions carry the regime LEVEL so a flat gated grid can start again.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

DAY = pd.Timedelta(days=1)
HOUR = pd.Timedelta(hours=1)
SMA_DAYS = 100
MAX_CLOSE_GAP = .01


def _validate_ohlc(frame, name):
    values = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f"{name} OHLC must be finite and positive")
    if len(values):
        o, h, l, c = values.T
        if ((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l)).any():
            raise ValueError(f"{name} OHLC geometry is invalid")


def _overlap_diagnostic(bars, daily):
    comparisons = []
    for day, group in bars.groupby(bars.index.floor("D")):
        if day not in daily.index or len(group) != 24:
            continue
        if not group.index.equals(pd.date_range(day, periods=24, freq="h")):
            continue
        close = float(daily.loc[day, "close"])
        hourly_close = float(group.iloc[-1]["close"])
        comparisons.append({"day": day.date().isoformat(), "daily_close": close,
                            "hourly_aggregated_close": hourly_close,
                            "relative_close_gap": abs(hourly_close - close) / close})
    maximum = max((x["relative_close_gap"] for x in comparisons), default=None)
    if maximum is not None and maximum > MAX_CLOSE_GAP:
        raise ValueError(f"Daily/hourly close mismatch exceeds 1%: maximum {maximum:.4%}")
    return {"complete_days_compared": len(comparisons), "max_relative_close_gap": maximum,
            "threshold": MAX_CLOSE_GAP,
            "status": "within_threshold" if comparisons else "no_complete_common_day",
            "comparisons": comparisons}


def build_sma_decisions(bars, daily_path, band=.02):
    """Return caller-aligned gated-grid decisions and auditable source metadata.

    For daily bar d, SMA includes its close and 99 prior complete UTC closes.
    Regime d is known at d+1 00:00 and may first execute at d+1 01:00. Unknown
    regimes or missing daily observations raise instead of becoming permission.
    """
    if not np.isfinite(band) or not 0 <= band < 1:
        raise ValueError("band must be finite and in [0,1)")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None or bars.empty:
        raise ValueError("bars must have a nonempty timezone-aware hourly index")
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError("bars must have unique increasing timestamps")
    bars = bars.copy()
    bars.index = bars.index.tz_convert("UTC")
    if not bars.index.equals(pd.date_range(bars.index[0], bars.index[-1], freq="h")) or not bars.index.equals(bars.index.floor("h")):
        raise ValueError("bars must contain a complete hourly UTC calendar")
    _validate_ohlc(bars, "Hourly")
    asof = bars.index[-1] + HOUR

    path = Path(daily_path)
    raw = path.read_bytes()
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, list) or len(row) != 12 for row in rows):
        raise ValueError("Expected a nonempty Binance public 12-column kline array")
    starts = pd.to_datetime([row[0] for row in rows], unit="ms", utc=True)
    keep = starts + DAY <= asof
    selected = [row for row, selected in zip(rows, keep) if selected]
    index = starts[keep]
    # Filtering precedes OHLC validation: even a wildly moving unclosed candle
    # cannot affect this historical comparator or its rejection decisions.
    if len(index) < SMA_DAYS:
        raise ValueError("At least 100 complete daily candles are required")
    if not index.is_unique or not index.is_monotonic_increasing or not index.equals(index.floor("D")):
        raise ValueError("Daily candles must be unique increasing UTC midnights")
    if not index.equals(pd.date_range(index[0], index[-1], freq="D")):
        raise ValueError("Daily calendar has missing days; no synthetic fills allowed")
    expected_end = index + DAY - pd.Timedelta(milliseconds=1)
    close_time = pd.to_datetime([row[6] for row in selected], unit="ms", utc=True)
    if not close_time.equals(expected_end):
        raise ValueError("Daily close timestamps do not match full UTC days")
    daily = pd.DataFrame([row[1:5] for row in selected], index=index,
                         columns=["open", "high", "low", "close"]).astype(float)
    _validate_ohlc(daily, "Daily")
    latest_required = (bars.index[-1] - HOUR).floor("D") - DAY
    if daily.index[-1] < latest_required:
        raise ValueError("Daily history ends before the latest required execution regime")

    average = daily.close.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()
    states, event_times = [], []
    state = None
    for day in daily.index[SMA_DAYS - 1:]:
        close, sma = float(daily.loc[day, "close"]), float(average.loc[day])
        if state is None:
            state = close > sma
        elif state and close < sma * (1 - band):
            state = False
        elif not state and close > sma * (1 + band):
            state = True
        states.append(state)
        event_times.append(day + DAY + HOUR)
    event_index = pd.DatetimeIndex(event_times)
    events = pd.Series(states, index=event_index, dtype="boolean")
    aligned = events.reindex(events.index.union(bars.index)).sort_index().ffill().reindex(bars.index)
    if aligned.isna().any():
        raise ValueError("Unknown SMA100 regime at execution start; insufficient warmup or publication guard")
    allowed = aligned.astype(bool)
    decisions = pd.DataFrame({"start": allowed, "stop_new": ~allowed, "exit": ~allowed}, index=bars.index)
    decisions["reason"] = "SMA100 completed UTC days, hysteresis band, one-hour publication guard"

    crossings = events.ne(events.shift()).fillna(False)
    eligible_events = event_index <= bars.index[-1]
    metadata = {
        "source_file": path.name, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows_in_file": len(rows), "rows_used": len(daily), "rows_discarded_unclosed_or_future": int((~keep).sum()),
        "asof": asof.isoformat(), "first_daily_start": daily.index[0].isoformat(),
        "last_daily_start": daily.index[-1].isoformat(), "sma_days": SMA_DAYS, "band": float(band),
        "crossings_count": int(crossings.loc[eligible_events].sum()),
        "crossings_in_execution_window": int(crossings.loc[(event_index >= bars.index[0]) & eligible_events].sum()),
        "initial_allowed": bool(allowed.iloc[0]), "allowed_hours": int(allowed.sum()),
        "first_regime_execution_time": event_index[0].isoformat(),
        "semantics": {"initial_state": "first complete 100-day close > SMA100; equality is OFF",
                      "on_to_off": "daily close < SMA100 * (1-band), strict",
                      "off_to_on": "daily close > SMA100 * (1+band), strict",
                      "inside_band": "persist previous regime",
                      "known_at": "daily start + 1 UTC day",
                      "executes_at": "daily start + 1 UTC day + 1 hour",
                      "signals": "start is permission level; OFF means stop_new and exit",
                      "crossings_count": "state transitions available by last execution bar; initial state excluded"},
        "overlap_diagnostic": _overlap_diagnostic(bars, daily),
    }
    provenance_path = path.with_name(path.stem + "_provenance.json")
    if provenance_path.exists():
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("sha256") not in (None, metadata["source_sha256"]):
            raise ValueError("Daily source hash does not match its provenance")
        metadata["source_url"] = provenance.get("url")
        metadata["retrieved_utc"] = provenance.get("retrieved_utc")
    return decisions, metadata
```

### FILE: fetch_daily.py
```python
"""Acquire public market candles only; no API keys or account endpoints."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

out = Path(__file__).resolve().parent / "daily_public"
out.mkdir(exist_ok=True)
for symbol in ("BTCUSDT", "ETHUSDT"):
    params = dict(symbol=symbol, interval="1d", startTime=1780272000000,
                  endTime=1793318399999, limit=200)
    url = "https://fapi.binance.com/fapi/v1/klines?" + urllib.parse.urlencode(params)
    record = {"url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            raw = response.read()
        data = json.loads(raw)
        if not isinstance(data, list) or not data:
            raise ValueError("No historical daily candles returned")
        record.update(rows=len(data), first_open_time=data[0][0], last_open_time=data[-1][0],
                      sha256=hashlib.sha256(raw).hexdigest(), status="downloaded")
        (out / (symbol + ".json")).write_bytes(raw)
    except Exception as error:
        record.update(status="unavailable", error=str(error))
    (out / (symbol + "_provenance.json")).write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))
```

### FILE: test_features.py
```python
"""Semantic checks for causal factor extraction; all data are synthetic."""
import numpy as np
import pandas as pd
import pytest

from features import FEATURES_METADATA, build_features


def frame(n=240):
    rng = np.random.default_rng(29)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    returns = rng.normal(0, .004, n)
    close = 100 * np.exp(np.cumsum(returns))
    buy = rng.uniform(20, 100, n)
    sell = rng.uniform(20, 100, n)
    return pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume_usd": rng.uniform(10000, 50000, n), "taker_buy": buy, "taker_sell": -sell,
        "taker_delta": buy - sell, "bid_ask_delta": rng.normal(0, 10, n),
        "oi_coins": 1000 * np.exp(np.cumsum(rng.normal(0, .002, n))),
        "fr_pct": rng.normal(.001, .002, n), "fr_oiw_pct": rng.normal(.001, .002, n),
        "liq_all_long": rng.uniform(0, 300, n), "liq_all_short": -rng.uniform(0, 300, n),
        "liq_coin_long": rng.uniform(0, 100, n), "liq_coin_short": -rng.uniform(0, 100, n),
        "ls_acc": rng.uniform(.8, 2, n), "ls_top_pos": rng.uniform(.8, 2, n),
        "wi2": rng.normal(0, 10, n),
    }, index=idx)


def test_prefix_is_unchanged_by_future_observations():
    d = frame()
    a = build_features(d.iloc[:130])
    future_changed = d.copy()
    future_changed.iloc[130:] = future_changed.iloc[130:] * 100
    b = build_features(future_changed).iloc[:130]
    pd.testing.assert_frame_equal(a, b)
    assert set(a.columns) == set(FEATURES_METADATA)


def test_missing_liquidations_remain_unknown_not_no_liquidations():
    d = frame()
    d["liq_all_long"] = np.nan
    f = build_features(d)
    assert f["liq_all_long_sum6"].isna().all()
    assert f["liq_long_share6"].isna().all()
    assert f["price_liquidation_interaction6"].isna().all()
    assert f["corr_return_liquidation_change_24h"].isna().all()
    assert f["missing_liquidations"].eq(1).all()


def test_known_zero_is_not_missing_or_positive():
    d = frame()
    d[["liq_all_long", "liq_all_short", "bid_ask_delta"]] = 0
    f = build_features(d)
    assert f["liq_all_long_sum6"].iloc[-1] == 0
    assert f["liq_all_long_sum6_z72"].iloc[-1] == 0
    assert f["liq_long_share6"].isna().all()  # 0/0 has no composition
    assert f["missing_liquidations"].eq(0).all()
    assert f["book_positive_share6"].iloc[-1] == 0
    assert pd.isna(f["corr_return_book_change_24h"].iloc[-1])  # no variance


def test_flow_imbalance_uses_matched_buy_sell_not_dollar_volume():
    d = frame()
    d["taker_buy"], d["taker_sell"], d["taker_delta"] = 30., -70., -40.
    d["volume_usd"] = 99999999.
    f = build_features(d)
    assert f["flow_imbalance_6h"].iloc[-1] == pytest.approx(-.4)
    assert f["flow_net_6h"].iloc[-1] == -240
    missing = build_features(d.drop(columns=["taker_buy", "taker_sell"]))
    assert missing["flow_imbalance_6h"].isna().all()
    assert missing["flow_net_6h"].iloc[-1] == -240
    assert missing["missing_paired_flow"].eq(1).all()


def test_correlations_use_returns_and_changes_not_levels():
    d = frame()
    # OI log changes equal twice the price log returns.
    d["oi_coins"] = 1000 * (d["close"] / d["close"].iloc[0]) ** 2
    f = build_features(d)
    expected = np.log(d["close"]).diff().rolling(24, min_periods=24).corr(np.log(d["oi_coins"]).diff())
    pd.testing.assert_series_equal(f["corr_return_oi_change_24h"], expected.clip(-1, 1), check_names=False)
    assert f["corr_return_oi_change_24h"].iloc[-1] == pytest.approx(1)
    d["oi_coins"] *= 1_000_000  # Units/scale of level must not change relation.
    changed = build_features(d)
    np.testing.assert_allclose(f["corr_return_oi_change_24h"], changed["corr_return_oi_change_24h"], atol=1e-9, equal_nan=True)


def test_lagged_relation_uses_prior_metric_and_current_known_return():
    d = frame()
    f = build_features(d)
    expected = np.log(d["close"]).diff().rolling(24, min_periods=24).corr(d["taker_delta"].shift())
    pd.testing.assert_series_equal(f["corr_prior_net_flow_return24"], expected.clip(-1, 1), check_names=False)


def test_cross_factor_relations_use_the_specified_changes_and_paired_windows():
    d = frame()
    # Executed flow is proportional to log OI changes and opposite to book changes.
    flow = d["taker_delta"]
    d["oi_coins"] = 1000 * np.exp(flow.cumsum() * .0001)
    d["bid_ask_delta"] = -flow.cumsum()
    d["fr_pct"] = flow.cumsum() * .00001
    d["ls_acc"] = np.exp(flow.cumsum() * .0002)
    f = build_features(d)
    for h in (24, 72):
        assert f[f"corr_cross_flow_oi_{h}h"].iloc[-1] == pytest.approx(1)
        assert f[f"corr_cross_flow_book_{h}h"].iloc[-1] == pytest.approx(-1)
        assert f[f"corr_cross_funding_oi_{h}h"].iloc[-1] == pytest.approx(1)
        assert f[f"corr_cross_positioning_funding_{h}h"].iloc[-1] == pytest.approx(1)
        liq_change = np.log1p(d["liq_all_long"].abs() + d["liq_all_short"].abs()).diff()
        expected = flow.rolling(h, min_periods=h).corr(liq_change).clip(-1, 1)
        pd.testing.assert_series_equal(f[f"corr_cross_flow_liquidations_{h}h"], expected, check_names=False)


def test_cross_factor_unknown_source_invalidates_both_pair_memberships():
    d = frame()
    d.loc[d.index[-10], "oi_coins"] = np.nan
    d.loc[d.index[-5], "liq_all_short"] = np.nan
    f = build_features(d)
    for h in (24, 72):
        assert pd.isna(f[f"corr_cross_flow_oi_{h}h"].iloc[-1])
        assert pd.isna(f[f"corr_cross_funding_oi_{h}h"].iloc[-1])
        assert pd.isna(f[f"corr_cross_flow_liquidations_{h}h"].iloc[-1])
        # Independent, fully observed pairs remain computable.
        assert pd.notna(f[f"corr_cross_flow_book_{h}h"].iloc[-1])


def test_z_score_baseline_excludes_current_observation():
    d = frame()
    d["fr_pct"] = np.arange(len(d), dtype=float)
    before = d["fr_pct"].iloc[-73:-1]
    d.loc[d.index[-1], "fr_pct"] = 10000
    f = build_features(d)
    assert f["funding_z72"].iloc[-1] == pytest.approx((10000 - before.mean()) / before.std(ddof=0))


def test_missing_calendar_hour_is_inserted_and_invalidates_full_windows():
    d = frame()
    missing_time = d.index[-3]
    f = build_features(d.drop(index=missing_time))
    assert len(f) == len(d)
    assert f.loc[missing_time, "missing_price"] == 1
    assert pd.isna(f["flow_net_6h"].iloc[-1])
    assert pd.isna(f["price_ret_6h"].iloc[-1])
    assert pd.isna(f["corr_return_oi_change_24h"].iloc[-1])


def test_optional_asof_excludes_the_still_open_last_bar():
    d = frame()
    d.attrs["asof"] = d.index[-1] + pd.Timedelta(minutes=30)
    f = build_features(d)
    assert f.index[-1] == d.index[-2]
    assert len(f) == len(d) - 1
    # Last completed hour is retained even if the live hour is extreme.
    d.iloc[-1] = 1e12
    pd.testing.assert_frame_equal(f, build_features(d))


def test_invalid_index_is_rejected_instead_of_guessing_time():
    d = frame()
    for changed in (d.set_axis(d.index.tz_localize(None)), d.iloc[::-1], pd.concat([d, d.iloc[-1:]])):
        with pytest.raises(ValueError):
            build_features(changed)
```

### FILE: test_controller.py
```python
"""Synthetic accounting/causality checks; no market files or network."""
from dataclasses import replace
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controller import Config, GridBook, Lot, PendingEntry, replay


def bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC"))


def instructions(data, **values):
    return pd.DataFrame(values, index=data.index)


def test_positive_takes_do_not_hide_negative_inventory():
    book = GridBook(Config(maker_fee=0, taker_fee=0, slippage=0))
    book.realized = 30
    book.lots = [Lot(100, 1, 110)]
    assert book.net(55) == -15
    assert book.liquidation_net(55) < book.config.profit_target


def test_standing_order_keeps_qty_with_existing_inventory():
    book = GridBook(Config(step_pct=1, target_pct=10, maker_fee=0))
    book.lots = [Lot(100, 1, 110)]
    book.pending = PendingEntry(99, 2)
    book.point(99)
    assert book.qty == 3
    assert book.turnover == 198


def test_stop_new_keeps_existing_lot_and_take():
    book = GridBook(Config(maker_fee=0))
    book.lots = [Lot(100, 1, 101)]
    book.pending = PendingEntry(99, 2)
    book.point(98, allow_new=False)
    assert book.qty == 1 and book.pending is None
    book.point(101, allow_new=False)
    assert book.qty == 0 and book.realized == 1 and book.entries == 0


def test_goal_is_intent_then_next_open_can_realize_a_loss():
    data = bars([(100, 104, 98, 104), (80, 80, 80, 80)])
    cfg = Config(step_pct=1, target_pct=100, maker_fee=0, taker_fee=0,
                 slippage=0, profit_target=2, loss_limit=1000)
    out = replay(data, instructions(data, start=[True, False]), cfg)
    cyc = out["cycles"][0]
    assert out["equity_curve"][0]["state"] == "EXIT_PENDING"
    assert cyc["exit_reason"] == "net_profit_target"
    assert cyc["exit_trigger_estimate"] > 2
    assert cyc["net_pnl"] < 0 and not cyc["successful"]
    assert cyc["end"] == data.index[1].isoformat()


def test_funding_precedes_exit_and_is_charged_once():
    data = bars([(100, 100, 99, 99), (100, 100, 100, 100)])
    data["funding_rate"] = [0, .01]
    cfg = Config(step_pct=1, target_pct=50, maker_fee=0, taker_fee=0,
                 slippage=0, profit_target=1000)
    out = replay(data, instructions(data, start=[True, False], exit=[False, True]), cfg)
    cyc = out["cycles"][0]
    assert cyc["funding"] == pytest.approx((100 / 99) * 100 * .01)
    assert cyc["net_pnl"] == pytest.approx(100 / 99 - cyc["funding"])
    assert cyc["open_qty"] == 0


def test_max_age_executes_on_next_open_and_no_same_bar_restart():
    data = bars([(100, 100, 99, 99), (99, 99, 99, 99), (99, 99, 99, 99), (99, 99, 99, 99)])
    cfg = Config(step_pct=1, target_pct=50, max_cycle_bars=1, cooldown_bars=1)
    out = replay(data, instructions(data, start=[True] * 4), cfg)
    first = out["cycles"][0]
    assert first["exit_reason"] == "max_cycle_bars"
    assert first["end"] == data.index[1].isoformat()
    assert out["equity_curve"][1]["state"] == "COOLDOWN"
    assert out["equity_curve"][2]["state"] == "COOLDOWN"
    assert out["cycles"][1]["start"] == data.index[3].isoformat()


def test_terminal_inventory_is_open_and_does_not_affect_prefix():
    data = bars([(100, 100, 99, 99), (99, 100, 98, 99), (99, 99, 90, 91)])
    cfg = Config(target_pct=50, profit_target=1000, loss_limit=1000)
    dec = instructions(data, start=[True, False, False])
    partial = replay(data.iloc[:2], dec.iloc[:2], cfg)
    full = replay(data, dec, cfg)
    assert partial["equity_curve"] == full["equity_curve"][:2]
    assert partial["cycles"][0]["status"] == "open"
    assert partial["cycles"][0]["open_qty"] > 0
    assert partial["summary"]["closed_cycles"] == 0


def test_continuous_ignores_profit_and_age_but_respects_risk():
    data = bars([(100, 104, 98, 104), (104, 104, 70, 70), (60, 60, 60, 60)])
    cfg = Config(target_pct=100, profit_target=.01, loss_limit=5, max_cycle_bars=1)
    out = replay(data, pd.DataFrame(), cfg, "continuous")
    assert out["equity_curve"][0]["state"] == "RUN"
    assert out["cycles"][0]["exit_reason"] == "loss_limit"
    assert out["cycles"][0]["end"] == data.index[2].isoformat()


def test_missing_decision_is_not_forward_filled_into_new_cycle():
    data = bars([(100, 100, 100, 100)] * 5)
    one = instructions(data.iloc[:1], start=[True])
    out = replay(data, one, Config(max_cycle_bars=1, cooldown_bars=0))
    assert out["summary"]["cycles"] == 1
    assert out["equity_curve"][-1]["state"] == "WAIT"


def test_invalid_or_missing_bars_are_not_invented():
    data = bars([(100, 100, 100, 100)] * 4).drop(pd.Timestamp("2026-01-01T01:00:00Z"))
    with pytest.raises(ValueError, match="complete regular grid"):
        replay(data, pd.DataFrame())


def test_unobserved_funding_is_explicit_not_silently_claimed_covered():
    data = bars([(100, 100, 100, 100)])
    out = replay(data, pd.DataFrame())
    assert out["summary"]["funding_rates_supplied"] is False
    data["funding_rate"] = float("nan")
    with pytest.raises(ValueError, match="funding_rate"):
        replay(data, pd.DataFrame())


def test_gated_waits_for_start_ignores_goal_age_and_honors_exit():
    data = bars([(100, 100, 100, 100), (100, 104, 98, 104),
                 (104, 104, 104, 104), (103, 103, 103, 103)])
    cfg = Config(target_pct=100, profit_target=.01, loss_limit=1000, max_cycle_bars=1)
    dec = instructions(data, start=[False, True, True, True],
                       exit=[False, False, False, True], reason=["regime"] * 4)
    out = replay(data, dec, cfg, "gated")
    assert out["equity_curve"][0]["state"] == "WAIT"
    assert out["equity_curve"][1]["state"] == "RUN"
    assert out["equity_curve"][2]["state"] == "RUN"
    assert out["cycles"][0]["end"] == data.index[3].isoformat()
    assert out["cycles"][0]["exit_reason"] == "regime"


def test_gated_retains_the_common_loss_limit_and_cooldown():
    data = bars([(100, 104, 98, 104), (104, 104, 70, 70),
                 (60, 60, 60, 60), (60, 60, 60, 60), (60, 60, 60, 60)])
    cfg = Config(target_pct=100, profit_target=.01, loss_limit=5,
                 max_cycle_bars=1, cooldown_bars=1)
    out = replay(data, instructions(data, start=[True] * 5), cfg, "gated")
    assert out["cycles"][0]["exit_reason"] == "loss_limit"
    assert out["cycles"][0]["end"] == data.index[2].isoformat()
    assert out["equity_curve"][3]["state"] == "COOLDOWN"
    assert out["cycles"][1]["start"] == data.index[4].isoformat()


def test_gated_stop_new_drains_without_replacing_entries():
    data = bars([(100, 100, 99, 99), (102, 102, 98, 101), (101, 101, 101, 101)])
    cfg = Config(step_pct=1, target_pct=1, maker_fee=0, taker_fee=0,
                 slippage=0, profit_target=1000, max_cycle_bars=1)
    out = replay(data, instructions(data, start=[True, True, True],
                                   stop_new=[False, True, False]), cfg, "gated")
    first = out["cycles"][0]
    assert first["entries"] == 1 and first["takes"] == 1
    assert first["exit_reason"] == "drain_complete"
    assert first["end"] == data.index[2].isoformat()
```

### FILE: test_prototype.py
```python
"""Independent chronology checks using synthetic public-schema inputs only."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype as model


PRICE_COLUMNS = ["price_ret_1h", "price_ret_6h", "price_ret_24h"]


def synthetic_features(n=180):
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(94021)
    frame = pd.DataFrame(rng.normal(size=(n, 3)), index=index, columns=PRICE_COLUMNS)
    labels = pd.Series(np.sin(np.arange(n) / 4) + .2, index=index)
    return frame, labels


def synthetic_bars(n=180):
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    close = 100 + np.sin(np.arange(n) / 6) * 3
    return pd.DataFrame({"open": close, "high": close + 1,
                         "low": close - 1, "close": close,
                         "funding_rate": 0.0}, index=index)


def test_only_mature_cycle_labels_enter_neighbors():
    features, labels = synthetic_features()
    i = model.MIN_TRAIN - 1 + model.EXECUTION_DELAY + model.HORIZON
    last_mature = model.MIN_TRAIN - 1
    labels.iloc[:model.MIN_TRAIN] = 1.0
    labels.iloc[model.MIN_TRAIN:] = 1e12

    assert model.neighbors_at(features, labels, i - 1, PRICE_COLUMNS) is None
    result = model.neighbors_at(features, labels, i, PRICE_COLUMNS)
    assert result is not None
    assert result["training_cases"] == model.MIN_TRAIN
    assert result["mean"] == pytest.approx(1.0)
    assert result["q20"] == pytest.approx(1.0)
    assert pd.Timestamp(result["latest_training_bar"]) <= features.index[last_mature]


def test_scaling_ignores_unmatured_features_and_all_future_rows():
    features, labels = synthetic_features()
    i = 110
    original = model.neighbors_at(features, labels, i, PRICE_COLUMNS)
    assert original is not None
    changed = features.copy()
    first_unmatured = i - model.EXECUTION_DELAY - model.HORIZON + 1
    changed.iloc[first_unmatured:i] = 1e15
    changed.iloc[i + 1:] = -1e15
    future_labels = labels.copy()
    future_labels.iloc[first_unmatured:] = -1e12
    assert model.neighbors_at(changed, future_labels, i, PRICE_COLUMNS) == original


@pytest.mark.parametrize("variant", ["price_cycles", "multifactor"])
def test_predictions_and_execution_signals_are_prefix_invariant(variant):
    features, labels = synthetic_features()
    cut = 130
    full_decisions, full_estimates = model.decisions_from_history(features, labels, model.Config(), variant)
    prefix_decisions, prefix_estimates = model.decisions_from_history(
        features.iloc[:cut], labels.iloc[:cut], model.Config(), variant)
    pd.testing.assert_frame_equal(full_estimates.iloc[:cut], prefix_estimates)
    pd.testing.assert_frame_equal(full_decisions.iloc[:cut], prefix_decisions)

    changed_features, changed_labels = features.copy(), labels.copy()
    changed_features.iloc[cut:] = 1e20
    changed_labels.iloc[cut:] = -1e20
    changed_decisions, changed_estimates = model.decisions_from_history(
        changed_features, changed_labels, model.Config(), variant)
    pd.testing.assert_frame_equal(full_estimates.iloc[:cut], changed_estimates.iloc[:cut])
    pd.testing.assert_frame_equal(full_decisions.iloc[:cut], changed_decisions.iloc[:cut])


def test_signal_executes_two_hours_after_its_source_bar(monkeypatch):
    features, labels = synthetic_features(8)
    means = [-1, -1, 1, 1, -10, -10, 1, 1]
    monkeypatch.setattr(model, "neighbors_at", lambda _f, _y, i, _cols: {"mean": means[i]})
    decisions, _ = model.decisions_from_history(features, labels, model.Config(), "price_cycles")
    # Positive transition at bar 02:00 is observable at 03:00; execution is
    # delayed to 04:00, with a further complete hour between close and action.
    assert list(decisions.index[decisions.start]) == [features.index[4]]
    # Two consecutive adverse observations end at 05:00's close, execute 07:00.
    assert list(decisions.index[decisions.exit]) == [features.index[7]]
    assert not decisions.iloc[:2][["start", "stop_new", "exit"]].to_numpy().any()


def test_recomputed_cycle_labels_are_prefix_invariant_when_mature():
    bars = synthetic_bars(145)
    cut = 125
    full = model.cycle_labels(bars, model.Config())
    prefix = model.cycle_labels(bars.iloc[:cut], model.Config())
    known = prefix.notna()
    assert known.any()
    pd.testing.assert_series_equal(full.loc[prefix.index][known], prefix[known])
    # Labels which would need a bar outside the prefix remain unavailable.
    assert prefix.iloc[cut - model.EXECUTION_DELAY - model.HORIZON:].isna().all()


def test_loader_drops_unfinished_hour_and_converts_paid_funding_percent(tmp_path):
    payload = {"BTCUSDT": {
        "t": ["2024-01-01 00:00:00", "2024-01-01 01:00:00", "2024-01-01 02:00:00"],
        "built": "2024-01-01T02:35:00Z",
        "ohlc": {"open": [100, 100, 100], "high": [101, 101, 101],
                 "low": [99, 99, 99], "close": [100, 100, 100]},
        "s": {"fr_pct": [.5, .5, .5]},
        "paid": {"t": ["2024-01-01 00:00:00", "2024-01-01T01:00:00+00:00", "2024-01-01 02:00:00"],
                 "v": [.01, -.02, 99.0]},
    }}
    path = tmp_path / "synthetic_metrics.html"
    path.write_text('<script id="data" type="application/json">' + json.dumps(payload) + '</script>', encoding="utf-8")
    frames, provenance = model.load_html(path)
    actual = frames["BTCUSDT"]
    assert len(actual) == 2
    assert actual.index[-1] == pd.Timestamp("2024-01-01T01:00:00Z")
    np.testing.assert_allclose(actual.funding_rate.to_numpy(), [.0001, -.0002])
    # Observed funding-indicator levels are not substituted for paid events.
    np.testing.assert_allclose(actual.fr_pct.to_numpy(), [.5, .5])
    assert actual.attrs["historical_availability_verified"] is False
    assert provenance["publication_times_verified"] is False


def test_hindsight_diagnostics_do_not_change_predictor_inputs():
    bars = synthetic_bars(180)
    features = model.build_features(bars)
    before = features.copy(deep=True)
    labels = pd.Series(np.sin(np.arange(len(features))), index=features.index)
    before_decisions, before_estimates = model.decisions_from_history(features, labels, model.Config(), "multifactor")
    model.regime_diagnostics(bars, features)
    pd.testing.assert_frame_equal(features, before)
    assert not any("reversal" in col or "retrospective" in col for col in features)
    after_decisions, after_estimates = model.decisions_from_history(features, labels, model.Config(), "multifactor")
    pd.testing.assert_frame_equal(before_decisions, after_decisions)
    pd.testing.assert_frame_equal(before_estimates, after_estimates)


def test_common_evaluation_window_keeps_first_eligible_entry(monkeypatch, tmp_path):
    bars = synthetic_bars(180)
    features, labels = synthetic_features(180)
    labels[:] = 1.0
    labels.iloc[:model.WARMUP] = np.nan
    decisions, _ = model.decisions_from_history(features, labels, model.Config(), "price_cycles")
    first_possible_entry = decisions.index[decisions.start][0]
    monkeypatch.setattr(model, "load_html", lambda _: ({"BTCUSDT": bars}, {}))
    monkeypatch.setattr(model, "build_features", lambda _: features)
    monkeypatch.setattr(model, "cycle_labels", lambda _bars, _cfg: labels)
    monkeypatch.setattr(model, "regime_diagnostics", lambda _bars, _features: {})
    result = model.run("synthetic-input-is-not-read.html", tmp_path)
    assert pd.Timestamp(result["symbols"]["BTCUSDT"]["evaluation_start"]) == first_possible_entry
    assert result["symbols"]["BTCUSDT"]["policies"]["price_cycles"]["cycles"] > 0
```

### FILE: test_sma_baseline.py
```python
"""SMA comparator chronology and source checks with synthetic daily prices."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sma_baseline import build_sma_decisions


def daily_file(tmp_path, closes):
    days = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    rows = [[int(day.timestamp() * 1000), close, close + 1, close - 1, close,
             0, int((day + pd.Timedelta(days=1)).timestamp() * 1000) - 1, 0, 0, 0, 0, 0]
            for day, close in zip(days, closes)]
    path = tmp_path / "synthetic_daily.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path, days, rows


def bars_from(start, hours=1, close=100):
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close},
                        index=pd.date_range(start, periods=hours, freq="h", tz="UTC"))


def test_first_warmup_requires_100_closed_days_and_publication_guard(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 101)
    with pytest.raises(ValueError, match="100 complete"):
        build_sma_decisions(bars_from(days[99] - pd.Timedelta(hours=2)), path)
    with pytest.raises(ValueError, match="Unknown SMA100"):
        build_sma_decisions(bars_from(days[100]), path)
    decisions, metadata = build_sma_decisions(bars_from(days[100] + pd.Timedelta(hours=1)), path)
    assert not decisions.start.iloc[0]  # equality at initialization is OFF
    assert metadata["rows_used"] == 100
    assert metadata["rows_discarded_unclosed_or_future"] == 1


def test_daily_close_is_never_used_before_next_day_one_hour(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 99 + [101, 90, 100])
    hours = bars_from(days[100] + pd.Timedelta(hours=23), 3)
    decisions, _ = build_sma_decisions(hours, path)
    assert decisions.start.tolist() == [True, True, False]
    assert decisions.exit.tolist() == [False, False, True]


def test_hysteresis_retains_state_inside_the_band(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 99 + [101, 99, 97, 101, 103, 100])
    hours = bars_from(days[100] + pd.Timedelta(hours=1), 4 * 24 + 1)
    # Keep the synthetic hourly source close to each corresponding daily close
    # so the separate cross-source guard is satisfied for full calendar days.
    for day, close in zip(days, [100] * 99 + [101, 99, 97, 101, 103, 100]):
        mask = hours.index.floor("D") == day
        hours.loc[mask, ["open", "close"]] = close
        hours.loc[mask, "high"] = close + 1
        hours.loc[mask, "low"] = close - 1
    decisions, metadata = build_sma_decisions(hours, path)
    at_daily_guard = decisions.loc[decisions.index.hour == 1]
    assert at_daily_guard.start.tolist() == [True, True, False, False, True]
    assert metadata["crossings_count"] == 2


def test_missing_daily_day_rejected(tmp_path):
    path, days, rows = daily_file(tmp_path, [100] * 110)
    path.write_text(json.dumps(rows[:70] + rows[71:]), encoding="utf-8")
    with pytest.raises(ValueError, match="missing days"):
        build_sma_decisions(bars_from(days[-1] + pd.Timedelta(hours=2)), path)


def test_unclosed_future_daily_prices_do_not_affect_decisions(tmp_path):
    path, days, rows = daily_file(tmp_path, [100] * 99 + [101] + [100] * 10)
    hours = bars_from(days[100] + pd.Timedelta(hours=1), 3)
    decisions, _ = build_sma_decisions(hours, path)
    for row in rows[100:]:
        row[1:5] = [-999, None, 0, 1e20]
    path.write_text(json.dumps(rows), encoding="utf-8")
    changed, metadata = build_sma_decisions(hours, path)
    pd.testing.assert_frame_equal(decisions, changed)
    assert metadata["rows_used"] == 100


def test_explicitly_incompatible_daily_and_hourly_prices_rejected(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 110)
    hours = bars_from(days[104], 24, close=102)
    with pytest.raises(ValueError, match="mismatch exceeds 1%"):
        build_sma_decisions(hours, path)


def test_matching_daily_overlap_is_recorded(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 110)
    decisions, metadata = build_sma_decisions(bars_from(days[104], 24), path)
    assert metadata["overlap_diagnostic"]["complete_days_compared"] == 1
    assert metadata["overlap_diagnostic"]["max_relative_close_gap"] == 0
    assert len(metadata["source_sha256"]) == 64
    assert decisions.stop_new.all()


def test_stale_daily_history_rejected(tmp_path):
    path, days, _ = daily_file(tmp_path, [100] * 101)
    with pytest.raises(ValueError, match="latest required"):
        build_sma_decisions(bars_from(days[-1] + pd.Timedelta(days=3, hours=1)), path)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_invalid_closed_daily_prices_rejected(tmp_path, bad):
    path, days, rows = daily_file(tmp_path, [100] * 101)
    rows[10][4] = bad
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="finite and positive"):
        build_sma_decisions(bars_from(days[-1] + pd.Timedelta(hours=1)), path)
```

### FILE: pytest.ini
```text
[pytest]
```

### FILE: requirements.txt
```text
numpy==2.2.6
pandas==2.3.3
pytest==9.0.3
```

### FILE: result_summary.json
```json
{
  "status": "RETROSPECTIVE_HOURLY_ENGINEERING_DEMO_ONLY",
  "feature_count": 93,
  "tests_passed": 47,
  "source_provenance": {
    "source_sha256": "a2502aec14a6fb05d203a33193503eb1624808f6d28ed3d4c1f79723c5f6fe65",
    "source_file": "metrics_20261029_0802.html",
    "publication_times_verified": false,
    "execution_data": "hourly OHLC from snapshot",
    "funding": "embedded Binance paid events, percent converted to decimal; completeness not independently verified"
  },
  "config": {
    "step_pct": 0.6,
    "target_pct": 1.4,
    "order_notional": 100.0,
    "capital_cap": 1000.0,
    "maker_fee": 0.00016,
    "taker_fee": 0.00048,
    "slippage": 0.0002,
    "profit_target": 5.0,
    "loss_limit": 30.0,
    "max_cycle_bars": 24,
    "cooldown_bars": 2
  },
  "parameters": {
    "horizon": 24,
    "delay": 2,
    "minimum_train": 48,
    "neighbors": 20,
    "warmup": 80
  },
  "source_code_sha256": {
    "features.py": "489d3150f287458f61e7a2c3e263e1f6c55bb0048220897238690c903cf0c5db",
    "controller.py": "0322bbe548769d598b7a99123f9954134ff3b16fdd65b15af76ea4183fa28d14",
    "prototype.py": "ef4e44a8a0bf264745766f8cac76ab74afb360c7fbd7056de1e00dfb37aa6ae8",
    "sma_baseline.py": "412093b5e61d3bdd4b612164d93e5b95c0e83c631c1ed288f61259e9374440a8"
  },
  "execution_assumptions": [
    "Prototype, not validated WEEX/production execution parity",
    "Fixed O-L-H-C path for up bars; O-H-L-C for down bars",
    "Full limit fills at touches; no queue, partials, tick/qty rounding",
    "One new entry per synthetic point; immediate cancel/replace and TP",
    "Decisions are caller-lagged to execution; close exits execute next open",
    "End-of-data inventory remains open; no synthetic terminal liquidation",
    "Funding absent from input is not modeled; supplied event rates use existing inventory",
    "No exchange restart, asynchronous cancel/fill race or live connectivity"
  ],
  "symbols": {
    "BTCUSDT": {
      "hours": 336,
      "evaluation_start": "2026-10-21 18:00:00+00:00",
      "evaluation_end_exclusive": "2026-10-29 07:00:00+00:00",
      "missing_inputs": [
        "taker_buy",
        "taker_sell"
      ],
      "regime_diagnostics": {
        "definitions": {
          "flat": "ER24 < .3 from past data, descriptive only",
          "reversal": "prior 6h move >1 ATR and opposite following 6h move >1 ATR; hindsight label only"
        },
        "groups": {
          "causal_flat_er24_below_0_3": {
            "hours": 212,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 212,
                "median": -0.00040071503851901724
              },
              "funding_level": {
                "known": 212,
                "median": 0.007692
              },
              "funding_change_6h": {
                "known": 212,
                "median": 0.0
              },
              "flow_net6_z72": {
                "known": 207,
                "median": 0.003177246289561639
              },
              "book_mean6_z72": {
                "known": 207,
                "median": -0.12075178127110428
              },
              "liq_long_share6": {
                "known": 182,
                "median": 0.6492647915122531
              },
              "ls_accounts_change_6h": {
                "known": 212,
                "median": 0.005347333553185785
              },
              "wi2_change_6h": {
                "known": 212,
                "median": 1.2000000000000028
              },
              "corr_return_oi_change_24h": {
                "known": 212,
                "median": 0.07066254470363428
              },
              "corr_return_net_flow_24h": {
                "known": 212,
                "median": 0.8060530574281282
              },
              "corr_return_book_change_24h": {
                "known": 212,
                "median": 0.023734240494437155
              },
              "corr_return_liquidation_change_24h": {
                "known": 91,
                "median": -0.21448503749685272
              },
              "corr_cross_flow_oi_24h": {
                "known": 212,
                "median": 0.008633645226387748
              },
              "corr_cross_flow_book_24h": {
                "known": 212,
                "median": -0.09446981062236395
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 91,
                "median": -0.19175299978846144
              },
              "corr_cross_funding_oi_24h": {
                "known": 212,
                "median": -0.09755768091322664
              },
              "corr_cross_positioning_funding_24h": {
                "known": 212,
                "median": -0.03553496625966387
              }
            }
          },
          "retrospective_down_to_up_6h": {
            "hours": 22,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 22,
                "median": 0.005935042171265614
              },
              "funding_level": {
                "known": 22,
                "median": 0.0048125
              },
              "funding_change_6h": {
                "known": 22,
                "median": -0.0017515
              },
              "flow_net6_z72": {
                "known": 22,
                "median": -0.9327068460818368
              },
              "book_mean6_z72": {
                "known": 22,
                "median": 0.7726065457437022
              },
              "liq_long_share6": {
                "known": 21,
                "median": 0.9439042947893067
              },
              "ls_accounts_change_6h": {
                "known": 22,
                "median": 0.04129316347967016
              },
              "wi2_change_6h": {
                "known": 22,
                "median": -11.1
              },
              "corr_return_oi_change_24h": {
                "known": 22,
                "median": 0.008037025759443303
              },
              "corr_return_net_flow_24h": {
                "known": 22,
                "median": 0.8268110720117527
              },
              "corr_return_book_change_24h": {
                "known": 22,
                "median": 0.005311075132230855
              },
              "corr_return_liquidation_change_24h": {
                "known": 5,
                "median": -0.5475025436366447
              },
              "corr_cross_flow_oi_24h": {
                "known": 22,
                "median": -0.05269200808996205
              },
              "corr_cross_flow_book_24h": {
                "known": 22,
                "median": -0.1085536114328912
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 5,
                "median": -0.6422456267888578
              },
              "corr_cross_funding_oi_24h": {
                "known": 22,
                "median": 0.02664914602853847
              },
              "corr_cross_positioning_funding_24h": {
                "known": 22,
                "median": -0.015392751153239674
              }
            }
          },
          "retrospective_up_to_down_6h": {
            "hours": 21,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 21,
                "median": 0.003831559561973563
              },
              "funding_level": {
                "known": 21,
                "median": 0.008927
              },
              "funding_change_6h": {
                "known": 21,
                "median": 0.002059
              },
              "flow_net6_z72": {
                "known": 20,
                "median": 1.0505053859215887
              },
              "book_mean6_z72": {
                "known": 20,
                "median": -1.12107843431856
              },
              "liq_long_share6": {
                "known": 15,
                "median": 0.07000887333841786
              },
              "ls_accounts_change_6h": {
                "known": 21,
                "median": -0.03590129150654442
              },
              "wi2_change_6h": {
                "known": 21,
                "median": 5.5
              },
              "corr_return_oi_change_24h": {
                "known": 21,
                "median": -0.02820435506300534
              },
              "corr_return_net_flow_24h": {
                "known": 21,
                "median": 0.8207821504946515
              },
              "corr_return_book_change_24h": {
                "known": 21,
                "median": -0.047091180682732534
              },
              "corr_return_liquidation_change_24h": {
                "known": 4,
                "median": 0.027955905767484662
              },
              "corr_cross_flow_oi_24h": {
                "known": 21,
                "median": -0.0337241378962487
              },
              "corr_cross_flow_book_24h": {
                "known": 21,
                "median": -0.11359241861913091
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 4,
                "median": 0.06897282647717948
              },
              "corr_cross_funding_oi_24h": {
                "known": 21,
                "median": 0.02556157041584322
              },
              "corr_cross_positioning_funding_24h": {
                "known": 21,
                "median": 0.12297281679274909
              }
            }
          }
        },
        "predictive_significance_established": false
      },
      "policies": {
        "continuous": {
          "policy": "continuous",
          "bars": 181,
          "cycles": 2,
          "closed_cycles": 1,
          "open_cycles": 1,
          "profitable_closed_cycles": 0,
          "net_pnl": -30.352343078275617,
          "estimated_liquidation_net": -30.555398004984585,
          "net_liquidation": -30.555398004984585,
          "max_drawdown": 31.31714929429632,
          "turnover": 2472.239221415213,
          "drawdown_sampling": "bar_close",
          "fees": 0.7062268262793022,
          "funding": 0.5376866884766612,
          "open_qty": 0.0037361152340888593,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "sma100_daily": {
          "policy": "gated",
          "bars": 181,
          "cycles": 2,
          "closed_cycles": 1,
          "open_cycles": 1,
          "profitable_closed_cycles": 0,
          "net_pnl": -30.352343078275617,
          "estimated_liquidation_net": -30.555398004984585,
          "net_liquidation": -30.555398004984585,
          "max_drawdown": 31.31714929429632,
          "turnover": 2472.239221415213,
          "drawdown_sampling": "bar_close",
          "fees": 0.7062268262793022,
          "funding": 0.5376866884766612,
          "open_qty": 0.0037361152340888593,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "price_cycles": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 4,
          "closed_cycles": 3,
          "open_cycles": 1,
          "profitable_closed_cycles": 1,
          "net_pnl": -13.666517648779315,
          "estimated_liquidation_net": -13.733393806453599,
          "net_liquidation": -13.733393806453599,
          "max_drawdown": 15.714950333739305,
          "turnover": 2088.5861957535176,
          "drawdown_sampling": "bar_close",
          "fees": 0.5856253739616885,
          "funding": 0.028265009620128505,
          "open_qty": 0.0012304898754923897,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "multifactor_without_correlations": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 7,
          "closed_cycles": 6,
          "open_cycles": 1,
          "profitable_closed_cycles": 2,
          "net_pnl": -3.933264729507272,
          "estimated_liquidation_net": -4.000140887181555,
          "net_liquidation": -4.000140887181555,
          "max_drawdown": 4.974030797032372,
          "turnover": 898.003264107319,
          "drawdown_sampling": "bar_close",
          "fees": 0.2385935667715131,
          "funding": 0.059112251339695276,
          "open_qty": 0.0012304898754923897,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "multifactor": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 6,
          "closed_cycles": 5,
          "open_cycles": 1,
          "profitable_closed_cycles": 2,
          "net_pnl": -8.638702785236013,
          "estimated_liquidation_net": -8.705578942910297,
          "net_liquidation": -8.705578942910297,
          "max_drawdown": 9.789806870375429,
          "turnover": 1293.4206781838732,
          "drawdown_sampling": "bar_close",
          "fees": 0.36439392552825917,
          "funding": 0.05616402486588384,
          "open_qty": 0.0012304898754923897,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        }
      },
      "sma100_daily_diagnostics": {
        "source_file": "BTCUSDT.json",
        "source_sha256": "748b9a3360384341948d4eb2e716d90071ea0327cc6839e96ec5ceb048116e59",
        "rows_in_file": 151,
        "rows_used": 150,
        "rows_discarded_unclosed_or_future": 1,
        "asof": "2026-10-29T07:00:00+00:00",
        "first_daily_start": "2026-06-01T00:00:00+00:00",
        "last_daily_start": "2026-10-28T00:00:00+00:00",
        "sma_days": 100,
        "band": 0.02,
        "crossings_count": 0,
        "crossings_in_execution_window": 0,
        "initial_allowed": true,
        "allowed_hours": 336,
        "first_regime_execution_time": "2026-09-09T01:00:00+00:00",
        "semantics": {
          "initial_state": "first complete 100-day close > SMA100; equality is OFF",
          "on_to_off": "daily close < SMA100 * (1-band), strict",
          "off_to_on": "daily close > SMA100 * (1+band), strict",
          "inside_band": "persist previous regime",
          "known_at": "daily start + 1 UTC day",
          "executes_at": "daily start + 1 UTC day + 1 hour",
          "signals": "start is permission level; OFF means stop_new and exit",
          "crossings_count": "state transitions available by last execution bar; initial state excluded"
        },
        "overlap_diagnostic": {
          "complete_days_compared": 13,
          "max_relative_close_gap": 0.0,
          "threshold": 0.01,
          "status": "within_threshold",
          "comparisons": [
            {
              "day": "2026-10-16",
              "daily_close": 81578.3,
              "hourly_aggregated_close": 81578.3,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-17",
              "daily_close": 81455.9,
              "hourly_aggregated_close": 81455.9,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-18",
              "daily_close": 82078.0,
              "hourly_aggregated_close": 82078.0,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-19",
              "daily_close": 81903.3,
              "hourly_aggregated_close": 81903.3,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-20",
              "daily_close": 82984.8,
              "hourly_aggregated_close": 82984.8,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-21",
              "daily_close": 84050.0,
              "hourly_aggregated_close": 84050.0,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-22",
              "daily_close": 81384.6,
              "hourly_aggregated_close": 81384.6,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-23",
              "daily_close": 81160.0,
              "hourly_aggregated_close": 81160.0,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-24",
              "daily_close": 80843.7,
              "hourly_aggregated_close": 80843.7,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-25",
              "daily_close": 80114.3,
              "hourly_aggregated_close": 80114.3,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-26",
              "daily_close": 80115.9,
              "hourly_aggregated_close": 80115.9,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-27",
              "daily_close": 80868.5,
              "hourly_aggregated_close": 80868.5,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-28",
              "daily_close": 81308.8,
              "hourly_aggregated_close": 81308.8,
              "relative_close_gap": 0.0
            }
          ]
        },
        "source_url": "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1d&startTime=1780272000000&endTime=1793318399999&limit=200",
        "retrieved_utc": "2026-10-29T12:38:27.196734+00:00"
      }
    },
    "ETHUSDT": {
      "hours": 336,
      "evaluation_start": "2026-10-21 18:00:00+00:00",
      "evaluation_end_exclusive": "2026-10-29 07:00:00+00:00",
      "missing_inputs": [
        "taker_buy",
        "taker_sell"
      ],
      "regime_diagnostics": {
        "definitions": {
          "flat": "ER24 < .3 from past data, descriptive only",
          "reversal": "prior 6h move >1 ATR and opposite following 6h move >1 ATR; hindsight label only"
        },
        "groups": {
          "causal_flat_er24_below_0_3": {
            "hours": 219,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 219,
                "median": 0.0006081277452310019
              },
              "funding_level": {
                "known": 219,
                "median": 0.005882
              },
              "funding_change_6h": {
                "known": 219,
                "median": -5.6000000000000494e-05
              },
              "flow_net6_z72": {
                "known": 214,
                "median": 0.11003113819660099
              },
              "book_mean6_z72": {
                "known": 214,
                "median": -0.26419937069925514
              },
              "liq_long_share6": {
                "known": 208,
                "median": 0.5824779688521161
              },
              "ls_accounts_change_6h": {
                "known": 219,
                "median": -0.003636367643383931
              },
              "wi2_change_6h": {
                "known": 219,
                "median": 1.3999999999999915
              },
              "corr_return_oi_change_24h": {
                "known": 219,
                "median": 0.1557892666130751
              },
              "corr_return_net_flow_24h": {
                "known": 219,
                "median": 0.8641317574325587
              },
              "corr_return_book_change_24h": {
                "known": 219,
                "median": 0.07139885299389688
              },
              "corr_return_liquidation_change_24h": {
                "known": 189,
                "median": -0.14666907931184894
              },
              "corr_cross_flow_oi_24h": {
                "known": 219,
                "median": 0.07401111170333585
              },
              "corr_cross_flow_book_24h": {
                "known": 219,
                "median": -0.08945040656065885
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 189,
                "median": -0.18110095856553052
              },
              "corr_cross_funding_oi_24h": {
                "known": 219,
                "median": 0.15748680775160429
              },
              "corr_cross_positioning_funding_24h": {
                "known": 219,
                "median": -0.21406211938515962
              }
            }
          },
          "retrospective_down_to_up_6h": {
            "hours": 27,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 27,
                "median": -3.6762926303168797e-06
              },
              "funding_level": {
                "known": 27,
                "median": 0.003759
              },
              "funding_change_6h": {
                "known": 27,
                "median": -0.0029259999999999998
              },
              "flow_net6_z72": {
                "known": 27,
                "median": -1.2359086768592518
              },
              "book_mean6_z72": {
                "known": 27,
                "median": 0.39771686739429013
              },
              "liq_long_share6": {
                "known": 27,
                "median": 0.922392333274045
              },
              "ls_accounts_change_6h": {
                "known": 27,
                "median": 0.04621490502993231
              },
              "wi2_change_6h": {
                "known": 27,
                "median": -18.10000000000001
              },
              "corr_return_oi_change_24h": {
                "known": 27,
                "median": 0.41656683974313186
              },
              "corr_return_net_flow_24h": {
                "known": 27,
                "median": 0.9215077154404154
              },
              "corr_return_book_change_24h": {
                "known": 27,
                "median": -0.08708044667435196
              },
              "corr_return_liquidation_change_24h": {
                "known": 22,
                "median": -0.2935691516590942
              },
              "corr_cross_flow_oi_24h": {
                "known": 27,
                "median": 0.38368006786330816
              },
              "corr_cross_flow_book_24h": {
                "known": 27,
                "median": -0.18272647382685903
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 22,
                "median": -0.35120240629592614
              },
              "corr_cross_funding_oi_24h": {
                "known": 27,
                "median": 0.3044976468473992
              },
              "corr_cross_positioning_funding_24h": {
                "known": 27,
                "median": -0.2843885725370577
              }
            }
          },
          "retrospective_up_to_down_6h": {
            "hours": 20,
            "independent_events": null,
            "feature_medians": {
              "oi_change_6h": {
                "known": 20,
                "median": -0.002759418978354411
              },
              "funding_level": {
                "known": 20,
                "median": 0.0069110000000000005
              },
              "funding_change_6h": {
                "known": 20,
                "median": 0.0011855000000000004
              },
              "flow_net6_z72": {
                "known": 20,
                "median": 1.2429175724639299
              },
              "book_mean6_z72": {
                "known": 20,
                "median": -0.8956664423459577
              },
              "liq_long_share6": {
                "known": 20,
                "median": 0.11566234510133314
              },
              "ls_accounts_change_6h": {
                "known": 20,
                "median": -0.006625654617653187
              },
              "wi2_change_6h": {
                "known": 20,
                "median": 6.399999999999999
              },
              "corr_return_oi_change_24h": {
                "known": 20,
                "median": 0.24671582070136436
              },
              "corr_return_net_flow_24h": {
                "known": 20,
                "median": 0.8515526522794603
              },
              "corr_return_book_change_24h": {
                "known": 20,
                "median": -0.04428489321735067
              },
              "corr_return_liquidation_change_24h": {
                "known": 20,
                "median": 0.03009672631537423
              },
              "corr_cross_flow_oi_24h": {
                "known": 20,
                "median": 0.1375308788824022
              },
              "corr_cross_flow_book_24h": {
                "known": 20,
                "median": -0.2226948171524094
              },
              "corr_cross_flow_liquidations_24h": {
                "known": 20,
                "median": 0.11785416534058085
              },
              "corr_cross_funding_oi_24h": {
                "known": 20,
                "median": 0.27313027544743274
              },
              "corr_cross_positioning_funding_24h": {
                "known": 20,
                "median": -0.1472945805053113
              }
            }
          }
        },
        "predictive_significance_established": false
      },
      "policies": {
        "continuous": {
          "policy": "continuous",
          "bars": 181,
          "cycles": 2,
          "closed_cycles": 1,
          "open_cycles": 1,
          "profitable_closed_cycles": 0,
          "net_pnl": -32.04249395033022,
          "estimated_liquidation_net": -32.445385580452246,
          "net_liquidation": -32.445385580452246,
          "max_drawdown": 42.38065397296068,
          "turnover": 4977.048408967403,
          "drawdown_sampling": "bar_close",
          "fees": 1.1036072363043532,
          "funding": 0.5586441689550812,
          "open_qty": 0.25624374537304473,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "sma100_daily": {
          "policy": "gated",
          "bars": 181,
          "cycles": 2,
          "closed_cycles": 1,
          "open_cycles": 1,
          "profitable_closed_cycles": 0,
          "net_pnl": -32.04249395033022,
          "estimated_liquidation_net": -32.445385580452246,
          "net_liquidation": -32.445385580452246,
          "max_drawdown": 42.38065397296068,
          "turnover": 4977.048408967403,
          "drawdown_sampling": "bar_close",
          "fees": 1.1036072363043532,
          "funding": 0.5586441689550812,
          "open_qty": 0.25624374537304473,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "price_cycles": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 6,
          "closed_cycles": 5,
          "open_cycles": 1,
          "profitable_closed_cycles": 2,
          "net_pnl": -41.180061693234514,
          "estimated_liquidation_net": -41.312745764117174,
          "net_liquidation": -41.312745764117174,
          "max_drawdown": 41.66281045953701,
          "turnover": 4965.265556662216,
          "drawdown_sampling": "bar_close",
          "fees": 1.4215354671978635,
          "funding": 0.17526729468451058,
          "open_qty": 0.08438860659383095,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "multifactor_without_correlations": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 9,
          "closed_cycles": 8,
          "open_cycles": 1,
          "profitable_closed_cycles": 3,
          "net_pnl": -21.08730729891373,
          "estimated_liquidation_net": -21.219991369796386,
          "net_liquidation": -21.219991369796386,
          "max_drawdown": 26.85052235368088,
          "turnover": 3784.8559406111453,
          "drawdown_sampling": "bar_close",
          "fees": 0.9495948514933495,
          "funding": 0.14483746499715464,
          "open_qty": 0.08438860659383095,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        },
        "multifactor": {
          "policy": "cycles",
          "bars": 181,
          "cycles": 6,
          "closed_cycles": 5,
          "open_cycles": 1,
          "profitable_closed_cycles": 2,
          "net_pnl": -29.992665328582678,
          "estimated_liquidation_net": -30.125349399465335,
          "net_liquidation": -30.125349399465335,
          "max_drawdown": 33.68494234885845,
          "turnover": 3375.896842220557,
          "drawdown_sampling": "bar_close",
          "fees": 0.9146384842658675,
          "funding": 0.12605347130594596,
          "open_qty": 0.08438860659383095,
          "funding_rates_supplied": true,
          "config": {
            "step_pct": 0.6,
            "target_pct": 1.4,
            "order_notional": 100.0,
            "capital_cap": 1000.0,
            "maker_fee": 0.00016,
            "taker_fee": 0.00048,
            "slippage": 0.0002,
            "profit_target": 5.0,
            "loss_limit": 30.0,
            "max_cycle_bars": 24,
            "cooldown_bars": 2
          }
        }
      },
      "sma100_daily_diagnostics": {
        "source_file": "ETHUSDT.json",
        "source_sha256": "ee7608c204eff291daf5d82a9ec594fe1d97bd8f537be2ad0ef678ffedf1bdf9",
        "rows_in_file": 151,
        "rows_used": 150,
        "rows_discarded_unclosed_or_future": 1,
        "asof": "2026-10-29T07:00:00+00:00",
        "first_daily_start": "2026-06-01T00:00:00+00:00",
        "last_daily_start": "2026-10-28T00:00:00+00:00",
        "sma_days": 100,
        "band": 0.02,
        "crossings_count": 0,
        "crossings_in_execution_window": 0,
        "initial_allowed": true,
        "allowed_hours": 336,
        "first_regime_execution_time": "2026-09-09T01:00:00+00:00",
        "semantics": {
          "initial_state": "first complete 100-day close > SMA100; equality is OFF",
          "on_to_off": "daily close < SMA100 * (1-band), strict",
          "off_to_on": "daily close > SMA100 * (1+band), strict",
          "inside_band": "persist previous regime",
          "known_at": "daily start + 1 UTC day",
          "executes_at": "daily start + 1 UTC day + 1 hour",
          "signals": "start is permission level; OFF means stop_new and exit",
          "crossings_count": "state transitions available by last execution bar; initial state excluded"
        },
        "overlap_diagnostic": {
          "complete_days_compared": 13,
          "max_relative_close_gap": 0.0,
          "threshold": 0.01,
          "status": "within_threshold",
          "comparisons": [
            {
              "day": "2026-10-16",
              "daily_close": 2422.49,
              "hourly_aggregated_close": 2422.49,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-17",
              "daily_close": 2401.58,
              "hourly_aggregated_close": 2401.58,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-18",
              "daily_close": 2409.12,
              "hourly_aggregated_close": 2409.12,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-19",
              "daily_close": 2407.02,
              "hourly_aggregated_close": 2407.02,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-20",
              "daily_close": 2447.78,
              "hourly_aggregated_close": 2447.78,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-21",
              "daily_close": 2472.74,
              "hourly_aggregated_close": 2472.74,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-22",
              "daily_close": 2388.11,
              "hourly_aggregated_close": 2388.11,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-23",
              "daily_close": 2386.55,
              "hourly_aggregated_close": 2386.55,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-24",
              "daily_close": 2357.64,
              "hourly_aggregated_close": 2357.64,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-25",
              "daily_close": 2328.58,
              "hourly_aggregated_close": 2328.58,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-26",
              "daily_close": 2323.45,
              "hourly_aggregated_close": 2323.45,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-27",
              "daily_close": 2349.29,
              "hourly_aggregated_close": 2349.29,
              "relative_close_gap": 0.0
            },
            {
              "day": "2026-10-28",
              "daily_close": 2358.55,
              "hourly_aggregated_close": 2358.55,
              "relative_close_gap": 0.0
            }
          ]
        },
        "source_url": "https://fapi.binance.com/fapi/v1/klines?symbol=ETHUSDT&interval=1d&startTime=1780272000000&endTime=1793318399999&limit=200",
        "retrieved_utc": "2026-10-29T12:38:27.513983+00:00"
      }
    }
  },
  "zero_coverage_features": {
    "BTCUSDT": [
      "flow_imbalance_6h",
      "flow_imbalance_24h",
      "flow_imbalance_change6",
      "liq_coin_long_sum6_z72",
      "liq_coin_short_sum6",
      "liq_coin_short_sum6_z72",
      "corr_return_liquidation_change_72h",
      "corr_cross_flow_liquidations_72h"
    ],
    "ETHUSDT": [
      "flow_imbalance_6h",
      "flow_imbalance_24h",
      "flow_imbalance_change6",
      "liq_coin_long_sum6_z72",
      "liq_coin_short_sum6_z72"
    ]
  }
}
```

