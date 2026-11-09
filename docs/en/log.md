# Log and notifications

The log answers what happened and why. Notifications show what needs attention right now. They are different things. An event in the log stays as history, a notification stays until the problem is solved.

## Log

The **Log** page shows events of devices, automations and the system, newest first. New events appear at once without reloading the page. **Show earlier** loads the next batch.

Each row holds the time, the event text, the author and the section. The author can be a user, an automation, an extension, an API token or the system. The **has a cause** mark means that the event was triggered by another event.

## Filters

- The **Search** field looks in the event text and the author
- **Event type** keeps one section, for example Devices, Commands, Scenes, Automations, Rooms, Zigbee, Extensions, MQTT, Users, Tokens, Assistant, Backups or Home
- Level buttons keep events of one level

## Levels

- **info** is an ordinary event, for example a state change or an automation run
- **success** means something finished well, for example a device is back online or a backup was created
- **warning** is worth a look, for example a device went offline, a room was deleted or the Zigbee channel changed
- **critical** is an alarm or a failure, for example a leak, smoke, an automation error or Zigbee2MQTT being unavailable

## Cause chain

Click the text of an event to open the **Cause chain**. It runs from the first cause to the selected event, for example a button press, then an automation run, then a light command. The steps link to the device and the automation.

## What writes to the log

- devices, for example state changes, button presses, adding, removing, renaming, moving to another room, going offline and back online
- device commands with the result done, failed or no response
- scenes and automations, for example applying a scene, a run, success, an error, a stop by a condition and the **Log entry** block
- the Zigbee network, for example devices joining and leaving, interviews, firmware updates, opening and closing the network, a channel change
- extensions, for example installing, updating, enabling, disabling, restarting and crashing
- the system, for example user logins, changes to users, tokens and home settings, backups and restores

A user limited to some rooms sees only the events of those rooms.

## Notifications

The bell in the top bar shows the number of active notifications. A click opens the **Notifications** panel with critical ones first. Each notification leads to the source of the problem, for example the device or automation page. The **Dismiss** button closes a notification by hand.

Most notifications close by themselves when the cause goes away. If the problem comes back, the notification appears again.

## What creates notifications

- **critical** a leak, smoke, carbon monoxide, a gas leak, Zigbee2MQTT offline longer than set in [System](/docs/system), an extension that keeps crashing, a failed backup
- **warning** an offline device, a device that does not respond to commands, a battery below 15%, an automation that failed
- an automation with the **Notification** block, at the level set in the block, see [Automations](/docs/flows)
- an extension with the **Notification delivery** permission

A battery notification closes when the charge rises to 20% or more.

## External delivery

Notifications can also reach you outside the interface, for example in Telegram, through a delivery extension. Which levels are sent out is set in System, tab Home, field **Levels sent to external delivery**, by default only critical. The automation **Notification** block with **Send externally** checked sends the message regardless of its level. See [Extensions](/docs/extensions) and [System](/docs/system).

## Short messages

After actions in the interface a short message appears at the bottom of the screen for a few seconds, for example **Device saved** or an error. Such messages are not notifications. Errors of the software itself are collected separately in System, tab **Errors**.
