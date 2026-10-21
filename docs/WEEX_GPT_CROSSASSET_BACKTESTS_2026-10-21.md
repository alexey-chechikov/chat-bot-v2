# Золото, индексы и VIX: новые проверки на истории, 21.10.2026

Для Claude, репозиторий `alexey-chechikov/chat-bot-v2`, ветка `alexey/mac-2026-05-29`. Контекст действующего кода: `31c5c1f`; этот документ меняет только исследовательскую документацию. Запрос пользователя: найти варианты отдельной торговли, противовеса BTC/ETH и ручной торговли на 15 минутах, проверить расходы и просадку и передать результаты через обычный Git.

## Что получилось

Новые расчёты действительно выполнены: GLD и SPY на 15 минутах, дневной long/cash SMA200 на GLD/SPY/QQQ, диагностика постоянной доли VIXY и отдельно GLD рядом с BTC/ETH. Это не переименование прежних исследований.

| Задача | Результат | Решение по этому исследованию |
|---|---|---|
| Руками на 15 минутах: золото GLD | Пробой утреннего диапазона: контрольный участок −2,54% после расходов | Проверенный вариант отклонён; прибыльный ручной сетап не найден |
| Руками на 15 минутах: S&P 500 через SPY | Проверенный пробой: контрольный участок −0,90% после расходов | Проверенный вариант отклонён |
| Отдельная более медленная система | Дневной QQQ SMA200 положителен: на 2021–20.10.2026 CAGR 15,16%, close-DD 21,83%; 11 сделок | Кандидат для следующей проверки точного исполнения. Оснований запускать бота пока нет |
| Постоянный противовес через VIXY | На 2023+ хуже эквивалентного cash и по CAGR, и по DD | Постоянную долю VIXY этот тест не обосновывает |
| Золото как противовес | GLD помогает доходности части портфеля, но в 10 худших криптомесяцах лучше cash лишь 4 раза | Возможная диверсификация; системная защита от падения крипты не доказана |

**Готовая к запуску новая система не подтверждена.** Наиболее полезное направление следующего исследования из проверенных здесь — дневной QQQ SMA200; это относительный приоритет исследования, не торговый сигнал. Доходность всех трёх дневных фильтров ниже обычного удержания соответствующего ETF. Уменьшение просадки измерено на дневных закрытиях, но не делает систему гарантированной страховкой.

Везде только публичные рыночные данные и синтетические счета. Балансы пользователя, частный учёт, ключи, активные ордера и сырые аккаунтные данные сюда не включены. Торговый код, процессы и настройки не менялись; публикация исследования не разрешает Claude запускать новую торговлю.

## Как читать результаты

