## What it does

Brings all leak, smoke, carbon monoxide and gas sensors together. When a sensor fires, the extension records an incident, raises the alarm, sends a critical notification and starts flows. When the home is armed and a leak sensor fires, the extension switches off the devices listed in the settings, for example a pump, a water heater or an electric valve.

Creates the device "Home safety" with the flags `armed` (can be switched) and `alarm`, the number of sensors and warnings and the date of the last smoke detector test. Sensors are found by the capabilities `leak`, `smoke`, `co` and `gas`, new ones are picked up within a minute.

Besides alarms the extension watches batteries (below 20%) and sensor connectivity, and every given number of days reminds you to test the smoke detectors with the test button.

## One-time setup

1. Install the extension
2. In **Switch off on a leak** tick the plugs or relays to switch off on a leak. The list shows only devices that can be switched on and off. The field can stay empty
3. In **Smoke detector test, days** set how often to remind about the test, 30 days by default
4. In **Exclude** tick the sensors that should not be watched

The extension restarts after the settings are saved. The home is armed by default.

## How to use

- The **Safety** page shows the overall state, sensors with battery and last seen time, reminders and the incident log
- **Clear alarm** acknowledges the alarm. While a sensor still reports a leak or smoke, the alarm stays on
- **Disarm** and **Arm** control switching devices off on a leak. Alarm notifications are always sent
- Press the test button on a smoke detector, then **Tested today** on the page. If the detector reports the test button itself, the test date is recorded automatically and smoke within two minutes after the test is not treated as an alarm
- The **Home safety** widget shows the state and the sensors that need attention

## Flow blocks

- Trigger **Safety alarm** with an optional kind (`leak`, `smoke`, `co`, `gas`) and device. The text can use `{name}` (the sensor), `{room}`, `{what}` (what happened), `{kind}` and `{shutoff}` (what was switched off)
- Condition **Armed**
- Actions **Arm**, **Disarm** and **Clear alarm**

## Ready templates

- **Leak, notify everyone** sends a critical message to every notification service
- **Smoke, lights on and notify**, add a command that turns the lights on after the trigger
- **Arm for the night** arms the home at 23:00 if it was disarmed

## Limitations

The core itself creates a critical notification about a leak or smoke, the extension adds its own with the list of devices switched off. Switching off works only for devices with a controllable on state.
