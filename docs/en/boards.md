# Dashboards and widgets

A dashboard is your own screen of widgets, for example for a kitchen tablet, a phone or energy tracking. Dashboards are shared by all users of the home. Any user can view them, residents, administrators and the owner can create and edit them.

## Dashboard list

The **Dashboards** page shows dashboard cards with the name, the number of widgets and the first widgets. A click on a card opens the dashboard. **New dashboard** asks for a name and opens the empty dashboard right away.

## Customize mode

On a dashboard press **Customize**. The button turns into **Done**, and the **Add widget** and **Dashboard settings** buttons appear. Each widget gets its tools.

- **Widget settings** opens the parameters of this widget
- **Width** switches between normal width 1× and double width 2×
- **Height** cycles through auto, 1×, 2×, 3× and 4×
- **Delete** has to be pressed twice within three seconds, after the first press the button shows **Confirm deletion**

Changes are saved immediately, there is no separate save button.

## Widget order

In customize mode widgets can be dragged with the mouse or a finger. With the keyboard, Tab to a widget, press space or Enter, choose the new place with the arrow keys and press space or Enter again. Outside customize mode the order cannot change, so widgets do not move by accident.

## Adding a widget

1. Press **Customize**, then **Add widget**
2. Choose a type in the **Devices**, **Home** or **Services** groups. A short description of the type is shown below
3. Choose a device, a room or a value if the type needs one
4. Optionally set the title, width and height
5. Press **Add**

## Devices group

- **Device** shows all readings of a device, its controls, battery and update time
- **Sensor** shows temperature and humidity in large digits, the 24 hour minimum and maximum and a chart. Only devices with readings are listed
- **Plug** shows power, voltage, current, energy today and total, a power chart and a switch. Only devices that measure power are listed
- **Thermostat** shows the current temperature and setpoint buttons. Only devices with a writable setpoint are listed
- **Value** shows one value in large digits with a 24 hour chart and the minimum, average and maximum. A device and a capability have to be chosen
- **Chart** shows the chosen capability for **24 h**, **7 days** or **30 days**
- **Camera** shows a camera snapshot that refreshes every 10 seconds. A tap opens the camera page with live video, see [Cameras](/docs/cameras). The snapshot is shown to residents and higher

Energy today is calculated from the device energy counter since the start of the day in the home time zone.

## Home group

- **Room** shows the temperature, humidity, lights and up to six devices of a room, a **Turn all off** button and a link to the remaining devices
- **Room lights** shows the lights of the chosen room with switches
- **Scenes** shows buttons for all scenes
- **Needs attention** lists alarms, offline devices, open doors and windows and low batteries. When everything is calm it shows **All good**
- **Batteries** shows up to eight battery devices, lowest charge first
- **Power use** shows the total power and up to eight plugs and meters with the highest power now
- **Leaks** shows the state of all leak sensors
- **Doors and windows** shows the state of all contact sensors

## Services group

- **Clock and weather** shows the time, date, outside weather, a holiday or calendar event and the next alarm. Weather comes from a weather service or, if there is none, from a sensor in an outdoor room
- Widgets of installed extensions, for example **Weather now**, **Calendar today**, **Energy today**, **Timers and alarms**

If a matching extension from the catalog is not installed yet, the line **More services in the catalog** links to it. If the extension of a widget is disabled or removed, the widget shows **The extension is disabled or not installed** and an **Open extension** link. See [Extensions](/docs/extensions).

## Widget settings

- **Title** up to 60 characters. When left empty, the name of the device, room or widget is used
- **Width** 1× or 2×. Charts, rooms and power use are added at double width by default
- **Height** auto or 1× to 4×. One step is 164 pixels and the widget height is always a multiple of the step. In auto mode the height follows the content, up to four steps. If the height is set larger than needed, the chart inside the widget stretches into the free space
- **Place** is available in weather widgets. Type a city, press **Search** and pick a result. The **Home, coordinates from settings** option uses the coordinates from the home settings

## Dashboard settings

**Dashboard settings** in customize mode lets you change the **Dashboard name** and delete the dashboard with **Delete dashboard**. The button has to be pressed twice within three seconds, after the first press it shows **Confirm deletion**.

A dashboard can also be built in words through the assistant, for example by asking for a dashboard with a plug voltage chart, see [Assistant](/docs/assistant).