- История обрезана по завершённый день **20.10.2026**. Внутридневной публичный источник дал лишь 41 полную сессию — это короткий скрининг. Дневной источник позволяет длинный тест с 2010 года. Данные скачаны 21.10; поздние строки, которые Yahoo добавляет сверх запроса, исключены.
- Правила и границы частей записаны до просмотра результатов конкретного эксперимента. Это ретроспективные хронологические части, а не исторически зарегистрированное исследование и не будущий out-of-sample. Ни часы, ни SMA, ни цели на результатах не оптимизировались.
- Расходы — заданные сценарии, не подтверждённый тариф выбранного брокера. 1 bp = 0,01% номинала. 6 bp **за круг** на 15м нельзя путать с 10 bp **на сторону** в дневном тесте. Удвоенные расходы проверены отдельно. Доходность cash принята нулевой: проценты денежного фонда сделали бы cash-контроль сильнее в периоды положительных ставок.
- GLD — доли золотого траста, SPY — ETF S&P 500, QQQ — ETF Nasdaq-100. Это исполнимые классы инструментов в подходящем брокерском счёте, но доступность конкретному пользователю не проверялась. Результаты не переносятся автоматически на XAUUSDT, GC/MGC, ES/MES, NQ/MNQ, CFD или токены биржи. Отличаются сессии, лот, финансирование, маржа и исполнение.
- VIXY содержит реальные краткосрочные **фьючерсы** VIX; это не покупка spot VIX. Roll и расходы фонда уже отражаются в исторических ценах, второй раз они не вычитаются. Сам VIX — индекс, а не бесплатная страховка. [Описание VIXY у эмитента](https://www.proshares.com/our-etfs/strategic/vixy).
- Источники идентификации инструментов: [GLD](https://www.spdrgoldshares.com/usa/gld/), [SPY](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy), [QQQ](https://www.invesco.com/qqq-etf/en/home.html), [часы и календарь NYSE](https://www.nyse.com/markets/hours-calendars). Рыночные свечи получены из Yahoo chart; URL, SHA256 и QA сохранены ниже.

## 1. Ручная торговля на 15 минутах

Оба кандидата: диапазон первых 30 минут Нью-Йорка, первое завершённое закрытие 15м вне диапазона, вход на следующем open, стоп за противоположной границей, цель 2R, не более одной сделки в день, без ночной позиции. Условный риск 0,25% и предел номинала 1x. В отличие от дневного теста здесь не вкладывается весь капитал в каждую сделку. Дробные доли и внутридневной шорт — допущения; заём и минимальные комиссии конкретного брокера не подтверждены.

GLD: сигнальные бары с началом 10:00–11:30, выход оставшейся позиции на close последнего бара 15:45. SPY: сигналы до 12:00, выход на open 15:45. Это два родственных, но не идентичных правила; их результат не является чистым экспериментом замены одного актива другим. Цены вне запрошенного интервала исключены; 1 066 баров и 41 полная сессия у каждого инструмента. Пропущенное 07.09 — официальный праздник NYSE.

| Инструмент / участок | Сделок | Доходность, 6 bp круг | Доходность, 12 bp круг | PF, база | Просадка, база |
|---|---:|---:|---:|---:|---:|
| GLD, весь 24.08–20.10 | 34 | −2,990% | −3,416% | 0,321 | 3,783% по закрытиям 15м |
| GLD, контроль 22.09–20.10 | 18 | −2,537% | −2,696% | 0,115 | 2,628% по закрытиям 15м |
| SPY, весь 24.08–20.10 | 38 | −2,700% | −4,007% | 0,444 | 3,396% по закрытиям сессий; OHLC-граница 3,706% |
| SPY, контроль 28.09–20.10 | 17 | −0,898% | −1,514% | 0,581 | 1,608% по закрытиям сессий; OHLC-граница 1,774% |

У GLD первые 20 сессий, у SPY первые 24 — техническая/диагностическая часть без подбора; контрольные части стартуют с нового одинакового условного капитала. Малые контрольные N не позволяют вывод обо всём классе стратегий. При этом отрицательный результат не даёт основания рекомендовать эти правила как готовые ручные входы. Годовая доходность из этих двух месяцев не рассчитывается.

Хронология расходов сохранена: GLD сразу зафиксирован 6/12 bp. SPY сначала зафиксирован 4/8 bp и уже при них убыточен; 6/12 добавлены после первого расчёта как более консервативная чувствительность для общего сравнения. Структура стресс-расходов у GLD 1 bp комиссии +5 bp slippage на сторону; у SPY 2+4. SPY дополнительно округляет исполнение неблагоприятно к $0,01. Доходности сопоставимы по порядку заданной стоимости круга, но модели не полностью одинаковы.

Входы причинны. При двух касаниях в свече — стоп, разрыв через стоп — худший open; известное событие на open предшествует остальным экстремумам свечи. Exact tick-DD не реконструируется. У SPY OHLC-DD — консервативная верхняя граница модели с допустимым неблагоприятным порядком экстремумов; у GLD дополнительный adverse-DD считается относительно прошлого close-peak и верхней границей полной тиковой DD не является. Разные частоты close-DD явно указаны, смешивать их как равные оценки нельзя. SPY buy-and-hold с дивидендом и расходами 6 bp за круг за весь период +0,739%, cash 0%; benchmark несёт ночной риск.

## 2. Отдельная дневная система: SMA200 long/cash

Правило зафиксировано до скачивания/расчёта: предыдущий завершённый daily close выше своей SMA200 → держать long; иначе cash. Изменение позиции на следующем open, без плеча и шорта. Сохраняются доли до выхода; в конце каждого отчётного отрезка позиция закрывается с расходами. Это медленная система с переносом через ночь, не сетка и не ручной сетап на 15 минутах. Adjusted OHLC учитывают дивиденды и сплиты как total-return proxy; это не буквальный брокерский учёт дивидендных выплат.

Заранее заданы development 2010–2015, validation 2016–2020, holdout 2021–20.10.2026, отдельно полный 2010–20.10.2026. Для SMA используется предыдущая история с 2008; каждый отрезок стартует с cash. База 10 bp на каждую торговую сторону, стресс 20; стоимость фондов уже в ценах, налог/FX/особенности брокера не моделируются. Полный дневной номинал 1x, поэтому размеры процентов DD не следует напрямую ранжировать с 15м-стратегией с риском 0,25% на сделку.

| ETF / период | SMA200 CAGR, база | SMA200 CAGR, стресс | SMA200 close-DD, база | Buy-and-hold CAGR, база | Buy-and-hold close-DD, база | Сделок SMA200 |
|---|---:|---:|---:|---:|---:|---:|
| GLD, 2010–20.10.2026 | 5.47% | 4.61% | 35.92% | 7.62% | 45.56% | 69 |
| GLD, 2021–20.10.2026 | 9.22% | 8.10% | 25.49% | 13.39% | 26.40% | 30 |
| SPY, 2010–20.10.2026 | 8.35% | 7.76% | 24.89% | 14.11% | 33.72% | 46 |
| SPY, 2021–20.10.2026 | 11.50% | 10.89% | 20.37% | 14.65% | 24.50% | 16 |
| QQQ, 2010–20.10.2026 | 11.55% | 10.88% | 27.08% | 18.72% | 35.12% | 51 |
| QQQ, 2021–20.10.2026 | 15.16% | 14.72% | 21.83% | 15.89% | 35.12% | 11 |

Здесь CAGR — геометрическая годовая доходность всего условного капитала, не ежедневный заработок. Полные доходности, все три хронологические части, годовые результаты, число закрытий и метрики лежат в JSON приложения. Close-DD включает плавающий результат и стартовый капитал. Дополнительная оценка до дневного low от прошлого close-peak отдельно сохранена в JSON; она не учитывает все внутридневные пики и не выдаётся за максимальную тиковую просадку.

Почему приоритет QQQ: на контрольном отрезке доходность 15,16% годовых близка к 15,89% buy-and-hold, при close-DD 21,83% против 35,12%. Это реально посчитанный компромисс доходности и просадки, но **всего 11 контрольных сделок**, нет доказанной статистической устойчивости. Во всём периоде SMA200 существенно отстаёт от удержания: 11,55% против 18,72% CAGR. Выбор QQQ как направления сделан после сравнения трёх ETF, это ещё один источник selection bias. Нельзя считать его независимым подтверждением преимущества над рынком.

GLD не дал очевидного превосходства как отдельный бот: контрольный SMA200 CAGR 9,22%, close-DD 25,49%; удержание 13,39% и 26,40%. Небольшое уменьшение DD куплено значительной потерей доходности. SPY SMA200 также положителен, но отстаёт от удержания. Исследование не тестировало соседние параметры, другие рыночные источники и точный контракт исполнения, поэтому к реальным деньгам ни один вариант не допущен.

## 3. Противовес BTC/ETH: VIXY и золото

Проверены фиксированные доли с ежемесячной ребалансировкой: 50% BTC/50% ETH; 45/45/10% cash; 45/45/10% VIXY. Доля GLD 45/45/10 добавлена **после** просмотра VIXY как отдельная exploratory-диагностика, без перебора размера доли. ETH в публичной серии начинается 09.11.2017; общий тест с 10.11.2017. Части: development до конца 2019, validation 2020–2022, final с 2023. База 10 bp на сторону фактического оборота, стресс 20. Начальный вход, ребалансировки и конечная ликвидация оплачены; cash без процентов.

**Существенный предел:** это асинхронная диагностика дневной оценки, а не буквально исполнимая синхронная симуляция. На американскую дату D VIXY/GLD оценены по close D, крипта — по последнему полностью завершённому UTC-дню D−1. Воскресный крипторезультат попадает в понедельник, не теряется; но все инструменты одновременно по этим ценам ребалансировать нельзя. Дневная корреляция и timing искажены. Месячное сравнение полезнее, однако также не заменяет синхронное исполнение. **Это buy-and-hold proxy экспозиции, не P&L действующих сеток BTC/ETH. Защита их капитала данным тестом не установлена.**

| Период / состав | CAGR, база | Close-DD, база | CAGR, стресс | Close-DD, стресс |
|---|---:|---:|---:|---:|
| 10.11.2017–20.10.2026, BTC/ETH 50/50 | 33.38% | 86.73% | 33.26% | 86.74% |
| 10.11.2017–20.10.2026, 90% crypto +10% cash | 32.83% | 82.99% | 32.71% | 83.01% |
| 10.11.2017–20.10.2026, 90% crypto +10% VIXY | 29.97% | 81.25% | 29.82% | 81.28% |
| 2023–20.10.2026, BTC/ETH 50/50 | 37.04% | 60.19% | 36.91% | 60.20% |
| 2023–20.10.2026, 90% crypto +10% cash | 34.40% | 55.97% | 34.27% | 55.98% |
| 2023–20.10.2026, 90% crypto +10% VIXY | 27.68% | 58.21% | 27.53% | 58.23% |

GLD exploratory: весь общий период CAGR34,52% / DD83,07% против cash32,83% /82,99%; final2023+ CAGR37,40% /DD55,65% против cash34,40% /55,97%. При стресс-расходах final GLD37,25% /55,67% против cash34,27% /55,98%. Улучшение доходности не тождественно страховке.

У VIXY на всём периоде улучшение DD относительно cash лишь около1,74 п.п. ценой примерно2,85 п.п. CAGR; на финальном участке VIXY уже уступает cash по обеим метрикам. VIXY сам по себе на общем интервале потерял99,27% цены, около−42,32% CAGR до внешних торговых расходов; это включает фактический roll/expense drag продукта. Сплиты проверены: искусственные скачки от reverse split в доходность не попали. Результат не является сигналом шортить VIXY: шорт волатильности не исследовался.

Месячная корреляция proxy-криптодоходности с VIXY −0,274, с GLD +0,105. Эти числа не дают ни постоянной отрицательной зависимости, ни доказанной защиты сеток. На десяти худших полных криптомесяцах VIXY лучше cash 7/10, в среднем на1,11 п.п., но значительная часть эффекта пришлась на март2020. GLD лучше cash4/10, средний эффект около−0,01 п.п. Ни постоянныйVIX, ни золото не дают здесь достаточного основания для нового защитного бота.

Десять худших месяцев, включая месяцы где хедж не помог:

| Month | Crypto100 | Cashcontrol | GLDportfolio | GLDstandalone | GLD-minus-cash |
|---|---:|---:|---:|---:|---:|
| 2022-06 | -40.78% | -36.72% | -36.89% | -1.57% | -0.17pp |
| 2018-03 | -37.51% | -33.84% | -33.78% | 0.63% | +0.06pp |
| 2018-11 | -36.48% | -32.84% | -32.83% | 0.34% | +0.00pp |
| 2020-03 | -34.17% | -30.86% | -30.90% | -0.22% | -0.04pp |
| 2018-08 | -26.28% | -23.80% | -23.99% | -2.14% | -0.19pp |
| 2022-05 | -26.14% | -23.57% | -23.88% | -3.26% | -0.30pp |
| 2022-01 | -24.70% | -22.21% | -22.38% | -1.68% | -0.17pp |
| 2026-02 | -24.08% | -21.76% | -20.88% | 8.72% | +0.87pp |
| 2025-02 | -24.02% | -21.77% | -21.57% | 1.82% | +0.20pp |
| 2018-06 | -22.37% | -20.12% | -20.48% | -3.61% | -0.37pp |

Таблица VIXY по тем же месяцам целиком сохранена ниже в results.json/CSV. Имеющийся cash-контроль обязателен: уменьшение криптодоли само по себе сокращает часть риска. Без него рост хеджа можно ошибочно принять за полезность страховки.

## 4. Что передать в работу Claude

1. Не запускать GLD/SPY OR30 и постоянный VIXY на основании этих результатов. Не подбирать новые часы/тейки на этих же 18/17 контрольных сделках и не называть такую подгонку новым подтверждением.
2. Если продолжать именно прибыльную отдельную систему, следующий предметный кандидат — **QQQ daily SMA200**. Сначала воспроизвести приложение и проверить точный доступный инструмент/лот/исполнение следующего открытия/стоимость, затем независимую более раннюю историю и чувствительность к соседним периодам без выбора одного красивого пика. 11 holdout-сделок не выполняют строгий допуск новой торговой системы. Это следующий этап исследования, здесь он не объявляется выполненным.
3. Для реального противовеса получить приватно синхронную equity существующих сеток, включая открытый P&L, funding и комиссии, и сопоставить с исполнимыми котировками хеджа в одно время. Не публиковать этот учёт. Наш proxy-портфель не заменяет этот шаг. Для VIX отдельный тактический тайминг или опционы в этом отчёте не проверены.
4. Для ручного M15 другой семейство правил, например Asia/FVG/footprint, потребует конкретного фьючерса/ленты/сессий и заранее однозначного сигнала. GLD regular-session OR30 не является тестом Asia/FVG. Из старых исследований нельзя выдать положительный gross/малое число сделок за готовый сетап. Старый XAU grid с положительным общим P&L имел заметную просадку и слабое продолжение второй половины; это не допуск на автоматический запуск.

Никаких действий с защитой второй копии, Telegram polling, F5, рестартами или живыми сетками для этой передачи не требуется.

## 5. Проверка расчётов и воспроизведение

Для исследования пройдены: 7 граничных проверок GLD15; 6 проверок SPY15; причинность и prefix invariance SMA200, next-open gap, знак расходов, сверка P&L; независимо пересчитаны DD всех72 дневных equity и24 closed-form buy-and-hold; VIX fixed-point ребаланс сверён независимым методом долей,18 простых точных cost-identities; все32 портфельных CSV сходятся по сумме компонентов с equity, включая терминальную ликвидацию. Найденная при review ошибка только представления terminal ledger исправлена: позиции0, cash=finalequity, доходности не менялись. Смысл дополнительной daily-low DD уточнён после расчёта, ордера и значения не менялись.

Полный тестовый набор торгового бота повторно не запускался: торговый код не менялся. Границы и негативные случаи исследовательских движков проверены отдельно. Наличие тестов не устраняет ограничения источника, короткой выборки и модели исполнения.

Внизу находятся полные исходники, протоколы, метрики и SHA. Они опубликованы внутри **одного Markdown**, чтобы Claude получил конкретный проверяемый результат одним docs-only коммитом. Не требуется менять рабочую ветку бота. Для восстановления файлов скопировать приложение `extract_report.py`, затем:

```text
python extract_report.py WEEX_GPT_CROSSASSET_BACKTESTS_2026-10-21.md crossasset_replay
python -m pip install numpy pandas tzdata
python crossasset_replay/gold15/fetch_data.py
python crossasset_replay/gold15/run_gold15.py
python -m unittest discover -s crossasset_replay/gold15 -p test_engine.py -v
python crossasset_replay/index15/download.py
python crossasset_replay/index15/check_engine.py
python crossasset_replay/index15/backtest.py --cost-scheme frozen4_8
python crossasset_replay/index15/backtest.py --cost-scheme comparable6_12
python crossasset_replay/daily/run_daily.py --download
python crossasset_replay/vix/download.py
python crossasset_replay/vix/analyze.py
python crossasset_replay/vix/check_engine.py
python crossasset_replay/vix/download_gld.py
python crossasset_replay/vix/analyze_gld_diagnostic.py
```

Повторная загрузка публичного источника может дать иные последние служебные строки или исправленные adjusted prices; сравнивать сначала фильтрованные бары и метрики. **Yahoo15m имеет короткий срок хранения:** спустя него фиксированный старый интервал по API станет недоступен. Raw/CSV сохранены локально в `research/crossasset_20261021/`; целиком в публичный Git они не копируются. Поэтому этот один документ содержит код, полные итоговые числа и контрольные SHA, но не обещает бессрочную самодостаточность без архива рыночных данных. Исходные ответы не являются аккаунтными данными. Для более позднего точного replay Claude потребуется сохранённый публичный raw-архив.

## Приложение A. Исходные файлы и протоколы

Каждый блок `### FILE` можно извлечь приложенным скриптом в отдельную новую директорию. Ничего из этого не является настройкой активного бота.

### FILE `extract_report.py`

````python
"""Extract explicitly named research files from the one-file Git handoff.

Usage: python extract_report.py REPORT.md OUTPUT_DIRECTORY
Only research scripts/text/results are extracted, no commands are run.
"""
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
root = pathlib.Path(sys.argv[2]).resolve()
pattern = r'^### FILE `([^`]+)`\n\n````[^\n]*\n(.*?)^````\s*$'
count = 0
for name,body in re.findall(pattern,source,re.M|re.S):
    relative = pathlib.PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe extracted path')
    destination = root.joinpath(*relative.parts).resolve()
    destination.relative_to(root)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(body,encoding='utf-8',newline='\n')
    count += 1
print('Extracted',count,'files into',root)
````

### FILE `gold15/PROTOCOL.md`

````text
# Frozen gold 15-minute screening protocol — 2026-10-21

Created before downloading or inspecting strategy returns. One candidate only; no optimization.

Instrument: GLD, a US-listed gold ETF, direct Yahoo Finance 15m OHLCV; no claim about WEEX XAUUSDT, CFD or futures execution. This uses a liquid regular-session gold instrument without futures rollover. It tests a fixed session breakout as a distinct rule from the earlier failed prior-day-low reclaim idea. It does not implement the Asia/FVG specification because GLD has no complete Asia session.

Requested sample: 2026-08-24 through 2026-10-20 inclusive (Yahoo intraday availability limits the sample to roughly 60 days). End-exclusive request 2026-10-21. Do not substitute a historical window after seeing results. First 20 complete sessions are calibration/sanity only, remainder chronological holdout. Rule identical on both; no fitting. If the requested sample is unavailable, report that limitation and attempt a clearly labelled alternate public source only before viewing its returns.

Session: America/New_York, IANA DST; use 09:30–16:00 regular hours only, requiring all 26 consecutive 15m bars per date. Reject incomplete dates. First two bars define the 09:30–10:00 opening range. The first completed bar starting 10:00 through 11:30 whose close is above range high or below range low gives one directional signal; enter next 15m bar open (latest entry 11:45). At most one trade per day. Long stop at range low, short stop at range high; target at 2 times initial raw entry-to-stop distance. Do not enter if next open is already on the wrong side of the stop. No post-signal filters.

Fixed risk: 0.25% of current $10,000 synthetic equity per trade, fractional shares, max 1x notional. This is a comparison account, not user funds. Long and short allowed in simulation; borrow permission/availability unverified. Risk sizing includes entry/exit adverse slippage and fees. Stop/target unadjusted levels fixed from observed range and next open. Flatten at close of 15:45 bar. This hypothetical strategy requires marketable execution, no future-bar confirmation.

Base costs per side: adverse spread+slippage 2 basis points and commission 1 basis point (6 bp round trip). Stress: adverse spread+slippage 5 bp + commission 1 bp each side (12 bp round trip). Costs are explicit scenarios, not a broker quote. No overnight carry. Same-bar stop and target => stop first; adverse stop gaps fill at worse open; target gap fills at target (conservative); stop/target execution occurs after entry. Full bar mark-to-market equity and conservative adverse excursion drawdown both recorded; never report closed-trades-only drawdown as full drawdown.

Report: source, timestamp/hash, sample coverage and rejected dates, calibration/holdout n, net expectancy R, profit factor, return, close-marked and adverse-bar max drawdown, base and stress costs, long/short split. Short sample can screen out a weak candidate, cannot qualify deployment. Repro script, raw response and trade ledger stay local; root report can publish only public data-derived summary and code.
````

### FILE `gold15/fetch_data.py`

````python
"""Fetch the fixed public GLD intraday window; never touches an account."""
import pathlib
import urllib.request

p = pathlib.Path(__file__).resolve().parent
url = 'https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1787529600&period2=1792540800&interval=15m&includePrePost=false'
request = urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(request,timeout=45) as response:
    (p/'yahoo_raw.json').write_bytes(response.read())
````

### FILE `gold15/run_gold15.py`

````python
"""Frozen one-candidate GLD opening-range screen. Public raw data only.

Run: python research/crossasset_20261021/gold15/run_gold15.py
No network, no bot imports, no trading operations.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
START, END = "2026-08-24", "2026-10-20"
CALIBRATION_DAYS = 20
INITIAL = 10000.0
RISK = 0.0025
COSTS = {"base": {"fee": 0.0001, "slip": 0.0002},
         "stress": {"fee": 0.0001, "slip": 0.0005}}


def load_data():
    raw = (ROOT / "yahoo_raw.json").read_bytes()
    response = json.loads(raw)["chart"]["result"][0]
    df = pd.DataFrame(response["indicators"]["quote"][0],
                      index=pd.to_datetime(response["timestamp"], unit="s", utc=True))
    df.index.name = "timestamp_utc"
    local = df.index.tz_convert("America/New_York")
    requested = (local.strftime("%Y-%m-%d") >= START) & (local.strftime("%Y-%m-%d") <= END)
    excluded = df.loc[~requested].index.astype(str).tolist()
    df = df.loc[requested].copy()
    df["local"] = df.index.tz_convert("America/New_York")
    df["date"] = df["local"].dt.strftime("%Y-%m-%d")
    complete, rejected = {}, {}
    for date, group in df.groupby("date", sort=True):
        regular = group.loc[(group["local"].dt.strftime("%H:%M") >= "09:30") &
                            (group["local"].dt.strftime("%H:%M") <= "15:45")]
        expected = pd.date_range(date + " 09:30", periods=26, freq="15min", tz="America/New_York")
        checks = {
            "missing_or_duplicate_timestamp": not regular["local"].tolist() == expected.tolist(),
            "bad_ohlcv": not np.isfinite(regular[["open", "high", "low", "close", "volume"]].to_numpy()).all(),
            "invalid_ohlc": bool(((regular["low"] > regular[["open", "close"]].min(axis=1)) |
                                  (regular["high"] < regular[["open", "close"]].max(axis=1)) |
                                  (regular["low"] <= 0) | (regular["volume"] < 0)).any()),
        }
        if any(checks.values()):
            rejected[date] = [k for k, v in checks.items() if v]
        else:
            complete[date] = regular
    meta = {"sha256": hashlib.sha256(raw).hexdigest(), "raw_rows": len(response["timestamp"]),
            "in_window_rows": len(df), "regular_complete_rows": sum(len(v) for v in complete.values()),
            "complete_sessions": len(complete), "first_date": min(complete), "last_date": max(complete),
            "rejected_dates": rejected, "excluded_outside_window_timestamps": excluded,
            "missing_business_days": sorted(set(pd.bdate_range(START, END).strftime("%Y-%m-%d")) - set(complete)),
            "timezone": "America/New_York (IANA DST)", "observed_utc_offsets": sorted(set(str(t.utcoffset()) for t in df["local"])),
            "raw_response_has_adjclose": "adjclose" in response["indicators"],
            "instrument": {k: response["meta"].get(k) for k in ("symbol", "currency", "exchangeName", "instrumentType", "dataGranularity")}}
    df.drop(columns=["local"]).to_csv(ROOT / "bars_filtered.csv")
    return complete, meta


def signal_for_day(bars):
    hi, lo = float(bars.iloc[:2]["high"].max()), float(bars.iloc[:2]["low"].min())
    for i in range(2, 9):  # 10:00 ... 11:30 closes, entry next open <= 11:45.
        close = float(bars.iloc[i]["close"])
        direction = 1 if close > hi else (-1 if close < lo else 0)
        if direction:
            entry_idx = i + 1
            entry = float(bars.iloc[entry_idx]["open"])
            stop = lo if direction == 1 else hi
            if direction * (entry - stop) <= 0:
                return None
            return {"signal_index": i, "entry_index": entry_idx, "direction": direction,
                    "entry_raw": entry, "stop": stop,
                    "target": entry + direction * 2 * abs(entry - stop),
                    "opening_range_high": hi, "opening_range_low": lo}
    return None


def exit_for_bar(bar, direction, stop, target):
    op, hi, lo = (float(bar[k]) for k in ("open", "high", "low"))
    if direction == 1:
        if op <= stop:
            return op, "stop_gap"
        if op >= target:
            return target, "target_gap"
        if lo <= stop:
            return stop, "stop"  # Also overrides target when both touch.
        if hi >= target:
            return target, "target"
    else:
        if op >= stop:
            return op, "stop_gap"
        if op <= target:
            return target, "target_gap"
        if hi >= stop:
            return stop, "stop"
        if lo <= target:
            return target, "target"
    return None, None


def execute_trade(bars, signal, equity, cost):
    d, raw, stop, target = (signal[k] for k in ("direction", "entry_raw", "stop", "target"))
    fee, slip = cost["fee"], cost["slip"]
    entry = raw * (1 + d * slip)
    stop_fill = stop * (1 - d * slip)
    unit_risk = d * (entry - stop_fill) + fee * (entry + stop_fill)
    quantity = min(equity * RISK / unit_risk, equity / entry)
    planned_risk = quantity * unit_risk
    entry_fee = quantity * entry * fee
    marks, adverse_marks = [], []
    for i in range(signal["entry_index"], len(bars)):
        bar = bars.iloc[i]
        exit_raw, reason = exit_for_bar(bar, d, stop, target)
        if exit_raw is None and i == len(bars) - 1:
            exit_raw, reason = float(bar["close"]), "session_close"
        if exit_raw is None:
            close = float(bar["close"])
            mark = equity + quantity * d * (close - entry) - entry_fee
            adverse_raw = float(bar["low"] if d == 1 else bar["high"])
        else:
            exit_fill = exit_raw * (1 - d * slip)
            exit_fee = quantity * exit_fill * fee
            net = quantity * d * (exit_fill - entry) - entry_fee - exit_fee
            mark = equity + net
            # If exit occurs, stop bounds adverse movement before fill. For a target
            # or session close, bar extreme remains possible before the exit.
            if reason in ("stop", "stop_gap", "target_gap"):
                adverse_raw = exit_raw
            else:
                adverse_raw = float(bar["low"] if d == 1 else bar["high"])
        marks.append((str(bars.index[i]), mark))
        adverse = equity + quantity * d * (adverse_raw * (1 - d * slip) - entry) - entry_fee
        adverse_marks.append((str(bars.index[i]), min(mark, adverse)))
        if exit_raw is not None:
            return {**signal, "entry_time": str(bars.index[signal["entry_index"]]),
                    "signal_time": str(bars.index[signal["signal_index"]]),
                    "exit_time": str(bars.index[i]), "entry_fill": entry,
                    "exit_raw": exit_raw, "exit_fill": exit_fill, "exit_reason": reason,
                    "shares": quantity, "planned_risk": planned_risk, "net_pnl": net,
                    "net_r": net / planned_risk, "total_fees": entry_fee + exit_fee,
                    "slippage_cost": quantity * (abs(entry - raw) + abs(exit_fill - exit_raw)),
                    "start_equity": equity, "end_equity": mark}, marks, adverse_marks
    raise AssertionError("Session must close every position")


def max_drawdown(points):
    peak, worst = points[0], 0.0
    for equity in points:
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return 100 * worst


def run_segment(days, costs):
    equity, trades, path, adverse_path = INITIAL, [], [INITIAL], [INITIAL]
    close_peak, adverse_dd = INITIAL, 0.0
    for date, bars in days.items():
        signal = signal_for_day(bars)
        if signal is None:
            continue
        trade, marks, adverse_marks = execute_trade(bars, signal, equity, costs)
        trades.append({"date": date, **trade})
        for (_, close), (_, adverse) in zip(marks, adverse_marks):
            adverse_dd = max(adverse_dd, (close_peak - adverse) / close_peak)
            close_peak = max(close_peak, close)
            path.append(close)
            adverse_path.append(adverse)
        equity = trade["end_equity"]
    wins = sum(max(t["net_pnl"], 0) for t in trades)
    losses = -sum(min(t["net_pnl"], 0) for t in trades)
    summary = {"start": min(days), "end": max(days), "sessions": len(days), "trades": len(trades),
               "longs": sum(t["direction"] == 1 for t in trades), "shorts": sum(t["direction"] == -1 for t in trades),
               "wins": sum(t["net_pnl"] > 0 for t in trades), "net_pnl": equity - INITIAL,
               "return_pct": 100 * (equity / INITIAL - 1),
               "expectancy_net_r": float(np.mean([t["net_r"] for t in trades])) if trades else None,
               "profit_factor": wins / losses if losses else None,
               "max_dd_close_mtm_pct": max_drawdown(path),
               "max_dd_adverse_from_prior_close_peak_pct": 100 * adverse_dd,
               "fees": sum(t["total_fees"] for t in trades),
               "slippage_cost": sum(t["slippage_cost"] for t in trades),
               "planned_risk_mean_usd": float(np.mean([t["planned_risk"] for t in trades])) if trades else None}
    return summary, trades


def main():
    days, quality = load_data()
    dates = list(days)
    assert len(dates) > CALIBRATION_DAYS
    segments = {"calibration": {d: days[d] for d in dates[:CALIBRATION_DAYS]},
                "holdout": {d: days[d] for d in dates[CALIBRATION_DAYS:]}, "all": days}
    output = {"protocol_sha256": hashlib.sha256((ROOT / "PROTOCOL.md").read_bytes()).hexdigest(),
              "quality": quality, "costs_per_side": COSTS, "initial_synthetic_equity": INITIAL,
              "results": {}}
    for cost_name, cost in COSTS.items():
        output["results"][cost_name] = {}
        for segment_name, segment_days in segments.items():
            summary, trades = run_segment(segment_days, cost)
            output["results"][cost_name][segment_name] = summary
            pd.DataFrame(trades).to_csv(ROOT / f"trades_{cost_name}_{segment_name}.csv", index=False)
    (ROOT / "results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
````

### FILE `gold15/test_engine.py`

````python
"""Small independent boundary checks for the new research simulator."""
import unittest
import pandas as pd

from run_gold15 import exit_for_bar, signal_for_day, execute_trade, COSTS


def bars():
    frame = pd.DataFrame({"open": [100.] * 26, "high": [101.] * 26,
                          "low": [99.] * 26, "close": [100.] * 26,
                          "volume": [100.] * 26},
                         index=pd.date_range("2026-08-24 09:30", periods=26,
                                             freq="15min", tz="America/New_York"))
    return frame


class EngineChecks(unittest.TestCase):
    def test_both_touched_long_is_stop(self):
        self.assertEqual(exit_for_bar({"open": 100, "high": 105, "low": 95}, 1, 98, 104), (98, "stop"))

    def test_both_touched_short_is_stop(self):
        self.assertEqual(exit_for_bar({"open": 100, "high": 105, "low": 95}, -1, 102, 96), (102, "stop"))

    def test_adverse_stop_gap(self):
        self.assertEqual(exit_for_bar({"open": 90, "high": 100, "low": 85}, 1, 95, 110), (90, "stop_gap"))
        self.assertEqual(exit_for_bar({"open": 110, "high": 115, "low": 100}, -1, 105, 90), (110, "stop_gap"))

    def test_target_gap_not_improved(self):
        self.assertEqual(exit_for_bar({"open": 110, "high": 115, "low": 90}, 1, 95, 105), (105, "target_gap"))
        self.assertEqual(exit_for_bar({"open": 90, "high": 115, "low": 85}, -1, 105, 95), (95, "target_gap"))

    def test_signal_only_after_opening_range_close_and_next_bar_entry(self):
        frame = bars()
        frame.iloc[2, frame.columns.get_loc("close")] = 102
        signal = signal_for_day(frame)
        self.assertEqual(signal["signal_index"], 2)
        self.assertEqual(signal["entry_index"], 3)
        frame.iloc[4:, frame.columns.get_loc("close")] = 9000
        self.assertEqual(signal_for_day(frame), signal)

    def test_stop_risk_includes_costs(self):
        frame = bars()
        signal = {"direction": 1, "entry_raw": 100., "stop": 98., "target": 104.,
                  "signal_index": 2, "entry_index": 3}
        frame.iloc[3, frame.columns.get_loc("low")] = 97.
        trade, _, _ = execute_trade(frame, signal, 10000., COSTS["base"])
        self.assertAlmostEqual(trade["net_r"], -1., places=12)
        self.assertLessEqual(trade["shares"] * trade["entry_fill"], 10000. + 1e-10)

    def test_no_stop_target_forces_flat(self):
        frame = bars()
        signal = {"direction": 1, "entry_raw": 100., "stop": 98., "target": 104.,
                  "signal_index": 2, "entry_index": 3}
        trade, marks, _ = execute_trade(frame, signal, 10000., COSTS["base"])
        self.assertEqual(trade["exit_reason"], "session_close")
        self.assertEqual(trade["exit_time"], str(frame.index[-1]))
        self.assertEqual(len(marks), 23)
        self.assertLess(trade["net_pnl"], 0.)


if __name__ == "__main__":
    unittest.main()
````

### FILE `index15/PROTOCOL.md`

````text
# Frozen protocol — SPY 15-minute opening range

Frozen before downloading or inspecting the return series, 2026-10-21.

Purpose: a new test of one simple manual 15-minute US broad equity index setup. SPY is a liquid ETF proxy; this is not an MES-futures backtest and cannot establish futures net returns.

Data: public Yahoo SPY 15-minute bars, requested last 59 calendar days through exclusive 2026-10-21 00:00 UTC. If the vendor's actual clock/data coverage differs, disclose observed timestamps, do not invent bars or relabel dates. RTH America/New_York 09:30–16:00, complete ordinary 26-bar sessions only. Inspect duplicates, OHLC validity and missing RTH bars. Retain raw download, SHA-256 and canonical CSV.

Signal: opening range is high/low of 09:30 and 09:45 bars. Take only the first closed 15-minute candle after 10:00 and before 12:00 with close strictly outside that range. Execute at next bar open. Long above range; short below. At most one trade per session. Stop opposite opening range, target 2R measured from slipped entry. Flatten at open of 15:45 bar; no overnight. No trades whose next open is already beyond the intended stop or has nonpositive risk. All stops, targets and prices rounded to SPY tick 0.01 conservatively for the strategy. Stop-first if stop and target both touched; gap through stop executes at worse open. Costs each leg: 1 bp fee plus 1 bp adverse slippage (base), doubled for stress. Target modeled conservatively as market-on-touch with adverse slippage too. Each day risk 0.25% of current hypothetical equity, initial $10,000, gross notional cap 1x current equity; fractional SPY units permitted for research only. Short borrowing is not separately charged for intraday flat positions; availability is a limitation.

Split: first floor(60% of complete chronological sessions) diagnostic; remaining 40% holdout. No fitting or alternative parameter selection. Report full, diagnostic and holdout trade count, return, marked-to-market max drawdown, average R, profit factor, win rate, base/stress, and buy/hold/cash same dates. Separate session segments start at $10,000 for clean comparison. Sample is short and cannot qualify deployment even if positive. Do not annualize intraday findings.

Drawdown: conservative OHLC bound visits adverse extreme before favorable extreme while position open, limited by stop or actual gap exit. Account fees and adverse slippage. Report daily realized close drawdown separately. Buy/hold is SPY first-session-open to last-session-close net same entry/exit cost. It carries overnight risk unlike the strategy.

No trading project services, credentials or live state are accessed. No parameters or processes changed. Output is research only.
````

### FILE `index15/COST_SENSITIVITY.md`

````text
# Cost chronology

The original frozen protocol had 1 bp commission plus 1 bp adverse slippage per leg, 4 bps nominal round trip; stress doubled, 8 bps. Its first actual run was completed before the coordinating agent requested alignment with gold at 6/12 bps. Original signal, time window, position sizing, data coverage and split remain unchanged.

An additional cost sensitivity uses 1 bp fee plus 2 bps adverse slippage per leg (6 bps nominal round trip), stress 2 bp fee plus 4 bp slippage (12 bps). These are assumptions, not a verified broker tariff. They were added after viewing the negative original outcome, solely for consistent cost comparison, and are not represented as fully preregistered. No positive strategy was selected and no parameter grid was run.

Drawdown clarification: the frozen protocol's wording "adverse extreme before favorable extreme" describes a pessimistic trade path, but does not maximize possible peak-to-trough drawdown inside every candle. The implemented OHLC drawdown is an explicit upper bound: it allows any admissible high/low ordering before stop/target, including favorable before adverse. The report labels it as an OHLC upper bound and also supplies exact session-close drawdown. This changes no trade signal, fill, or final PnL.

Reproduction:

```powershell
python research/crossasset_20261021/index15/download.py
python research/crossasset_20261021/index15/check_engine.py
python research/crossasset_20261021/index15/backtest.py --cost-scheme frozen4_8
python research/crossasset_20261021/index15/backtest.py --cost-scheme comparable6_12
```

The downloaded raw JSON is frozen locally because Yahoo intraday availability expires. A future download outside its retention window may fail. The local replays do not redownload data.
````

### FILE `index15/download.py`

````python
"""Public data only. Frozen historical SPY request; no account integration."""
import datetime as dt
import hashlib
import json
import pathlib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
start = int(dt.datetime(2026, 8, 23, tzinfo=dt.timezone.utc).timestamp())
end = int(dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc).timestamp())
url = f'https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1={start}&period2={end}&interval=15m&includePrePost=false&events=div%2Csplits'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = response.read()
except Exception as exc:
    (HERE / 'download_failure.json').write_text(json.dumps({'url': url, 'error': str(exc)}, indent=2), encoding='utf-8')
    raise
(HERE / 'SPY_15m_raw.json').write_bytes(payload)
result = json.loads(payload)
print(json.dumps({'url': url, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'chart_error': result.get('chart', {}).get('error'), 'timestamps': len((result.get('chart', {}).get('result') or [{}])[0].get('timestamp', []))}, indent=2))
````

### FILE `index15/backtest.py`

````python
"""Frozen SPY 15m test. Python 3.10+, stdlib + system IANA tzdata only.

Run: python research/crossasset_20261021/index15/backtest.py
No downloads or project imports in this program. See PROTOCOL.md first.
"""
from __future__ import annotations

import csv
import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
NY = ZoneInfo('America/New_York')
END = int(dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc).timestamp())
START = int(dt.datetime(2026, 8, 23, tzinfo=dt.timezone.utc).timestamp())
INITIAL = 10000.0
RISK = 0.0025


def tick(price, up):
    return (math.ceil(price * 100 - 1e-8) if up else math.floor(price * 100 + 1e-8)) / 100


def fill(price, side, slippage):
    return tick(price * (1 + side * slippage), side > 0)


def load_data():
    raw = (HERE / 'SPY_15m_raw.json').read_bytes()
    result = json.loads(raw)['chart']['result'][0]
    quotes = result['indicators']['quote'][0]
    dates = {}
    duplicates, invalid, beyond, outside = [], [], [], []
    seen = set()
    rows = []
    for i, timestamp in enumerate(result['timestamp']):
        local = dt.datetime.fromtimestamp(timestamp, NY)
        if not START <= timestamp < END:
            beyond.append(local.isoformat())
            continue
        if timestamp in seen:
            duplicates.append(timestamp)
            continue
        seen.add(timestamp)
        time = local.time()
        if not dt.time(9, 30) <= time < dt.time(16, 0):
            outside.append(local.isoformat())
            continue
        vals = {k: quotes[k][i] for k in ['open', 'high', 'low', 'close', 'volume']}
        good = all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals.values())
        good = good and vals['low'] > 0 and vals['low'] <= min(vals['open'], vals['close']) <= max(vals['open'], vals['close']) <= vals['high'] and vals['volume'] >= 0
        if not good:
            invalid.append({'time': local.isoformat(), 'values': vals})
            continue
        bar = {'timestamp': timestamp, 'ny': local.isoformat(), **vals}
        rows.append(bar)
        dates.setdefault(local.date().isoformat(), []).append(bar)
    expected = {}
    for item in result['meta'].get('tradingPeriods', []):
        for session in item:
            if START <= session['start'] < END:
                day = dt.datetime.fromtimestamp(session['start'], NY).date().isoformat()
                expected[day] = list(range(session['start'], session['end'], 900))
    skipped = []
    complete = []
    for day in sorted(set(dates) | set(expected)):
        bars = sorted(dates.get(day, []), key=lambda b: b['timestamp'])
        observed = [b['timestamp'] for b in bars]
        wanted = expected.get(day, [])
        if len(wanted) != 26 or observed != wanted:
            skipped.append({'date': day, 'observed': len(observed), 'expected': len(wanted), 'missing': sorted(set(wanted) - set(observed)), 'extra': sorted(set(observed) - set(wanted))})
        else:
            complete.append((day, bars))
    if duplicates or invalid:
        raise ValueError(f'Bad data: duplicates={duplicates}, invalid={invalid}')
    with (HERE / 'SPY_15m_clean.csv').open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    qa = {
        'symbol': 'SPY', 'vendor': 'Yahoo chart v8, unadjusted OHLC, volume; ETF not futures',
        'raw_sha256': hashlib.sha256(raw).hexdigest(),
        'clean_sha256': hashlib.sha256((HERE / 'SPY_15m_clean.csv').read_bytes()).hexdigest(),
        'raw_rows': len(result['timestamp']), 'clean_rth_rows': len(rows),
        'complete_sessions': len(complete), 'first': rows[0]['ny'], 'last': rows[-1]['ny'],
        'request_start_utc': dt.datetime.fromtimestamp(START, dt.timezone.utc).isoformat(),
        'request_end_exclusive_utc': dt.datetime.fromtimestamp(END, dt.timezone.utc).isoformat(),
        'duplicate_timestamps': duplicates, 'invalid_ohlcv': invalid,
        'excluded_out_of_request_timestamps': beyond, 'outside_rth': outside,
        'skipped_incomplete_sessions': skipped,
        'events_in_vendor_response': result.get('events', {}),
        'protocol_sha256': hashlib.sha256((HERE / 'PROTOCOL.md').read_bytes()).hexdigest(),
    }
    return complete, qa


def summarize(trades, equity, max_dd, close_dd, sessions):
    pnl = [t['net_pnl'] for t in trades]
    gains, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    return {
        'sessions': len(sessions), 'start_date': sessions[0][0], 'end_date': sessions[-1][0],
        'trades': len(trades), 'longs': sum(t['side'] == 1 for t in trades),
        'shorts': sum(t['side'] == -1 for t in trades), 'net_pnl': equity - INITIAL,
        'return_pct': (equity / INITIAL - 1) * 100,
        'max_dd_ohlc_upper_bound_pct': max_dd * 100,
        'max_dd_session_close_pct': close_dd * 100,
        'profit_factor': gains / losses if losses else None,
        'win_rate_pct': sum(x > 0 for x in pnl) / len(pnl) * 100 if pnl else None,
        'average_net_r': statistics.mean(t['net_r'] for t in trades) if trades else None,
        'total_fees': sum(t['entry_fee'] + t['exit_fee'] for t in trades),
        'ambiguous_stop_target_bars': sum(t['ambiguous_stop_target_bar'] for t in trades),
        'target_exits': sum(t['exit_reason'].startswith('target') for t in trades),
        'stop_exits': sum(t['exit_reason'].startswith('stop') for t in trades),
        'time_exits': sum(t['exit_reason'] == 'time' for t in trades),
        'notional_capped_trades': sum(t['notional_capped'] for t in trades),
        'qualification': 'Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search.',
    }


def run(sessions, fee, slip):
    equity = peak = close_peak = INITIAL
    max_dd = close_dd = 0.0
    trades = []
    for day, bars in sessions:
        range_high = max(b['high'] for b in bars[:2])
        range_low = min(b['low'] for b in bars[:2])
        signal = None
        for idx, bar in enumerate(bars):
            close_time = dt.datetime.fromtimestamp(bar['timestamp'] + 900, NY).time()
            if dt.time(10, 0) < close_time < dt.time(12, 0):
                if bar['close'] > range_high:
                    signal = (idx, 1)
                    break
                if bar['close'] < range_low:
                    signal = (idx, -1)
                    break
        if signal is None:
            close_peak = max(close_peak, equity)
            close_dd = max(close_dd, 1 - equity / close_peak)
            continue
        idx, side = signal
        entry_bar = bars[idx + 1]
        # Opposite range side rounded toward entry, target rounded toward entry.
        stop = tick(range_low, True) if side > 0 else tick(range_high, False)
        raw_entry = entry_bar['open']
        if side * (raw_entry - stop) <= 0:
            continue
        entry = fill(raw_entry, side, slip)
        per_share_risk = side * (entry - stop)
        if per_share_risk <= 0:
            continue
        target = tick(entry + side * 2 * per_share_risk, side < 0)
        pre_equity = equity
        risk_qty = equity * RISK / per_share_risk
        quantity = min(risk_qty, equity / entry)
        initial_dollar_risk = quantity * per_share_risk
        entry_fee = quantity * entry * fee
        base_equity = equity - entry_fee
        # Bound intrabar peak-to-trough: permit any admissible ordering of OHLC
        # extremes up to stop/target, even if favorable-first is not observed.
        # This is a conservative upper bound, not an observed tick path.
        for bar in bars[idx + 1:]:
            bar_time = dt.datetime.fromtimestamp(bar['timestamp'], NY).time()
            op, hi, lo = bar['open'], bar['high'], bar['low']
            ambiguous = lo <= stop and hi >= target if side > 0 else hi >= stop and lo <= target
            if bar_time >= dt.time(15, 45):
                raw_exit, reason = op, 'time'
                best_price = worst_price = raw_exit
            elif side * (op - stop) <= 0:
                raw_exit, reason = op, 'stop_gap'
                best_price = worst_price = raw_exit
            elif side * (op - target) >= 0:
                raw_exit, reason = target, 'target_gap'
                best_price = worst_price = target
            elif (lo <= stop if side > 0 else hi >= stop):
                raw_exit, reason = stop, 'stop'
                best_price = min(hi, target) if side > 0 else max(lo, target)
                worst_price = stop
            elif (hi >= target if side > 0 else lo <= target):
                # Gap through target still receives target rather than optimistic open.
                raw_exit, reason = target, 'target'
                best_price = target
                worst_price = max(lo, stop) if side > 0 else min(hi, stop)
            else:
                raw_exit, reason = None, None
                best_price = min(hi, target) if side > 0 else max(lo, target)
                worst_price = max(lo, stop) if side > 0 else min(hi, stop)
            best_value = base_equity + side * quantity * (best_price - entry)
            # Mark adverse endpoint at hypothetical liquidation including friction.
            worst_fill = fill(worst_price, -side, slip)
            worst_value = base_equity + side * quantity * (worst_fill - entry) - quantity * worst_fill * fee
            peak = max(peak, best_value)
            max_dd = max(max_dd, 1 - worst_value / peak)
            if reason:
                exit_price = fill(raw_exit, -side, slip)
                exit_fee = quantity * exit_price * fee
                equity = base_equity + side * quantity * (exit_price - entry) - exit_fee
                peak = max(peak, equity)
                max_dd = max(max_dd, 1 - equity / peak)
                trades.append({
                    'date': day, 'side': side, 'signal_bar_ny': bars[idx]['ny'],
                    'entry_ny': entry_bar['ny'], 'exit_bar_ny': bar['ny'],
                    'raw_entry': raw_entry, 'entry': entry, 'stop': stop, 'target': target,
                    'exit': exit_price, 'exit_reason': reason, 'quantity': quantity,
                    'initial_dollar_risk': initial_dollar_risk, 'entry_fee': entry_fee,
                    'exit_fee': exit_fee, 'net_pnl': equity - pre_equity,
                    'net_r': (equity - pre_equity) / initial_dollar_risk,
                    'equity_after': equity, 'ambiguous_stop_target_bar': ambiguous,
                    'notional_capped': quantity < risk_qty - 1e-10,
                })
                break
        close_peak = max(close_peak, equity)
        close_dd = max(close_dd, 1 - equity / close_peak)
    return summarize(trades, equity, max_dd, close_dd, sessions), trades


def buy_hold(sessions, fee, slip, dividend_events):
    entry = fill(sessions[0][1][0]['open'], 1, slip)
    quantity = INITIAL / (entry * (1 + fee))
    peak, max_dd, close_peak, close_dd = INITIAL, 0.0, INITIAL, 0.0
    dividend_cash = 0.0
    for day, bars in sessions:
        # Ex-date receivable credited, not reinvested. Ex-date before first buy
        # does not earn that dividend. Full/diagnostic spans one distribution.
        for event in dividend_events.values():
            if sessions[0][1][0]['timestamp'] < event['date'] <= bars[0]['timestamp'] and dt.datetime.fromtimestamp(event['date'], NY).date().isoformat() == day:
                dividend_cash += quantity * event['amount']
        for bar in bars:
            best = dividend_cash + quantity * bar['high']
            worst_fill = fill(bar['low'], -1, slip)
            worst = dividend_cash + quantity * worst_fill * (1 - fee)
            peak = max(peak, best)
            max_dd = max(max_dd, 1 - worst / peak)
        close_value = dividend_cash + quantity * fill(bars[-1]['close'], -1, slip) * (1 - fee)
        close_peak = max(close_peak, close_value)
        close_dd = max(close_dd, 1 - close_value / close_peak)
    end = dividend_cash + quantity * fill(sessions[-1][1][-1]['close'], -1, slip) * (1 - fee)
    return {'net_pnl': end - INITIAL, 'return_pct': (end / INITIAL - 1) * 100,
            'max_dd_ohlc_upper_bound_pct': max_dd * 100,
            'max_dd_session_close_pct': close_dd * 100,
            'overnight_exposure': True, 'dividend_receivable_usd': dividend_cash,
            'dividends': 'cash receivable credited on ex-date, not reinvested; raw vendor distribution events'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cost-scheme', choices=['frozen4_8', 'comparable6_12'], default='frozen4_8')
    args = parser.parse_args()
    if args.cost_scheme == 'frozen4_8':
        configs = [('base', 0.0001, 0.0001), ('stress', 0.0002, 0.0002)]
    else:
        configs = [('base', 0.0001, 0.0002), ('stress', 0.0002, 0.0004)]
    sessions, qa = load_data()
    split = int(len(sessions) * 0.6)
    summary = {'data_quality': qa, 'split': {'diagnostic_sessions': split, 'holdout_sessions': len(sessions) - split},
               'costs': {'cost_scheme': args.cost_scheme, 'base_fee_bps_each_leg': configs[0][1] * 10000,
                         'base_slippage_bps_each_leg': configs[0][2] * 10000,
                         'stress_fee_bps_each_leg': configs[1][1] * 10000,
                         'stress_slippage_bps_each_leg': configs[1][2] * 10000,
                         'tick': 0.01, 'initial_capital_hypothetical_usd': INITIAL, 'risk_fraction': RISK,
                         'notional_cap_x_equity': 1.0}, 'results': {}}
    for name, chosen in [('full', sessions), ('diagnostic', sessions[:split]), ('holdout', sessions[split:])]:
        summary['results'][name] = {}
        for cost, fee, slip in configs:
            stats, trades = run(chosen, fee, slip)
            summary['results'][name][cost] = stats
            summary['results'][name][f'buy_hold_{cost}'] = buy_hold(chosen, fee, slip, qa['events_in_vendor_response'].get('dividends', {}))
            with (HERE / f'trades_{args.cost_scheme}_{name}_{cost}.csv').open('w', newline='', encoding='utf-8') as out:
                if trades:
                    writer = csv.DictWriter(out, fieldnames=list(trades[0]))
                    writer.writeheader()
                    writer.writerows(trades)
        summary['results'][name]['cash_return_pct'] = 0.0
    (HERE / f'results_{args.cost_scheme}.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
````

### FILE `index15/check_engine.py`

````python
"""Small adversarial execution checks, not production bot tests."""
import datetime as dt
import math
from backtest import NY, fill, run


def fixture():
    start = dt.datetime(2026, 8, 24, 9, 30, tzinfo=NY)
    bars = []
    for i in range(26):
        when = start + dt.timedelta(minutes=15 * i)
        bars.append({'timestamp': int(when.timestamp()), 'ny': when.isoformat(),
                     'open': 100.5, 'high': 101, 'low': 100, 'close': 100.5, 'volume': 100})
    bars[0].update(open=100, high=101, low=99, close=100)
    bars[1].update(open=100, high=101, low=99, close=100)
    bars[2].update(open=100, high=102.5, low=100, close=102)  # closes 10:15
    return bars


bars = fixture()
bars[3].update(open=100.5, high=105, low=98, close=100)
stats, trades = run([('2026-08-24', bars)], 0, 0)
trade = trades[0]
assert trade['entry_ny'].startswith('2026-08-24T10:15:'), trade
assert trade['entry'] == 100.5 and trade['exit_reason'] == 'stop', trade
assert trade['ambiguous_stop_target_bar'] and math.isclose(trade['net_pnl'], -25), trade

bars = fixture()
bars[4].update(open=98, high=100, low=97, close=99)
_, trades = run([('2026-08-24', bars)], 0, 0)
assert trades[0]['exit_reason'] == 'stop_gap' and trades[0]['exit'] == 98, trades
assert trades[0]['net_pnl'] < -25, trades

bars = fixture()
bars[4].update(open=105, high=106, low=98, close=99)
_, trades = run([('2026-08-24', bars)], 0, 0)
assert trades[0]['exit_reason'] == 'target_gap' and trades[0]['exit'] == 103.5, trades
assert math.isclose(trades[0]['net_pnl'], 50), trades

bars = fixture()
_, trades = run([('2026-08-24', bars)], 0, 0)
assert trades[0]['exit_reason'] == 'time' and 'T15:45:' in trades[0]['exit_bar_ny'], trades
assert fill(100, 1, .0001) > 100 and fill(100, -1, .0001) < 100

# Future sessions may not alter any completed session's fills, quantity or PnL.
first_day = fixture()
first_day[4].update(open=98, high=100, low=97, close=99)
second_day = fixture()
for bar in second_day:
    when = dt.datetime.fromtimestamp(bar['timestamp'], NY) + dt.timedelta(days=1)
    bar['timestamp'], bar['ny'] = int(when.timestamp()), when.isoformat()
_, prefix_trades = run([('2026-08-24', first_day)], .0001, .0002)
_, extended_trades = run([('2026-08-24', first_day), ('2026-08-25', second_day)], .0001, .0002)
assert prefix_trades == extended_trades[:len(prefix_trades)]
print('6 execution checks passed: causal next-open entry, stop-first ambiguity, adverse gap stop, known open target before later stop, time exit + friction sign, future-session prefix invariance.')
````

### FILE `daily/PROTOCOL.md`

````text
# Daily crossasset screen — frozen 2026-10-21 before downloading/results

Purpose: test one simple executable long/flat candidate on gold and stock index ETFs, independently of the new 15-minute and VIX tests. This is research, not authorization to trade or to change the existing bot.

- Instruments GLD, SPY, QQQ; public Yahoo chart adjusted daily OHLC, download from 2008-01-01 through 2026-10-20 inclusive. Exclude later or incomplete dates, no forward filling. Data quality checks on timestamps, finite positive prices, OHLC consistency and missing cross-ETF sessions. Price adjustment factor = adjusted close / raw close applied to all four OHLC. This is a total-return ETF proxy, not WEEX gold, CME futures or an account-specific backtest.
- One fixed rule, no parameter search: hold long when the preceding completed session's adjusted close exceeds its 200-session SMA, otherwise cash. Execute a change at the next session open. No shorts, stops, targets or leverage. Fractional shares; start with hypothetical 10,000; cash yield zero. Retain shares until exit, dividend adjustment implies total-return reinvestment proxy. No capital added.
- Base friction 10 basis points per traded side, stress 20, including assumed fee/slippage. Expenses embedded in ETF prices, not charged twice. Tariffs/taxes/custody/borrow/FX are not verified and not represented; no margin. End each reported run by liquidating at the final close with one exit charge.
- Periods, selected before results: development 2010-01-01..2015-12-31; validation 2016-01-01..2020-12-31; final historical holdout 2021-01-01..2026-10-20; and full 2010..end. Each period starts in cash, using only prior history for the SMA warmup. These dates are retrospective segments, not a claim of a historically preregistered live experiment.
- Benchmarks on identical dates and friction: unlevered buy-and-hold ETF and zero-yield cash. Report CAGR, total return, daily-close maximum marked-to-market drawdown including initial capital, adverse-daily-low drawdown bound, completed round trips, profit factor, exposure, worst calendar year. Both strategy and benchmark pay entry/exit costs. CAGR uses elapsed calendar days.
- A positive historical holdout alone is a candidate for a faithful execution study, not a proven profitable bot. Few independent trades, daily OHLC execution, single vendor, hindsight choice of broad asset/strategy family, ETF/futures differences and segment selection limit inference. Do not annualize the short 15-minute tests into an expected income.
- Integrity checks: prefix invariance of signals; force next-open fill; changed future rows cannot affect earlier signals; friction only reduces wealth for identical order events; initial-capital drawdown included; constant series produces no SMA trades; output trades reconcile with cash/shares marked equity; invalid/duplicate OHLC refused. Save script, protocol, data source URLs/SHA256 and numeric results for replay.

Post-result terminology correction, with no change to orders or values: the additional daily-low metric is excursion from a prior daily-close peak, NOT a rigorous intraday max-drawdown upper bound. Intraday highs are not used to reconstruct peaks. Daily-close drawdown is the primary reported drawdown; exact intraday DD remains unmeasured.
````

### FILE `daily/run_daily.py`

````python
"""Frozen daily ETF screen. Public market data only; no imports from the trading app."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import urllib.request

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SYMBOLS = ('GLD', 'SPY', 'QQQ')
END = pd.Timestamp('2026-10-21', tz='UTC')
PERIODS = {'development': ('2010-01-01','2015-12-31'),
           'validation': ('2016-01-01','2020-12-31'),
           'holdout': ('2021-01-01','2026-10-20'),
           'full': ('2010-01-01','2026-10-20')}


def download():
    for symbol in SYMBOLS:
        start = int(pd.Timestamp('2008-01-01',tz='UTC').timestamp())
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
               f'?period1={start}&period2={int(END.timestamp())}'
               '&interval=1d&events=div%2Csplits&includeAdjustedClose=true')
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=45) as response:
            raw = response.read()
        (HERE/f'{symbol}_raw.json').write_bytes(raw)
        (HERE/f'{symbol}_source.txt').write_text(url,encoding='utf-8')
        print(symbol, len(raw), 'bytes downloaded', flush=True)


