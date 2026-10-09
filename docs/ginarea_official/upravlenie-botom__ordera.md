> For the complete documentation index, see [llms.txt](https://ginareas-organization.gitbook.io/ginarea.org/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://ginareas-organization.gitbook.io/ginarea.org/upravlenie-botom/ordera.md).

# Ордера

На странице **«Ордера»** собраны все данные по открытым и закрытым ордерам за всё время работы бота.&#x20;

* При нажатии на галочку слева от имени бота загрузится полный список ордеров.
* Если активировать пункт **«Только открытые»**, уже закрытые ордера будут скрыты.
* Для закрытия отдельных ордеров бота, его необходимо сначала поставить на паузу, а затем нажать на крестик ❌<br>

  <figure><img src="https://350783642-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FtOJARNyb8xHRAoEXMfKw%2Fuploads%2FXTu9lrKsHvz8hWyKWTff%2Ftelegram-cloud-document-2-5404600971986766043.jpg?alt=media&amp;token=7b07023b-54e6-48d6-916d-2044a16eb7ee" alt=""><figcaption></figcaption></figure>

***

Поля статистики:

* **Side** — направление сделки (Buy или Sell).
* **InTime** — время открытия ордера.
* **InQuantity** — объём открытого ордера.
* **InPrice** — цена открытия ордера.
* **TriggerPrice** — цена срабатывания стоп-лосса.
* **OutTime** — время закрытия ордера.
* **OutQuantity** — объём закрытого ордера.
* **OutPrice** — цена закрытия ордера.
* **Elapsed** — время между открытием и закрытием ордера.
* **Profit**:
  * строка 1 — движение цены между InPrice и OutPrice.
  * строка 2 — реализованная прибыль/убыток по ордеру.

Обозначения причин закрытия каждого ордера:

• TargetDistance — ордер закрыт по целевому уровню прибыли

• FullClose — ордер закрыт при полном закрытии позиции

• SingleClose — отдельное закрытие ордера

• TakeProfit — закрытие по тейк-профиту

• StopLoss — закрытие по стоп-лоссу

• LiquidationSL — сработал стоп-лосс до ликвидации

• IndicatorOUT — закрытие по сигналу индикатора

• Trailing — закрытие по PNL Trailing

<br>

***

[Видео по статистике ботов](https://youtu.be/OcgZKtvOmNo?si=a5mey-vuZoVdfgda)[<br>](https://ginarea.gitbook.io/ginarea.org/upravlenie-botom/sposoby-ostanovki-bota-i-zakrytie-pozicii)
