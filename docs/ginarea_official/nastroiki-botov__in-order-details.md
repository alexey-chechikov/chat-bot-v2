> For the complete documentation index, see [llms.txt](https://ginareas-organization.gitbook.io/ginarea.org/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://ginareas-organization.gitbook.io/ginarea.org/nastroiki-botov/in-order-details.md).

# IN order details

<figure><img src="https://350783642-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FtOJARNyb8xHRAoEXMfKw%2Fuploads%2FYizJT520NlysJYGhIOIH%2Fimage.png?alt=media&amp;token=e9f9c58d-9318-44fc-9816-263453c394c0" alt=""><figcaption></figcaption></figure>

**Disable IN** — функция, которая позволяет прекратить выставление новых IN-ордеров, но бот продолжает работу с уже открытыми ордерами.

* При активации режима **Disable-IN**, бот перестает открывать новые IN-ордера. Это удобно, если вы хотите сохранить текущие позиции и дождаться закрытия существующих ордеров без открытия новых.
* Бот будет завершать активные триггеры и продолжит закрывать существующие позиции, но не будет открывать новых до тех пор, пока режим не будет отключен.

Этот режим может быть полезен, если вы ожидаете сильное движение рынка и хотите приостановить дальнейший набор позиции, но при этом сохранить возможность для закрытия текущих ордеров. [Видео Disable In](https://youtu.be/cOpPLQQje6Q?si=daNHUQVtJBKh97-v)

***

**Disable IN out of range** — это функция, которая позволяет боту прекратить открывать новые IN-ордера, если цена актива выходит за пределы заданного ценового диапазона.

* Когда активирован режим **Disable IN out of range**, бот прекратит выставление новых IN-ордеров после того, как цена актива выйдет за пределы диапазона ([Order trading range](/ginarea.org/nastroiki-botov/granicy-torgov.md) можно ограничить как нижней границей **From**, так и верхней **To)**
* Если цена вернется в диапазон, бот **не возобновит** выставление IN-ордеров автоматически. Бот останется в режиме **Disable IN** и дальнейшее выключение режима необходимо отключить в настройках бота.

Этот функционал сделан для того, чтобы бот не набирал позиции в условиях резких движений или при откатах, когда цена возвращается в диапазон после значительного движения. Также можно его использовать при торговле до определенных уровней.

[Видео Disable IN out of range](https://youtu.be/uUikw8GKqE8?si=r7YSrERxzG5WZxP5)

***

**Disable IN by AVG price** — при вклюенном режиме бот не будет создавать новые IN-ордера выше средней цены открытых IN-ордеров при торговле в LONG и ниже средней цены при торговле в SHORT.

При активации режима Disable IN by AVG price бот продолжит работать с уже выставленными ордерами и закрывать позиции по заданным условиям, но перестанет открывать новые IN-ордера, если цена находится в зоне, которая ухудшает среднюю точку входа.

Среднюю цену необходимо отслеживать в [сводной статистике](/ginarea.org/upravlenie-botom/statistika-grafik.md) **Average IN-Orders price**, для режима Dynamic Auto средняя рассчитывается отдельно для каждой стороны.

Функция доступна только для типов ботов: [Default](/ginarea.org/strategii-i-tipy-botov-ginarea/default-grid.md), [Dynamic](/ginarea.org/strategii-i-tipy-botov-ginarea/dynamic-grid.md) и [Indicator Grid](/ginarea.org/strategii-i-tipy-botov-ginarea/indicator-grid.md).
