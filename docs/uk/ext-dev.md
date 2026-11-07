# Розробка розширень

Сторінка для розробника. Розширення це пакет з маніфестом і модулем Python на SDK `valo_sdk`. Ядро запускає модуль окремим процесом, передає налаштування в оточенні і спілкується з ним через брокер MQTT. Як розширення виглядають для користувача, описано в [Розширення](/docs/extensions).

## Пакет

```
extensions/
  catalog.json                 список пакетів каталогу
  sdk/valo_sdk.py              SDK
  packages/my.home.hello/
    manifest.json
    hello.py                   модуль з поля module
    docs/ru.md, uk.md, en.md   опис для кнопки Опис
    ui/                        файли ізольованих сторінок і віджетів
```

Пакет потрапляє в каталог рядком `{"source": "packages/my.home.hello"}` у `catalog.json`. Попередні версії можна залишити в каталозі через поле `older` зі шляхами за номерами версій.

## Маніфест

- `id`, `version`, `module`, `name` і `description` (рядок або словник за мовами), `author`, `icon`
- `trust`. `official`, `community` або `local`
- `perms`. Список прав, користувач підтверджує його під час встановлення
- `settings`. Поля налаштувань `{key, type, default, options, name, hint}`, типи `text`, `number`, `select`, `device`, `devices`, `textarea`, `secret`. Підпис поля береться зі словника інтерфейсу `prm.<key>`, якщо такого ключа немає, то з `name` за мовами. Тип `devices` дає вибір кількох пристроїв позначками і зберігає їхні id через кому, список звужують `caps` (потрібна хоча б одна з можливостей) і `access` (наприклад `w`, лише керовані)
- `blocks`. Блоки сценаріїв `{key, kind, icon, name, params}`, `kind` один із `trig`, `cond`, `act`, `logic`, `xf`
- `pages` і `widgets`. `{key, icon, level, name}`, `level` дорівнює `declarative` або `isolated`, для ізольованих `entry` з файлом в `ui/`. У віджета ще `kind` і `params`
- `templates`. Шаблони сценаріїв `{key, name, description, graph}`
- `services`. Наприклад `["notify.telegram"]`, разом із правом `notifications.send` ядро передає розширенню зовнішні сповіщення
- `runtime`. `{"memory": МБ, "cpu": відсотки}`, за замовчуванням 256 МБ і 80 відсотків
- `requires`. Пакети pip, ядро встановлює їх в окреме оточення версії
- `type: "z2m-converter"` і `converter` для зовнішнього конвертера Zigbee2MQTT замість процесу
- `camera`. Розділ драйвера камер `{"fields": [...]}`, поле `{key, type, required, default, options, name, hint}`, типи `text`, `secret`, `number`, `select`, `bool`. З полів будується вікно **Додати камеру**, підпис і пояснення беруться з `name` і `hint` за мовами. Розширення з цим розділом і правом `cameras.provide` з'являється в списку драйверів, докладніше в розділі «Драйвер камери» нижче

Підписи налаштувань і параметрів блоків інтерфейс бере зі своїх перекладів за ключем `prm.<key>`, варіанти списків за ключем `opt.<значення>`. Ключ без перекладу показується як є.

## Права і виклики ядра

Розширення викликає ядро через `await ext.call(метод, параметри)`, відповідь очікується до 10 секунд.

- `devices.list` з необов'язковим `room`, `devices.get` з `id`. Потрібно `devices.read`
- `devices.command` з `id` і `values`. Потрібно `devices.control`
- `notify` з `text`, `level` і `key`. Потрібно `notifications.send`
- `rooms` і `notifications` (активні сповіщення). Потрібно `devices.read`
- `event` з `text` і `level` пише запис у журнал, права не потрібні
- `home` повертає координати, часовий пояс, валюту, назву і мову дому, права не потрібні
- `cameras.mine` власні камери драйвера. Потрібно `cameras.provide`
- `cameras.event` з `camera`, `label`, `active`, `score` і `data`. Потрібно `cameras.provide` для своїх камер або `cameras.events` для будь-яких
- `cameras.list` камери дому. Потрібно одне з `cameras.stream`, `cameras.events` або `media.read`
- `cameras.stream` з `camera` і `sub`. Потрібно `cameras.stream`
- `cameras.snapshot` з `camera` і `cameras.clip` з `camera` і `seconds`. Потрібно `media.write`
- `media.list` з `camera`, `kind` і `limit`, `media.get` з `id`. Потрібно `media.read`

