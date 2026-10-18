# Finite Binance public context — допущения до реализации

16.10.2026. Новый отдельный helper; archive_daily.py/README и другие агенты
не изменяются. Это один конечный запуск по явной команде, не daemon/collector,
WebSocket, periodic loop, Mac, CoinGlass API, счёт или ордер. Ключи не читаются.
Claude/Anthropic не используются. До проверки root сетевой запуск запрещён;
unit tests используют только выдуманные ответы.

Официальная схема проверена через документацию Binance перед кодом:

- [Spot klines](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market#klinecandlestick-data): массив OHLC, base volume [5], close time [6], quote volume [7], taker-buy base [9], quote [10]; UTC default.
- [USD-M market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data): /fapi/v1/time, /klines, /fundingRate, /premiumIndex.
- [OI statistics](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#open-interest-statistics): timestamp конца периода, история ограничена последним месяцем; публикационный lag не указан.
- [Server time](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/general#check-server-time): публичный /api/v3/time.

По уточнению root план запросов фиксирован: futures clock + spot klines + perp
klines + OI15m + funding24h = **5 GET**, optional premiumIndex = **6 GET**.
Жёсткий budget6 GET; redirects запрещены, retries/pagination loops отсутствуют. Timeout8s на
запрос, max body2MiB. Это ограничение вызовов/сокета, не гарантия wallclock для
любой ОС/DNS. Ошибка не запускает повтор и не скрывает остальные источники.

96 полных UTC15m свечей берутся за 24h до последней закрытой границы futures
server clock. Для spot это явно общий futures UTC-anchor, не измеренная
синхронность двух серверов; отдельного spot-clock GET нет. При отказе clock
зависимые источники остаются MISSING. Локальное
время не заменяет provider clock для выбора закрытых баров. OI — до97 точек на
границах этого окна, с явной проверкой сетки. Funding — фактически наблюдаемые
события за последние24h по futures server clock; количество/период8h не
предполагаются. Premium current snapshot хранится отдельно от closed bars.

Отдельно хранятся реальные request/receive UTC ms, URL, provider event time и
provider_lag_ms=null/lag_status=unknown. Это не исторический receive. Clock age
не превращается в измерение публикационного lag. Время запуска/архивации не
передаётся CLI задним числом.

delta_base = 2*taker_buy_base − base_volume, F = delta_base/base_volume;
buy/sell shares — доли base-volume. При нулевом реальном объёме shares/F=null.
Нет оценки дельты по цвету, CVD-level как flow, подстановки missing→0 или
восстановления пропусков. Изолированные неверные строки исключаются с причинами,
дубликаты неоднозначны и не выбираются произвольно; usable rows/пропуски видны.

Выход — отдельный совместимый daily-as-seen-v1 fragment и evidence/... с точными
raw bytes/JSON и audit каждого запроса. FAILED/MISSING не содержат наблюдённых
значений, но сохраняют URL/ошибки/coverage/evidence. Оригинальные единицы OI и
денежная оценка разделены; размер единицы OI не угадывается по текущей цене.
Ордера, прогнозы и trade-primary labels всегда отсутствуют.

Код готов к проверенному одноразовому запуску root. **Рыночная сеть из этой
подзадачи ещё не запускалась**; просмотрена только официальная документация.

## CLI после проверки root

```powershell
python -B C:/bot7/research/coinglass_daily_context_20261016/fetch_public_context.py --run-network --include-premium --outdir C:/bot7/research/coinglass_daily_context_20261016/local/preflight_1792161145457
```

Без --run-network ни клиент, ни запросы не создаются. --include-premium означает
ровно шестой endpoint; без него план5 GET. При отказе clock будет только один
GET и явные MISSING dependent sources. При отказах остальных endpoint проверки
продолжаются по оставшемуся конечному плану. Provider clock, отличающийся от
реального локального времени начала более чем на5min, также не используется:
не делаем древний/будущий запрос по очевидно несогласованным часам.

Outdir может уже содержать UI evidence root; helper добавляет только собственные
новые evidence/binance_...raw.json (либо raw.body при не-JSON) и request.json,
затем **public_sources.json**. Существующие файлы не перезаписываются. В raw
evidence — точные bytes ответа; request audit отдельно сохраняет ошибки/HTTP,
фактическое время отправки/получения и SHA этих bytes. При транспортной ошибке
пустой raw-body отражает отсутствие ответа, а не рыночный ноль.

public_sources.json сам совместим с daily-as-seen-v1, но предназначен для
слияния с UI sources root. При merge сохранять все source objects и их settings,
реальные границы collected/finished и relative evidence paths; не изменять
event_asof/request/receive. Root может задать общий collected=min(actual starts)
и finished=max(actual finishes) для совместного прохода, без выдуманной
синхронности. archive_daily.py создаёт окончательную immutable запись отдельно.

Нормализованные decimals внутри typed JSON представлены строками, F и shares
— fraction, а не проценты. OI unit остаётся provider-native: текущий размер
контракта не угадывается; количество и provider-reported notional не смешиваются.
Funding — наблюдённые исторические ставки (включая различие Regular/Special,
если поставщик передал), не расчёт расходов пользователя/WEEX. Premium —
current mark/index/funding context, не closing bar и не executable quote.

## Offline verification

```powershell
python -B -m unittest discover -s C:/bot7/research/coinglass_daily_context_20261016 -p test_fetch_public_context.py -v
```

25 meaningful tests прошли: закрытость/UTC boundary, 96 и97 grid, delta и доли,
нулевой объём, gaps/duplicates/out-of-order, невалидные цены/NaN, отдельные OI
единицы, funding/empty/missing mark/Regular+Special, premium scope, 5/6 GET,
no retry после429/timeout, clock failure без local fallback, реальные по injected
clock request/receive отдельно от event time, raw SHA, существующий UI evidence,
структурная совместимость archive_daily, запрет overwrite и network opt-in,
allowlist/private endpoint refusal, budget и socket timeout. Это проверка
синтетического транспорта, не live-доступности Binance или текущей tzdata ОС.

Output guard проверяет root и его ancestors, evidence root и каждый вложенный
parent по resolved пути и Windows FILE_ATTRIBUTE_REPARSE_POINT. Symlinks/junctions
отвергаются, включая redirects внутри того же дерева. Проверка выполняется до
создания клиента/первого GET, снова после сети до любых записей и перед каждой
записью. Mocked tests закрывают root/evidence escape, nested escape и reparse
flags без действительных junctions/привилегий ОС. Это проверки namespace перед
операциями; защита от произвольной враждебной конкурентной замены каталога между
проверкой и open не заявляется. Root отдельно проверяет общий VERIFIED_FILES
manifest перед сетью; helper не создаёт/не подменяет такой manifest.
