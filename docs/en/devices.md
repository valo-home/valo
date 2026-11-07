# Devices

The **Devices** page is the full list of everything connected to the hub, with filters and a link to the page of each record. The subtitle shows the number of devices, the number of services and how many devices are offline. Services are not counted as devices, see [Key concepts](/docs/concepts).

## Devices and Services tabs

The top of the page has two tabs, each with a counter.

- **Devices** are home appliances that are controlled or measure something. They are connected over Zigbee, over MQTT or through an extension, for example **Device simulator**
- **Services** are records an extension creates without an appliance of its own, for example weather, air quality, calendar, timers and alarm clocks, energy usage, home safety, plug guard and presence

The chosen tab is kept in the page address, the **Services** tab opens with `?tab=services`. Such a link can be bookmarked or sent.

## List and filters

The **Devices** tab has a search field and three filters.

- The **Search** field looks in the name, model and identifier
- The room selector keeps the devices of one room, **No room** shows devices not yet assigned
- The source filter keeps devices by the way they are connected
- The state filter keeps devices with problems

The table shows the name, room, state with battery level, source, link quality and last activity. A page holds 50 rows, a pager is below. A click on a row opens the device page.

## Source filter

The buttons are built from what exists in the home. A source without devices is not shown, and if there is only one source the filter is hidden.

- **Any source** clears the filter
- **Zigbee** shows devices paired with the stick through Zigbee2MQTT
- **MQTT** shows devices connected through the broker. These are devices with firmware for the hub/v1 contract, third party devices that announced themselves in the Home Assistant format and devices created by hand from MQTT topics
- a button named after an extension, for example **Device simulator**, shows the devices that extension connects. Every extension that connects at least one device has such a button

HA discovery and manual topic mapping are ways of connecting over MQTT, so they have no buttons of their own. In the table such devices show the **MQTT** mark with a small **HA discovery** or **Mapping** note under it. Services are not part of this filter, they are collected on the **Services** tab.

## What an extension device is

An extension device is created by an installed extension rather than by the Zigbee network or the broker. It can be a virtual device, for example the simulator sensors for testing automations or a sauna with a heat up estimate, or an appliance that the extension connects through its own protocol or cloud service. The state of such a device is set by the extension process, and commands go to the extension too.

Differences from a Zigbee device

- it needs no pairing, it appears after the extension is installed and configured
- it has no Zigbee network data, link quality, firmware or updates
- while the extension is disabled the device is not updated, and removing the extension removes its devices
- extension services, for example weather, calendar, timers, energy usage, home safety and plug guard, are listed on the **Services** tab, not among the devices. The extension itself decides what is a service, see [Key concepts](/docs/concepts)

Elsewhere in the interface extension devices behave like any other device, they can be put into a room, added to a dashboard and used in automations.

## Cameras

A camera is an extension device of the camera kind. In the list it appears under the source button named after the driver, for example **Thingino cameras**. On the device page a camera shows the **Motion** capability. Live video, events, snapshots, clips and recording settings are on the camera page in the **Cameras** section, more in [Cameras](/docs/cameras).

## State filter

- **No filter** clears the filter
- **Offline** shows devices that stopped reporting
- **Low battery** shows devices with a charge below 15%
- **Weak signal** shows Zigbee devices with link quality below 60

## Services tab

The **Services** tab has a search field and a filter by extension.

- The **Search** field looks in the name, model and identifier
- The extension filter. **All extensions** clears it, the other buttons are named after the extensions that have services. If only one extension has services, the filter is hidden
- The table shows the name, state, extension and last activity. The extension name links to its card on the [Extensions](/docs/extensions) page

An address with `?ext=<extension id>` preselects the extension. The links in the **What it adds** section of an extension card work this way, the devices link opens the **Devices** tab with the button of that extension, the services link opens the **Services** tab filtered by it. A click on a row opens the service page, it works like a device page. A service has no battery or link quality, so this tab has no state filter.

## Device page

The header shows the name, room, model, a source mark and an **offline** mark if the device is unavailable. The source mark is **Zigbee**, **MQTT**, **MQTT · HA discovery**, **MQTT · Mapping**, **Extension** or **Service**. An extension device or service also has a link to the card of its extension. Administrators see the **Edit** button.

The **Control** card (or **State** for a device without controls) lists all capabilities of the device. Readings are shown as values, writable capabilities as controls, for example a switch, a brightness slider, a number field, a color picker or mode buttons. Until the device confirms a command, the control shows that it is pending. The bottom of the card shows the time of the last message.

The **History** card charts the chosen capability for **24 h**, **7 days** or **30 days**. If there are several capabilities, a switch above the chart selects one. The 24 hour chart uses every value, the week and month charts use hourly averages with minimum and maximum. Detailed history is kept for the number of days set in the home settings, see [System](/docs/system).

Tabs at the bottom of the page

- **Events** shows the log of this device
- **Commands** shows sent commands with time, values, status (done, pending, no response, failed) and author
- **Automations** shows automations that use the device
- **MQTT topics** shows the latest broker messages for the device, the tab is available to administrators

## Zigbee details

A Zigbee device has a separate card with the IEEE address, network address, network role, power source, link quality, model, firmware version and update state. Administrators get the **Check for update**, **Reconfigure** and **Re-interview** buttons, and an **Update** button when new firmware is available. See [Zigbee](/docs/zigbee).

## Device settings

The **Edit** button opens the **Device settings** window.

1. **Name** changes the device name across the interface
2. **Room** puts the device into a room or takes it out
3. **Type** changes the device kind, which defines the icon and the state summary
4. **Save** applies the changes

The same window contains **Remove device**. A Zigbee device is told to leave the network, and its history and references in automations are removed. **Force if the device does not respond** removes the record even if the device did not confirm leaving. For other sources the description and history are removed, but the device may reappear if it keeps announcing itself. The remove button has to be pressed twice.

## Pairing a new device

A new device is added with **Add device** in the top bar or **Pair new** in a room panel. Step by step pairing is described in [Zigbee](/docs/zigbee), issuing an account for an MQTT device in [MQTT](/docs/mqtt).
