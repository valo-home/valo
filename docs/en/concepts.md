# Key concepts

This page collects the terms used across the interface. Other pages of the documentation refer to these definitions.

## Device

A device is a home appliance that is controlled or measures something. It is connected over Zigbee, over MQTT or through an extension, for example the device simulator, and Valo knows it by its identifier. A device has a name, a type (light, plug, leak sensor and others), a room, a set of capabilities, its current state, an online flag and the time of its last message. The type defines the icon and the state summary and can be changed in the device settings.

## Capability

A capability is one property of a device, for example on and off, brightness, temperature, power or battery level. A capability has a value kind (yes or no, number, option from a list, text, color), a unit and access. A read only capability is shown as a reading, a writable one as a control. History and charts are kept for numeric capabilities.

## Source

The source tells how a device is connected to the home. It is shown in the device list and on the device page.

- **Zigbee** is a device paired with the stick through Zigbee2MQTT
- **MQTT** is a device connected through the broker. This source covers devices with their own firmware that follow the hub/v1 contract and have their own broker account, and also the two ways of connecting below
- **HA discovery** is a way of connecting over MQTT for a third party device that announced itself in the Home Assistant discovery format
- **Mapping** is a way of connecting over MQTT for a device created by hand on the MQTT page from topics with arbitrary JSON
- for a device connected by an extension the source is the name of that extension, for example **Device simulator**

Devices connected through HA discovery or mapping show the MQTT mark, and the way of connecting is shown under it in small text. More about Zigbee in [Zigbee](/docs/zigbee), about MQTT, HA discovery and mapping in [MQTT](/docs/mqtt).

## Service

A service is a record an extension creates without an appliance of its own. It describes a data source or a home function, for example weather, air quality, calendar, timers and alarm clocks, energy usage, home safety, plug guard or presence. For example, a weather extension creates a record with temperature and forecast, the energy usage extension creates a record with a consumption summary, the **Home safety** extension creates a record with an arming switch.

Whether an extension creates a device or a service is decided by the extension itself when it declares the record. If the extension does not say, the core decides by the record kind, see [Extension development](/docs/ext-dev).

Services are not counted as devices in the menu, on the Devices page or in the count of devices without a room, and they are not shown on the home plan. Such records measure nothing in the home, have no battery or link quality and need no pairing or place in a room. Counting them as devices would make summaries such as the number of offline or unassigned devices stop reflecting the real hardware. Services are collected on the **Services** tab of the Devices page, they can be put on dashboards and used in automations.

## Camera, camera event and recording

A camera is a device of the camera kind connected by a driver extension, for example **Thingino cameras** or **RTSP camera**. It is in the device list and in a separate **Cameras** section with live video. A camera has the motion capability, so it can be used as a motion sensor in automations.

A camera event is something the camera noticed, for example motion or a person. An event has a start and an end, a label, a confidence score, a source (the driver or a detection extension), a snapshot and a clip. Camera events start automations.

A recording is a snapshot or a clip that Valo saved on its own disk. A recording is linked to a camera and an event and is kept until the storage rotation or an administrator deletes it. Cameras and recordings are visible to residents and higher, more in [Cameras](/docs/cameras).

## Room, floor and plan

A room is a room or an area, for example the kitchen or the yard. A room has a name, a floor number, an **outdoor** flag and a position on the plan. A device belongs to at most one room. Rooms are used for user access, average temperature and lights, and sensors in outdoor rooms provide the outside temperature.

The plan is a floor diagram of room rectangles with device icons. It shows lights, motion and alarms right on the diagram. See [Overview and home plan](/docs/home).

## Dashboard and widget

A dashboard is your set of widgets for a particular screen, for example a kitchen tablet or an energy page. A widget is a card on a dashboard that shows one device, a room, a home summary or an extension service. Dashboards are shared by all users of the home. See [Dashboards and widgets](/docs/boards).

## Automation

An automation (also called a flow) is a diagram of blocks. A trigger starts it (a device event, a time, a schedule, the sun, a button), conditions and logic check the situation, actions send commands, apply scenes, write to the log and create notifications. See [Automations](/docs/flows).

## Scene

A scene is a saved target state of several devices applied with one tap, for example evening lights. A scene can be captured from the current state of the home. See [Scenes](/docs/scenes).

## Extension

An extension is a software module installed from the catalog on the Extensions page, it runs in a separate process and gets only the permissions you grant. Extensions add devices, services, widgets, pages and automation blocks, for example weather, a calendar, energy usage or Telegram notifications. An extension itself is neither a device nor a service, it is the module that creates them. See [Extensions](/docs/extensions).

## Event and log

An event is a record of something that happened, for example a state change, a command, an automation run or a user login. An event has a level, an author and, if there is one, a cause, so the log lets you follow the chain back to the first cause. See [Log and notifications](/docs/log).

## Notification

A notification is an active problem that needs attention, for example a leak, a low battery or an offline device. It stays until the cause disappears or until someone dismisses it. Active notifications are collected under the bell in the top bar.

## Roles

Each user has one role.

- **Guest** sees the home but changes nothing
- **Resident** controls devices, applies scenes, runs automations manually, creates and edits dashboards
- **Administrator** also sets up rooms and the plan, pairs and removes devices, edits automations and scenes, manages extensions, users and backups
- **Owner** has all administrator rights, appoints other owners and restores the hub from a backup

A user can be limited to selected rooms, then they see only the devices and events of those rooms. API tokens for external programs get read or control scope. Users and tokens are managed in System, see [System](/docs/system).