Право `devices.read` також відкриває підписку на `hub/v1/core/state/<id пристрою>`, туди ядро публікує зміни стану. Право `mqtt.publish:<топік>` дозволяє публікацію в цей топік. Права `network.outbound`, `devices.virtual`, `ui.page`, `ui.widget` і `z2m.converter` показуються користувачеві під час встановлення, ядро їх окремо не перевіряє. Виклик без потрібного права повертає помилку `ext_permission`.

## SDK

- `ext = Extension()`, `ext.settings` словник налаштувань, `ext.data` папка даних, `ext.log` журнал, `ext.demo` ознака демо середовища
- `ext.device(dev, name, caps, kind, model, service)` оголошує запис розширення, пристрій або сервіс. Можливість `{id, type, unit, access, min, max, step, values}`, `type` один із `num`, `bool`, `enum`, `text`, `color`, `access` `r` або `rw`. У ядрі запис отримує id `<остання частина id розширення>-<dev>`
- `await ext.state(dev, values)` і `await ext.available(dev, online)` публікують стан і доступність
- `@ext.on_set(dev)` обробник команди. Повернені значення стають станом і підтверджують команду. `ValueError` вважається неправильним введенням
- `@ext.block(key)` обробник блоку сценарію
- `await ext.trigger(key, payload)` запускає сценарії з тригером `key`
- `@ext.page(key)` дані сторінки або віджета з цим ключем
- `await ext.changed(*keys)` просить інтерфейс перечитати сторінки і віджети з цими ключами
- `@ext.subscribe(topic)`, `@ext.loop`, `@ext.on_start`, `@ext.service(name)`, `ext.spawn(coro)`, `ext.run()`

Параметр `service` повідомляє ядру, чим є запис. `service=True` це сервіс, тобто дані або функція без власного приладу, наприклад погода, облік енергії або охорона. `service=False` це пристрій, тобто прилад, який розширення підключає або імітує. Ядро зберігає ознаку в метаданих запису і за нею вирішує, на якій вкладці сторінки Пристрої показати запис і чи входить він до кількості пристроїв.

```
ext.device("now", {"uk": "Погода", "en": "Weather"}, caps, kind="weather", service=True)
ext.device("motion-1", {"uk": "Датчик руху", "en": "Motion sensor"}, caps, kind="motion", service=False)
```

Якщо `service` не вказано, ядро вирішує за видом запису. Види `weather`, `air`, `calendar`, `clock`, `timer`, `meter`, `presence` і `plugguard` вважаються сервісами, решта пристроями. Указуйте `service` завжди, тоді запис нового виду не потрапить не на ту вкладку.

## Драйвер камери

Драйвер камери це розширення з розділом `camera` у маніфесті і правом `cameras.provide`. Відео йде повз процес розширення. Служба відео ядра сама підключається до камери за адресами, які повернув драйвер, і тримає одне підключення на всіх глядачів, запис і аналіз. Як камери виглядають для користувача, описано в [Камери](/docs/cameras).

Ядро викликає два обробники драйвера
- `@ext.camera_probe`, обробник `fn(config)`. Отримує значення полів камери, перевіряє камеру і повертає `{"streams": {"main": url, "sub": url}, "stills": {"snapshot": url, "preview": url}, "info": {"model", "vendor", "firmware", ...}, "caps": [...]}`. Адреса `main` обов'язкова. Адреси починаються з `rtsp://`, `rtsps://`, `rtmp://`, `http://` або `https://` і можуть містити пароль, ядро зберігає їх зашифрованими і в браузер не віддає. Без `stills` кадр береться з потоку. `caps` додають до можливості `occ` власні можливості пристрою. Помилка в обробнику означає, що камера не додасться, її текст побачить користувач. Відповідь очікується до 25 секунд
- `@ext.camera_sync`, обробник `fn(cameras)`. Отримує список своїх камер `[{"id", "config"}]` під час старту і після кожної зміни в інтерфейсі. За ним драйвер запускає і зупиняє стеження за подіями

