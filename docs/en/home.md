# Overview and home plan

The **Overview** page opens first and answers what is happening at home right now. The **Rooms** page is where you create rooms, assign devices to them and draw the plan.

## Overview page

The header shows the home name, the date, the outside and inside temperature and the current power use. The outside temperature is the average of climate sensors in outdoor rooms, the inside one is the average of the other climate sensors. Power use comes from an electricity meter if there is one. The **Dashboards** and **Rooms** buttons lead to those pages.

A warning strip appears under the header when something needs attention. It lists open doors and windows, leaks, smoke, carbon monoxide and gas, low batteries and offline devices. Each warning leads to the device page.

Cards on the right side

- **Scenes** with buttons that apply scenes
- **Climate** with the temperature per room and the heating target if the room has a radiator valve or floor heating. A tap opens the room panel
- **Energy** with today's energy use and cost if the energy usage extension is installed, and the current load
- **Home pulse** with the latest events and a link to the Log

## Home plan

The plan of the selected floor is in the middle of the page. The **Floor 1**, **Floor 2** and further buttons above it switch between floors that have placed rooms. Next to them are the lights, open, leaks and automations now summaries.

Each room on the plan shows its name, temperature, humidity or heating target and short notes, for example offline, leak, open or heating. A room with lights on glows. Device icons are colored by state.

- amber means a light or heating is on
- a blue pulse means motion
- red means an alarm, a low battery or a lost connection

Hover over an icon to see the device name and state. Click a room to open its panel. Extension services are not shown on the plan, see [Key concepts](/docs/concepts).

If no room has been placed yet, the plan is replaced by **The home plan is empty** with an **Add rooms** button.

## Room panel

The room panel slides in when you click a room on the plan, in the Climate card or on the Rooms page.

- The list of room devices with their state and quick controls, for example a switch, setpoint buttons or blind buttons
- **Choose existing** opens a list of all devices with check boxes. Check the devices of this room and press **Save**, a device from another room is moved here
- **Pair new** opens device pairing, and the new device lands in this room right away
- **Automations with devices of this room** lists automations that use the room devices and the result of their last run
- On the Rooms page there is also an **Edit room** button

Choosing, pairing and editing are available to administrators.

## Rooms page

Rooms are grouped by floor. A room card shows the temperature, how many lights are on, the number of devices and problem notes, or **all fine**.

To create a room, press **Add room** and fill in the fields.

1. **Name** and **Floor** (from -2 to 20)
2. The **outdoor** check box for a yard, balcony or other outside area
3. **Position on the plan** in the Left, Top, Width and Height fields. The defaults can be kept and adjusted later in the plan editor

Room removal is in the **Edit room** window. The first press on **Delete** turns the button into **Confirm deletion**, the second one deletes. Devices of a removed room stay without a room.

## Plan editor

The editor opens with **Edit plan** on the Overview or next to a floor on the Rooms page. It is available to administrators.

1. Drag a room with the mouse or a finger, its position snaps to the grid
2. Resize it by the square in the bottom right corner
3. Device icons can be dragged inside the room too. Dashed icons are not placed yet and sit in the common row at the bottom of the room
4. A selected icon has a **Back to the row** button that drops its manual position
5. A selected room shows its coordinates and a **Remove from plan** button. The room stays in the list but disappears from the diagram
6. Rooms of the floor that are not on the diagram are listed in the **Not on the plan** row, a click on a name adds the room to the diagram

With the keyboard, the arrow keys move the selected room by one grid step and Shift with the arrows resizes it. If a device icon is selected, the arrows move the icon. Changes are applied only with **Save**, **Cancel** closes the editor without saving.
