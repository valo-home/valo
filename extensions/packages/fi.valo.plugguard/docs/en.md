## What it does

Watches every plug and relay with power metering that can be switched on and off. When power stays above the limit for longer than the delay, the plug is switched off, a warning is sent and flows start. An overloaded extension cord or a faulty appliance is cut off before the wiring overheats.

Plugs from a separate list are switched off when they draw less than a threshold for a long time, for example a TV or a charger left in standby. The list is empty by default, so this feature is off.

For every plug it counts energy today, peak power and time on, and the usage of all plugs by hour. When a plug reports a kWh counter, its increase is used, otherwise energy is integrated from power. Totals are kept in the extension data and survive restarts. Creates the device "Plug guard" with total power, energy today, peak and the number of overloads.

## One-time setup

1. Install the extension
2. **Power limit, W** is 2500 W by default. A regular 16 A plug allows about 3500 W, use less for extension cords or old wiring
3. **Switch off delay, s** is 10 s by default, so a short inrush current does not switch the appliance off
4. For standby switch off tick the plugs in **Switch off in standby**, then set **Standby below, W** (3 by default) and **Standby longer than, min** (30 by default)
5. In **Never switch off on overload** tick the plugs that must not be switched off automatically, for example a fridge. Their usage is still counted

The plug id is shown on the device page. The extension restarts after the settings are saved.

## How to use

- The **Plugs** page shows total power, usage by hour today and the list of plugs with power, energy, peak and time on. The buttons in a row switch the plug on and off
- The **Plugs now** widget shows total power and the busiest plugs
- In the demo environment the coffee machine briefly draws about 1350 W. To see the protection at work, set the limit to 1000 W for a while

## Flow blocks

- Trigger **Plug overload** with an optional plug. The text can use `{name}`, `{w}` (power) and `{limit}`
- Trigger **Switched off after standby** with an optional plug, `{name}`, `{w}` and `{minutes}` are available
- Condition **Plug power above** for the chosen plug and a threshold in W, `{plug}` and `{power}` are available

## Ready templates

- **Plug overload, notify** sends a message with the power and the limit
- **Device switched off after standby** records a message without sending it outside
- **High load at night** checks the chosen plug at 01:00

## Limitations

The protection runs in the extension, not in the plug itself, so it adds to, and does not replace, the circuit breaker and the plug's own protection. After a trip the same plug can be switched off again no sooner than in 30 s, and a repeated notification and trigger for it come at most once in 10 minutes. If a plug is offline for more than 10 minutes, energy for that gap is not integrated from power.