def load(symbol):
    raw = (HERE/f'{symbol}_raw.json').read_bytes()
    j = json.loads(raw)['chart']['result'][0]
    q = j['indicators']['quote'][0]
    d = pd.DataFrame({c:q[c] for c in ('open','high','low','close')})
    d.index = pd.to_datetime(j['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    d['adjclose'] = j['indicators']['adjclose'][0]['adjclose']
    excluded_later = int((d.index >= '2026-10-21').sum())
    d = d.loc[d.index < '2026-10-21'].copy()
    if d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError('Invalid chronology')
    if not np.isfinite(d.to_numpy()).all() or (d <= 0).any().any():
        raise ValueError('Invalid or missing prices')
    factor = d.adjclose / d.close
    for c in ('open','high','low','close'):
        d[c] *= factor
    assert ((d.low <= d[['open','close']].min(axis=1)+1e-8) &
            (d.high >= d[['open','close']].max(axis=1)-1e-8)).all()
    d['sma'] = d.close.rolling(200,min_periods=200).mean()
    d['target'] = (d.close > d.sma).shift(1,fill_value=False)
    assert d.sma.notna().loc['2010-01-01':].all()
    d.to_csv(HERE/f'{symbol}_adjusted.csv',index_label='date')
    meta = {'url':(HERE/f'{symbol}_source.txt').read_text(encoding='utf-8'),
            'sha256':hashlib.sha256(raw).hexdigest(),'first':str(d.index[0].date()),
            'last':str(d.index[-1].date()),'rows':len(d),'excluded_later_rows':excluded_later,
            'split_events':j.get('events',{}).get('splits',{}),
            'dividend_events':len(j.get('events',{}).get('dividends',{}))}
    return d, meta


def simulate(d, start, end, cost, mode):
    x = d.loc[start:end]
    cash, qty = 10000., 0.
    peak, dd, adverse_dd = cash, 0., 0.
    marks, trades = [], []
    entry_cost, entry_date = None, None
    for i,(date,row) in enumerate(x.iterrows()):
        before = cash + qty*row.open
        adverse_dd = min(adverse_dd,before/peak-1)
        target = bool(row.target) if mode=='sma200' else mode=='buy_hold'
        if target and qty==0:
            entry_cost = cash
            entry_date = date
            qty = cash/(row.open*(1+cost))
            cash = 0.
        elif not target and qty:
            cash = qty*row.open*(1-cost)
            trades.append({'entry':str(entry_date.date()),'exit':str(date.date()),
                           'pnl':cash-entry_cost,'return':cash/entry_cost-1,'forced_final':False})
            qty = 0.
        adverse_dd = min(adverse_dd,(cash+qty*row.low)/peak-1)
        mark = cash+qty*row.close
        peak = max(peak,mark)
        dd = min(dd,mark/peak-1)
        if i==len(x)-1 and qty:
            cash = qty*row.close*(1-cost)
            trades.append({'entry':str(entry_date.date()),'exit':str(date.date()),
                           'pnl':cash-entry_cost,'return':cash/entry_cost-1,'forced_final':True})
            qty = 0.
            mark = cash
            dd = min(dd,mark/peak-1)
            adverse_dd = min(adverse_dd,mark/peak-1)
        marks.append({'date':date,'equity':mark,'target':int(target)})
    eq = pd.DataFrame(marks).set_index('date')
    elapsed = ((eq.index[-1]-eq.index[0]).days+1)/365.2425
    total = eq.equity.iloc[-1]/10000-1
    wins = sum(t['pnl'] for t in trades if t['pnl']>0)
    losses = -sum(t['pnl'] for t in trades if t['pnl']<0)
    previous = 10000.
    yearly = {}
    for y,seg in eq.groupby(eq.index.year):
        yearly[str(y)] = seg.equity.iloc[-1]/previous-1
        previous = seg.equity.iloc[-1]
    metrics = {'first':str(eq.index[0].date()),'last':str(eq.index[-1].date()),
               'sessions':len(eq),'return_pct':total*100,
               'cagr_pct':((1+total)**(1/elapsed)-1)*100,
               'max_dd_close_pct':dd*100,'daily_low_dd_from_prior_close_peak_pct':adverse_dd*100,
               'trades':len(trades),'forced_final_trades':sum(t['forced_final'] for t in trades),
               'profit_factor':wins/losses if losses else None,
               'exposure_pct':eq.target.mean()*100,'worst_year_pct':min(yearly.values())*100,
               'yearly_returns_pct':{y:v*100 for y,v in yearly.items()}}
    assert abs(sum(t['pnl'] for t in trades)-(eq.equity.iloc[-1]-10000))<1e-6
    return metrics,eq,trades


def checks(d):
    causal = (d.close > d.close.rolling(200,min_periods=200).mean()).shift(1,fill_value=False)
    for n in (250,500,len(d)//2):
        p = d.iloc[:n]
        s = (p.close > p.close.rolling(200,min_periods=200).mean()).shift(1,fill_value=False)
        assert np.array_equal(s,causal.iloc[:n])
    changed = d.close.copy()
    changed.iloc[-20:] *= 5
    altered = (changed > changed.rolling(200,min_periods=200).mean()).shift(1,fill_value=False)
    assert np.array_equal(altered.iloc[:-20],causal.iloc[:-20])
    constant = pd.Series([1.]*300)
    assert not (constant > constant.rolling(200).mean()).any()
    # Next open gap: signal already known; a fall within entry bar hurts at that open.
    sample = pd.DataFrame({'open':[100.,200.],'high':[110.,210.], 'low':[90.,90.],
                           'close':[100.,100.], 'target':[False,True]},
                          index=pd.to_datetime(['2020-01-01','2020-01-02']))
    m,_,_ = simulate(sample,'2020-01-01','2020-01-02',0,'sma200')
    assert abs(m['return_pct']+50)<1e-8
    assert m['max_dd_close_pct'] <= -50
    return ['prefix_signal_invariance','future_mutation_invariance','constant_no_trades',
            'next_open_gap_fill','initial_capital_drawdown','cash_trade_reconciliation']


def run():
    frames, metadata, results = {}, {}, {}
    qa = []
    for symbol in SYMBOLS:
        frames[symbol],metadata[symbol] = load(symbol)
        qa.extend(checks(frames[symbol]))
    common = frames['GLD'].index
    for symbol in SYMBOLS:
        if not common.equals(frames[symbol].index):
            raise ValueError('ETF calendars differ; investigate rather than forward-fill')
    for symbol,d in frames.items():
        results[symbol]={}
        for period,(start,end) in PERIODS.items():
            results[symbol][period]={}
            for mode in ('sma200','buy_hold','cash'):
                costs = {}
                for cost in (.001,.002):
                    tag = f'{int(cost*10000)}bps'
                    m,eq,trades = simulate(d,start,end,cost,mode)
                    costs[tag]=m
                    eq.to_csv(HERE/f'equity_{symbol}_{period}_{mode}_{tag}.csv')
                    pd.DataFrame(trades).to_csv(HERE/f'trades_{symbol}_{period}_{mode}_{tag}.csv',index=False)
                assert costs['20bps']['return_pct'] <= costs['10bps']['return_pct']+1e-9
                results[symbol][period][mode]=costs
    qa.append('higher_friction_never_improves_terminal_wealth')
    output={'protocol':'PROTOCOL.md','metadata':metadata,'qa_passed':sorted(set(qa)), 'results':results}
    (HERE/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    rows=[]
    for s in SYMBOLS:
        for p in ('full','holdout'):
            for mode in ('sma200','buy_hold'):
                rows.append({'symbol':s,'period':p,'mode':mode,**results[s][p][mode]['10bps']})
    print(pd.DataFrame(rows)[['symbol','period','mode','cagr_pct','max_dd_close_pct','trades']].to_string(index=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--download',action='store_true')
    args=parser.parse_args()
    if args.download:
        download()
    run()
````

### FILE `vix/PROTOCOL.md`

````text
# VIXY hedge experiment — protocol frozen 2026-10-21 before data inspection

Aim: measure whether a fixed tradable VIX-futures allocation reduces a crypto buy-and-hold proxy's losses beyond simply replacing the same exposure with cash. This is not the live grid P&L and cannot establish protection for the live bots.

Data: Yahoo Finance chart daily adjusted closes for VIXY, BTC-USD and ETH-USD, requested 2015-01-01 through completed 2026-10-20. ETF fund expenses and VIX futures roll already appear in VIXY's actual adjusted prices; do not separately charge them. Preserve raw JSON, timestamps, splits, dividends, source URLs and hashes. Start at common available positive prices, no fabricated early ETH observations. VIXY is an actual fund, not spot VIX or a synthetic free index. Verify split dates do not create artificial return jumps. Reject nonfinite/nonpositive/duplicate data.

Alignment: use VIXY observed US-business sessions. Each crypto mark is the latest completed UTC daily close available BEFORE that US close, i.e. Yahoo crypto bar dated D-1 (24:00 UTC). On Monday the Friday-to-Monday marks include the weekend; never discard weekend returns. This conservative asynchronous marking differs from a synchronized 16:00 New York mark; show this limitation. Rebalance on first observed VIXY session of each calendar month at that session's marks. This schedule is fixed and contains no price signal. Record each session's holding-period return before rebalancing; trades only affect subsequent returns. Include initial entry and final liquidation.

Fixed portfolios, equal BTC/ETH sleeve, rebalance all weights monthly:
1) crypto100: BTC 50%, ETH 50%.
2) crypto90_cash10: BTC 45%, ETH 45%, cash 10% (cash return zero).
3) crypto90_VIXY10: BTC 45%, ETH 45%, VIXY 10%.
No parameter search and no conditional volatility strategy. No leverage/borrowing, fractional units permitted, no taxes or currency conversions.

Costs: base 10 basis points per traded notional on every instrument and side (one-way), including initial entry/final exit; stress 20 bps. For rebalance, solve cost-adjusted target portfolio value, deduct spread/commission/slippage as a combined assumption. Quantify turnover and cost. These are explicit assumptions, not claimed broker quotes. VIXY cost paid only when actually traded, no daily artificial fee. Cash no fee.

Report full period and fixed chronological slices: development through 2019-12-31, validation 2020-01-01..2022-12-31, final unseen slice 2023-01-01..2026-10-20, with separate initial/final costs in each slice. Although protocol is frozen now, historical prices are publicly known and the final slice is a chronological holdout, not a prospective live test. Report total return, calendar CAGR, max close-to-close drawdown (initial equity included), worst month, loss months, annualized volatility and correlation; 10 worst full crypto100 calendar months comparing all three portfolios, and VIXY standalone returns in those months. Report wealth and drawdown difference vs cash control. Incomplete first/last months excluded from worst-full-month table. Do not label historical return as an expected future return or recommend live activation.

Expected deliverables: reproducible Python, raw data, quality metadata, equity CSVs and results JSON/Markdown. Reject any conclusion of 'working hedge' if loss reduction is merely lower crypto weight or not stable across time slices.
````

### FILE `vix/PROTOCOL_GLD_DIAGNOSTIC.md`

````text
# Post-VIX diagnostic addendum — NOT part of the original frozen experiment

This GLD comparison was requested after the VIXY results were visible. Freeze before downloading GLD: same BTC/ETH 45%/45% sleeve + 10% adjusted GLD, same sessions, monthly rebalance, initial/final costs 10/20bps one-way; cash control unchanged. No weight search or winner selection. Use the exact same VIXY-based observed calendar to avoid changing the comparison sample. All existing period boundaries unchanged. Report monthly correlation against crypto100 proxy, full/final results, and GLD-vs-cash in the already chosen 10 worst crypto months. This is post-hoc exploratory portfolio diagnostics, not unseen strategy validation.

Important execution limitation, also applicable to the original experiment: crypto daily marks precede ETF close by up to about 20 hours; the simultaneous target-weight calculation at mixed timestamps is a valuation approximation and cannot be executed literally. It avoids using unfinished crypto daily closes but does not provide synchronous realizable rebalancing. Require hourly crypto marks at US ETF close and correct next-fill rules before live interpretation. Close-to-close drawdowns do not include intraday losses.
````

### FILE `vix/download.py`

````python
import urllib.request,json,datetime,time,pathlib
p=pathlib.Path(__file__).resolve().parent
start=int(datetime.datetime(2015,1,1,tzinfo=datetime.timezone.utc).timestamp())
end=int(datetime.datetime(2026,10,21,tzinfo=datetime.timezone.utc).timestamp())
for s in ['VIXY','BTC-USD','ETH-USD']:
 url=f'https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1={start}&period2={end}&interval=1d&events=div%2Csplits&includeAdjustedClose=true'
 try:
  r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=40).read()
  (p/(s+'.json')).write_bytes(r)
  o=json.loads(r)['chart']['result'][0]
  print(s,len(o['timestamp']),datetime.datetime.fromtimestamp(o['timestamp'][0],datetime.timezone.utc),datetime.datetime.fromtimestamp(o['timestamp'][-1],datetime.timezone.utc))
 except Exception as e: print(s,type(e).__name__,str(e))
````

### FILE `vix/download_gld.py`

````python
import urllib.request,pathlib
p=pathlib.Path(__file__).resolve().parent
u='https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true'
r=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=40).read()
(p/'GLD.json').write_bytes(r)
print('bytes',len(r))
````

### FILE `vix/analyze.py`

````python
"""Reproduce the predeclared VIXY fixed-allocation crypto-proxy hedge experiment."""
import json, hashlib, math, pathlib, datetime
import numpy as np
import pandas as pd
P=pathlib.Path(__file__).resolve().parent
CUTOFF=pd.Timestamp('2026-10-20')
START_EPOCH=int(pd.Timestamp('2015-01-01',tz='UTC').timestamp())
END_EPOCH=int(pd.Timestamp('2026-10-21',tz='UTC').timestamp())
SYMS=['BTC-USD','ETH-USD','VIXY']
meta={}; frames={}
for symbol in SYMS:
 raw=(P/f'{symbol}.json').read_bytes(); obj=json.loads(raw)['chart']['result'][0]
 dates=pd.to_datetime(obj['timestamp'],unit='s',utc=True).tz_localize(None).normalize()
 q=obj['indicators']['quote'][0]
 df=pd.DataFrame({'date':dates,'adj_close':obj['indicators']['adjclose'][0]['adjclose'],'close':q['close'],'open':q['open'],'high':q['high'],'low':q['low'],'volume':q['volume']}).set_index('date')
 assert not df.index.duplicated().any()
 invalid=(~np.isfinite(df.adj_close.to_numpy(dtype=float))) | (df.adj_close<=0)
 assert not invalid.any(), (symbol,df.loc[invalid])
 df=df.loc[:CUTOFF]
 df.to_csv(P/f'{symbol}.csv',float_format='%.12g')
 events=obj.get('events',{})
 splits=[]
 for event in events.get('splits',{}).values():
  d=pd.Timestamp(event['date'],unit='s',tz='UTC').tz_localize(None).normalize()
  if d in df.index and df.index.get_loc(d)>0:
   prev=df.iloc[df.index.get_loc(d)-1]
   splits.append({'date':str(d.date()),'split':event.get('splitRatio'),'adj_return':float(df.loc[d,'adj_close']/prev.adj_close-1),'split_adjusted_close_return':float(df.loc[d,'close']/prev.close-1)})
 # Yahoo quote close is already split-adjusted. Dividend adjustment is separate.
 meta[symbol]={'source':f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={START_EPOCH}&period2={END_EPOCH}&interval=1d&events=div%2Csplits&includeAdjustedClose=true','raw_sha256':hashlib.sha256(raw).hexdigest(),'rows':len(df),'first':str(df.index[0].date()),'last':str(df.index[-1].date()),'invalid_prices':int(invalid.sum()),'max_daily_return':float(df.adj_close.pct_change().max()),'min_daily_return':float(df.adj_close.pct_change().min()),'split_checks':splits,'dividends':list(events.get('dividends',{}).values()),'exchange_timezone':obj['meta'].get('exchangeTimezoneName'),'currency':obj['meta'].get('currency')}
 frames[symbol]=df
sessions=frames['VIXY'].index
price=pd.DataFrame(index=sessions)
for s in ['BTC-USD','ETH-USD']:
 # At US session D close, crypto UTC bar D-1 has fully finished. D is not yet finished.
 price[s]=frames[s].adj_close.reindex(sessions-pd.Timedelta(days=1)).to_numpy()
price['VIXY']=frames['VIXY'].adj_close
first=price.dropna().index[0]
price=price.loc[first:]
assert not price.isna().any().any(),price[price.isna().any(axis=1)]
assert (price>0).all().all()
price.to_csv(P/'aligned_prices.csv',float_format='%.12g')
meta['alignment']={'first':str(price.index[0].date()),'last':str(price.index[-1].date()),'observations':len(price),'crypto_mark_lag_days':1,'calendar':'Observed VIXY sessions; crypto marked at previous completed UTC day close','weekend_return_example':'Monday crypto mark = Sunday UTC close; Friday mark = Thursday UTC close. Three calendar-day cumulative return therefore appears on Monday.','max_session_gap_calendar_days':int(price.index.to_series().diff().dt.days.max()),'missing_prices_after_common_start':int(price.isna().sum().sum())}
meta['protocol_sha256']=hashlib.sha256((P/'PROTOCOL.md').read_bytes()).hexdigest()
meta['download_note']='Fetched 2026-10-21; data truncated to complete 2026-10-20; Yahoo sometimes returned a 2026-10-21 crypto bar, which was discarded.'
(P/'data_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')

WEIGHTS={'crypto100':np.array([.5,.5,0]),'crypto90_cash10':np.array([.45,.45,0]),'crypto90_VIXY10':np.array([.45,.45,.1])}
def backtest(px,target,cost):
 vals=np.zeros(3,dtype=float); cash=1.; previous=None; rec=[]; cum_fee=0.; cum_turn=0.; reb_count=0
 for date,row in px.iterrows():
  p=row.to_numpy(dtype=float)
  if previous is not None: vals*=p/previous
  nav=float(vals.sum()+cash)
  turnover=0.; fee=0.
  if previous is None or date.month!=lastdate.month or date.year!=lastdate.year:
   # Fixed point for post-cost wealth: N = preNAV - c * sum(abs(w*N-current)).
   after=nav
   for _ in range(100):
    new=nav-cost*float(np.abs(target*after-vals).sum())
    if abs(new-after)<1e-14*max(1.,nav): break
    after=new
   desired=target*new
   turnover=float(np.abs(desired-vals).sum()); fee=cost*turnover
   assert abs(new-(nav-fee))<1e-11*max(1.,nav)
   vals=desired; cash=(nav-fee)*(1-float(target.sum()))
   cum_turn+=turnover/nav; cum_fee+=fee; reb_count+=1
  post=float(vals.sum()+cash)
  assert cash>-1e-11 and np.all(vals>=0)
  assert abs(post-(nav-fee))<1e-11*max(1.,nav)
  rec.append({'date':date,'equity':post,'fee':fee,'traded_notional':turnover,'BTC_value':vals[0],'ETH_value':vals[1],'VIXY_value':vals[2],'cash':cash})
  previous=p;lastdate=date
 # Terminal liquidation includes all risky holdings cost, no cash transaction fee.
 terminalturn=float(vals.sum());terminalfee=cost*terminalturn
 rec[-1]['equity']-=terminalfee;rec[-1]['fee']+=terminalfee;rec[-1]['traded_notional']+=terminalturn
 rec[-1]['BTC_value']=0.;rec[-1]['ETH_value']=0.;rec[-1]['VIXY_value']=0.;rec[-1]['cash']=rec[-1]['equity']
 cum_turn+=terminalturn/(vals.sum()+cash);cum_fee+=terminalfee
 out=pd.DataFrame(rec).set_index('date')
 assert np.allclose(out[['BTC_value','ETH_value','VIXY_value','cash']].sum(axis=1),out.equity,rtol=1e-12,atol=1e-14)
 eq=out.equity
 years=(px.index[-1]-px.index[0]).days/365.2425
 rawreturn=eq.pct_change();rawreturn.iloc[0]=eq.iloc[0]-1
 dd=eq/eq.cummax().clip(lower=1)-1
 monthly=eq.groupby(eq.index.to_period('M')).last().pct_change()
 # Calendar full-month filtering: exclude first common month and incomplete October 2026.
 fullmonths=monthly[(monthly.index>eq.index[0].to_period('M')) & (monthly.index<CUTOFF.to_period('M'))]
 st={'start':str(px.index[0].date()),'end':str(px.index[-1].date()),'total_return':float(eq.iloc[-1]-1),'CAGR':float(eq.iloc[-1]**(1/years)-1),'max_drawdown':float(dd.min()),'worst_month':float(fullmonths.min()),'worst_month_date':str(fullmonths.idxmin()),'losing_full_months':int((fullmonths<0).sum()),'full_month_count':len(fullmonths),'annualized_volatility':float(rawreturn.std(ddof=1)*math.sqrt(len(px)/years)),'final_wealth':float(eq.iloc[-1]),'fees_in_initial_capital_units':cum_fee,'annualized_one_way_turnover':cum_turn/years,'rebalance_count_including_initial':reb_count}
 return out,st,monthly

ranges={'all':(str(price.index[0].date()),'2026-10-20'),'development':(str(price.index[0].date()),'2019-12-31'),'validation':('2020-01-01','2022-12-31'),'final':('2023-01-01','2026-10-20')}
results={'portfolios':{},'cost_note':'10 or 20bps of actual traded notional per side; all returns net of modeled costs, VIXY historical prices already include roll/fund fees','not_live_bot':'BTC/ETH buy-and-hold proxy only, cannot infer hedge of grid realized+unrealized P&L','periods':ranges,'execution_limitation':'Asynchronous mark allocation diagnostic, not a synchronous executable strategy. Mixed crypto prior-UTC-close and ETF US-close marks cannot literally execute simultaneous target weights; need synchronized hourly crypto marks before adoption.'}
allcurves={};allmonths={}
for cost in [.001,.002]:
 ck=f'{int(cost*10000)}bps';results['portfolios'][ck]={}
 for period,(a,b) in ranges.items():
  sub=price.loc[a:b];results['portfolios'][ck][period]={}
  for name,w in WEIGHTS.items():
   curve,stats,months=backtest(sub,w,cost)
   results['portfolios'][ck][period][name]=stats
   curve.to_csv(P/f'equity_{ck}_{period}_{name}.csv',float_format='%.12g')
   if cost==.001 and period=='all': allcurves[name]=curve;allmonths[name]=months
   # Monotonic costs sanity check applied after all runs below.
for period in ranges:
 for name in WEIGHTS:
  assert results['portfolios']['20bps'][period][name]['final_wealth']<results['portfolios']['10bps'][period][name]['final_wealth']
monthly=pd.DataFrame(allmonths)
monthly=monthly[(monthly.index>price.index[0].to_period('M')) & (monthly.index<price.index[-1].to_period('M'))].dropna()
vixmonths=price.VIXY.groupby(price.index.to_period('M')).last().pct_change()
worst=monthly.nsmallest(10,'crypto100').copy()
worst['VIXY_standalone_before_transaction_cost']=vixmonths.reindex(worst.index)
worst['VIXY_minus_cash_control']=worst.crypto90_VIXY10-worst.crypto90_cash10
worst.to_csv(P/'ten_worst_crypto_months.csv',float_format='%.10g')
results['ten_worst_crypto_months']=json.loads(worst.reset_index(names='month').assign(month=lambda x:x.month.astype(str)).to_json(orient='records'))
results['monthly_correlations']=monthly.corr().to_dict()
results['crypto_vs_VIXY_monthly_return_correlation']=float(pd.concat([monthly.crypto100,vixmonths],axis=1).dropna().corr().iloc[0,1])
results['10_worst_months_summary']={'VIXY_beats_cash_count':int((worst.VIXY_minus_cash_control>0).sum()),'mean_return_crypto100':float(worst.crypto100.mean()),'mean_return_cash_control':float(worst.crypto90_cash10.mean()),'mean_return_VIXY':float(worst.crypto90_VIXY10.mean()),'mean_VIXY_minus_cash_control_pp':float(worst.VIXY_minus_cash_control.mean()*100)}
results['standalone_VIXY']={'start':str(price.index[0].date()),'end':str(price.index[-1].date()),'total_return_before_transaction_cost':float(price.VIXY.iloc[-1]/price.VIXY.iloc[0]-1),'CAGR_before_transaction_cost':float((price.VIXY.iloc[-1]/price.VIXY.iloc[0])**(365.2425/(price.index[-1]-price.index[0]).days)-1)}
(P/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
lines=['# VIXY allocation diagnostic — fixed protocol, 2026-10-21','',f'Common period: {price.index[0].date()} to {price.index[-1].date()}, {len(price)} ETF sessions. Actual adjusted ETF prices; not spot VIX. Crypto marks use previous completed UTC daily close, so this is an asynchronous daily approximation.','', 'All numbers below net of 10bps one-way trading costs unless stated; cash earns 0. Initial and final trades included. Monthly rebalancing. BTC/ETH exposure is a buy-and-hold proxy, not the user\'s live grid P&L.','', '| Period | Portfolio | Total return | CAGR | Max DD | Worst full month |','|---|---|---:|---:|---:|---:|']
for period in ranges:
 for name,st in results['portfolios']['10bps'][period].items():
  lines.append(f"| {period} | {name} | {st['total_return']:.2%} | {st['CAGR']:.2%} | {st['max_drawdown']:.2%} | {st['worst_month']:.2%} |")
lines+=['','## Ten worst crypto100 months','', '| Month | Crypto100 | 90% crypto +10% cash | 90% crypto +10% VIXY | VIXY standalone gross | Hedge minus cash |','|---|---:|---:|---:|---:|---:|']
for d,r in worst.iterrows(): lines.append(f'| {d} | {r.crypto100:.2%} | {r.crypto90_cash10:.2%} | {r.crypto90_VIXY10:.2%} | {r.VIXY_standalone_before_transaction_cost:.2%} | {r.VIXY_minus_cash_control*100:+.2f} pp |')
lines+=['','## Cost stress: 20bps one-way','', '| Period | Portfolio | CAGR | Max DD |','|---|---|---:|---:|']
for period in ranges:
 for name,st in results['portfolios']['20bps'][period].items(): lines.append(f"| {period} | {name} | {st['CAGR']:.2%} | {st['max_drawdown']:.2%} |")
lines+=['','## Data quality and limits','','- Raw JSON and CSVs, split-date checks, source URLs and SHA256 are in `data_metadata.json`. No duplicate or nonfinite/nonpositive prices. ETH series starts November 2017; no early ETH backfill.','- ETF distributions are handled via adjusted closes; reverse splits already appear in split-adjusted OHLC and do not produce artificial gains. Fund roll and expense drag are embedded, not charged a second time.','- Three chronological slices have fixed boundaries; no optimized parameters. Public historic knowledge means this is not prospective out-of-sample evidence.','- No zero-cost spot-VIX hedge, no leveraged short volatility, no trade signal or production activation.','- Close-mark DD omits intraday losses. Asynchronous crypto/ETF marks can distort daily correlation and timing; monthly stress table is more robust but also not a synchronized execution simulation. Mixed-time target-weight rebalancing is a valuation approximation, not literally executable at both marks. Exact common-time intraday marks and live bot equity are required before selecting a hedge.','- US ETF market access, local product restrictions, tax and FX costs are not modeled. Fractional units assumed; small accounts require lot feasibility separately.','', 'Official instrument sources: [ProShares VIXY](https://www.proshares.com/our-etfs/strategic/vixy), [factsheet](https://www.proshares.com/globalassets/proshares/fact-sheet/prosharesfactsheetvixy.pdf), [2023 reverse split](https://prod.proshares.com/press-releases/proshares-announces-etf-share-splits).','', 'Reproduce: `python analyze.py` from this directory; `download.py` refreshes public source data.']
(P/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:24]))
print(json.dumps(results['10_worst_months_summary'],indent=2))
print('VIXY standalone',results['standalone_VIXY'])
print('Split checks',meta['VIXY']['split_checks'])
````

### FILE `vix/analyze_gld_diagnostic.py`

````python
"""Post-VIX-results GLD exploratory diagnostic; run base engine first."""
import json,pathlib,hashlib
import pandas as pd
import numpy as np
from analyze import backtest, price, ranges, results as vixresults
P=pathlib.Path(__file__).resolve().parent
raw=(P/'GLD.json').read_bytes();o=json.loads(raw)['chart']['result'][0]
dates=pd.to_datetime(o['timestamp'],unit='s',utc=True).tz_localize(None).normalize()
q=o['indicators']['quote'][0]
gld=pd.DataFrame({'date':dates,'adj_close':o['indicators']['adjclose'][0]['adjclose'],'close':q['close'],'volume':q['volume']}).set_index('date')
assert not gld.index.duplicated().any()
assert np.isfinite(gld.adj_close).all() and (gld.adj_close>0).all()
gld.to_csv(P/'GLD.csv',float_format='%.12g')
px=price.copy();px['VIXY']=gld.adj_close.reindex(px.index)
assert not px.isna().any().any()
px.rename(columns={'VIXY':'GLD'}).to_csv(P/'aligned_prices_gld.csv',float_format='%.12g')
out={'status':'Exploratory diagnostic proposed after original VIXY results; no tuning, not unseen validation','data':{'first':str(gld.index[0].date()),'last':str(gld.index[-1].date()),'rows':len(gld),'raw_sha256':hashlib.sha256(raw).hexdigest(),'source':'https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true','protocol_sha256':hashlib.sha256((P/'PROTOCOL_GLD_DIAGNOSTIC.md').read_bytes()).hexdigest()},'portfolios':{},'execution_limitation':'Mixed timestamp marks are a valuation approximation and cannot literally execute target rebalance at both marks; need synchronized hourly crypto marks before adoption.'}
for cost in [.001,.002]:
 ck=f'{int(cost*10000)}bps';out['portfolios'][ck]={}
 for period,(a,b) in ranges.items():
  curve,stats,months=backtest(px.loc[a:b],np.array([.45,.45,.1]),cost)
  curve.rename(columns={'VIXY_value':'GLD_value'}).to_csv(P/f'equity_{ck}_{period}_crypto90_GLD10.csv',float_format='%.12g')
  out['portfolios'][ck][period]=stats
  if cost==.001 and period=='all':allmonths=months
worst=pd.read_csv(P/'ten_worst_crypto_months.csv',index_col=0)
worst.index=pd.PeriodIndex(worst.index,freq='M')
gldmonths=px.VIXY.groupby(px.index.to_period('M')).last().pct_change()
worst['crypto90_GLD10']=allmonths.reindex(worst.index)
worst['GLD_standalone_before_transaction_cost']=gldmonths.reindex(worst.index)
worst['GLD_minus_cash_control']=worst.crypto90_GLD10-worst.crypto90_cash10
worst.to_csv(P/'ten_worst_crypto_months_with_GLD.csv',float_format='%.10g')
fullmonths=pd.concat([allmonths.rename('crypto90_GLD10'),gldmonths.rename('GLD_standalone')],axis=1)
cryptomonths=pd.Series({pd.Period(r['month'],freq='M'):r['crypto100'] for r in vixresults['ten_worst_crypto_months']})
# For full correlation use original full equity, not only the selected stress months.
cryptocurve=pd.read_csv(P/'equity_10bps_all_crypto100.csv',index_col='date',parse_dates=True).equity
cryptoall=cryptocurve.groupby(cryptocurve.index.to_period('M')).last().pct_change()
fullmonths['crypto100']=cryptoall
fullmonths=fullmonths[(fullmonths.index>px.index[0].to_period('M')) & (fullmonths.index<px.index[-1].to_period('M'))].dropna()
out['monthly_correlations']=fullmonths.corr().to_dict()
out['10_worst_months_summary']={'GLD_beats_cash_count':int((worst.GLD_minus_cash_control>0).sum()),'mean_return_GLD_portfolio':float(worst.crypto90_GLD10.mean()),'mean_return_cash_control':float(worst.crypto90_cash10.mean()),'mean_GLD_minus_cash_control_pp':float(worst.GLD_minus_cash_control.mean()*100)}
out['ten_worst_crypto_months']=json.loads(worst.reset_index(names='month').assign(month=lambda x:x.month.astype(str)).to_json(orient='records'))
lines=['# GLD diagnostic added after viewing VIXY results','',out['status'], '', 'Same period/calendar/costs as VIXY: 45% BTC,45% ETH,10%GLD; monthly rebalance. Cash control 45/45/10cash. These are crypto buy-and-hold proxy values, not live bot outcomes. Mixed daily timestamps preclude literal simultaneous execution; this is an approximate valuation diagnostic.','', '| Period | GLD CAGR | Cash CAGR | GLD max DD | Cash max DD |','|---|---:|---:|---:|---:|']
for period in ranges:
 g=out['portfolios']['10bps'][period];c=vixresults['portfolios']['10bps'][period]['crypto90_cash10']
 lines.append(f"| {period} | {g['CAGR']:.2%} | {c['CAGR']:.2%} | {g['max_drawdown']:.2%} | {c['max_drawdown']:.2%} |")
lines+=['',f"Monthly GLD standalone vs crypto100 correlation: {out['monthly_correlations']['GLD_standalone']['crypto100']:.4f}.",f"In 10 already selected worst crypto months, GLD beats cash {out['10_worst_months_summary']['GLD_beats_cash_count']}/10; average benefit {out['10_worst_months_summary']['mean_GLD_minus_cash_control_pp']:+.2f}pp.",'','| Month | Crypto100 | Cashcontrol | GLDportfolio | GLDstandalone | GLD-minus-cash |','|---|---:|---:|---:|---:|---:|']
for d,r in worst.iterrows():lines.append(f'| {d} | {r.crypto100:.2%} | {r.crypto90_cash10:.2%} | {r.crypto90_GLD10:.2%} | {r.GLD_standalone_before_transaction_cost:.2%} | {r.GLD_minus_cash_control*100:+.2f}pp |')
lines+=['','GLD fund expenses already embedded in adjusted price; assumed external trading friction 10bps/side, stress20bps. Zero-yield cash understates cash control when safe yield is positive. No optimization, no production activation.','', 'GLD trades a gold-trust share; results cannot be copied to XAU CFD/futures with different financing, margin, execution and currency costs.']
(P/'results_gld_diagnostic.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
(P/'RESULTS_GLD_DIAGNOSTIC.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:20]))
````

### FILE `vix/check_engine.py`

````python
"""Independent accounting identities for the research-only portfolio engine."""
import json,pathlib
import numpy as np
import pandas as pd
from analyze import backtest,price
p=pathlib.Path(__file__).resolve().parent
checks={}
# With a single 100%-weight asset, monthly target never creates turnover.
# Exact net final wealth = price ratio * entry multiplier * exit multiplier.
for j in range(3):
 w=np.zeros(3);w[j]=1
 for c in [0.,.001,.002]:
  curve,_,_=backtest(price,w,c)
  exact=price.iloc[-1,j]/price.iloc[0,j]*(1-c)/(1+c)
  assert np.isclose(curve.equity.iloc[-1],exact,rtol=1e-12)
checks['single_asset_entry_exit_exact_identity_9_cases']=True
flat=price*0+100
for w in [np.array([.5,.5,0]),np.array([.45,.45,0]),np.zeros(3)]:
 for c in [0.,.001,.002]:
  curve,_,_=backtest(flat,w,c)
  exact=(1-c*w.sum())/(1+c*w.sum())
  assert np.isclose(curve.equity.iloc[-1],exact,rtol=1e-12)
checks['flat_prices_cash_weights_exact_identity_9_cases']=True
# Independent no-cost share-accounting reference, rebalances on first observed
# session each month; unlike main code, track share units then multiply prices.
w=np.array([.45,.45,.1]);curve,_,_=backtest(price,w,0)
shares=np.zeros(3);cash=1.;lastmonth=None;reference=[]
for d,r in price.iterrows():
 vals=shares*r.to_numpy();nav=float(vals.sum()+cash)
 if lastmonth!=(d.year,d.month):
  shares=nav*w/r.to_numpy();cash=nav*(1-w.sum())
 reference.append(float((shares*r.to_numpy()).sum()+cash));lastmonth=(d.year,d.month)
assert np.allclose(curve.equity.to_numpy(),reference,rtol=1e-12)
checks['independent_share_unit_monthly_rebalance_reference_2246_sessions']=True
checks['tolerance_relative']=1e-12
checks['all_rows_components_plus_cash_equal_equity_including_terminal_exit']=True
assert np.allclose(curve[['BTC_value','ETH_value','VIXY_value','cash']].sum(axis=1),curve.equity,rtol=1e-12)
assert curve.iloc[-1][['BTC_value','ETH_value','VIXY_value']].sum()==0
assert curve.cash.iloc[-1]==curve.equity.iloc[-1]
(p/'engine_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(checks,indent=2))
````

### FILE `gold15/results.json`

````json
{
  "protocol_sha256": "eee48c2a6f4dbee5b3d35cfd186f195bc3b4437e5f11a058559758c49b1a0b4a",
  "quality": {
    "sha256": "7a9c36fb426d9c5e33eb32b346073f8254613e91ca2b6f1d34b92ec954433e24",
    "raw_rows": 1067,
    "in_window_rows": 1066,
    "regular_complete_rows": 1066,
    "complete_sessions": 41,
    "first_date": "2026-08-24",
    "last_date": "2026-10-20",
    "rejected_dates": {},
    "excluded_outside_window_timestamps": [
      "2026-10-21 20:00:00+00:00"
    ],
    "missing_business_days": [
      "2026-09-07"
    ],
    "timezone": "America/New_York (IANA DST)",
    "observed_utc_offsets": [
      "-1 day, 20:00:00"
    ],
    "raw_response_has_adjclose": false,
    "instrument": {
      "symbol": "GLD",
      "currency": "USD",
      "exchangeName": "PCX",
      "instrumentType": "ETF",
      "dataGranularity": "15m"
    }
  },
  "costs_per_side": {
    "base": {
      "fee": 0.0001,
      "slip": 0.0002
    },
    "stress": {
      "fee": 0.0001,
      "slip": 0.0005
    }
  },
  "initial_synthetic_equity": 10000.0,
  "results": {
    "base": {
      "calibration": {
        "start": "2026-08-24",
        "end": "2026-09-21",
        "sessions": 20,
        "trades": 16,
        "longs": 8,
        "shorts": 8,
        "wins": 7,
        "net_pnl": -46.512483411344874,
        "return_pct": -0.4651248341134506,
        "expectancy_net_r": -0.11577081733272085,
        "profit_factor": 0.7002789846669083,
        "max_dd_close_mtm_pct": 1.3313423609327413,
        "max_dd_adverse_from_prior_close_peak_pct": 1.3835388298404911,
        "fees": 12.111150002947499,
        "slippage_cost": 24.222299598732274,
        "planned_risk_mean_usd": 25.07135613576704
      },
      "holdout": {
        "start": "2026-09-22",
        "end": "2026-10-20",
        "sessions": 21,
        "trades": 18,
        "longs": 5,
        "shorts": 13,
        "wins": 3,
        "net_pnl": -253.6849452815004,
        "return_pct": -2.5368494528150043,
        "expectancy_net_r": -0.5702097821027164,
        "profit_factor": 0.1154004645171196,
        "max_dd_close_mtm_pct": 2.627814416453482,
        "max_dd_adverse_from_prior_close_peak_pct": 2.6444530511452986,
        "fees": 16.317817886723695,
        "slippage_cost": 32.63562758418418,
        "planned_risk_mean_usd": 24.716930959564635
      },
      "all": {
        "start": "2026-08-24",
        "end": "2026-10-20",
        "sessions": 41,
        "trades": 34,
        "longs": 13,
        "shorts": 21,
        "wins": 10,
        "net_pnl": -299.0174770119356,
        "return_pct": -2.990174770119358,
        "expectancy_net_r": -0.3563561516227185,
        "profit_factor": 0.32138873710255916,
        "max_dd_close_mtm_pct": 3.782556801192087,
        "max_dd_adverse_from_prior_close_peak_pct": 3.798998117352067,
        "fees": 28.353069666294637,
        "slippage_cost": 56.70613077425362,
        "planned_risk_mean_usd": 24.822855674417976
      }
    },
    "stress": {
      "calibration": {
        "start": "2026-08-24",
        "end": "2026-09-21",
        "sessions": 20,
        "trades": 16,
        "longs": 8,
        "shorts": 8,
        "wins": 6,
        "net_pnl": -73.9800370532721,
        "return_pct": -0.7398003705327172,
        "expectancy_net_r": -0.18495378825664183,
        "profit_factor": 0.5397923085731317,
        "max_dd_close_mtm_pct": 1.4539722785291982,
        "max_dd_adverse_from_prior_close_peak_pct": 1.5122166234251755,
        "fees": 11.012174473797895,
        "slippage_cost": 55.060870392236275,
        "planned_risk_mean_usd": 25.02891026698245
      },
      "holdout": {
        "start": "2026-09-22",
        "end": "2026-10-20",
        "sessions": 21,
        "trades": 18,
        "longs": 5,
        "shorts": 13,
        "wins": 2,
        "net_pnl": -269.59667570317833,
        "return_pct": -2.695966757031787,
        "expectancy_net_r": -0.6065266536866952,
        "profit_factor": 0.08696527295938605,
        "max_dd_close_mtm_pct": 2.7605485654321416,
        "max_dd_adverse_from_prior_close_peak_pct": 2.7761973763506993,
        "fees": 14.554806169466595,
        "slippage_cost": 72.77398528035253,
        "planned_risk_mean_usd": 24.697863687255534
      },
      "all": {
        "start": "2026-08-24",
        "end": "2026-10-20",
        "sessions": 41,
        "trades": 34,
        "longs": 13,
        "shorts": 21,
        "wins": 8,
        "net_pnl": -341.5822355506534,
        "return_pct": -3.415822355506537,
        "expectancy_net_r": -0.4081394228960819,
        "profit_factor": 0.24735846325759597,
        "max_dd_close_mtm_pct": 4.073727358944398,
        "max_dd_adverse_from_prior_close_peak_pct": 4.0891648391084505,
        "fees": 25.459304133292452,
        "slippage_cost": 127.29647345983335,
        "planned_risk_mean_usd": 24.756918902206564
      }
    }
  }
}
````

### FILE `gold15/download_meta.json`

````json
{
  "url": "https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1787529600&period2=1792540800&interval=15m&includePrePost=false",
  "retrieved_utc": "2026-10-21T20:09:18.527199+00:00",
  "status": 200,
  "sha256": "7a9c36fb426d9c5e33eb32b346073f8254613e91ca2b6f1d34b92ec954433e24"
}
````

### FILE `gold15/audit_daily.json`

````json
{
  "date": "2026-10-21",
  "scope": "Independent read-only review of daily research engine and saved numeric outputs; no live trading code or private state",
  "equity_drawdown_checks": {
    "status": "PASS",
    "cases": 72,
    "dimensions": "3 symbols x 4 periods x 3 modes x 2 costs",
    "formula": "min(equity / cumulative_max([10000, equity]) - 1) * 100",
    "comparison": "results.json max_dd_close_pct",
    "absolute_tolerance_percentage_points": 1e-9,
    "initial_capital_in_peak": true
  },
  "buyhold_closed_form_checks": {
    "status": "PASS",
    "cases": 24,
    "dimensions": "3 symbols x 4 periods x 2 costs",
    "data": "Independently reconstructed adjusted OHLC from each original Yahoo JSON using adjclose / close",
    "formula": "last_adjusted_close / first_adjusted_open * (1 - one_way_cost) / (1 + one_way_cost) - 1",
    "comparison": "results.json return_pct / 100",
    "absolute_tolerance_return_units": 1e-10
  },
  "source_review": {
    "lagged_completed_bar_signal": "PASS",
    "next_open_execution": "PASS",
    "prior_history_warmup_for_each_segment": "PASS",
    "final_exit_friction": "PASS",
    "trade_pnl_terminal_wealth_reconciliation": "PASS",
    "dividend_adjustment_interpretation": "Acceptable explicitly labelled total-return proxy, not exact broker dividend cash accounting",
    "material_numerical_blockers_found": 0
  },
  "terminology_correction": "daily-low excursion from prior close peaks is not a rigorous full intraday maximum drawdown bound; author renamed metric daily_low_dd_from_prior_close_peak_pct without changing numbers",
  "qualification": "Historical positive SMA200 results underperform respective buy-and-hold CAGR; lower measured DD does not establish protection of live BTC/ETH grid equity or authorize activation"
}
````

### FILE `index15/results_frozen4_8.json`

````json
{
  "data_quality": {
    "symbol": "SPY",
    "vendor": "Yahoo chart v8, unadjusted OHLC, volume; ETF not futures",
    "raw_sha256": "49d65ce9939b855c05a818cb7ad3509ad18b4309ef9ddddb823dacced8b425b9",
    "clean_sha256": "b1f60a7cf15982e8d123b4cf14b1011b1e7c0db7e832e71e4a8373c8c88f28c7",
    "raw_rows": 1067,
    "clean_rth_rows": 1066,
    "complete_sessions": 41,
    "first": "2026-08-24T09:30:00-04:00",
    "last": "2026-10-20T15:45:00-04:00",
    "request_start_utc": "2026-08-23T00:00:00+00:00",
    "request_end_exclusive_utc": "2026-10-21T00:00:00+00:00",
    "duplicate_timestamps": [],
    "invalid_ohlcv": [],
    "excluded_out_of_request_timestamps": [
      "2026-10-21T16:00:00-04:00"
    ],
    "outside_rth": [],
    "skipped_incomplete_sessions": [],
    "events_in_vendor_response": {
      "dividends": {
        "1789738200": {
          "amount": 1.889,
          "date": 1789738200
        }
      }
    },
    "protocol_sha256": "464e4688f0e830b4f132a9f2e4e04752d6b0d82e79e5b1f2320b3cbc651b668b"
  },
  "split": {
    "diagnostic_sessions": 24,
    "holdout_sessions": 17
  },
  "costs": {
    "cost_scheme": "frozen4_8",
    "base_fee_bps_each_leg": 1.0,
    "base_slippage_bps_each_leg": 1.0,
    "stress_fee_bps_each_leg": 2.0,
    "stress_slippage_bps_each_leg": 2.0,
    "tick": 0.01,
    "initial_capital_hypothetical_usd": 10000.0,
    "risk_fraction": 0.0025,
    "notional_cap_x_equity": 1.0
  },
  "results": {
    "full": {
      "base": {
        "sessions": 41,
        "start_date": "2026-08-24",
        "end_date": "2026-10-20",
        "trades": 38,
        "longs": 18,
        "shorts": 20,
        "net_pnl": -226.48378370034698,
        "return_pct": -2.264837837003475,
        "max_dd_ohlc_upper_bound_pct": 3.3303832324861116,
        "max_dd_session_close_pct": 3.0188012487881277,
        "profit_factor": 0.5052297918003081,
        "win_rate_pct": 28.947368421052634,
        "average_net_r": -0.24049076604657993,
        "total_fees": 55.66578747313018,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 2,
        "stop_exits": 11,
        "time_exits": 25,
        "notional_capped_trades": 8,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 76.02748864040768,
        "return_pct": 0.7602748864040665,
        "max_dd_ohlc_upper_bound_pct": 3.3348304140400464,
        "max_dd_session_close_pct": 2.463035069790287,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.694860744294523,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 41,
        "start_date": "2026-08-24",
        "end_date": "2026-10-20",
        "trades": 38,
        "longs": 18,
        "shorts": 20,
        "net_pnl": -323.60303313365694,
        "return_pct": -3.23603033133657,
        "max_dd_ohlc_upper_bound_pct": 4.181543430575063,
        "max_dd_session_close_pct": 3.872729538101416,
        "profit_factor": 0.38120285712251456,
        "win_rate_pct": 28.947368421052634,
        "average_net_r": -0.34983447847884386,
        "total_fees": 108.29772704927997,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 2,
        "stop_exits": 11,
        "time_exits": 25,
        "notional_capped_trades": 6,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": 71.91596428537741,
        "return_pct": 0.7191596428537839,
        "max_dd_ohlc_upper_bound_pct": 3.3535248551959995,
        "max_dd_session_close_pct": 2.46328999288441,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.68980933857415,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    },
    "diagnostic": {
      "base": {
        "sessions": 24,
        "start_date": "2026-08-24",
        "end_date": "2026-09-25",
        "trades": 21,
        "longs": 9,
        "shorts": 12,
        "net_pnl": -159.09079761626344,
        "return_pct": -1.5909079761626366,
        "max_dd_ohlc_upper_bound_pct": 1.8427999040424137,
        "max_dd_session_close_pct": 1.5909079761626366,
        "profit_factor": 0.38743387628719095,
        "win_rate_pct": 28.57142857142857,
        "average_net_r": -0.2905502976358048,
        "total_fees": 31.229926078698405,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 6,
        "time_exits": 14,
        "notional_capped_trades": 5,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 105.830904240589,
        "return_pct": 1.0583090424058916,
        "max_dd_ohlc_upper_bound_pct": 3.3348304140400464,
        "max_dd_session_close_pct": 2.463035069790287,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.694860744294523,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 24,
        "start_date": "2026-08-24",
        "end_date": "2026-09-25",
        "trades": 21,
        "longs": 9,
        "shorts": 12,
        "net_pnl": -212.01571088602577,
        "return_pct": -2.1201571088602544,
        "max_dd_ohlc_upper_bound_pct": 2.350796169736491,
        "max_dd_session_close_pct": 2.1201571088602544,
        "profit_factor": 0.2843363183743278,
        "win_rate_pct": 28.57142857142857,
        "average_net_r": -0.40146625485454795,
        "total_fees": 61.00566841806165,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 6,
        "time_exits": 14,
        "notional_capped_trades": 4,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": 101.71030348012937,
        "return_pct": 1.0171030348012922,
        "max_dd_ohlc_upper_bound_pct": 3.3535248551959995,
        "max_dd_session_close_pct": 2.46328999288441,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.68980933857415,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    },
    "holdout": {
      "base": {
        "sessions": 17,
        "start_date": "2026-09-28",
        "end_date": "2026-10-20",
        "trades": 17,
        "longs": 9,
        "shorts": 8,
        "net_pnl": -68.48247930969956,
        "return_pct": -0.6848247930969942,
        "max_dd_ohlc_upper_bound_pct": 1.6153669050481323,
        "max_dd_session_close_pct": 1.450976981150942,
        "profit_factor": 0.6597060750559648,
        "win_rate_pct": 29.411764705882355,
        "average_net_r": -0.17865252114225402,
        "total_fees": 24.83089813338867,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 5,
        "time_exits": 11,
        "notional_capped_trades": 3,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 4.635781753217088,
        "return_pct": 0.04635781753217216,
        "max_dd_ohlc_upper_bound_pct": 2.704133882094284,
        "max_dd_session_close_pct": 2.031935922778716,
        "overnight_exposure": true,
        "dividend_receivable_usd": 0.0,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 17,
        "start_date": "2026-09-28",
        "end_date": "2026-10-20",
        "trades": 17,
        "longs": 9,
        "shorts": 8,
        "net_pnl": -114.00439452251703,
        "return_pct": -1.1400439452251665,
        "max_dd_ohlc_upper_bound_pct": 1.9620399218464923,
        "max_dd_session_close_pct": 1.7905345753265633,
        "profit_factor": 0.5077850910908084,
        "win_rate_pct": 29.411764705882355,
        "average_net_r": -0.2860540488382782,
        "total_fees": 48.31644313509549,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 5,
        "time_exits": 11,
        "notional_capped_trades": 2,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": 0.5532458458674228,
        "return_pct": 0.00553245845866801,
        "max_dd_ohlc_upper_bound_pct": 2.7240975474271623,
        "max_dd_session_close_pct": 2.0321445993478737,
        "overnight_exposure": true,
        "dividend_receivable_usd": 0.0,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    }
  }
}
````

### FILE `index15/results_comparable6_12.json`

````json
{
  "data_quality": {
    "symbol": "SPY",
    "vendor": "Yahoo chart v8, unadjusted OHLC, volume; ETF not futures",
    "raw_sha256": "49d65ce9939b855c05a818cb7ad3509ad18b4309ef9ddddb823dacced8b425b9",
    "clean_sha256": "b1f60a7cf15982e8d123b4cf14b1011b1e7c0db7e832e71e4a8373c8c88f28c7",
    "raw_rows": 1067,
    "clean_rth_rows": 1066,
    "complete_sessions": 41,
    "first": "2026-08-24T09:30:00-04:00",
    "last": "2026-10-20T15:45:00-04:00",
    "request_start_utc": "2026-08-23T00:00:00+00:00",
    "request_end_exclusive_utc": "2026-10-21T00:00:00+00:00",
    "duplicate_timestamps": [],
    "invalid_ohlcv": [],
    "excluded_out_of_request_timestamps": [
      "2026-10-21T16:00:00-04:00"
    ],
    "outside_rth": [],
    "skipped_incomplete_sessions": [],
    "events_in_vendor_response": {
      "dividends": {
        "1789738200": {
          "amount": 1.889,
          "date": 1789738200
        }
      }
    },
    "protocol_sha256": "464e4688f0e830b4f132a9f2e4e04752d6b0d82e79e5b1f2320b3cbc651b668b"
  },
  "split": {
    "diagnostic_sessions": 24,
    "holdout_sessions": 17
  },
  "costs": {
    "cost_scheme": "comparable6_12",
    "base_fee_bps_each_leg": 1.0,
    "base_slippage_bps_each_leg": 2.0,
    "stress_fee_bps_each_leg": 2.0,
    "stress_slippage_bps_each_leg": 4.0,
    "tick": 0.01,
    "initial_capital_hypothetical_usd": 10000.0,
    "risk_fraction": 0.0025,
    "notional_cap_x_equity": 1.0
  },
  "results": {
    "full": {
      "base": {
        "sessions": 41,
        "start_date": "2026-08-24",
        "end_date": "2026-10-20",
        "trades": 38,
        "longs": 18,
        "shorts": 20,
        "net_pnl": -269.9609561390207,
        "return_pct": -2.699609561390204,
        "max_dd_ohlc_upper_bound_pct": 3.7058897789480127,
        "max_dd_session_close_pct": 3.396259467502527,
        "profit_factor": 0.443772548245928,
        "win_rate_pct": 28.947368421052634,
        "average_net_r": -0.2897494003378477,
        "total_fees": 54.29362557423835,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 2,
        "stop_exits": 11,
        "time_exits": 25,
        "notional_capped_trades": 6,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 73.92807925524176,
        "return_pct": 0.7392807925524103,
        "max_dd_ohlc_upper_bound_pct": 3.343858274365352,
        "max_dd_session_close_pct": 2.46328999288441,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.6922780726346,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 41,
        "start_date": "2026-08-24",
        "end_date": "2026-10-20",
        "trades": 38,
        "longs": 18,
        "shorts": 20,
        "net_pnl": -400.66438294080945,
        "return_pct": -4.006643829408096,
        "max_dd_ohlc_upper_bound_pct": 4.846886782346682,
        "max_dd_session_close_pct": 4.543904001970256,
        "profit_factor": 0.29704507865470303,
        "win_rate_pct": 28.947368421052634,
        "average_net_r": -0.4311750051501214,
        "total_fees": 103.10123942349729,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 2,
        "stop_exits": 11,
        "time_exits": 25,
        "notional_capped_trades": 4,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": 67.98154151861854,
        "return_pct": 0.6798154151861802,
        "max_dd_ohlc_upper_bound_pct": 3.3728683354438127,
        "max_dd_session_close_pct": 2.463768115942022,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.684968768966932,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    },
    "diagnostic": {
      "base": {
        "sessions": 24,
        "start_date": "2026-08-24",
        "end_date": "2026-09-25",
        "trades": 21,
        "longs": 9,
        "shorts": 12,
        "net_pnl": -181.77629027842704,
        "return_pct": -1.81776290278427,
        "max_dd_ohlc_upper_bound_pct": 2.058885543019562,
        "max_dd_session_close_pct": 1.81776290278427,
        "profit_factor": 0.33914650327468776,
        "win_rate_pct": 28.57142857142857,
        "average_net_r": -0.3406100143716544,
        "total_fees": 30.54742295413663,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 6,
        "time_exits": 14,
        "notional_capped_trades": 4,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 103.72837791389975,
        "return_pct": 1.0372837791389866,
        "max_dd_ohlc_upper_bound_pct": 3.343858274365352,
        "max_dd_session_close_pct": 2.46328999288441,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.6922780726346,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 24,
        "start_date": "2026-08-24",
        "end_date": "2026-09-25",
        "trades": 21,
        "longs": 9,
        "shorts": 12,
        "net_pnl": -253.1189866221921,
        "return_pct": -2.5311898662219168,
        "max_dd_ohlc_upper_bound_pct": 2.7410208122829682,
        "max_dd_session_close_pct": 2.5311898662219168,
        "profit_factor": 0.21331619178002992,
        "win_rate_pct": 28.57142857142857,
        "average_net_r": -0.4826167095632829,
        "total_fees": 58.247227346100736,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 6,
        "time_exits": 14,
        "notional_capped_trades": 2,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": 97.77003937329391,
        "return_pct": 0.9777003937329498,
        "max_dd_ohlc_upper_bound_pct": 3.3728683354438127,
        "max_dd_session_close_pct": 2.463768115942022,
        "overnight_exposure": true,
        "dividend_receivable_usd": 24.684968768966932,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    },
    "holdout": {
      "base": {
        "sessions": 17,
        "start_date": "2026-09-28",
        "end_date": "2026-10-20",
        "trades": 17,
        "longs": 9,
        "shorts": 8,
        "net_pnl": -89.81733200199051,
        "return_pct": -0.8981733200199016,
        "max_dd_ohlc_upper_bound_pct": 1.7743968819364575,
        "max_dd_session_close_pct": 1.6077211228700095,
        "profit_factor": 0.5806318268380343,
        "win_rate_pct": 29.411764705882355,
        "average_net_r": -0.2269215830019543,
        "total_fees": 24.185843918578954,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 5,
        "time_exits": 11,
        "notional_capped_trades": 2,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_base": {
        "net_pnl": 2.5535565661139117,
        "return_pct": 0.025535565661138904,
        "max_dd_ohlc_upper_bound_pct": 2.7143680112746704,
        "max_dd_session_close_pct": 2.0321445993478737,
        "overnight_exposure": true,
        "dividend_receivable_usd": 0.0,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "stress": {
        "sessions": 17,
        "start_date": "2026-09-28",
        "end_date": "2026-10-20",
        "trades": 17,
        "longs": 9,
        "shorts": 8,
        "net_pnl": -151.3770365269702,
        "return_pct": -1.5137703652697065,
        "max_dd_ohlc_upper_bound_pct": 2.237665098807007,
        "max_dd_session_close_pct": 2.064982770371193,
        "profit_factor": 0.40557959498037816,
        "win_rate_pct": 29.411764705882355,
        "average_net_r": -0.36762937028679227,
        "total_fees": 46.01883619573632,
        "ambiguous_stop_target_bars": 0,
        "target_exits": 1,
        "stop_exits": 5,
        "time_exits": 11,
        "notional_capped_trades": 2,
        "qualification": "Short 41-session exploratory screening, not deployable evidence. Holdout is chronological, no parameter search."
      },
      "buy_hold_stress": {
        "net_pnl": -3.3489776428687037,
        "return_pct": -0.03348977642868567,
        "max_dd_ohlc_upper_bound_pct": 2.7432846205492245,
        "max_dd_session_close_pct": 2.031278087362931,
        "overnight_exposure": true,
        "dividend_receivable_usd": 0.0,
        "dividends": "cash receivable credited on ex-date, not reinvested; raw vendor distribution events"
      },
      "cash_return_pct": 0.0
    }
  }
}
````

### FILE `daily/results.json`

````json
{
  "protocol": "PROTOCOL.md",
  "metadata": {
    "GLD": {
      "url": "https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1199145600&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
      "sha256": "b209c626d1349aa34ee6e8d9e9b4bbfa2450c1654ce0cea8b9727e5a720e2bb2",
      "first": "2008-01-02",
      "last": "2026-10-20",
      "rows": 4730,
      "excluded_later_rows": 0,
      "split_events": {},
      "dividend_events": 0
    },
    "SPY": {
      "url": "https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1=1199145600&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
      "sha256": "fc1290e3188e6a9a699bd03267c9382fab9556afb4c4b1a18f59e3cdfe1dbf3e",
      "first": "2008-01-02",
      "last": "2026-10-20",
      "rows": 4730,
      "excluded_later_rows": 0,
      "split_events": {},
      "dividend_events": 75
    },
    "QQQ": {
      "url": "https://query1.finance.yahoo.com/v8/finance/chart/QQQ?period1=1199145600&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
      "sha256": "18afc5f9d37e7ee6865a1c8f554e8f323d09b9abfffadc0d074f8215b18469ce",
      "first": "2008-01-02",
      "last": "2026-10-20",
      "rows": 4730,
      "excluded_later_rows": 0,
      "split_events": {},
      "dividend_events": 78
    }
  },
  "qa_passed": [
    "cash_trade_reconciliation",
    "constant_no_trades",
    "future_mutation_invariance",
    "higher_friction_never_improves_terminal_wealth",
    "initial_capital_drawdown",
    "next_open_gap_fill",
    "prefix_signal_invariance"
  ],
  "results": {
    "GLD": {
      "development": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 7.642857260668334,
            "cagr_pct": 1.2370047279483654,
            "max_dd_close_pct": -35.91618582400275,
            "daily_low_dd_from_prior_close_peak_pct": -35.95036550636519,
            "trades": 24,
            "forced_final_trades": 0,
            "profit_factor": 1.2049745278792159,
            "exposure_pct": 48.80794701986755,
            "worst_year_pct": -11.239303585986205,
            "yearly_returns_pct": {
              "2010": 26.189601334913814,
              "2011": 11.436897438982996,
              "2012": -4.075572847302555,
              "2013": -5.481884809968496,
              "2014": -11.239303585986205,
              "2015": -4.880913986006852
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 2.5980327016930094,
            "cagr_pct": 0.4290690926105789,
            "max_dd_close_pct": -38.838231887910744,
            "daily_low_dd_from_prior_close_peak_pct": -38.838231887910744,
            "trades": 24,
            "forced_final_trades": 0,
            "profit_factor": 1.0630180739122967,
            "exposure_pct": 48.80794701986755,
            "worst_year_pct": -12.9968871933562,
            "yearly_returns_pct": {
              "2010": 26.06366360903065,
              "2011": 11.325348993098117,
              "2012": -5.030039060959446,
              "2013": -6.422357953308766,
              "2014": -12.9968871933562,
              "2015": -5.449921101404054
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": -7.797047819189862,
            "cagr_pct": -1.3459635066287667,
            "max_dd_close_pct": -45.55501273425702,
            "daily_low_dd_from_prior_close_peak_pct": -45.70128103071019,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": 0.0,
            "exposure_pct": 100.0,
            "worst_year_pct": -28.32983601746557,
            "yearly_returns_pct": {
              "2010": 26.189601334913814,
              "2011": 9.566035291009257,
              "2012": 6.599117321400438,
              "2013": -28.32983601746557,
              "2014": -2.18739308943231,
              "2015": -10.760224113964533
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": -7.981269869944841,
            "cagr_pct": -1.3788946919280676,
            "max_dd_close_pct": -45.555012734257005,
            "daily_low_dd_from_prior_close_peak_pct": -45.701281030710184,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": 0.0,
            "exposure_pct": 100.0,
            "worst_year_pct": -28.32983601746558,
            "yearly_returns_pct": {
              "2010": 26.06366360903065,
              "2011": 9.566035291009257,
              "2012": 6.599117321400461,
              "2013": -28.32983601746558,
              "2014": -2.18739308943231,
              "2015": -10.849553218955565
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          }
        }
      },
      "validation": {
        "sma200": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 33.362854520520656,
            "cagr_pct": 5.934472856179096,
            "max_dd_close_pct": -15.248863619677977,
            "daily_low_dd_from_prior_close_peak_pct": -15.550314513510944,
            "trades": 16,
            "forced_final_trades": 1,
            "profit_factor": 3.6630475906031115,
            "exposure_pct": 73.62986497220015,
            "worst_year_pct": -5.791440717750906,
            "yearly_returns_pct": {
              "2016": 9.610627269925565,
              "2017": -5.791440717750906,
              "2018": -0.3423327455706504,
              "2019": 17.85566506926546,
              "2020": 9.958973558902118
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 29.16279276381335,
            "cagr_pct": 5.257838436787088,
            "max_dd_close_pct": -16.760739895222155,
            "daily_low_dd_from_prior_close_peak_pct": -17.05681320387936,
            "trades": 16,
            "forced_final_trades": 1,
            "profit_factor": 3.0669140661679366,
            "exposure_pct": 73.62986497220015,
            "worst_year_pct": -6.821918717479947,
            "yearly_returns_pct": {
              "2016": 8.519980773592128,
              "2017": -6.821918717479947,
              "2018": -0.938489880252491,
              "2019": 17.85566506926546,
              "2020": 9.410385497754348
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 72.60122342034585,
            "cagr_pct": 11.54915389134068,
            "max_dd_close_pct": -17.759735807380117,
            "daily_low_dd_from_prior_close_peak_pct": -18.02022946870493,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -1.9409636039321887,
            "yearly_returns_pct": {
              "2016": 6.177157981658188,
              "2017": 12.809051033069153,
              "2018": -1.9409636039321887,
              "2019": 17.85566506926546,
              "2020": 24.689746830090552
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 72.25636514206685,
            "cagr_pct": 11.504488946631565,
            "max_dd_close_pct": -17.759735807380128,
            "daily_low_dd_from_prior_close_peak_pct": -18.02022946870494,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -1.9409636039321776,
            "yearly_returns_pct": {
              "2016": 6.071192754131549,
              "2017": 12.809051033069153,
              "2018": -1.9409636039321776,
              "2019": 17.85566506926546,
              "2020": 24.564932268699067
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          }
        }
      },
      "holdout": {
        "sma200": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 66.72724765045113,
            "cagr_pct": 9.224616529061702,
            "max_dd_close_pct": -25.48843810589595,
            "daily_low_dd_from_prior_close_peak_pct": -25.801210159462396,
            "trades": 30,
            "forced_final_trades": 0,
            "profit_factor": 3.2940703874807187,
            "exposure_pct": 69.5054945054945,
            "worst_year_pct": -15.8611462847138,
            "yearly_returns_pct": {
              "2021": -15.8611462847138,
              "2022": -9.557607164831506,
              "2023": 6.28347728294032,
              "2024": 26.656906000925716,
              "2025": 63.6765330882483,
              "2026": -0.5609655154297788
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 57.01778663676209,
            "cagr_pct": 8.099256551104506,
            "max_dd_close_pct": -28.838339360799083,
            "daily_low_dd_from_prior_close_peak_pct": -29.137049764493927,
            "trades": 30,
            "forced_final_trades": 0,
            "profit_factor": 2.7395883635439797,
            "exposure_pct": 69.5054945054945,
            "worst_year_pct": -17.938423679130644,
            "yearly_returns_pct": {
              "2021": -17.938423679130644,
              "2022": -11.525616916028147,
              "2023": 5.225936558980071,
              "2024": 26.656906000925716,
              "2025": 63.67653308824828,
              "2026": -0.858984996364387
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 107.11955043458757,
            "cagr_pct": 13.39212242605441,
            "max_dd_close_pct": -26.404517857029674,
            "daily_low_dd_from_prior_close_peak_pct": -26.735226498095244,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -6.144300516199708,
            "yearly_returns_pct": {
              "2021": -6.144300516199708,
              "2022": -0.7721146890383723,
              "2023": 12.691581500094395,
              "2024": 26.656906000925716,
              "2025": 63.676533088248256,
              "2026": -4.803727832576621
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 106.70572433216856,
            "cagr_pct": 13.352983890179516,
            "max_dd_close_pct": -26.404517857029663,
            "daily_low_dd_from_prior_close_peak_pct": -26.735226498095244,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -6.237968878958,
            "yearly_returns_pct": {
              "2021": -6.237968878958,
              "2022": -0.7721146890383834,
              "2023": 12.691581500094395,
              "2024": 26.65690600092574,
              "2025": 63.67653308824828,
              "2026": -4.899019396307769
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      },
      "full": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 144.67951032783216,
            "cagr_pct": 5.472351956099075,
            "max_dd_close_pct": -35.91618582400275,
            "daily_low_dd_from_prior_close_peak_pct": -36.46338269447752,
            "trades": 69,
            "forced_final_trades": 0,
            "profit_factor": 2.687965046156239,
            "exposure_pct": 63.337278106508876,
            "worst_year_pct": -14.072336801152751,
            "yearly_returns_pct": {
              "2010": 26.189601334913814,
              "2011": 11.436897438982996,
              "2012": -4.075572847302555,
              "2013": -5.481884809968496,
              "2014": -11.239303585986205,
              "2015": -4.880913986006852,
              "2016": 9.610627269925542,
              "2017": -5.791440717750884,
              "2018": -0.3423327455706726,
              "2019": 17.85566506926546,
              "2020": 10.069042601503607,
              "2021": -14.072336801152751,
              "2022": -9.557607164831516,
              "2023": 6.283477282940275,
              "2024": 26.65690600092574,
              "2025": 63.676533088248256,
              "2026": -0.5609655154297788
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 113.13993271232397,
            "cagr_pct": 4.609228000292198,
            "max_dd_close_pct": -42.246543735497966,
            "daily_low_dd_from_prior_close_peak_pct": -42.4889714427856,
            "trades": 69,
            "forced_final_trades": 0,
            "profit_factor": 2.2195407770239655,
            "exposure_pct": 63.337278106508876,
            "worst_year_pct": -16.110055043924522,
            "yearly_returns_pct": {
              "2010": 26.06366360903065,
              "2011": 11.325348993098117,
              "2012": -5.030039060959446,
              "2013": -6.422357953308766,
              "2014": -12.9968871933562,
              "2015": -5.449921101404054,
              "2016": 8.51998077359215,
              "2017": -6.821918717479947,
              "2018": -0.938489880252491,
              "2019": 17.85566506926546,
              "2020": 9.629644787329017,
              "2021": -16.110055043924522,
              "2022": -11.52561691602817,
              "2023": 5.225936558980071,
              "2024": 26.65690600092574,
              "2025": 63.67653308824828,
              "2026": -0.858984996364387
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 243.19381670140072,
            "cagr_pct": 7.618795430593539,
            "max_dd_close_pct": -45.55501273425702,
            "daily_low_dd_from_prior_close_peak_pct": -45.70128103071019,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -28.32983601746557,
            "yearly_returns_pct": {
              "2010": 26.189601334913814,
              "2011": 9.566035291009257,
              "2012": 6.599117321400438,
              "2013": -28.32983601746557,
              "2014": -2.18739308943231,
              "2015": -10.670895008973503,
              "2016": 8.032723831481059,
              "2017": 12.809051033069153,
              "2018": -1.9409636039321887,
              "2019": 17.85566506926546,
              "2020": 24.814561391482037,
              "2021": -4.148908875959545,
              "2022": -0.7721146890383612,
              "2023": 12.691581500094395,
              "2024": 26.65690600092574,
              "2025": 63.67653308824828,
              "2026": -4.80372783257661
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 242.50811339989275,
            "cagr_pct": 7.605980070568252,
            "max_dd_close_pct": -45.555012734257005,
            "daily_low_dd_from_prior_close_peak_pct": -45.701281030710184,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -28.32983601746558,
            "yearly_returns_pct": {
              "2010": 26.06366360903065,
              "2011": 9.566035291009257,
              "2012": 6.599117321400461,
              "2013": -28.32983601746558,
              "2014": -2.18739308943231,
              "2015": -10.670895008973513,
              "2016": 8.032723831481059,
              "2017": 12.809051033069153,
              "2018": -1.9409636039321887,
              "2019": 17.85566506926546,
              "2020": 24.814561391482016,
              "2021": -4.148908875959545,
              "2022": -0.7721146890383723,
              "2023": 12.691581500094395,
              "2024": 26.656906000925716,
              "2025": 63.676533088248256,
              "2026": -4.899019396307757
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      }
    },
    "SPY": {
      "development": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 31.30600684231237,
            "cagr_pct": 4.651444899357315,
            "max_dd_close_pct": -24.888718783429166,
            "daily_low_dd_from_prior_close_peak_pct": -25.33542715795748,
            "trades": 19,
            "forced_final_trades": 1,
            "profit_factor": 1.8871541560811034,
            "exposure_pct": 85.89403973509934,
            "worst_year_pct": -7.890967192149844,
            "yearly_returns_pct": {
              "2010": -7.857067378803528,
              "2011": -7.295327851265377,
              "2012": 13.316889276470544,
              "2013": 32.30772768233776,
              "2014": 11.311200007225896,
              "2015": -7.890967192149844
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 26.40998079546053,
            "cagr_pct": 3.989705313329628,
            "max_dd_close_pct": -25.784669791123548,
            "daily_low_dd_from_prior_close_peak_pct": -26.226049687534836,
            "trades": 19,
            "forced_final_trades": 1,
            "profit_factor": 1.6999923544865956,
            "exposure_pct": 85.89403973509934,
            "worst_year_pct": -9.047039384603705,
            "yearly_returns_pct": {
              "2010": -9.047039384603705,
              "2011": -8.40113836447104,
              "2012": 13.090481452925529,
              "2013": 32.307727682337784,
              "2014": 11.08879956285489,
              "2015": -8.716368080561399
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 104.53930256717841,
            "cagr_pct": 12.688064090973295,
            "max_dd_close_pct": -18.605489943514677,
            "daily_low_dd_from_prior_close_peak_pct": -20.456524735874726,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": 1.1330057499479462,
            "yearly_returns_pct": {
              "2010": 13.989915727385661,
              "2011": 1.895023423429465,
              "2012": 15.990344109923527,
              "2013": 32.30772768233776,
              "2014": 13.463820316104357,
              "2015": 1.1330057499479462
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 104.13063181545432,
            "cagr_pct": 12.650448280698278,
            "max_dd_close_pct": -18.605489943514677,
            "daily_low_dd_from_prior_close_peak_pct": -20.456524735874726,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": 1.031771509958035,
            "yearly_returns_pct": {
              "2010": 13.87615333644019,
              "2011": 1.895023423429465,
              "2012": 15.990344109923527,
              "2013": 32.30772768233776,
              "2014": 13.463820316104336,
              "2015": 1.031771509958035
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          }
        }
      },
      "validation": {
        "sma200": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 57.48944496628135,
            "cagr_pct": 9.521187342288417,
            "max_dd_close_pct": -19.76547793060074,
            "daily_low_dd_from_prior_close_peak_pct": -20.798411720571607,
            "trades": 12,
            "forced_final_trades": 1,
            "profit_factor": 3.7978353410772594,
            "exposure_pct": 86.02065131056395,
            "worst_year_pct": -3.5454287334422574,
            "yearly_returns_pct": {
              "2016": 10.759874106883327,
              "2017": 21.70537676789992,
              "2018": -3.5454287334422574,
              "2019": 14.13144940063975,
              "2020": 6.128270354668364
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 53.754685947999434,
            "cagr_pct": 8.996109471248314,
            "max_dd_close_pct": -20.245444842301975,
            "daily_low_dd_from_prior_close_peak_pct": -21.272199570836726,
            "trades": 12,
            "forced_final_trades": 1,
            "profit_factor": 3.4290047633221064,
            "exposure_pct": 86.02065131056395,
            "worst_year_pct": -4.409770550827908,
            "yearly_returns_pct": {
              "2016": 10.42825727562735,
              "2017": 21.70537676789992,
              "2018": -4.409770550827908,
              "2019": 13.562385440964908,
              "2020": 5.387806744847068
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 104.98160038294837,
            "cagr_pct": 15.456555711913666,
            "max_dd_close_pct": -33.71725721081139,
            "daily_low_dd_from_prior_close_peak_pct": -35.111588808746184,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -4.568969823202851,
            "yearly_returns_pct": {
              "2016": 13.772261886231728,
              "2017": 21.7053767678999,
              "2018": -4.568969823202851,
              "2019": 31.22385066418827,
              "2020": 18.213297621462132
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 104.57204591753894,
            "cagr_pct": 15.410326220274495,
            "max_dd_close_pct": -33.717257210811404,
            "daily_low_dd_from_prior_close_peak_pct": -35.111588808746184,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -4.5689698232028615,
            "yearly_returns_pct": {
              "2016": 13.658716714688591,
              "2017": 21.70537676789992,
              "2018": -4.5689698232028615,
              "2019": 31.22385066418827,
              "2020": 18.094965992211453
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          }
        }
      },
      "holdout": {
        "sma200": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 87.9005580002032,
            "cagr_pct": 11.502008503644134,
            "max_dd_close_pct": -20.37319801743478,
            "daily_low_dd_from_prior_close_peak_pct": -20.66721271557449,
            "trades": 16,
            "forced_final_trades": 1,
            "profit_factor": 6.137032276196655,
            "exposure_pct": 81.18131868131869,
            "worst_year_pct": -14.126723533900732,
            "yearly_returns_pct": {
              "2021": 28.110175161768524,
              "2022": -14.126723533900732,
              "2023": 12.001135711679577,
              "2024": 24.88647122661338,
              "2025": 10.50458853043239,
              "2026": 10.501526748564526
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 81.98291361145647,
            "cagr_pct": 10.887821731736146,
            "max_dd_close_pct": -22.105862510775754,
            "daily_low_dd_from_prior_close_peak_pct": -22.393479503428082,
            "trades": 16,
            "forced_final_trades": 1,
            "profit_factor": 5.30480516221755,
            "exposure_pct": 81.18131868131869,
            "worst_year_pct": -15.405339913638972,
            "yearly_returns_pct": {
              "2021": 27.982320695539208,
              "2022": -15.405339913638972,
              "2023": 10.99781212474884,
              "2024": 24.88647122661336,
              "2025": 10.063452008219432,
              "2026": 10.170352901042934
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 120.785973539825,
            "cagr_pct": 14.649687360555275,
            "max_dd_close_pct": -24.4963905210945,
            "daily_low_dd_from_prior_close_peak_pct": -26.285726907381868,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -18.17536081973149,
            "yearly_returns_pct": {
              "2021": 28.110175161768524,
              "2022": -18.17536081973149,
              "2023": 26.175771411093017,
              "2024": 24.886471226613338,
              "2025": 17.719063776702647,
              "2026": 13.544366862024383
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 120.34484184217958,
            "cagr_pct": 14.61011476233769,
            "max_dd_close_pct": -24.49639052109451,
            "daily_low_dd_from_prior_close_peak_pct": -26.28572690738188,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -18.1753608197315,
            "yearly_returns_pct": {
              "2021": 27.982320695539208,
              "2022": -18.1753608197315,
              "2023": 26.175771411092995,
              "2024": 24.88647122661338,
              "2025": 17.719063776702647,
              "2026": 13.430708837137463
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      },
      "full": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 284.35289800039556,
            "cagr_pct": 8.347060915982919,
            "max_dd_close_pct": -24.888718783429166,
            "daily_low_dd_from_prior_close_peak_pct": -25.33542715795748,
            "trades": 46,
            "forced_final_trades": 1,
            "profit_factor": 3.872270913347828,
            "exposure_pct": 84.3076923076923,
            "worst_year_pct": -14.126723533900709,
            "yearly_returns_pct": {
              "2010": -7.857067378803528,
              "2011": -7.295327851265377,
              "2012": 13.316889276470544,
              "2013": 32.30772768233776,
              "2014": 11.311200007225896,
              "2015": -7.7987659581079445,
              "2016": 8.814683846141126,
              "2017": 21.70537676789992,
              "2018": -3.5454287334422685,
              "2019": 14.13144940063975,
              "2020": 6.2345048595278785,
              "2021": 28.728762372808635,
              "2022": -14.126723533900709,
              "2023": 12.0011357116796,
              "2024": 24.88647122661336,
              "2025": 10.50458853043239,
              "2026": 10.501526748564526
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 250.57018225279805,
            "cagr_pct": 7.755152507810692,
            "max_dd_close_pct": -25.784669791123548,
            "daily_low_dd_from_prior_close_peak_pct": -26.226049687534836,
            "trades": 46,
            "forced_final_trades": 1,
            "profit_factor": 3.4087956867046474,
            "exposure_pct": 84.3076923076923,
            "worst_year_pct": -15.40533991363896,
            "yearly_returns_pct": {
              "2010": -9.047039384603705,
              "2011": -8.40113836447104,
              "2012": 13.090481452925529,
              "2013": 32.307727682337784,
              "2014": 11.08879956285489,
              "2015": -8.533434950462325,
              "2016": 8.380293457144994,
              "2017": 21.70537676789992,
              "2018": -4.409770550827929,
              "2019": 13.562385440964908,
              "2020": 5.599004754355752,
              "2021": 28.728762372808635,
              "2022": -15.40533991363896,
              "2023": 10.99781212474884,
              "2024": 24.88647122661336,
              "2025": 10.063452008219453,
              "2026": 10.170352901042934
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 817.4824433314863,
            "cagr_pct": 14.10820115107252,
            "max_dd_close_pct": -33.71725721081139,
            "daily_low_dd_from_prior_close_peak_pct": -35.11158880874618,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -18.175360819731512,
            "yearly_returns_pct": {
              "2010": 13.989915727385661,
              "2011": 1.895023423429465,
              "2012": 15.990344109923527,
              "2013": 32.30772768233776,
              "2014": 13.463820316104357,
              "2015": 1.2342399899378798,
              "2016": 11.997939488677778,
              "2017": 21.7053767678999,
              "2018": -4.568969823202851,
              "2019": 31.223850664188248,
              "2020": 18.33162925071288,
              "2021": 28.72876237280866,
              "2022": -18.175360819731512,
              "2023": 26.175771411093017,
              "2024": 24.88647122661336,
              "2025": 17.719063776702626,
              "2026": 13.544366862024404
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 815.64930791397,
            "cagr_pct": 14.094613025747948,
            "max_dd_close_pct": -33.717257210811404,
            "daily_low_dd_from_prior_close_peak_pct": -35.11158880874618,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -18.17536081973149,
            "yearly_returns_pct": {
              "2010": 13.87615333644019,
              "2011": 1.895023423429465,
              "2012": 15.990344109923527,
              "2013": 32.30772768233776,
              "2014": 13.463820316104336,
              "2015": 1.234239989937902,
              "2016": 11.997939488677755,
              "2017": 21.70537676789992,
              "2018": -4.568969823202851,
              "2019": 31.223850664188248,
              "2020": 18.3316292507129,
              "2021": 28.728762372808635,
              "2022": -18.17536081973149,
              "2023": 26.175771411093017,
              "2024": 24.88647122661336,
              "2025": 17.719063776702626,
              "2026": 13.430708837137484
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      }
    },
    "QQQ": {
      "development": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 42.879973336881314,
            "cagr_pct": 6.137620054003379,
            "max_dd_close_pct": -23.605358718811843,
            "daily_low_dd_from_prior_close_peak_pct": -23.722374068628337,
            "trades": 25,
            "forced_final_trades": 1,
            "profit_factor": 2.17964419350083,
            "exposure_pct": 89.5364238410596,
            "worst_year_pct": -12.194950825512208,
            "yearly_returns_pct": {
              "2010": -0.29183081275401257,
              "2011": -12.194950825512208,
              "2012": 10.025926172174993,
              "2013": 33.224881590635746,
              "2014": 19.18139562915673,
              "2015": -6.581629976318459
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 35.91161895352002,
            "cagr_pct": 5.255427900822673,
            "max_dd_close_pct": -24.66743429864855,
            "daily_low_dd_from_prior_close_peak_pct": -24.782822843974273,
            "trades": 25,
            "forced_final_trades": 1,
            "profit_factor": 1.9137611904715655,
            "exposure_pct": 89.5364238410596,
            "worst_year_pct": -13.76130587854868,
            "yearly_returns_pct": {
              "2010": -1.7761481594851136,
              "2011": -13.76130587854868,
              "2012": 9.039969698174598,
              "2013": 33.091922626972426,
              "2014": 19.18139562915673,
              "2015": -7.233415813025202
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 157.88376680637617,
            "cagr_pct": 17.132913344720645,
            "max_dd_close_pct": -16.099246228865706,
            "daily_low_dd_from_prior_close_peak_pct": -25.65362659607805,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": 3.475800593059808,
            "yearly_returns_pct": {
              "2010": 18.521200444140497,
              "2011": 3.475800593059808,
              "2012": 18.1125190740975,
              "2013": 36.634211242854995,
              "2014": 19.18139562915673,
              "2015": 9.32646743762735
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 157.3685134955676,
            "cagr_pct": 17.093813822682733,
            "max_dd_close_pct": -16.099246228865695,
            "daily_low_dd_from_prior_close_peak_pct": -25.65362659607805,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": 3.4758005930597857,
            "yearly_returns_pct": {
              "2010": 18.40291581295872,
              "2011": 3.4758005930597857,
              "2012": 18.11251907409752,
              "2013": 36.634211242854995,
              "2014": 19.181395629156704,
              "2015": 9.217031534286392
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2015-12-31",
            "sessions": 1510,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0
            }
          }
        }
      },
      "validation": {
        "sma200": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 96.35456011322943,
            "cagr_pct": 14.466733507425268,
            "max_dd_close_pct": -23.361885422050666,
            "daily_low_dd_from_prior_close_peak_pct": -24.166955254923817,
            "trades": 17,
            "forced_final_trades": 1,
            "profit_factor": 2.9871165667525363,
            "exposure_pct": 86.73550436854647,
            "worst_year_pct": -2.0741288448941075,
            "yearly_returns_pct": {
              "2016": -2.0741288448941075,
              "2017": 32.66356398692971,
              "2018": -1.6829020855184784,
              "2019": 14.922997839558949,
              "2020": 33.76912630671518
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 89.79070755430949,
            "cagr_pct": 13.690060636002377,
            "max_dd_close_pct": -24.291427930689803,
            "daily_low_dd_from_prior_close_peak_pct": -24.69708232616936,
            "trades": 17,
            "forced_final_trades": 1,
            "profit_factor": 2.7693899083543436,
            "exposure_pct": 86.73550436854647,
            "worst_year_pct": -3.338784114737059,
            "yearly_returns_pct": {
              "2016": -3.338784114737059,
              "2017": 32.66356398692973,
              "2018": -2.5639342437211,
              "2019": 14.121515228430837,
              "2020": 33.10174879975145
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 198.48397946401914,
            "cagr_pct": 24.479954371912882,
            "max_dd_close_pct": -28.559353599511926,
            "daily_low_dd_from_prior_close_peak_pct": -30.255088826968233,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -0.1261872848003498,
            "yearly_returns_pct": {
              "2016": 9.34676107391994,
              "2017": 32.66356398692971,
              "2018": -0.1261872848003498,
              "2019": 38.96148867401179,
              "2020": 48.25773292064759
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 197.8876066851244,
            "cagr_pct": 24.430111857779323,
            "max_dd_close_pct": -28.559353599511926,
            "daily_low_dd_from_prior_close_peak_pct": -30.255088826968233,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -0.1261872848003498,
            "yearly_returns_pct": {
              "2016": 9.237632569854126,
              "2017": 32.66356398692973,
              "2018": -0.1261872848003498,
              "2019": 38.96148867401177,
              "2020": 48.1093267815879
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          },
          "20bps": {
            "first": "2016-01-04",
            "last": "2020-12-31",
            "sessions": 1259,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0
            }
          }
        }
      },
      "holdout": {
        "sma200": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 126.51171169575215,
            "cagr_pct": 15.157480773557076,
            "max_dd_close_pct": -21.828131077163093,
            "daily_low_dd_from_prior_close_peak_pct": -22.19012381447223,
            "trades": 11,
            "forced_final_trades": 1,
            "profit_factor": 8.176544643447986,
            "exposure_pct": 78.77747252747253,
            "worst_year_pct": -17.796443185656706,
            "yearly_returns_pct": {
              "2021": 26.739019281231037,
              "2022": -17.796443185656706,
              "2023": 34.98605506751326,
              "2024": 25.57826058622956,
              "2025": 12.612780725941231,
              "2026": 13.893426617316983
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 121.58285871648711,
            "cagr_pct": 14.721008004906677,
            "max_dd_close_pct": -22.837906465492008,
            "daily_low_dd_from_prior_close_peak_pct": -23.27187468051256,
            "trades": 11,
            "forced_final_trades": 1,
            "profit_factor": 7.378533390949992,
            "exposure_pct": 78.77747252747253,
            "worst_year_pct": -18.53307982982484,
            "yearly_returns_pct": {
              "2021": 26.612533234044157,
              "2022": -18.53307982982484,
              "2023": 34.31300921204572,
              "2024": 25.578260586229582,
              "2025": 12.163228258420933,
              "2026": 13.55208722219623
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 135.00818563408785,
            "cagr_pct": 15.891768237181303,
            "max_dd_close_pct": -35.11872767702523,
            "daily_low_dd_from_prior_close_peak_pct": -36.67045360858913,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -32.57700076485729,
            "yearly_returns_pct": {
              "2021": 26.739019281231037,
              "2022": -32.57700076485729,
              "2023": 54.855558053065835,
              "2024": 25.578260586229582,
              "2025": 20.772551391310845,
              "2026": 17.099509974036664
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 134.53863787148674,
            "cagr_pct": 15.851766921113564,
            "max_dd_close_pct": -35.11872767702524,
            "daily_low_dd_from_prior_close_peak_pct": -36.670453608589135,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -32.57700076485729,
            "yearly_returns_pct": {
              "2021": 26.612533234044157,
              "2022": -32.57700076485729,
              "2023": 54.855558053065856,
              "2024": 25.578260586229582,
              "2025": 20.772551391310824,
              "2026": 16.982293247335956
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2021-01-04",
            "last": "2026-10-20",
            "sessions": 1456,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      },
      "full": {
        "sma200": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 527.0084237086631,
            "cagr_pct": 11.5508270146925,
            "max_dd_close_pct": -27.075013889706412,
            "daily_low_dd_from_prior_close_peak_pct": -27.652067656697433,
            "trades": 51,
            "forced_final_trades": 1,
            "profit_factor": 4.497806342193652,
            "exposure_pct": 84.99408284023669,
            "worst_year_pct": -17.796443185656695,
            "yearly_returns_pct": {
              "2010": -0.29183081275401257,
              "2011": -12.194950825512208,
              "2012": 10.025926172174993,
              "2013": 33.224881590635746,
              "2014": 19.18139562915673,
              "2015": -6.488118094412865,
              "2016": -4.088128304515615,
              "2017": 32.66356398692971,
              "2018": -1.6829020855184562,
              "2019": 14.92299783955897,
              "2020": 33.903029336051226,
              "2021": 27.419752599682656,
              "2022": -17.796443185656695,
              "2023": 34.98605506751326,
              "2024": 25.578260586229582,
              "2025": 12.612780725941208,
              "2026": 13.893426617317006
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 466.2070009965995,
            "cagr_pct": 10.875376807364411,
            "max_dd_close_pct": -28.3759233654187,
            "daily_low_dd_from_prior_close_peak_pct": -28.942683065128882,
            "trades": 51,
            "forced_final_trades": 1,
            "profit_factor": 4.037744707828486,
            "exposure_pct": 84.99408284023669,
            "worst_year_pct": -18.53307982982486,
            "yearly_returns_pct": {
              "2010": -1.7761481594851136,
              "2011": -13.76130587854868,
              "2012": 9.039969698174598,
              "2013": 33.091922626972426,
              "2014": 19.18139562915673,
              "2015": -7.0475108346945925,
              "2016": -5.232195303554777,
              "2017": 32.66356398692971,
              "2018": -2.5639342437210777,
              "2019": 14.121515228430791,
              "2020": 33.368485771294054,
              "2021": 27.419752599682678,
              "2022": -18.53307982982486,
              "2023": 34.31300921204574,
              "2024": 25.578260586229582,
              "2025": 12.163228258420933,
              "2026": 13.552087222196207
            }
          }
        },
        "buy_hold": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 1684.836267976161,
            "cagr_pct": 18.720329494895992,
            "max_dd_close_pct": -35.11872767702523,
            "daily_low_dd_from_prior_close_peak_pct": -36.670453608589135,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -32.5770007648573,
            "yearly_returns_pct": {
              "2010": 18.521200444140497,
              "2011": 3.475800593059808,
              "2012": 18.1125190740975,
              "2013": 36.634211242854995,
              "2014": 19.18139562915673,
              "2015": 9.43590334096831,
              "2016": 7.0978730618294295,
              "2017": 32.66356398692973,
              "2018": -0.1261872848003387,
              "2019": 38.96148867401177,
              "2020": 48.4061390597073,
              "2021": 27.419752599682678,
              "2022": -32.5770007648573,
              "2023": 54.855558053065835,
              "2024": 25.578260586229607,
              "2025": 20.772551391310824,
              "2026": 17.099509974036685
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 1681.270154421536,
            "cagr_pct": 18.7061921524484,
            "max_dd_close_pct": -35.11872767702523,
            "daily_low_dd_from_prior_close_peak_pct": -36.67045360858913,
            "trades": 1,
            "forced_final_trades": 1,
            "profit_factor": null,
            "exposure_pct": 100.0,
            "worst_year_pct": -32.57700076485729,
            "yearly_returns_pct": {
              "2010": 18.40291581295872,
              "2011": 3.4758005930597857,
              "2012": 18.11251907409752,
              "2013": 36.634211242854995,
              "2014": 19.181395629156704,
              "2015": 9.435903340968332,
              "2016": 7.097873061829407,
              "2017": 32.66356398692973,
              "2018": -0.1261872848003387,
              "2019": 38.96148867401177,
              "2020": 48.40613905970732,
              "2021": 27.419752599682656,
              "2022": -32.57700076485729,
              "2023": 54.855558053065856,
              "2024": 25.578260586229582,
              "2025": 20.772551391310824,
              "2026": 16.982293247335956
            }
          }
        },
        "cash": {
          "10bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          },
          "20bps": {
            "first": "2010-01-04",
            "last": "2026-10-20",
            "sessions": 4225,
            "return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_dd_close_pct": 0.0,
            "daily_low_dd_from_prior_close_peak_pct": 0.0,
            "trades": 0,
            "forced_final_trades": 0,
            "profit_factor": null,
            "exposure_pct": 0.0,
            "worst_year_pct": 0.0,
            "yearly_returns_pct": {
              "2010": 0.0,
              "2011": 0.0,
              "2012": 0.0,
              "2013": 0.0,
              "2014": 0.0,
              "2015": 0.0,
              "2016": 0.0,
              "2017": 0.0,
              "2018": 0.0,
              "2019": 0.0,
              "2020": 0.0,
              "2021": 0.0,
              "2022": 0.0,
              "2023": 0.0,
              "2024": 0.0,
              "2025": 0.0,
              "2026": 0.0
            }
          }
        }
      }
    }
  }
}
````

### FILE `vix/results.json`

````json
{
  "portfolios": {
    "10bps": {
      "all": {
        "crypto100": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 12.140377186626756,
          "CAGR": 0.33381584689043753,
          "max_drawdown": -0.8672552237354227,
          "worst_month": -0.40780231660614596,
          "worst_month_date": "2022-06",
          "losing_full_months": 49,
          "full_month_count": 106,
          "annualized_volatility": 0.698160220096055,
          "final_wealth": 13.140377186626756,
          "fees_in_initial_capital_units": 0.05372969640145417,
          "annualized_one_way_turnover": 0.9404518871434382,
          "rebalance_count_including_initial": 108
        },
        "crypto90_cash10": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 11.660363055761557,
          "CAGR": 0.32827648695016687,
          "max_drawdown": -0.8298664348307653,
          "worst_month": -0.3672397712618929,
          "worst_month_date": "2022-06",
          "losing_full_months": 50,
          "full_month_count": 106,
          "annualized_volatility": 0.6271205112351799,
          "final_wealth": 12.660363055761557,
          "fees_in_initial_capital_units": 0.04744739344694448,
          "annualized_one_way_turnover": 0.8697074901662665,
          "rebalance_count_including_initial": 108
        },
        "crypto90_VIXY10": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 9.424926426865557,
          "CAGR": 0.299729231329259,
          "max_drawdown": -0.8124670990563159,
          "worst_month": -0.362838975709076,
          "worst_month_date": "2022-06",
          "losing_full_months": 46,
          "full_month_count": 106,
          "annualized_volatility": 0.6297679076944823,
          "final_wealth": 10.424926426865557,
          "fees_in_initial_capital_units": 0.06056178738756017,
          "annualized_one_way_turnover": 1.1876131105105965,
          "rebalance_count_including_initial": 108
        }
      },
      "development": {
        "crypto100": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.23439182444646467,
          "CAGR": -0.11741914384877539,
          "max_drawdown": -0.8672552237354227,
          "worst_month": -0.37514036240753734,
          "worst_month_date": "2018-03",
          "losing_full_months": 14,
          "full_month_count": 25,
          "annualized_volatility": 0.8062785354137352,
          "final_wealth": 0.7656081755535353,
          "fees_in_initial_capital_units": 0.004867648640453679,
          "annualized_one_way_turnover": 2.005520122581818,
          "rebalance_count_including_initial": 26
        },
        "crypto90_cash10": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.14871478113442083,
          "CAGR": -0.07253204277353065,
          "max_drawdown": -0.8298664348307653,
          "worst_month": -0.3383948557154558,
          "worst_month_date": "2018-03",
          "losing_full_months": 14,
          "full_month_count": 25,
          "annualized_volatility": 0.7249255204344136,
          "final_wealth": 0.8512852188655792,
          "fees_in_initial_capital_units": 0.004507503297177406,
          "annualized_one_way_turnover": 1.8244256771624812,
          "rebalance_count_including_initial": 26
        },
        "crypto90_VIXY10": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.17054443057398205,
          "CAGR": -0.08373142934369093,
          "max_drawdown": -0.8124670990563159,
          "worst_month": -0.3368265859198444,
          "worst_month_date": "2018-11",
          "losing_full_months": 13,
          "full_month_count": 25,
          "annualized_volatility": 0.7234467602923674,
          "final_wealth": 0.829455569426018,
          "fees_in_initial_capital_units": 0.005571413389194732,
          "annualized_one_way_turnover": 2.213108579945951,
          "rebalance_count_including_initial": 26
        }
      },
      "validation": {
        "crypto100": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 4.205488240164283,
          "CAGR": 0.7354673543260868,
          "max_drawdown": -0.7613660887642999,
          "worst_month": -0.4078023166061463,
          "worst_month_date": "2022-06",
          "losing_full_months": 15,
          "full_month_count": 35,
          "annualized_volatility": 0.8042285398092248,
          "final_wealth": 5.205488240164283,
          "fees_in_initial_capital_units": 0.023696194164861416,
          "annualized_one_way_turnover": 1.4345473766957706,
          "rebalance_count_including_initial": 36
        },
        "crypto90_cash10": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 3.855114698549663,
          "CAGR": 0.6955240380630014,
          "max_drawdown": -0.7143944792099122,
          "worst_month": -0.3672397712618931,
          "worst_month_date": "2022-06",
          "losing_full_months": 16,
          "full_month_count": 35,
          "annualized_volatility": 0.7213333464626228,
          "final_wealth": 4.855114698549663,
          "fees_in_initial_capital_units": 0.01937917243583794,
          "annualized_one_way_turnover": 1.3190939308808607,
          "rebalance_count_including_initial": 36
        },
        "crypto90_VIXY10": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 4.003288346459377,
          "CAGR": 0.712642922663145,
          "max_drawdown": -0.7163186654264438,
          "worst_month": -0.3628389757090762,
          "worst_month_date": "2022-06",
          "losing_full_months": 14,
          "full_month_count": 35,
          "annualized_volatility": 0.7285716355243355,
          "final_wealth": 5.003288346459377,
          "fees_in_initial_capital_units": 0.02897701211305509,
          "annualized_one_way_turnover": 1.7811744667870475,
          "rebalance_count_including_initial": 36
        }
      },
      "final": {
        "crypto100": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 2.3060471215635134,
          "CAGR": 0.3704075238649307,
          "max_drawdown": -0.6019470569861127,
          "worst_month": -0.24082632535741788,
          "worst_month_date": "2026-02",
          "losing_full_months": 20,
          "full_month_count": 44,
          "annualized_volatility": 0.5221392165477432,
          "final_wealth": 3.3060471215635134,
          "fees_in_initial_capital_units": 0.010126127157246204,
          "annualized_one_way_turnover": 0.9884872750154574,
          "rebalance_count_including_initial": 46
        },
        "crypto90_cash10": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 2.070430502442379,
          "CAGR": 0.34396537758079915,
          "max_drawdown": -0.5596760591778729,
          "worst_month": -0.21773602974806316,
          "worst_month_date": "2025-02",
          "losing_full_months": 20,
          "full_month_count": 44,
          "annualized_volatility": 0.4697126750140571,
          "final_wealth": 3.070430502442379,
          "fees_in_initial_capital_units": 0.008583306802473396,
          "annualized_one_way_turnover": 0.9086256611925506,
          "rebalance_count_including_initial": 46
        },
        "crypto90_VIXY10": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 1.5277319239228588,
          "CAGR": 0.2768173487023542,
          "max_drawdown": -0.5820664127327987,
          "worst_month": -0.21544077791537197,
          "worst_month_date": "2025-02",
          "losing_full_months": 19,
          "full_month_count": 44,
          "annualized_volatility": 0.47042177127521684,
          "final_wealth": 2.527731923922859,
          "fees_in_initial_capital_units": 0.009949345057591864,
          "annualized_one_way_turnover": 1.180273616847455,
          "rebalance_count_including_initial": 46
        }
      }
    },
    "20bps": {
      "all": {
        "crypto100": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 12.030309400603334,
          "CAGR": 0.3325617403882861,
          "max_drawdown": -0.8674304043372011,
          "worst_month": -0.4078569341126479,
          "worst_month_date": "2022-06",
          "losing_full_months": 50,
          "full_month_count": 106,
          "annualized_volatility": 0.6981633270615973,
          "final_wealth": 13.030309400603334,
          "fees_in_initial_capital_units": 0.1068236700976183,
          "annualized_one_way_turnover": 0.9403403901061658,
          "rebalance_count_including_initial": 108
        },
        "crypto90_cash10": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 11.562266218221113,
          "CAGR": 0.3271215412473967,
          "max_drawdown": -0.8300669133303065,
          "worst_month": -0.36729065683860485,
          "worst_month_date": "2022-06",
          "losing_full_months": 50,
          "full_month_count": 106,
          "annualized_volatility": 0.6271224278344112,
          "final_wealth": 12.562266218221113,
          "fees_in_initial_capital_units": 0.094377096358926,
          "annualized_one_way_turnover": 0.8696130522495776,
          "rebalance_count_including_initial": 108
        },
        "crypto90_VIXY10": {
          "start": "2017-11-10",
          "end": "2026-10-20",
          "total_return": 9.31477197651311,
          "CAGR": 0.2981861324046442,
          "max_drawdown": -0.8127507999085175,
          "worst_month": -0.36289846464077935,
          "worst_month_date": "2022-06",
          "losing_full_months": 46,
          "full_month_count": 106,
          "annualized_volatility": 0.6297677746469938,
          "final_wealth": 10.31477197651311,
          "fees_in_initial_capital_units": 0.12024989486709448,
          "annualized_one_way_turnover": 1.1875253019137282,
          "rebalance_count_including_initial": 108
        }
      },
      "development": {
        "crypto100": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.23766917806021137,
          "CAGR": -0.11918801888450847,
          "max_drawdown": -0.8674304043372011,
          "worst_month": -0.37522893886412,
          "worst_month_date": "2018-03",
          "losing_full_months": 14,
          "full_month_count": 25,
          "annualized_volatility": 0.8062910334908299,
          "final_wealth": 0.7623308219397886,
          "fees_in_initial_capital_units": 0.009716990521991533,
          "annualized_one_way_turnover": 2.005053862244135,
          "rebalance_count_including_initial": 26
        },
        "crypto90_cash10": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.15203032660454596,
          "CAGR": -0.07422310646482544,
          "max_drawdown": -0.8300669133303065,
          "worst_month": -0.3384782411697538,
          "worst_month_date": "2018-03",
          "losing_full_months": 14,
          "full_month_count": 25,
          "annualized_volatility": 0.7249349063867275,
          "final_wealth": 0.847969673395454,
          "fees_in_initial_capital_units": 0.008999207810173757,
          "annualized_one_way_turnover": 1.824044889188514,
          "rebalance_count_including_initial": 26
        },
        "crypto90_VIXY10": {
          "start": "2017-11-10",
          "end": "2019-12-31",
          "total_return": -0.17446184324444902,
          "CAGR": -0.08575774071279074,
          "max_drawdown": -0.8127507999085175,
          "worst_month": -0.3368900759398902,
          "worst_month_date": "2018-11",
          "losing_full_months": 13,
          "full_month_count": 25,
          "annualized_volatility": 0.7234622393754103,
          "final_wealth": 0.825538156755551,
          "fees_in_initial_capital_units": 0.011119330708017927,
          "annualized_one_way_turnover": 2.2126776755194197,
          "rebalance_count_including_initial": 26
        }
      },
      "validation": {
        "crypto100": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 4.183182205863317,
          "CAGR": 0.732978731490356,
          "max_drawdown": -0.7615291402806403,
          "worst_month": -0.40785693411264745,
          "worst_month_date": "2022-06",
          "losing_full_months": 16,
          "full_month_count": 35,
          "annualized_volatility": 0.8042229092931628,
          "final_wealth": 5.183182205863317,
          "fees_in_initial_capital_units": 0.047274653582203965,
          "annualized_one_way_turnover": 1.4342142117152306,
          "rebalance_count_including_initial": 36
        },
        "crypto90_cash10": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 3.8359819138191824,
          "CAGR": 0.6932883334035023,
          "max_drawdown": -0.7145771868332398,
          "worst_month": -0.36729065683860507,
          "worst_month_date": "2022-06",
          "losing_full_months": 16,
          "full_month_count": 35,
          "annualized_volatility": 0.7213262955384461,
          "final_wealth": 4.835981913819182,
          "fees_in_initial_capital_units": 0.03866987789038656,
          "annualized_one_way_turnover": 1.318822523855997,
          "rebalance_count_including_initial": 36
        },
        "crypto90_VIXY10": {
          "start": "2020-01-02",
          "end": "2022-12-30",
          "total_return": 3.9766836113977897,
          "CAGR": 0.70959431323413,
          "max_drawdown": -0.716606589094408,
          "worst_month": -0.36289846464077924,
          "worst_month_date": "2022-06",
          "losing_full_months": 14,
          "full_month_count": 35,
          "annualized_volatility": 0.7285578985311466,
          "final_wealth": 4.97668361139779,
          "fees_in_initial_capital_units": 0.057773834171801264,
          "annualized_one_way_turnover": 1.7807927587574486,
          "rebalance_count_including_initial": 36
        }
      },
      "final": {
        "crypto100": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 2.293665284532023,
          "CAGR": 0.3690531340125758,
          "max_drawdown": -0.6020343617640782,
          "worst_month": -0.24087852086904304,
          "worst_month_date": "2026-02",
          "losing_full_months": 20,
          "full_month_count": 44,
          "annualized_volatility": 0.5221558139818081,
          "final_wealth": 3.293665284532023,
          "fees_in_initial_capital_units": 0.020209691123982895,
          "annualized_one_way_turnover": 0.988224541015652,
          "rebalance_count_including_initial": 46
        },
        "crypto90_cash10": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 2.0598591457106545,
          "CAGR": 0.3427444526134136,
          "max_drawdown": -0.5598340052303447,
          "worst_month": -0.21780239791656064,
          "worst_month_date": "2025-02",
          "losing_full_months": 20,
          "full_month_count": 44,
          "annualized_volatility": 0.46972881941309974,
          "final_wealth": 3.0598591457106545,
          "fees_in_initial_capital_units": 0.01713342469869424,
          "annualized_one_way_turnover": 0.9084059717424742,
          "rebalance_count_including_initial": 46
        },
        "crypto90_VIXY10": {
          "start": "2023-01-03",
          "end": "2026-10-20",
          "total_return": 1.51643126359866,
          "CAGR": 0.2753106171188715,
          "max_drawdown": -0.5822947844490496,
          "worst_month": -0.21550888934437085,
          "worst_month_date": "2025-02",
          "losing_full_months": 19,
          "full_month_count": 44,
          "annualized_volatility": 0.4704385361715236,
          "final_wealth": 2.51643126359866,
          "fees_in_initial_capital_units": 0.019850811416485467,
          "annualized_one_way_turnover": 1.180086209319893,
          "rebalance_count_including_initial": 46
        }
      }
    }
  },
  "cost_note": "10 or 20bps of actual traded notional per side; all returns net of modeled costs, VIXY historical prices already include roll/fund fees",
  "not_live_bot": "BTC/ETH buy-and-hold proxy only, cannot infer hedge of grid realized+unrealized P&L",
  "periods": {
    "all": [
      "2017-11-10",
      "2026-10-20"
    ],
    "development": [
      "2017-11-10",
      "2019-12-31"
    ],
    "validation": [
      "2020-01-01",
      "2022-12-31"
    ],
    "final": [
      "2023-01-01",
      "2026-10-20"
    ]
  },
  "execution_limitation": "Asynchronous mark allocation diagnostic, not a synchronous executable strategy. Mixed crypto prior-UTC-close and ETF US-close marks cannot literally execute simultaneous target weights; need synchronized hourly crypto marks before adoption.",
  "ten_worst_crypto_months": [
    {
      "month": "2022-06",
      "crypto100": -0.4078023166,
      "crypto90_cash10": -0.3672397713,
      "crypto90_VIXY10": -0.3628389757,
      "VIXY_standalone_before_transaction_cost": 0.0434534384,
      "VIXY_minus_cash_control": 0.0044007956
    },
    {
      "month": "2018-03",
      "crypto100": -0.3751403624,
      "crypto90_cash10": -0.3383948557,
      "crypto90_VIXY10": -0.3303861698,
      "VIXY_standalone_before_transaction_cost": 0.0670482598,
      "VIXY_minus_cash_control": 0.0080086859
    },
    {
      "month": "2018-11",
      "crypto100": -0.3647890583,
      "crypto90_cash10": -0.3283591737,
      "crypto90_VIXY10": -0.3368265859,
      "VIXY_standalone_before_transaction_cost": -0.083360219,
      "VIXY_minus_cash_control": -0.0084674122
    },
    {
      "month": "2020-03",
      "crypto100": -0.3417424356,
      "crypto90_cash10": -0.3085788924,
      "crypto90_VIXY10": -0.2051526428,
      "VIXY_standalone_before_transaction_cost": 1.0132696395,
      "VIXY_minus_cash_control": 0.1034262496
    },
    {
      "month": "2018-08",
      "crypto100": -0.2628164691,
      "crypto90_cash10": -0.2379969017,
      "crypto90_VIXY10": -0.2454138329,
      "VIXY_standalone_before_transaction_cost": -0.0749613401,
      "VIXY_minus_cash_control": -0.0074169312
    },
    {
      "month": "2022-05",
      "crypto100": -0.2614379904,
      "crypto90_cash10": -0.2357172328,
      "crypto90_VIXY10": -0.2500976095,
      "VIXY_standalone_before_transaction_cost": -0.1522055681,
      "VIXY_minus_cash_control": -0.0143803767
    },
    {
      "month": "2022-01",
      "crypto100": -0.2469641529,
      "crypto90_cash10": -0.2221427593,
      "crypto90_VIXY10": -0.2042496208,
      "VIXY_standalone_before_transaction_cost": 0.1522742687,
      "VIXY_minus_cash_control": 0.0178931385
    },
    {
      "month": "2026-02",
      "crypto100": -0.2408263254,
      "crypto90_cash10": -0.2175660337,
      "crypto90_VIXY10": -0.2133296887,
      "VIXY_standalone_before_transaction_cost": 0.0430550942,
      "VIXY_minus_cash_control": 0.004236345
    },
    {
      "month": "2025-02",
      "crypto100": -0.2401513508,
      "crypto90_cash10": -0.2177360297,
      "crypto90_VIXY10": -0.2154407779,
      "VIXY_standalone_before_transaction_cost": 0.0322804141,
      "VIXY_minus_cash_control": 0.0022952518
    },
    {
      "month": "2018-06",
      "crypto100": -0.2236569949,
      "crypto90_cash10": -0.2011503142,
      "crypto90_VIXY10": -0.200259166,
      "VIXY_standalone_before_transaction_cost": -0.0013088805,
      "VIXY_minus_cash_control": 0.0008911482
    }
  ],
  "monthly_correlations": {
    "crypto100": {
      "crypto100": 1.0,
      "crypto90_cash10": 0.9999527192012344,
      "crypto90_VIXY10": 0.9951902466040538
    },
    "crypto90_cash10": {
      "crypto100": 0.9999527192012344,
      "crypto90_cash10": 1.0,
      "crypto90_VIXY10": 0.9953246143126936
    },
    "crypto90_VIXY10": {
      "crypto100": 0.9951902466040538,
      "crypto90_cash10": 0.9953246143126936,
      "crypto90_VIXY10": 1.0
    }
  },
  "crypto_vs_VIXY_monthly_return_correlation": -0.2744258092177683,
  "10_worst_months_summary": {
    "VIXY_beats_cash_count": 7,
    "mean_return_crypto100": -0.2965327456466864,
    "mean_return_cash_control": -0.2674881964593545,
    "mean_return_VIXY": -0.2563995070160319,
    "mean_VIXY_minus_cash_control_pp": 1.1088689443322586
  },
  "standalone_VIXY": {
    "start": "2017-11-10",
    "end": "2026-10-20",
    "total_return_before_transaction_cost": -0.9927076121927545,
    "CAGR_before_transaction_cost": -0.42323223256327225
  }
}
````

### FILE `vix/results_gld_diagnostic.json`

````json
{
  "status": "Exploratory diagnostic proposed after original VIXY results; no tuning, not unseen validation",
  "data": {
    "first": "2015-01-02",
    "last": "2026-10-20",
    "rows": 2967,
    "raw_sha256": "4bd95a7b0ab5f00f2f28e84f4c6aa9e5c1d1b812fcb18ae0f02859286d48bb2f",
    "source": "https://query1.finance.yahoo.com/v8/finance/chart/GLD?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
    "protocol_sha256": "f60cc32a6f7d8bf26611b3752837b055095452760c67e15c07c00ff6bd89450e"
  },
  "portfolios": {
    "10bps": {
      "all": {
        "start": "2017-11-10",
        "end": "2026-10-20",
        "total_return": 13.179199961139906,
        "CAGR": 0.3452135389151163,
        "max_drawdown": -0.8306721549859419,
        "worst_month": -0.36892768662017894,
        "worst_month_date": "2022-06",
        "losing_full_months": 48,
        "full_month_count": 106,
        "annualized_volatility": 0.6273920989891456,
        "final_wealth": 14.179199961139906,
        "fees_in_initial_capital_units": 0.0629418011089123,
        "annualized_one_way_turnover": 1.0758716040236789,
        "rebalance_count_including_initial": 108
      },
      "development": {
        "start": "2017-11-10",
        "end": "2019-12-31",
        "total_return": -0.1352046587345126,
        "CAGR": -0.06567732250525693,
        "max_drawdown": -0.8306721549859419,
        "worst_month": -0.3377709693490669,
        "worst_month_date": "2018-03",
        "losing_full_months": 14,
        "full_month_count": 25,
        "annualized_volatility": 0.7248743211089317,
        "final_wealth": 0.8647953412654874,
        "fees_in_initial_capital_units": 0.005283282815005406,
        "annualized_one_way_turnover": 2.142871504518076,
        "rebalance_count_including_initial": 26
      },
      "validation": {
        "start": "2020-01-02",
        "end": "2022-12-30",
        "total_return": 3.910959854164455,
        "CAGR": 0.702016291136178,
        "max_drawdown": -0.7157627984348645,
        "worst_month": -0.36892768662017883,
        "worst_month_date": "2022-06",
        "losing_full_months": 14,
        "full_month_count": 35,
        "annualized_volatility": 0.7221139280317779,
        "final_wealth": 4.910959854164455,
        "fees_in_initial_capital_units": 0.02420811057519417,
        "annualized_one_way_turnover": 1.5983464897367656,
        "rebalance_count_including_initial": 36
      },
      "final": {
        "start": "2023-01-03",
        "end": "2026-10-20",
        "total_return": 2.339433959568648,
        "CAGR": 0.3740410261208773,
        "max_drawdown": -0.5564927499916511,
        "worst_month": -0.21574831386762572,
        "worst_month_date": "2025-02",
        "losing_full_months": 20,
        "full_month_count": 44,
        "annualized_volatility": 0.46968647426235,
        "final_wealth": 3.339433959568648,
        "fees_in_initial_capital_units": 0.011055384928113136,
        "annualized_one_way_turnover": 1.098382744341404,
        "rebalance_count_including_initial": 46
      }
    },
    "20bps": {
      "all": {
        "start": "2017-11-10",
        "end": "2026-10-20",
        "total_return": 13.04341772620793,
        "CAGR": 0.3437667615154929,
        "max_drawdown": -0.8309154812794848,
        "worst_month": -0.36899564044720334,
        "worst_month_date": "2022-06",
        "losing_full_months": 48,
        "full_month_count": 106,
        "annualized_volatility": 0.6273938036876228,
        "final_wealth": 14.04341772620793,
        "fees_in_initial_capital_units": 0.1250237699399659,
        "annualized_one_way_turnover": 1.0757380338022207,
        "rebalance_count_including_initial": 108
      },
      "development": {
        "start": "2017-11-10",
        "end": "2019-12-31",
        "total_return": -0.13915951153752848,
        "CAGR": -0.0676779844038774,
        "max_drawdown": -0.8309154812794848,
        "worst_month": -0.33786019407604007,
        "worst_month_date": "2018-03",
        "losing_full_months": 14,
        "full_month_count": 25,
        "annualized_volatility": 0.7248868084007934,
        "final_wealth": 0.8608404884624715,
        "fees_in_initial_capital_units": 0.010544760272315074,
        "annualized_one_way_turnover": 2.142403868445564,
        "rebalance_count_including_initial": 26
      },
      "validation": {
        "start": "2020-01-02",
        "end": "2022-12-30",
        "total_return": 3.887520338872429,
        "CAGR": 0.6992973583593329,
        "max_drawdown": -0.7160041553393477,
        "worst_month": -0.36899564044720357,
        "worst_month_date": "2022-06",
        "losing_full_months": 15,
        "full_month_count": 35,
        "annualized_volatility": 0.7221020583440125,
        "final_wealth": 4.887520338872429,
        "fees_in_initial_capital_units": 0.04828109386130034,
        "annualized_one_way_turnover": 1.597972315814377,
        "rebalance_count_including_initial": 36
      },
      "final": {
        "start": "2023-01-03",
        "end": "2026-10-20",
        "total_return": 2.325540340519975,
        "CAGR": 0.3725322432028242,
        "max_drawdown": -0.5566563669087877,
        "worst_month": -0.21582288585067677,
        "worst_month_date": "2025-02",
        "losing_full_months": 20,
        "full_month_count": 44,
        "annualized_volatility": 0.4697062890208248,
        "final_wealth": 3.325540340519975,
        "fees_in_initial_capital_units": 0.022058266133577868,
        "annualized_one_way_turnover": 1.0980988669609735,
        "rebalance_count_including_initial": 46
      }
    }
  },
  "execution_limitation": "Mixed timestamp marks are a valuation approximation and cannot literally execute target rebalance at both marks; need synchronized hourly crypto marks before adoption.",
  "monthly_correlations": {
    "crypto90_GLD10": {
      "crypto90_GLD10": 1.0,
      "GLD_standalone": 0.12743569010793504,
      "crypto100": 0.9996981980697999
    },
    "GLD_standalone": {
      "crypto90_GLD10": 0.12743569010793504,
      "GLD_standalone": 1.0,
      "crypto100": 0.10541789679935416
    },
    "crypto100": {
      "crypto90_GLD10": 0.9996981980697999,
      "GLD_standalone": 0.10541789679935416,
      "crypto100": 1.0
    }
  },
  "10_worst_months_summary": {
    "GLD_beats_cash_count": 4,
    "mean_return_GLD_portfolio": -0.2675849364915719,
    "mean_return_cash_control": -0.26748819645000005,
    "mean_GLD_minus_cash_control_pp": -0.009674004157190497
  },
  "ten_worst_crypto_months": [
    {
      "month": "2022-06",
      "crypto100": -0.4078023166,
      "crypto90_cash10": -0.3672397713,
      "crypto90_VIXY10": -0.3628389757,
      "VIXY_standalone_before_transaction_cost": 0.0434534384,
      "VIXY_minus_cash_control": 0.0044007956,
      "crypto90_GLD10": -0.3689276866,
      "GLD_standalone_before_transaction_cost": -0.0156596511,
      "GLD_minus_cash_control": -0.0016879153
    },
    {
      "month": "2018-03",
      "crypto100": -0.3751403624,
      "crypto90_cash10": -0.3383948557,
      "crypto90_VIXY10": -0.3303861698,
      "VIXY_standalone_before_transaction_cost": 0.0670482598,
      "VIXY_minus_cash_control": 0.0080086859,
      "crypto90_GLD10": -0.3377709693,
      "GLD_standalone_before_transaction_cost": 0.0063200073,
      "GLD_minus_cash_control": 0.0006238864
    },
    {
      "month": "2018-11",
      "crypto100": -0.3647890583,
      "crypto90_cash10": -0.3283591737,
      "crypto90_VIXY10": -0.3368265859,
      "VIXY_standalone_before_transaction_cost": -0.083360219,
      "VIXY_minus_cash_control": -0.0084674122,
      "crypto90_GLD10": -0.3283322958,
      "GLD_standalone_before_transaction_cost": 0.0033868813,
      "GLD_minus_cash_control": 2.68779e-05
    },
    {
      "month": "2020-03",
      "crypto100": -0.3417424356,
      "crypto90_cash10": -0.3085788924,
      "crypto90_VIXY10": -0.2051526428,
      "VIXY_standalone_before_transaction_cost": 1.013269639,
      "VIXY_minus_cash_control": 0.1034262496,
      "crypto90_GLD10": -0.3089611659,
      "GLD_standalone_before_transaction_cost": -0.0022240317,
      "GLD_minus_cash_control": -0.0003822735
    },
    {
      "month": "2018-08",
      "crypto100": -0.2628164691,
      "crypto90_cash10": -0.2379969017,
      "crypto90_VIXY10": -0.2454138329,
      "VIXY_standalone_before_transaction_cost": -0.0749613401,
      "VIXY_minus_cash_control": -0.0074169312,
      "crypto90_GLD10": -0.2399062366,
      "GLD_standalone_before_transaction_cost": -0.0213811171,
      "GLD_minus_cash_control": -0.0019093349
    },
    {
      "month": "2022-05",
      "crypto100": -0.2614379904,
      "crypto90_cash10": -0.2357172328,
      "crypto90_VIXY10": -0.2500976095,
      "VIXY_standalone_before_transaction_cost": -0.1522055681,
      "VIXY_minus_cash_control": -0.0143803767,
      "crypto90_GLD10": -0.2387614978,
      "GLD_standalone_before_transaction_cost": -0.0326154777,
      "GLD_minus_cash_control": -0.003044265
    },
    {
      "month": "2022-01",
      "crypto100": -0.2469641529,
      "crypto90_cash10": -0.2221427593,
      "crypto90_VIXY10": -0.2042496208,
      "VIXY_standalone_before_transaction_cost": 0.1522742687,
      "VIXY_minus_cash_control": 0.0178931385,
      "crypto90_GLD10": -0.2237939599,
      "GLD_standalone_before_transaction_cost": -0.0167876127,
      "GLD_minus_cash_control": -0.0016512006
    },
    {
      "month": "2026-02",
      "crypto100": -0.2408263254,
      "crypto90_cash10": -0.2175660337,
      "crypto90_VIXY10": -0.2133296887,
      "VIXY_standalone_before_transaction_cost": 0.0430550942,
      "VIXY_minus_cash_control": 0.004236345,
      "crypto90_GLD10": -0.2088364909,
      "GLD_standalone_before_transaction_cost": 0.0872007793,
      "GLD_minus_cash_control": 0.0087295428
    },
    {
      "month": "2025-02",
      "crypto100": -0.2401513508,
      "crypto90_cash10": -0.2177360297,
      "crypto90_VIXY10": -0.2154407779,
      "VIXY_standalone_before_transaction_cost": 0.0322804141,
      "VIXY_minus_cash_control": 0.0022952518,
      "crypto90_GLD10": -0.2157483139,
      "GLD_standalone_before_transaction_cost": 0.0182162419,
      "GLD_minus_cash_control": 0.0019877158
    },
    {
      "month": "2018-06",
      "crypto100": -0.2236569949,
      "crypto90_cash10": -0.2011503142,
      "crypto90_VIXY10": -0.200259166,
      "VIXY_standalone_before_transaction_cost": -0.0013088805,
      "VIXY_minus_cash_control": 0.0008911482,
      "crypto90_GLD10": -0.2048107482,
      "GLD_standalone_before_transaction_cost": -0.0361494476,
      "GLD_minus_cash_control": -0.003660434
    }
  ]
}
````

### FILE `vix/data_metadata.json`

````json
{
  "BTC-USD": {
    "source": "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
    "raw_sha256": "e2b2382c399132deec8b61014add97fb6f4c949a3b976287607c18f6925482b0",
    "rows": 4311,
    "first": "2015-01-01",
    "last": "2026-10-20",
    "invalid_prices": 0,
    "max_daily_return": 0.2524716942763181,
    "min_daily_return": -0.37169538560117077,
    "split_checks": [],
    "dividends": [],
    "exchange_timezone": "UTC",
    "currency": "USD"
  },
  "ETH-USD": {
    "source": "https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
    "raw_sha256": "8b440336baa5e2456a6767d2ba508afd305bc41dc06682be9e2ebb6c1499322f",
    "rows": 3268,
    "first": "2017-11-09",
    "last": "2026-10-20",
    "invalid_prices": 0,
    "max_daily_return": 0.2645807079346558,
    "min_daily_return": -0.42347221465293294,
    "split_checks": [],
    "dividends": [],
    "exchange_timezone": "UTC",
    "currency": "USD"
  },
  "VIXY": {
    "source": "https://query1.finance.yahoo.com/v8/finance/chart/VIXY?period1=1420070400&period2=1792540800&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
    "raw_sha256": "8ecca33483a133b988a45b6c8390a2ce6311842480fc6e6d978d8c5b365d21f5",
    "rows": 2967,
    "first": "2015-01-02",
    "last": "2026-10-20",
    "invalid_prices": 0,
    "max_daily_return": 0.4305105868635464,
    "min_daily_return": -0.20922372869678374,
    "split_checks": [
      {
        "date": "2016-07-25",
        "split": "1:5",
        "adj_return": -0.006738544474393482,
        "split_adjusted_close_return": -0.006738544474393482
      },
      {
        "date": "2017-07-17",
        "split": "1:4",
        "adj_return": -0.02675003051757807,
        "split_adjusted_close_return": -0.02675003051757807
      },
      {
        "date": "2021-05-26",
        "split": "1:4",
        "adj_return": -0.04701686214970213,
        "split_adjusted_close_return": -0.04701686214970213
      },
      {
        "date": "2023-06-23",
        "split": "1:5",
        "adj_return": 0.011809503464471627,
        "split_adjusted_close_return": 0.011809503464471627
      },
      {
        "date": "2024-11-07",
        "split": "1:4",
        "adj_return": -0.03059435669871613,
        "split_adjusted_close_return": -0.03059435669871613
      }
    ],
    "dividends": [],
    "exchange_timezone": "America/New_York",
    "currency": "USD"
  },
  "alignment": {
    "first": "2017-11-10",
    "last": "2026-10-20",
    "observations": 2246,
    "crypto_mark_lag_days": 1,
    "calendar": "Observed VIXY sessions; crypto marked at previous completed UTC day close",
    "weekend_return_example": "Monday crypto mark = Sunday UTC close; Friday mark = Thursday UTC close. Three calendar-day cumulative return therefore appears on Monday.",
    "max_session_gap_calendar_days": 4,
    "missing_prices_after_common_start": 0
  },
  "protocol_sha256": "11f4a309e82435b6ec4ffc993f5eda97c97d4cc1debfcf82080d0c013392d7c7",
  "download_note": "Fetched 2026-10-21; data truncated to complete 2026-10-20; Yahoo sometimes returned a 2026-10-21 crypto bar, which was discarded."
}
````

### FILE `vix/engine_checks.json`

````json
{
  "single_asset_entry_exit_exact_identity_9_cases": true,
  "flat_prices_cash_weights_exact_identity_9_cases": true,
  "independent_share_unit_monthly_rebalance_reference_2246_sessions": true,
  "tolerance_relative": 1e-12,
  "all_rows_components_plus_cash_equal_equity_including_terminal_exit": true
}
````

### FILE `vix/ten_worst_crypto_months.csv`

````csv
date,crypto100,crypto90_cash10,crypto90_VIXY10,VIXY_standalone_before_transaction_cost,VIXY_minus_cash_control
2022-06,-0.4078023166,-0.3672397713,-0.3628389757,0.04345343836,0.004400795553
2018-03,-0.3751403624,-0.3383948557,-0.3303861698,0.06704825978,0.008008685885
2018-11,-0.3647890583,-0.3283591737,-0.3368265859,-0.08336021904,-0.008467412181
2020-03,-0.3417424356,-0.3085788924,-0.2051526428,1.013269639,0.1034262496
2018-08,-0.2628164691,-0.2379969017,-0.2454138329,-0.07496134008,-0.007416931178
2022-05,-0.2614379904,-0.2357172328,-0.2500976095,-0.1522055681,-0.01438037669
2022-01,-0.2469641529,-0.2221427593,-0.2042496208,0.1522742687,0.01789313848
2026-02,-0.2408263254,-0.2175660337,-0.2133296887,0.04305509417,0.004236344977
2025-02,-0.2401513508,-0.2177360297,-0.2154407779,0.03228041412,0.002295251833
2018-06,-0.2236569949,-0.2011503142,-0.200259166,-0.001308880525,0.0008911481752
````

### FILE `vix/ten_worst_crypto_months_with_GLD.csv`

````csv
date,crypto100,crypto90_cash10,crypto90_VIXY10,VIXY_standalone_before_transaction_cost,VIXY_minus_cash_control,crypto90_GLD10,GLD_standalone_before_transaction_cost,GLD_minus_cash_control
2022-06,-0.4078023166,-0.3672397713,-0.3628389757,0.04345343836,0.004400795553,-0.3689276866,-0.01565965108,-0.00168791532
2018-03,-0.3751403624,-0.3383948557,-0.3303861698,0.06704825978,0.008008685885,-0.3377709693,0.006320007324,0.0006238863509
2018-11,-0.3647890583,-0.3283591737,-0.3368265859,-0.08336021904,-0.008467412181,-0.3283322958,0.003386881324,2.687792649e-05
2020-03,-0.3417424356,-0.3085788924,-0.2051526428,1.013269639,0.1034262496,-0.3089611659,-0.002224031677,-0.000382273531
2018-08,-0.2628164691,-0.2379969017,-0.2454138329,-0.07496134008,-0.007416931178,-0.2399062366,-0.02138111711,-0.001909334933
2022-05,-0.2614379904,-0.2357172328,-0.2500976095,-0.1522055681,-0.01438037669,-0.2387614978,-0.03261547766,-0.003044264965
2022-01,-0.2469641529,-0.2221427593,-0.2042496208,0.1522742687,0.01789313848,-0.2237939599,-0.01678761268,-0.001651200564
2026-02,-0.2408263254,-0.2175660337,-0.2133296887,0.04305509417,0.004236344977,-0.2088364909,0.08720077925,0.008729542771
2025-02,-0.2401513508,-0.2177360297,-0.2154407779,0.03228041412,0.002295251833,-0.2157483139,0.01821624188,0.001987715832
2018-06,-0.2236569949,-0.2011503142,-0.200259166,-0.001308880525,0.0008911481752,-0.2048107482,-0.03614944763,-0.003660433983
````

## Приложение B. Контрольные суммы файлов

```json
[
  {
    "file": "extract_report.py",
    "sha256_original_bytes": "9c7daa12fcf2f730912d80c3d58257afb5f01378b48c4132198ab81e4460f340",
    "sha256_extracted_lf_utf8": "9c7daa12fcf2f730912d80c3d58257afb5f01378b48c4132198ab81e4460f340"
  },
  {
    "file": "gold15/PROTOCOL.md",
    "sha256_original_bytes": "eee48c2a6f4dbee5b3d35cfd186f195bc3b4437e5f11a058559758c49b1a0b4a",
    "sha256_extracted_lf_utf8": "eee48c2a6f4dbee5b3d35cfd186f195bc3b4437e5f11a058559758c49b1a0b4a"
  },
  {
    "file": "gold15/fetch_data.py",
    "sha256_original_bytes": "dbd07ffc2d99fded4077b198980184a224afc1060cf78b88b1fc24f37a639b3f",
    "sha256_extracted_lf_utf8": "dbd07ffc2d99fded4077b198980184a224afc1060cf78b88b1fc24f37a639b3f"
  },
  {
    "file": "gold15/run_gold15.py",
    "sha256_original_bytes": "4a9939e64ca8c8f289a9ac8c0c28321cfbb6e8b2469c8f9fedbac61d1f375343",
    "sha256_extracted_lf_utf8": "4a9939e64ca8c8f289a9ac8c0c28321cfbb6e8b2469c8f9fedbac61d1f375343"
  },
  {
    "file": "gold15/test_engine.py",
    "sha256_original_bytes": "06de05de38d9adfb2a173608cc1e86b3cab987cf1cb9bf801ed5999f521cf354",
    "sha256_extracted_lf_utf8": "06de05de38d9adfb2a173608cc1e86b3cab987cf1cb9bf801ed5999f521cf354"
  },
  {
    "file": "index15/PROTOCOL.md",
    "sha256_original_bytes": "464e4688f0e830b4f132a9f2e4e04752d6b0d82e79e5b1f2320b3cbc651b668b",
    "sha256_extracted_lf_utf8": "464e4688f0e830b4f132a9f2e4e04752d6b0d82e79e5b1f2320b3cbc651b668b"
  },
  {
    "file": "index15/COST_SENSITIVITY.md",
    "sha256_original_bytes": "cea3f7dc574c4a7d663c9f8feedfb8e6c3e85fedbb4578abcc9f6d51d01417dc",
    "sha256_extracted_lf_utf8": "cea3f7dc574c4a7d663c9f8feedfb8e6c3e85fedbb4578abcc9f6d51d01417dc"
  },
  {
    "file": "index15/download.py",
    "sha256_original_bytes": "368f43eb5d836e1531b08672ac6019d2b08abd7810e0db5c2fd3c70fbbfc0da8",
    "sha256_extracted_lf_utf8": "368f43eb5d836e1531b08672ac6019d2b08abd7810e0db5c2fd3c70fbbfc0da8"
  },
  {
    "file": "index15/backtest.py",
    "sha256_original_bytes": "07bcc96c48952e45f997e24c16601ac3a896060f09d3733aa0fbc5122f0a74b6",
    "sha256_extracted_lf_utf8": "07bcc96c48952e45f997e24c16601ac3a896060f09d3733aa0fbc5122f0a74b6"
  },
  {
    "file": "index15/check_engine.py",
    "sha256_original_bytes": "a8b79864f356b0560409309a9aef0537d831073cb1153647214d321ae1081883",
    "sha256_extracted_lf_utf8": "a8b79864f356b0560409309a9aef0537d831073cb1153647214d321ae1081883"
  },
  {
    "file": "daily/PROTOCOL.md",
    "sha256_original_bytes": "d69dd4584e767bf1233b628abccae1dd1e41b4486ee2b65e4b018c33866a8ea9",
    "sha256_extracted_lf_utf8": "d69dd4584e767bf1233b628abccae1dd1e41b4486ee2b65e4b018c33866a8ea9"
  },
  {
    "file": "daily/run_daily.py",
    "sha256_original_bytes": "ced17bbdd719982905550eab49b93e7649d395d4e85ab0bf36e1cdbaa22f668f",
    "sha256_extracted_lf_utf8": "ced17bbdd719982905550eab49b93e7649d395d4e85ab0bf36e1cdbaa22f668f"
  },
  {
    "file": "vix/PROTOCOL.md",
    "sha256_original_bytes": "11f4a309e82435b6ec4ffc993f5eda97c97d4cc1debfcf82080d0c013392d7c7",
    "sha256_extracted_lf_utf8": "11e369afa37d11f5179d33e47540355866c34b3e55de3c312bf3fc298600e55e"
  },
  {
    "file": "vix/PROTOCOL_GLD_DIAGNOSTIC.md",
    "sha256_original_bytes": "f60cc32a6f7d8bf26611b3752837b055095452760c67e15c07c00ff6bd89450e",
    "sha256_extracted_lf_utf8": "737dd381fcc1731ae88f6178d802a1b4b47585a269299507bb8790e4a490720d"
  },
  {
    "file": "vix/download.py",
    "sha256_original_bytes": "5e3a8fff14198565fbf9cc2757a28de5d35e15b108343ac011cb98e6feae6847",
    "sha256_extracted_lf_utf8": "d2e3b9f32c43a4735f9a3591a1f79a7bacdf62583f766987f539e42261e47f7d"
  },
  {
    "file": "vix/download_gld.py",
    "sha256_original_bytes": "0ce3eb60a5575c8a5a0abd98a42a5e86d598eda59eba8a32b16e5798d7ed619e",
    "sha256_extracted_lf_utf8": "452425a4b534e0b371ffa88fac758af79c2aa620104829aed4129bdb5b2613f5"
  },
  {
    "file": "vix/analyze.py",
    "sha256_original_bytes": "a4d22dd28b0c4638839f64f245636353e147934f878dc6d894d9a6fc4e820b8c",
    "sha256_extracted_lf_utf8": "3a19c558f3796e65bcec2796a32c5598615f765c65bd0fc5f57b76c9a3e53cdf"
  },
  {
    "file": "vix/analyze_gld_diagnostic.py",
    "sha256_original_bytes": "018de164ec7c46850896b0edba91062a90e1d7f2c5884f370fe56e18857a5799",
    "sha256_extracted_lf_utf8": "62e3c900095850fd05dd117ad874de40d776da5e55dee83a7ed0838399b89d83"
  },
  {
    "file": "vix/check_engine.py",
    "sha256_original_bytes": "ef7065e53d682497bdc9a7ff1164c9951e7496468410c983c6230c62ef274cab",
    "sha256_extracted_lf_utf8": "5994389bcf858fc09e78d36e4e4edbc84dd408bd0de56639fe927248055cde8b"
  },
  {
    "file": "gold15/results.json",
    "sha256_original_bytes": "9d80bc61ed16301e907d539ded7f29d825a8b4647d04bf1a45086f3f3bbc652c",
    "sha256_extracted_lf_utf8": "4ec31334e89e27460304ee5eedb8cabc46abca0934d3e060a033c6715e0cb2d3"
  },
  {
    "file": "gold15/download_meta.json",
    "sha256_original_bytes": "b39fd9896bc04bf8798aaf0a46a3fe4535c9714d68be982755aab9cfdb1ae4c5",
    "sha256_extracted_lf_utf8": "8214882745200592367e597ca5857764af17fc62d8be6d682fa91edac28bf14d"
  },
  {
    "file": "gold15/audit_daily.json",
    "sha256_original_bytes": "1c974cea19472578bcf61f33dbc6f395e011f0af781e2b05760884c6b28d7853",
    "sha256_extracted_lf_utf8": "1c974cea19472578bcf61f33dbc6f395e011f0af781e2b05760884c6b28d7853"
  },
  {
    "file": "index15/results_frozen4_8.json",
    "sha256_original_bytes": "78e607448caf5cc12947d554ae513e64a9126d18ab15748c8546e09eceadd940",
    "sha256_extracted_lf_utf8": "e115b115365e21d98cc2c03c12f1afaa127e4910d77954df2154723cca5dc3d3"
  },
  {
    "file": "index15/results_comparable6_12.json",
    "sha256_original_bytes": "6df65ad13ac9759be6c61337b9dd0ee7fd9834ee0276b9a9d546f65488f918c6",
    "sha256_extracted_lf_utf8": "0e7884d6df61ce82ac67daa5883948e151d38c2a3ead10de679174daa17e0661"
  },
  {
    "file": "daily/results.json",
    "sha256_original_bytes": "b0c5aaaa7ad1fa3f94c074d61099be0eab02c1ae1b09b86dab804806704e08a7",
    "sha256_extracted_lf_utf8": "0ee48405a11925505e5a0465df13fc51c1430e7bc92265832de5d6648c1c49e7"
  },
  {
    "file": "vix/results.json",
    "sha256_original_bytes": "033b8f8ddbb3e217dd2b71e958ec9a1dc6d93a280ed0be92b1917b98b501a05c",
    "sha256_extracted_lf_utf8": "f0315d6664c024f652bdf6c2836184a805673f0cc233ed17974e2566b70d24a6"
  },
  {
    "file": "vix/results_gld_diagnostic.json",
    "sha256_original_bytes": "770ca03e0ffb18a9c888b8f6f0ca1207defc29331c55a3fe1b5adef7ef4fbe79",
    "sha256_extracted_lf_utf8": "7d3093b3f638f32f7625f2efc0c91ef6323bea7afd4efe8b016f87fab05a2117"
  },
  {
    "file": "vix/data_metadata.json",
    "sha256_original_bytes": "52866819ba8d393babb794c564eb4b68afe22423c0138d1645c4ebe9830d3446",
    "sha256_extracted_lf_utf8": "e272a8969f468880575bdaf62a83f17f3e1c5b847f670eb9d7bff6065d2026a4"
  },
  {
    "file": "vix/engine_checks.json",
    "sha256_original_bytes": "39430ff8688a93f58b61f08cd7265c9fdf2bab171b697c48d861dbb294d3d801",
    "sha256_extracted_lf_utf8": "9ed864300d8bd5ddbf3a3fcfc930fb2782ca6caa5f824d1c5ed1992c7f237599"
  },
  {
    "file": "vix/ten_worst_crypto_months.csv",
    "sha256_original_bytes": "b0aeab898aeced22aeb60cb410d7d180c7ad9d34e9c8313e6bff2bf99f627d61",
    "sha256_extracted_lf_utf8": "f17eb781930e2b4bb355cdbfb0187bc310ee661d1c76cc39f8ec51ae10ecd5b4"
  },
  {
    "file": "vix/ten_worst_crypto_months_with_GLD.csv",
    "sha256_original_bytes": "35f8ce09f1f1554336d01ceaf7bca34bac6095d5e20d6e1792f11ad6f0712c01",
    "sha256_extracted_lf_utf8": "915bc41dd5a3bf1923339487c7ab82169b25f9409b736f84d2bd467f664d5d78"
  }
]
```
