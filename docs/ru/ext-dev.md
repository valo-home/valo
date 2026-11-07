# Разработка расширений

Страница для разработчика. Расширение это пакет с манифестом и модулем Python на SDK `valo_sdk`. Ядро запускает модуль отдельным процессом, передает настройки в окружении и общается с ним через брокер MQTT. Как расширения выглядят для пользователя, описано в [Расширения](/docs/extensions).

## Пакет

```
extensions/
  catalog.json                 список пакетов каталога
  sdk/valo_sdk.py              SDK
  packages/my.home.hello/
    manifest.json
    hello.py                   модуль из поля module
    docs/ru.md, uk.md, en.md   описание для кнопки Описание
    ui/                        файлы изолированных страниц и виджетов
```

Пакет попадает в каталог строкой `{"source": "packages/my.home.hello"}` в `catalog.json`. Прежние версии можно оставить в каталоге через поле `older` с путями по номерам версий.

## Манифест

- `id`, `version`, `module`, `name` и `description` (строка или словарь по языкам), `author`, `icon`
- `trust`. `official`, `community` или `local`
- `perms`. Список прав, пользователь подтверждает его при установке
- `settings`. Поля настроек `{key, type, default, options, name, hint}`, типы `text`, `number`, `select`, `device`, `devices`, `textarea`, `secret`. Подпись поля берется из словаря интерфейса `prm.<key>`, если такого ключа нет, то из `name` по языкам. Тип `devices` дает выбор нескольких устройств галочками и хранит их id через запятую, список сужают `caps` (нужна хотя бы одна из возможностей) и `access` (например `w`, только управляемые)
- `blocks`. Блоки сценариев `{key, kind, icon, name, params}`, `kind` один из `trig`, `cond`, `act`, `logic`, `xf`
- `pages` и `widgets`. `{key, icon, level, name}`, `level` равен `declarative` или `isolated`, для изолированных `entry` с файлом в `ui/`. У виджета еще `kind` и `params`
- `templates`. Шаблоны сценариев `{key, name, description, graph}`
- `services`. Например `["notify.telegram"]`, вместе с правом `notifications.send` ядро передает расширению внешние уведомления
- `runtime`. `{"memory": МБ, "cpu": проценты}`, по умолчанию 256 МБ и 80 процентов
- `requires`. Пакеты pip, ядро ставит их в отдельное окружение версии
- `type: "z2m-converter"` и `converter` для внешнего конвертера Zigbee2MQTT вместо процесса
- `camera`. Раздел драйвера камер `{"fields": [...]}`, поле `{key, type, required, default, options, name, hint}`, типы `text`, `secret`, `number`, `select`, `bool`. Из полей строится окно **Добавить камеру**, подпись и пояснение берутся из `name` и `hint` по языкам. Расширение с этим разделом и правом `cameras.provide` появляется в списке драйверов, подробнее в разделе «Драйвер камеры» ниже

Подписи настроек и параметров блоков интерфейс берет из своих переводов по ключу `prm.<key>`, варианты списков по ключу `opt.<значение>`. Ключ без перевода показывается как есть.

## Права и вызовы ядра

Расширение вызывает ядро через `await ext.call(метод, параметры)`, ответ ждется до 10 секунд.

- `devices.list` с необязательным `room`, `devices.get` с `id`. Нужно `devices.read`
- `devices.command` с `id` и `values`. Нужно `devices.control`
- `notify` с `text`, `level` и `key`. Нужно `notifications.send`
- `rooms` и `notifications` (активные уведомления). Нужно `devices.read`
- `event` с `text` и `level` пишет запись в журнал, права не нужны
- `home` возвращает координаты, часовой пояс, валюту, название и язык дома, права не нужны
- `cameras.mine` свои камеры драйвера. Нужно `cameras.provide`
- `cameras.event` с `camera`, `label`, `active`, `score` и `data`. Нужно `cameras.provide` для своих камер или `cameras.events` для любых
- `cameras.list` камеры дома. Нужно одно из `cameras.stream`, `cameras.events` или `media.read`
- `cameras.stream` с `camera` и `sub`. Нужно `cameras.stream`
- `cameras.snapshot` с `camera` и `cameras.clip` с `camera` и `seconds`. Нужно `media.write`
- `media.list` с `camera`, `kind` и `limit`, `media.get` с `id`. Нужно `media.read`

Право `devices.read` также открывает подписку на `hub/v1/core/state/<id устройства>`, туда ядро публикует изменения состояния. Право `mqtt.publish:<топик>` разрешает публикацию в этот топик. Права `network.outbound`, `devices.virtual`, `ui.page`, `ui.widget` и `z2m.converter` показываются пользователю при установке, ядро их отдельно не проверяет. Вызов без нужного права возвращает ошибку `ext_permission`.

## SDK

