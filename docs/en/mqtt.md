# MQTT

MQTT is a protocol over which devices in the home network exchange messages through a broker. In Valo the broker is Mosquitto. It carries the data of Zigbee2MQTT, extensions and Wi-Fi devices, for example relays and sensors with Tasmota, ESPHome or custom firmware. The **MQTT** page in the System section is available to an administrator.

The broker does not accept anonymous clients. Every device connects with its own account and sees only the topics allowed to it. In the production environment the broker accepts connections from the local network on port 1883.

## How an MQTT device gets into Valo

There are three ways, in the device list they differ by source.

- **HA discovery**. The device publishes its own description to `homeassistant/.../config` topics by the Home Assistant standard, Valo creates the device automatically. Tasmota, ESPHome and many other firmwares can do this
- **MQTT**. A device with firmware for Valo's own `hub/v1` contract
- **Mapping**. For a device that publishes arbitrary JSON you set by hand in which topic and at which path each value is

## A device with the hub/v1 contract

1. Press **Add device**, the **MQTT device** tab
2. Enter the device identifier, for example `sauna-ctrl`, and press **Issue account**
3. Write the username, password and base topic into the device firmware. The password is shown once, issuing again revokes the old one

The device works in its own topics under the base `hub/v1/dev/<id>`
- `meta` a description with name and capabilities, for example `{"name": "Sauna", "caps": [{"id": "t", "type": "num", "unit": "°C"}]}`
- `state` current values, for example `{"t": 21.5}`
- `avail` the string `online` or `offline`
- `set` commands from Valo of the form `{"cmd": "...", "values": {...}}`
- `ack` the answer to a command `{"cmd": "...", "ok": true, "values": {...}}`. A command is confirmed by an `ack` answer or by a new value in `state`, without them it ends with a timeout
- `event` events such as a button press `{"action": "single"}`, they are caught by the **Device button** trigger

The account gives access only to the topics of this device. For devices with other firmware the interface does not issue accounts, the hub administrator creates them.

## Page tabs

The header shows the number of topics, clients, the Mosquitto version and the state of the core connection to the broker.

### Explorer

On the left is a tree of all topics with their latest values and **Filter topics**. New messages are highlighted. Pressing a topic shows the whole message, time, QoS, the retain flag, the number of messages and **Previous values**.

On the right is the **Publish** form. Enter a topic, a payload, QoS and retain if needed and press **Send**. Publishing is written to the log. Below is the **Recent messages** feed.

### HA discovery

A table of devices created by HA discovery with origin, list of configs and the time of the last contact. The **stale** mark means the device is offline or never sent data within 10 minutes after it appeared. The trash button **Remove** next to a config deletes it from the broker, this is needed when a device was removed long ago but its description stayed on the broker.

### Topic mapping

At the top are **Mapped devices** with the **Edit** and **Delete** buttons. Below is the **New mapping** form.

1. Set the **ID** in Latin letters, for example `garage-temp`, the **Name**, **Room** and **Device type**. The type is used for the icon and summaries
2. Fill in a row for each reading. **Capability** is the value identifier, for common quantities use the standard `t` temperature, `h` humidity, `on` power, `w` power draw. **Value type** is number, yes or no, text. **Topic** is where the value comes from. **JSON path** uses dots, an empty path takes the whole message. **Unit** is for display
3. If the value can be changed, set the **Command topic**. Without it the capability is read only
4. The **Add capability** button adds a row, then press **Create**

Example for a Tasmota sensor and relay in the garage
- `t`, number, topic `tele/garage/SENSOR`, path `DS18B20.Temperature`, unit `°C`
- `on`, yes or no, topic `stat/garage/POWER`, command topic `cmnd/garage/POWER`

For yes or no values the incoming `ON`, `OFF`, `true`, `false`, `1`, `0` are recognized by themselves, a command is sent as `ON` or `OFF`.

### Accounts

**Broker clients** shows the accounts and their roles. **Roles and topic access** expands the rules of each role, which topics the role can read and publish. The accounts of the core, Zigbee2MQTT and extensions are created automatically, accounts of hub/v1 devices when issued, the role of an extension is built from the permissions granted to it, see [Extensions](/docs/extensions).

## If data does not arrive

1. Find the device topic in the **Explorer**. If it is missing, the device has not connected to the broker, check the hub address, port and account in the device settings
2. If the topic is there, compare the JSON path with the message shown in the **Explorer**
3. Check the [Log](/docs/log) and System, the Errors tab

Mapped devices and HA discovery devices work in automations and on dashboards the same way as Zigbee devices, see [Devices](/docs/devices).
