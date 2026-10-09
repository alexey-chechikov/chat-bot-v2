> For the complete documentation index, see [llms.txt](https://ginareas-organization.gitbook.io/ginarea.org/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://ginareas-organization.gitbook.io/ginarea.org/nastroiki-botov/granicy-torgov.md).

# Границы торгов

<figure><img src="https://350783642-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FtOJARNyb8xHRAoEXMfKw%2Fuploads%2FrPvbccZAYvDDLJInLafh%2Fimage.png?alt=media&amp;token=600a18f9-dd4c-4a40-a29e-3a376a5375c8" alt=""><figcaption></figcaption></figure>

**Границы торгов** — диапазон, в котором бот будет создавать IN-ордера. При этом ордера могут быть закрыты за пределами этого диапазона.&#x20;

Диапазон может быть ограничен: только **нижней границей**, только **верхней** или **обеими**.&#x20;

Если диапазон не ограничен, IN-ордера будут созданы по любой цене актива.

***

**Disable IN вне границ** — это функция, которая позволяет боту прекратить открывать новые IN-ордера, если цена актива выходит за пределы заданного ценового диапазона:

* Когда активирован режим **Disable IN out of range**, бот прекратит выставление новых IN-ордеров после того, как цена актива выйдет за пределы **Границы торгов** можно ограничить как **нижней границей**, так и **верхней)**
* Если цена вернется в диапазон (**Границы торгов**), бот **не возобновит** выставление IN-ордеров автоматически. Бот останется в режиме **Disable IN** и дальнейшее выключение режима необходимо отключить в настройках бота.

Этот функционал сделан для того, чтобы бот не набирал позиции в условиях резких движений или при откатах, когда цена возвращается в диапазон после значительного движения. Также можно его использовать при торговле до определенных уровней.

[Активация Disable IN вне границ](https://www.youtube.com/watch?v=DmVLO6omcuA)

***

[Границы торгов](https://www.youtube.com/watch?v=GQnJEjVxEkQ)

[Примеры настроек Границы торгов](https://www.youtube.com/watch?v=grWbX3jC8cU\&t=29s)