- `ext = Extension()`, `ext.settings` словарь настроек, `ext.data` папка данных, `ext.log` журнал, `ext.demo` признак демо среды
- `ext.device(dev, name, caps, kind, model, service)` объявляет запись расширения, устройство или сервис. Возможность `{id, type, unit, access, min, max, step, values}`, `type` один из `num`, `bool`, `enum`, `text`, `color`, `access` `r` или `rw`. В ядре запись получает id `<последняя часть id расширения>-<dev>`
- `await ext.state(dev, values)` и `await ext.available(dev, online)` публикуют состояние и доступность
- `@ext.on_set(dev)` обработчик команды. Возвращенные значения становятся состоянием и подтверждают команду. `ValueError` считается неверным вводом
- `@ext.block(key)` обработчик блока сценария
- `await ext.trigger(key, payload)` запускает сценарии с триггером `key`
- `@ext.page(key)` данные страницы или виджета с этим ключом
- `await ext.changed(*keys)` просит интерфейс перечитать страницы и виджеты с этими ключами
- `@ext.subscribe(topic)`, `@ext.loop`, `@ext.on_start`, `@ext.service(name)`, `ext.spawn(coro)`, `ext.run()`

Параметр `service` говорит ядру, чем является запись. `service=True` это сервис, то есть данные или функция без своего прибора, например погода, учет энергии или охрана. `service=False` это устройство, то есть прибор, который расширение подключает или имитирует. Ядро сохраняет признак в метаданных записи и по нему решает, на какой вкладке страницы Устройства показать запись и входит ли она в число устройств.

```
ext.device("now", {"ru": "Погода", "en": "Weather"}, caps, kind="weather", service=True)
ext.device("motion-1", {"ru": "Датчик движения", "en": "Motion sensor"}, caps, kind="motion", service=False)
```

Если `service` не указан, ядро решает по виду записи. Виды `weather`, `air`, `calendar`, `clock`, `timer`, `meter`, `presence` и `plugguard` считаются сервисами, остальные устройствами. Указывайте `service` всегда, тогда запись нового вида не попадет не на ту вкладку.

## Драйвер камеры

Драйвер камеры это расширение с разделом `camera` в манифесте и правом `cameras.provide`. Видео идет мимо процесса расширения. Служба видео ядра сама подключается к камере по адресам, которые вернул драйвер, и держит одно подключение на всех зрителей, запись и анализ. Как камеры выглядят для пользователя, описано в [Камеры](/docs/cameras).

Ядро вызывает два обработчика драйвера
- `@ext.camera_probe`, обработчик `fn(config)`. Получает значения полей камеры, проверяет камеру и возвращает `{"streams": {"main": url, "sub": url}, "stills": {"snapshot": url, "preview": url}, "info": {"model", "vendor", "firmware", ...}, "caps": [...]}`. Адрес `main` обязателен. Адреса начинаются с `rtsp://`, `rtsps://`, `rtmp://`, `http://` или `https://` и могут содержать пароль, ядро хранит их зашифрованными и в браузер не отдает. Без `stills` кадр берется из потока. `caps` добавляют к возможности `occ` свои возможности устройства. Ошибка в обработчике означает, что камера не добавится, ее текст увидит пользователь. Ответ ждется до 25 секунд
- `@ext.camera_sync`, обработчик `fn(cameras)`. Получает список своих камер `[{"id", "config"}]` при старте и после каждого изменения в интерфейсе. По нему драйвер запускает и останавливает слежение за событиями

Секретные поля приходят в `config` расшифрованными, в журнал их выводить нельзя.

Вызовы SDK
- `await ext.camera_event(camera, label="motion", active=True, score=None, data=None)` сообщает событие. `active=True` это начало, `False` конец, `None` мгновенное событие, например распознан человек. Событие с меткой `motion` меняет возможность `occ` камеры
- `await ext.available(camera, online)` сообщает связь с камерой, `camera` это id из `camera_sync`
- `await ext.cameras()` возвращает камеры дома
- `await ext.camera_stream(camera, sub=True)` возвращает `{"rtsp", "sub"}`, внутренний адрес RTSP службы видео для анализа. Расширение распознавания читает поток отсюда, а не с камеры
- `await ext.snapshot(camera)` сохраняет снимок и возвращает запись медиа
- `await ext.clip(camera, seconds)` записывает клип, запись появится через `seconds` секунд
- `await ext.media(media_id)` возвращает описание записи и содержимое в base64 в поле `data`, до 8 МБ

Папка записей в контейнер расширений не монтируется, снимки и клипы доступны только через эти вызовы.

Модуль `valo_camera` лежит рядом с SDK и подключается обычным импортом
- `with_auth(url, user, password)` вставляет логин и пароль в адрес потока, при пустом `user` возвращает адрес без изменений
- `rtsp_check(url, user="", password="")` проверяет адрес, логин и пароль запросом RTSP DESCRIBE без чтения видео
- `CameraError` ошибка с понятной пользователю причиной
- `Onvif(host, user, password, port=80)` клиент событий ONVIF PullPoint с методами `subscribe(seconds)`, `pull(addr, wait)`, `renew(addr, seconds)` и `unsubscribe(addr)`. Функция `onvif_motion(messages)` возвращает последнее состояние движения из сообщений `pull` или `None`

Пример драйвера для камеры с одним потоком RTSP. Фрагмент `manifest.json`

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

