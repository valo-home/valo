# Extension development

A page for developers. An extension is a package with a manifest and a Python module built on the `valo_sdk` SDK. The core starts the module as a separate process, passes the settings in the environment and talks to it through the MQTT broker. How extensions look to the user is described in [Extensions](/docs/extensions).

## Package

```
extensions/
  catalog.json                 list of catalog packages
  sdk/valo_sdk.py              SDK
  packages/my.home.hello/
    manifest.json
    hello.py                   module from the module field
    docs/ru.md, uk.md, en.md   description for the About button
    ui/                        files of isolated pages and widgets
```

A package gets into the catalog with the line `{"source": "packages/my.home.hello"}` in `catalog.json`. Earlier versions can be kept in the catalog with the `older` field holding paths by version number.

## Manifest

- `id`, `version`, `module`, `name` and `description` (a string or a dictionary by language), `author`, `icon`
- `trust`. `official`, `community` or `local`
- `perms`. The list of permissions, the user confirms it at install
- `settings`. Setting fields `{key, type, default, options, name, hint}`, types `text`, `number`, `select`, `device`, `devices`, `textarea`, `secret`. The field label comes from the UI dictionary `prm.<key>`, and if there is no such key, from `name` by language. The `devices` type lets the user tick several devices and stores their ids separated by commas, `caps` (at least one of the capabilities) and `access` (for example `w`, controllable only) narrow the list
- `blocks`. Automation blocks `{key, kind, icon, name, params}`, `kind` is one of `trig`, `cond`, `act`, `logic`, `xf`
- `pages` and `widgets`. `{key, icon, level, name}`, `level` is `declarative` or `isolated`, isolated ones have `entry` with a file in `ui/`. A widget also has `kind` and `params`
- `templates`. Automation templates `{key, name, description, graph}`
- `services`. For example `["notify.telegram"]`, together with the `notifications.send` permission the core passes external notifications to the extension
- `runtime`. `{"memory": MB, "cpu": percent}`, 256 MB and 80 percent by default
- `requires`. pip packages, the core installs them into a separate environment of the version
- `type: "z2m-converter"` and `converter` for an external Zigbee2MQTT converter instead of a process
- `camera`. The camera driver section `{"fields": [...]}`, a field is `{key, type, required, default, options, name, hint}`, types `text`, `secret`, `number`, `select`, `bool`. The **Add camera** dialog is built from the fields, the label and hint come from `name` and `hint` by language. An extension with this section and the `cameras.provide` permission appears in the driver list, see "Camera driver" below

The interface takes the labels of settings and block parameters from its own translations by the key `prm.<key>`, list options by the key `opt.<value>`. A key without a translation is shown as is.

## Permissions and core calls

An extension calls the core with `await ext.call(method, params)`, the answer is awaited for up to 10 seconds.

- `devices.list` with an optional `room`, `devices.get` with `id`. Needs `devices.read`
- `devices.command` with `id` and `values`. Needs `devices.control`
- `notify` with `text`, `level` and `key`. Needs `notifications.send`
- `rooms` and `notifications` (active notifications). Needs `devices.read`
- `event` with `text` and `level` writes a log entry, no permission needed
- `home` returns the coordinates, time zone, currency, name and language of the home, no permission needed
- `cameras.mine` the driver's own cameras. Needs `cameras.provide`
- `cameras.event` with `camera`, `label`, `active`, `score` and `data`. Needs `cameras.provide` for own cameras or `cameras.events` for any camera
- `cameras.list` the home cameras. Needs one of `cameras.stream`, `cameras.events` or `media.read`
- `cameras.stream` with `camera` and `sub`. Needs `cameras.stream`
- `cameras.snapshot` with `camera` and `cameras.clip` with `camera` and `seconds`. Needs `media.write`
- `media.list` with `camera`, `kind` and `limit`, `media.get` with `id`. Needs `media.read`

The `devices.read` permission also opens the subscription to `hub/v1/core/state/<device id>`, the core publishes state changes there. The `mqtt.publish:<topic>` permission allows publishing to that topic. The `network.outbound`, `devices.virtual`, `ui.page`, `ui.widget` and `z2m.converter` permissions are shown to the user at install, the core does not check them separately. A call without the required permission returns the `ext_permission` error.

## SDK

