# Extensions

An extension adds to Valo a feature the core does not have. For example weather, energy usage, Telegram notifications or leak protection. Extensions are installed from the catalog on the **Extensions** page.

## How an extension works

- Every extension runs as a separate process. The core starts it, watches it and restarts it after a crash. A crash of an extension does not stop the core or Zigbee
- An extension talks to the core only through the MQTT broker and only with the set of calls defined by the core. It has no direct access to the database
- Permissions are granted at install. On every call the core checks reading devices, controlling devices and notification delivery. The broker lets an extension into its own topics only and into those allowed by its permissions
- The process runs with a lowered priority and with memory and CPU limits. When a limit is exceeded, the process is stopped and restarted. After five crashes within 10 minutes the extension stays in the error state until it is started by hand
- Secret settings, for example a bot token, are stored encrypted in the database and are not shown after saving
- Extension data is stored apart from the code and survives updates

## What an extension can add

- devices and services. An extension device is an appliance the extension connects or simulates, it is controlled like any other. A service is a record without an appliance of its own, for example weather, calendar, timers, energy usage, home safety or plug guard. Services are not counted as devices, see [Key concepts](/docs/concepts)
- pages in the menu. They appear in the Extensions section, if there are more than three, they are collapsed into the **Pages** item
- dashboard widgets, see [Dashboards](/docs/boards)
- automation blocks and templates, see [Automations](/docs/flows)
- notification delivery to external channels, for example Telegram
- a Zigbee2MQTT converter for a device that Zigbee2MQTT does not recognize by itself
- cameras. A driver extension connects cameras of its make and reports their streams and motion events, a detection extension adds events such as a person or a car on any camera, see [Cameras](/docs/cameras)

## Trust level

- **official** is published by the Valo team
- **community** is written by third party authors. At install a warning is shown that the extension is not reviewed by the valo team
- **local** is an extension for development, it runs directly from the source folder

## The Extensions page

The **Installed** tab shows extensions with their version, state (**running**, **starting**, **stopped**, **error**, **installing**, **updating**, **removing**), trust level and the **update to** mark when a new version is available. Below the description of an installed extension there is the **Adds** line with what it brought into the home, for example "Adds: 2 services, 1 page, 1 widget, 6 flow blocks, 4 templates".

The **Catalog** tab shows available extensions. The **About** button opens the detailed description of the extension with its one time setup, it can be read before installing.

### Installing

1. Open the **Catalog**, read **About**
2. Press **Install**
3. In the **Install «name»** dialog check the list of permissions the extension will receive
4. Press **Allow and install**
5. Open the extension in the **Installed** tab and fill in the settings as its description says

### Extension card

Pressing an extension opens its card. It shows
- the state, the process number, current memory and CPU with limits, the number of restarts
- the error text if the process crashed
- **What it adds** with links. Devices and services open the **Devices** page filtered by this extension, the page leads to the extension page, widgets to dashboards, blocks and templates to automations
- the **About**, **Disable** or **Enable**, **Restart** buttons
- **Settings**. After **Save** the extension restarts with the new values. For a secret field leave it empty to keep it, or press **Remove the stored value**
- **Permissions** granted to the extension
- **Automation blocks** it adds
- **Process log** with the extension output in real time
- **Remove extension**, the press must be confirmed. The extension devices and services are removed together with it

### Updating

When the catalog has a new version, the card shows the **update to** button with the version number. The new version is started next to the old one, and the old one is stopped only after the new one has started successfully. If the new version failed to start, the previous one keeps running and the card shows the error text. If the new version needs new permissions, a dialog with the list of these permissions and the **Allow and update** button appears first. New settings get default values, existing ones are kept.

## Extension devices and services

Extension devices are shown on the **Devices** page, **Devices** tab, under the source filter button named after the extension. Extension services are collected on the **Services** tab, where they can be filtered by extension. The quickest way to them is the links in the **What it adds** section of the extension card. An extension device can be renamed and placed in a room like any other, see [Devices](/docs/devices). If the extension is stopped, its devices and services stay in the list but are not updated, and commands to them end with a timeout. The extension blocks in automations are unavailable at that time, see the "Missing block" section on the [Automations](/docs/flows) page.

## Extensions in the catalog

- **Telegram notifications**. Forwards notifications to Telegram, gives the "Telegram message" block with variables and action buttons, answers the `/status`, `/devices`, `/help` commands. Has a Telegram page and automation templates
- **Energy usage**. Counts consumption by plugs, relays and meters, keeps daily totals and computes the cost by tariff. Page, widget, the "Day summary" block and conditions on usage and cost
- **Open-Meteo weather**. Current weather, hourly and daily forecast, air quality and pollen for the home coordinates, no key needed. The **Weather** page, the **Weather now** widget with a city choice, conditions for precipitation, frost, heat, wind, air and pollen
- **FMI weather**. Forecast of the Finnish Meteorological Institute, the "Rain expected" and "Frost expected" conditions
- **Calendar and workdays**. Public holidays of Ukraine and Finland, vacations and moved days, events from an ICS calendar. The **Calendar** page, a widget, workday and holiday conditions, event start and end triggers
- **Alarms and timers**. Named timers and alarms as services, the **Timers** page, a widget and blocks to start, stop and finish a timer
- **Home safety**. Leak, smoke, carbon monoxide and gas sensors in one place. Alarm, notifications, switching devices off on a leak, reminders about batteries and smoke detector tests. Works as a service with an arming switch. A page, a widget and automation blocks
- **Plug guard**. Overload protection for plugs, switching off devices left in standby, usage of every plug today and by hour. Works as a service. A page, a widget and automation blocks
- **Room presence**. Room occupancy from motion and door sensors, the "Room became empty" trigger. From the community
- **Sauna**. Watches heating by a temperature sensor, a widget with progress and the "Sauna is ready" trigger. From the community
- **Tuya TS0601 converter**. External Zigbee2MQTT converter for the Tuya TS0601 floor heating thermostat. From the community
- **Thingino cameras**. Driver for cameras on the open Thingino firmware, for example Sonoff CAM Slim Gen2 and CAM-PT2. Video, snapshots and motion from the camera without a cloud
- **RTSP camera**. Driver for any IP camera with an RTSP stream. Live view, snapshots and recording on events from detection or automations
- **Device simulator**. Virtual sensors to test automations without hardware and demo cameras with a test picture, for development only

The one time setup of every extension is described in its **About** in the catalog.

## Permissions

Permissions an extension can request
- **Read device state**
- **Control devices**
- **Own virtual devices**
- **Notification delivery**
- **Outbound requests** to given addresses or to any address
- **Publish** to a given MQTT topic
- **Page in the interface** and **Dashboard widget**
- **Zigbee2MQTT converter**
- **Connect its own cameras**. A driver creates its own cameras and reports their streams and events
- **Camera video for analysis**. The internal address of a camera stream for detection, for example of people
- **Detection events on cameras**. Report detection events on any camera
- **Save snapshots and clips**
- **Read snapshots and clips**

The recordings folder is not accessible to extension processes. An extension gets and saves snapshots and clips only through the core and only with these permissions.

Extensions are installed, configured, updated and removed by an administrator. Extension pages and widgets are visible to all users. How to write your own extension is described in [Extension development](/docs/ext-dev).
