> For the complete documentation index, see [llms.txt](https://ginareas-organization.gitbook.io/ginarea.org/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://ginareas-organization.gitbook.io/ginarea.org/nastroiki-botov/nastroiki-setki.md).

# Настройки сетки

<figure><img src="https://350783642-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FtOJARNyb8xHRAoEXMfKw%2Fuploads%2FPC9UUeyaTtqXAFT2aKbm%2Fimage.png?alt=media&amp;token=4bcbec24-61c6-46f9-a167-5ca8948fcf3d" alt=""><figcaption></figcaption></figure>

**Шаг сетки**  —  шаг цены, через который бот будет открывать рыночные ордера для набора позиции. Каждый такой ордер называется **IN-ордером**.

[Видео Шаг сетки](https://youtu.be/V1bMdhGli40?si=4J7r9a6LMiOig2aL)

**Множитель шага сетки** — множитель, который увеличивает размер каждого следующего **Шаг сетки** на фиксированное значение.

Максимальное значение шага сетки при использовании этого параметра ограничено 50% от текущей цены актива.&#x20;

Множитель шага сетки применяется и рассчитывается последовательно, начиная с первого ордера.

Для стратегии **Dynamic Auto** расчёт выполняется отдельно для каждого направления.\
Для стратегии **Auto Grid** расчёт ведётся последовательно от занятого шага сетки.

[Множитель шага сетки](https://www.youtube.com/watch?v=jP3bXvV3rcQ)

***

**Количество ордеров** — это максимальное количество IN-ордеров, которое может открыть бот.

[Видео Количество ордеров](https://youtu.be/VzmEsODgYDE?si=L_SrVKdHIG3Da8i_)

**Количество лонг ордеров** и **Количество шорт ордеров** — данные параметры позволят вам ограничивать максимально возможную набранную позицию для каждого направления в стратегиях с авторежимом ([Auto Grid ](/ginarea.org/strategii-i-tipy-botov-ginarea/auto-grid.md)и [Dynamic Auto](/ginarea.org/strategii-i-tipy-botov-ginarea/dynamic-grid.md))

***

Если перемножить **Шаг сетки** и **Количество ордеров**, вы получите примерный диапазон цен, который бот охватит своими ордерами.

Это обязательные параметры для запуска бота.

[<br>](https://ginarea.gitbook.io/ginarea.org/nastroiki-botov)