Секретні поля приходять у `config` розшифрованими, виводити їх у журнал не можна.

Виклики SDK
- `await ext.camera_event(camera, label="motion", active=True, score=None, data=None)` повідомляє подію. `active=True` це початок, `False` кінець, `None` миттєва подія, наприклад розпізнано людину. Подія з міткою `motion` змінює можливість `occ` камери
- `await ext.available(camera, online)` повідомляє зв'язок з камерою, `camera` це id з `camera_sync`
- `await ext.cameras()` повертає камери дому
- `await ext.camera_stream(camera, sub=True)` повертає `{"rtsp", "sub"}`, внутрішню адресу RTSP служби відео для аналізу. Розширення розпізнавання читає потік звідси, а не з камери
- `await ext.snapshot(camera)` зберігає знімок і повертає запис медіа
- `await ext.clip(camera, seconds)` записує кліп, запис з'явиться через `seconds` секунд
- `await ext.media(media_id)` повертає опис запису і вміст у base64 у полі `data`, до 8 МБ

Тека записів у контейнер розширень не монтується, знімки і кліпи доступні лише через ці виклики.

Модуль `valo_camera` лежить поруч із SDK і підключається звичайним імпортом
- `with_auth(url, user, password)` вставляє логін і пароль в адресу потоку, при порожньому `user` повертає адресу без змін
- `rtsp_check(url, user="", password="")` перевіряє адресу, логін і пароль запитом RTSP DESCRIBE без читання відео
- `CameraError` помилка зі зрозумілою користувачеві причиною
- `Onvif(host, user, password, port=80)` клієнт подій ONVIF PullPoint з методами `subscribe(seconds)`, `pull(addr, wait)`, `renew(addr, seconds)` і `unsubscribe(addr)`. Функція `onvif_motion(messages)` повертає останній стан руху з повідомлень `pull` або `None`

Приклад драйвера для камери з одним потоком RTSP. Фрагмент `manifest.json`

```
"perms": ["cameras.provide", "network.outbound:lan"],
"camera": {"fields": [
  {"key": "url", "type": "text", "required": true, "default": "", "name": {"ru": "Поток", "uk": "Потік", "en": "Stream"}},
  {"key": "user", "type": "text", "default": ""},
  {"key": "password", "type": "secret", "default": ""}
]}
```

Модуль

```
from valo_camera import rtsp_check, with_auth
from valo_sdk import Extension

ext = Extension()

@ext.camera_probe
async def probe(cfg: dict) -> dict:
    url = with_auth(cfg["url"], cfg.get("user") or "", cfg.get("password") or "")
    await rtsp_check(url)
    return {"streams": {"main": url}, "info": {"vendor": "My", "model": "Cam"}}

@ext.camera_sync
async def sync(cameras: list) -> dict:
    for c in cameras:
        await ext.available(c["id"], True)
    return {"cameras": [c["id"] for c in cameras]}

if __name__ == "__main__":
    ext.run()
```

Повні драйвери `fi.valo.thingino` і `fi.valo.rtsp` лежать у `extensions/packages`.

## Блоки сценаріїв

Обробник отримує параметри блоку, дані події й ознаку пробного запуску. У прикладі `last` це словник з останнім вимірюванням, який розширення оновлює саме.

```
@ext.block("hot")
async def hot(params: dict, token: dict, dry: bool) -> dict:
    t, limit = last.get("t"), float(params.get("value") or 0)
    ok = t is not None and t >= limit
    trace = {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": t, "target": limit}}
    return {"outs": [[0, {"temp": t}]] if ok else [[1]], "trace": trace}
```

- `outs` список виходів `[порт]` або `[порт, словник]`, ключі словника стають змінними тексту наступних блоків
- `trace` рядок сліду. Код `m` перекладається інтерфейсом за ключем `tr.<m>`, готові `ext_value` (`value`, `target`) і `ext_sent` (`text`, `count`)
- тригер не потребує обробника. Ядро запускає його за `ext.trigger`, непорожні параметри тригера порівнюються з однойменними ключами даних події, ключі даних доступні в тексті як змінні
- дії (`act`) у пробному запуску ядро не викликає, умови викликає з `dry=True`
- текстові параметри надходять з уже підставленими змінними

