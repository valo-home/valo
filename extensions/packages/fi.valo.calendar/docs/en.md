## What it does

Knows the public holidays of Ukraine and Finland, tells workdays from days off taking your vacations and swapped days into account and, with an ICS calendar link, sees events from Google Calendar, Nextcloud, Outlook and other calendars. Creates the "Calendar" device, the **Calendar** page, a widget and flow blocks.

## One-time setup

1. Install the extension
2. Choose **Holiday country**: `FI`, `UA` or `none`
3. **Holidays are days off** `auto` means holidays are days off in Finland and not in Ukraine, because public holidays are working days under martial law. Choose `yes` or `no` to set it explicitly
4. In **Extra days off** list vacation or swapped dates, one per line or separated by commas. A range is written with two dots, for example `2026-07-01..2026-07-14`
5. In **Extra workdays** list Saturdays and Sundays that became working days
6. For calendar events paste an ICS link into **ICS calendar link**

Where to get an ICS link
- Google Calendar: Settings, choose the calendar, Integrate calendar, **Secret address in iCal format**
- Nextcloud: Calendar, calendar menu, **Copy subscription link** (the `?export` download link)
- Outlook: Settings, Calendar, Shared calendars, **Publish a calendar**, ICS link

The link is stored encrypted and is not shown after saving. The calendar is reloaded every 15 minutes.

## How to use

- **Workday** for today or tomorrow. For example an alarm and morning light only on workdays
- **Public holiday** passes on a public holiday, notification text can use `{holiday}`
- **Calendar event now** checks whether an event whose title contains the given text is running now. Empty text means any event
- **Event on day** checks whether there is an event today or tomorrow
- The **Event starts** and **Event ends** triggers fire at the event time, `{title}` and `{start}` are available
- The "Calendar" device shows the workday flag, holiday, current and next event

## Ready templates

- **Holiday tomorrow** reminder at 20:00
- **Workday morning** at 6:30 on workdays only, add your own commands
- **Vacation start from calendar** for an event with the word "Отпуск" (change the text as needed)
- **Event reminder** when an event starts

## Limitations

Supported ICS recurrence rules are daily, weekly with weekdays, monthly and yearly with interval, count and end date, plus exceptions. Rules like "second Tuesday of the month" show only the first event. Events with invalid dates are skipped one by one, their number and the number of repeats shown once appear on the **Calendar** page.
