## What it does

Tracks electricity usage of every device that reports power or energy: plugs, relays, meters. Keeps daily totals for more than two years, calculates cost by your tariff and creates the virtual device "Energy" with totals for today, month and year.

When a device reports a kWh counter, the counter increase is used (counter resets are detected). When it reports power only, energy is integrated from polls once a minute.

## One-time setup

1. Install the extension
2. Set **Price per kWh** from your electricity contract, including taxes
3. Set **Transfer per kWh**, the grid company fee added to the price
4. If the home has a main meter, choose it in **Main meter**. Home totals then come from it only and plugs show the breakdown. When the field is empty and the home has exactly one device of kind Meter, it is chosen automatically
5. In **Exclude** list device ids to skip, separated by commas

The currency comes from the home settings.

## How to use

- The **Energy usage** page shows totals, a 30 day chart and devices for the month
- The **Energy today** widget can be added to a dashboard
- The "Energy" device works in conditions and dashboards like any other
- The **Day summary** trigger fires after midnight. Notification text can use `{day}`, `{kwh}`, `{cost}`, `{currency}`, `{top}` (three most consuming devices)
- The **Usage above threshold** and **Cost above threshold** conditions check the total for today, yesterday, month or year

## Ready templates

- **Daily energy report** sends the day summary to all notification services, for example Telegram
- **Monthly budget exceeded** checks the monthly cost every evening at 20:00

## Limitations

Tracking starts when the extension is installed, past device data is not restored. When a device was offline for more than 10 minutes, power is not integrated for that gap.