Типи параметрів у редакторі `device`, `cap`, `value`, `number`, `duration`, `time`, `select` з `options`, `bool`, `scene`, `days`, `list`, `values`, `text`.

## Сторінки і віджети

Декларативна сторінка або віджет це відповідь обробника `@ext.page(key)` виду `{"blocks": [...], "updated": "<час ISO>"}`. У параметрах надходить `lang`, під час натискання кнопки `action` з її ключем, у віджета з параметром місця `place`.

- `hero` зведення з головним значенням. `icon`, `tone` (`amber`, `frost`, `violet`, `ok`, `warn`, `crit`), `value`, `unit`, `digits`, `text`, `sub` і `items`
- `strip` стрічка за часом. `items` з `label`, `icon`, `tone`, `value`, `unit`, `digits`, `sub` та індекс `now`
- `bars` графік. `values`, `labels`, `unit`, `digits`, `now`, `series` і `kinds`
- `stats` плитки однорідних чисел, `items` з `label`, `value`, `unit`, `digits`
- `list` рядки `{text, value | values, action | actions}`
- `clock`, `text` і `actions` (кнопки `{key, label, icon, primary}`)

Числа передаються числами з `unit` і `digits`, форматує їх клієнт за мовою. Тексти можна давати словником за мовами. Віджет показує ті самі блоки компактно, головне значення краще давати блоком `hero`, а не `stats`. Параметр віджета типу `place` дає в налаштуванні віджета пошук міста через сторінку розширення `geocode`.

Ізольована сторінка або віджет відкриває файл `ui/<entry>` в iframe з `sandbox="allow-scripts"` без доступу до cookie. Віджет надсилає `parent.postMessage({type: "ready", device: "<dev>"}, "*")` і отримує повідомлення `{type: "state", state, lang}` зі станом цього пристрою.

## Приклад

`manifest.json`

```
{
  "id": "my.home.hello", "version": "0.1.0", "module": "hello", "trust": "community",
  "name": {"uk": "Привіт", "en": "Hello"}, "perms": ["devices.virtual", "ui.page"],
  "settings": [{"key": "period", "type": "number", "default": 60}],
  "pages": [{"key": "hello", "icon": "spark", "level": "declarative", "name": {"uk": "Привіт", "en": "Hello"}}]
}
```

`hello.py`

```
import asyncio
from valo_sdk import Extension

ext = Extension()
ext.device("counter", {"uk": "Лічильник", "en": "Counter"}, [{"id": "n", "type": "num", "access": "r"}], service=True)
n = {"v": 0}

@ext.loop
async def tick() -> None:
    while True:
        n["v"] += 1
        await ext.state("counter", {"n": n["v"]})
        await ext.changed("hello")
        await asyncio.sleep(float(ext.settings.get("period") or 60))

@ext.page("hello")
async def page(params: dict) -> dict:
    return {"blocks": [{"type": "hero", "icon": "spark", "tone": "ok", "value": n["v"], "digits": 0, "text": "тиків"}]}

if __name__ == "__main__":
    ext.run()
```

## Перевірка

- Розширення з `trust: "local"` працює з папки пакета і перезапускається саме у разі зміни файлів `.py` і `.json`. Так зручно налагоджувати в демо середовищі
- Вивід процесу видно в картці розширення в **Журналі процесу**, помилки потрапляють у Система, вкладка Помилки
- Процес має повідомити про готовність за 25 секунд після старту, `ext.run()` робить це сам після підключення до брокера
- Тест `backend/tests/test_home_exts.py` перевіряє, що модуль збігається з маніфестом, у блоків і сторінок є обробники, сторінки повертають блоки, а описи трьома мовами відповідають правилам стилю. Логіку розширення зручно виносити в окремий модуль і тестувати без брокера

## Версії

Під час встановлення й оновлення код версії копіюється в `/data/extensions/<id>/<версія>` і далі запускається звідти. Дані з `ext.data` лежать поруч у `/data/extensions/<id>/data` і переживають оновлення. Тому будь-яка зміна коду публікується лише з новим номером `version`, інакше вузли продовжать запускати попередню копію. Користувач побачить позначку **оновлення до** і оновить розширення. Якщо новій версії потрібні нові права, їх треба підтвердити під час оновлення.