- `ext = Extension()`, `ext.settings` the settings dictionary, `ext.data` the data folder, `ext.log` the logger, `ext.demo` the demo environment flag
- `ext.device(dev, name, caps, kind, model, service)` declares an extension record, a device or a service. A capability is `{id, type, unit, access, min, max, step, values}`, `type` is one of `num`, `bool`, `enum`, `text`, `color`, `access` is `r` or `rw`. In the core the record gets the id `<last part of the extension id>-<dev>`
- `await ext.state(dev, values)` and `await ext.available(dev, online)` publish state and availability
- `@ext.on_set(dev)` a command handler. The returned values become the state and confirm the command. `ValueError` is treated as invalid input
- `@ext.block(key)` an automation block handler
- `await ext.trigger(key, payload)` starts automations with the `key` trigger
- `@ext.page(key)` data of the page or widget with this key
- `await ext.changed(*keys)` asks the interface to reload pages and widgets with these keys
- `@ext.subscribe(topic)`, `@ext.loop`, `@ext.on_start`, `@ext.service(name)`, `ext.spawn(coro)`, `ext.run()`

The `service` parameter tells the core what the record is. `service=True` is a service, that is data or a function without an appliance of its own, for example weather, energy usage or safety. `service=False` is a device, that is an appliance the extension connects or simulates. The core stores the flag in the record metadata and uses it to decide on which tab of the Devices page the record is shown and whether it is counted as a device.

```
ext.device("now", {"ru": "Погода", "en": "Weather"}, caps, kind="weather", service=True)
ext.device("motion-1", {"ru": "Датчик движения", "en": "Motion sensor"}, caps, kind="motion", service=False)
```

If `service` is not given, the core decides by the record kind. The kinds `weather`, `air`, `calendar`, `clock`, `timer`, `meter`, `presence` and `plugguard` are services, all others are devices. Always declare `service`, then a record of a new kind does not end up on the wrong tab.

## Camera driver

A camera driver is an extension with a `camera` section in the manifest and the `cameras.provide` permission. Video does not pass through the extension process. The core video service connects to the camera itself at the addresses the driver returned and keeps one connection for all viewers, recording and analysis. How cameras look to the user is described in [Cameras](/docs/cameras).

The core calls two driver handlers
- `@ext.camera_probe`, the handler `fn(config)`. Gets the camera field values, checks the camera and returns `{"streams": {"main": url, "sub": url}, "stills": {"snapshot": url, "preview": url}, "info": {"model", "vendor", "firmware", ...}, "caps": [...]}`. The `main` address is required. Addresses start with `rtsp://`, `rtsps://`, `rtmp://`, `http://` or `https://` and may contain a password, the core stores them encrypted and never sends them to the browser. Without `stills` the frame is taken from the stream. `caps` add device capabilities of their own to `occ`. An error in the handler means the camera is not added, the user sees its text. The answer is awaited for up to 25 seconds
- `@ext.camera_sync`, the handler `fn(cameras)`. Gets the list of its cameras `[{"id", "config"}]` at start and after every change in the interface. The driver starts and stops watching for events by it

Secret fields arrive in `config` decrypted, they must not be written to the log.

SDK calls
- `await ext.camera_event(camera, label="motion", active=True, score=None, data=None)` reports an event. `active=True` is the start, `False` the end, `None` an instant event, for example a recognized person. An event with the `motion` label changes the camera `occ` capability
- `await ext.available(camera, online)` reports camera availability, `camera` is the id from `camera_sync`
- `await ext.cameras()` returns the home cameras
- `await ext.camera_stream(camera, sub=True)` returns `{"rtsp", "sub"}`, the internal RTSP address of the video service for analysis. A detection extension reads the stream from here, not from the camera
- `await ext.snapshot(camera)` saves a snapshot and returns the media record
- `await ext.clip(camera, seconds)` records a clip, the record appears after `seconds` seconds
- `await ext.media(media_id)` returns the record description and the content in base64 in the `data` field, up to 8 MB

The recordings folder is not mounted into the extensions container, snapshots and clips are available only through these calls.

The `valo_camera` module lies next to the SDK and is imported as usual
- `with_auth(url, user, password)` inserts the login and password into a stream address, with an empty `user` it returns the address unchanged
- `rtsp_check(url, user="", password="")` checks the address, login and password with an RTSP DESCRIBE request without reading video
- `CameraError` an error with a reason the user can understand
- `Onvif(host, user, password, port=80)` an ONVIF PullPoint events client with the methods `subscribe(seconds)`, `pull(addr, wait)`, `renew(addr, seconds)` and `unsubscribe(addr)`. The function `onvif_motion(messages)` returns the last motion state from `pull` messages or `None`

