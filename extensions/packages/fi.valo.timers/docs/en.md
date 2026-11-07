## What it does

Creates named timers and alarms. Each of them becomes a device: a timer can be started or stopped with a switch on a dashboard, in the device list, from a flow or on the **Timers** page. An alarm fires at the given time on chosen weekdays or on workdays only. A finished timer and a firing alarm start flows.

## One-time setup

1. Install the extension
2. In **Timers** write one per line `Name=minutes`, for example `Kettle=4` or `Laundry=90`
3. In **Alarms** write one per line `Name=HH:MM days`, for example `Wake up=07:00 mon-fri`
4. Save the settings, the extension restarts and creates the devices

How days are written
- empty or `every` means every day
- `mon-fri`, `sat,sun`, `mon wed fri`, numbers `1-5` (1 is Monday)
- `workdays` workdays only, `weekends` days off only. With the "Calendar and workdays" extension installed holidays and vacations are taken into account, without it Monday to Friday are workdays

Day names are understood in English, Ukrainian and Russian.

## How to use

- The timer switch starts it for the time in **minutes**, pressing again stops it. The duration can be changed right in the device card
- In the alarm card you can turn it off and change time and days. Changes are kept until the line of this alarm changes in the settings
- The **Timer finished** trigger with an optional timer name, `{timer}` and `{minutes}` are available
- The **Alarm** trigger with an optional name, `{alarm}` and `{at}` are available
- Actions **Start timer** (another number of minutes can be given) and **Stop timer**, condition **Timer running**. A timer is referenced by name
- The **Timers and alarms** widget shows the remaining time and the next alarm

## Ready templates

- **Timer finished, notify** for all timers
- **Alarm: light and message** for the alarm "Подъем", add a command that turns on the light
- **Sauna: turn off after timer**, add a command that turns off the heater

## Limitations

If the server was off when an alarm was due, the missed alarm is not repeated. A running timer survives a restart and, if its time ran out during the restart, fires right after the start.