Полные драйверы `fi.valo.thingino` и `fi.valo.rtsp` лежат в `extensions/packages`.

## Блоки сценариев

Обработчик получает параметры блока, данные события и признак пробного прогона. В примере `last` это словарь с последним измерением, который расширение обновляет само.

```
@ext.block("hot")
async def hot(params: dict, token: dict, dry: bool) -> dict:
    t, limit = last.get("t"), float(params.get("value") or 0)
    ok = t is not None and t >= limit
    trace = {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": t, "target": limit}}
    return {"outs": [[0, {"temp": t}]] if ok else [[1]], "trace": trace}
```

- `outs` список выходов `[порт]` или `[порт, словарь]`, ключи словаря становятся переменными текста следующих блоков
- `trace` строка следа. Код `m` переводится интерфейсом по ключу `tr.<m>`, готовы `ext_value` (`value`, `target`) и `ext_sent` (`text`, `count`)
- триггер не требует обработчика. Ядро запускает его по `ext.trigger`, непустые параметры триггера сравниваются с одноименными ключами данных события, ключи данных доступны в тексте как переменные
- действия (`act`) в пробном прогоне ядро не вызывает, условия вызывает с `dry=True`
- текстовые параметры приходят с уже подставленными переменными

Типы параметров в редакторе `device`, `cap`, `value`, `number`, `duration`, `time`, `select` с `options`, `bool`, `scene`, `days`, `list`, `values`, `text`.

## Страницы и виджеты

Декларативная страница или виджет это ответ обработчика `@ext.page(key)` вида `{"blocks": [...], "updated": "<время ISO>"}`. В параметрах приходит `lang`, при нажатии кнопки `action` с ее ключом, у виджета с параметром места `place`.

- `hero` сводка с главным значением. `icon`, `tone` (`amber`, `frost`, `violet`, `ok`, `warn`, `crit`), `value`, `unit`, `digits`, `text`, `sub` и `items`
- `strip` лента по времени. `items` с `label`, `icon`, `tone`, `value`, `unit`, `digits`, `sub` и индекс `now`
- `bars` график. `values`, `labels`, `unit`, `digits`, `now`, `series` и `kinds`
- `stats` плитки однородных чисел, `items` с `label`, `value`, `unit`, `digits`
- `list` строки `{text, value | values, action | actions}`
- `clock`, `text` и `actions` (кнопки `{key, label, icon, primary}`)

Числа передаются числами с `unit` и `digits`, форматирует их клиент по языку. Тексты можно давать словарем по языкам. Виджет показывает те же блоки компактно, главное значение лучше давать блоком `hero`, а не `stats`. Параметр виджета типа `place` дает в настройке виджета поиск города через страницу расширения `geocode`.

Изолированная страница или виджет открывает файл `ui/<entry>` в iframe с `sandbox="allow-scripts"` без доступа к cookie. Виджет отправляет `parent.postMessage({type: "ready", device: "<dev>"}, "*")` и получает сообщения `{type: "state", state, lang}` с состоянием этого устройства.

## Пример

`manifest.json`

```
{
  "id": "my.home.hello", "version": "0.1.0", "module": "hello", "trust": "community",
  "name": {"ru": "Привет", "en": "Hello"}, "perms": ["devices.virtual", "ui.page"],
  "settings": [{"key": "period", "type": "number", "default": 60}],
  "pages": [{"key": "hello", "icon": "spark", "level": "declarative", "name": {"ru": "Привет", "en": "Hello"}}]
}
```

`hello.py`

```
import asyncio
from valo_sdk import Extension

ext = Extension()
ext.device("counter", {"ru": "Счетчик", "en": "Counter"}, [{"id": "n", "type": "num", "access": "r"}], service=True)
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
    return {"blocks": [{"type": "hero", "icon": "spark", "tone": "ok", "value": n["v"], "digits": 0, "text": "тиков"}]}

if __name__ == "__main__":
    ext.run()
```

## Проверка

- Расширение с `trust: "local"` работает из папки пакета и перезапускается само при изменении файлов `.py` и `.json`. Так удобно отлаживать в демо среде
- Вывод процесса виден в карточке расширения в **Журнале процесса**, ошибки попадают в Система, вкладка Ошибки
- Процесс должен сообщить о готовности за 25 секунд после старта, `ext.run()` делает это сам после подключения к брокеру
- Тест `backend/tests/test_home_exts.py` проверяет, что модуль совпадает с манифестом, у блоков и страниц есть обработчики, страницы возвращают блоки, а описания на трех языках соответствуют правилам стиля. Логику расширения удобно выносить в отдельный модуль и тестировать без брокера

## Версии

При установке и обновлении код версии копируется в `/data/extensions/<id>/<версия>` и дальше запускается оттуда. Данные из `ext.data` лежат рядом в `/data/extensions/<id>/data` и переживают обновления. Поэтому любое изменение кода публикуется только с новым номером `version`, иначе узлы продолжат запускать прежнюю копию. Пользователь увидит пометку **обновление до** и обновит расширение. Если новой версии нужны новые права, их надо подтвердить при обновлении.