A driver example for a camera with one RTSP stream. A part of `manifest.json`

```
"perms": ["cameras.provide", "network.outbound:lan"],
"camera": {"fields": [
  {"key": "url", "type": "text", "required": true, "default": "", "name": {"ru": "Поток", "uk": "Потік", "en": "Stream"}},
  {"key": "user", "type": "text", "default": ""},
  {"key": "password", "type": "secret", "default": ""}
]}
```

The module

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

The complete `fi.valo.thingino` and `fi.valo.rtsp` drivers are in `extensions/packages`.

## Automation blocks

The handler receives the block parameters, the event data and the dry run flag. In the example `last` is a dictionary with the latest measurement that the extension updates itself.

```
@ext.block("hot")
async def hot(params: dict, token: dict, dry: bool) -> dict:
    t, limit = last.get("t"), float(params.get("value") or 0)
    ok = t is not None and t >= limit
    trace = {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": t, "target": limit}}
    return {"outs": [[0, {"temp": t}]] if ok else [[1]], "trace": trace}
```

- `outs` is the list of outputs `[port]` or `[port, dictionary]`, the dictionary keys become text variables of the following blocks
- `trace` is the trace line. The code `m` is translated by the interface by the key `tr.<m>`, ready ones are `ext_value` (`value`, `target`) and `ext_sent` (`text`, `count`)
- a trigger needs no handler. The core starts it on `ext.trigger`, non empty trigger parameters are compared with event data keys of the same name, the data keys are available in texts as variables
- actions (`act`) are not called by the core in a dry run, conditions are called with `dry=True`
- text parameters arrive with the variables already substituted

Parameter types in the editor are `device`, `cap`, `value`, `number`, `duration`, `time`, `select` with `options`, `bool`, `scene`, `days`, `list`, `values`, `text`.

## Pages and widgets

A declarative page or widget is the answer of the `@ext.page(key)` handler of the form `{"blocks": [...], "updated": "<ISO time>"}`. The parameters carry `lang`, on a button press `action` with its key, and for a widget with a place parameter `place`.

- `hero` a summary with the main value. `icon`, `tone` (`amber`, `frost`, `violet`, `ok`, `warn`, `crit`), `value`, `unit`, `digits`, `text`, `sub` and `items`
- `strip` a time strip. `items` with `label`, `icon`, `tone`, `value`, `unit`, `digits`, `sub` and the `now` index
- `bars` a chart. `values`, `labels`, `unit`, `digits`, `now`, `series` and `kinds`
- `stats` tiles of uniform numbers, `items` with `label`, `value`, `unit`, `digits`
- `list` rows `{text, value | values, action | actions}`
- `clock`, `text` and `actions` (buttons `{key, label, icon, primary}`)

Numbers are passed as numbers with `unit` and `digits`, the client formats them by language. Texts can be given as a dictionary by language. A widget shows the same blocks in compact form, the main value is better given with a `hero` block rather than `stats`. A widget parameter of type `place` gives a city search in the widget settings through the `geocode` page of the extension.

An isolated page or widget opens the file `ui/<entry>` in an iframe with `sandbox="allow-scripts"` without access to cookies. The widget sends `parent.postMessage({type: "ready", device: "<dev>"}, "*")` and receives messages `{type: "state", state, lang}` with the state of that device.

## Example

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
    return {"blocks": [{"type": "hero", "icon": "spark", "tone": "ok", "value": n["v"], "digits": 0, "text": "ticks"}]}

if __name__ == "__main__":
    ext.run()
```

## Testing

- An extension with `trust: "local"` runs from the package folder and restarts by itself when `.py` and `.json` files change. This is convenient for debugging in the demo environment
- The process output is shown in the extension card in the **Process log**, errors go to System, the Errors tab
- The process must report readiness within 25 seconds after start, `ext.run()` does this by itself after connecting to the broker
- The test `backend/tests/test_home_exts.py` checks that the module matches the manifest, blocks and pages have handlers, pages return blocks and the descriptions in three languages follow the style rules. It is convenient to move the extension logic into a separate module and test it without the broker

## Versions

On install and update the code of the version is copied to `/data/extensions/<id>/<version>` and runs from there. Data from `ext.data` lies next to it in `/data/extensions/<id>/data` and survives updates. Therefore any code change is published only with a new `version` number, otherwise hubs keep running the earlier copy. The user sees the **update to** mark and updates the extension. If the new version needs new permissions, they must be confirmed on update.
