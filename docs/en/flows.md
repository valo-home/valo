# Automations

An automation is a rule of the form "when this happens, under these conditions, do that". It consists of blocks connected by lines. An event starts the automation in a trigger block, then execution follows the links from block to block. Automations run on the hub by themselves, no open page is needed.

An automation is not the same as a scene. A scene is a saved set of device states that is applied with one tap, see [Scenes](/docs/scenes). An automation can apply a scene with the **Scene** block.

## Automation list

The **Automations** page in the Automation section, **Automations** tab. The table shows for each automation

- the enable toggle. A disabled automation does not react to events
- the name and the **missing block** mark if the automation uses an unavailable block
- the run **Mode**
- **Last run** with the result and time
- **Runs**, the total number of runs
- the **Run** button for a manual run

Below the table the line "Today successful runs, failed, waiting" counts runs since the start of the day.

## Creating an automation

1. Press **New automation**
2. Enter a name and choose a **Template** or **Empty automation**
3. Press **Create**, the editor opens

A new automation is created disabled. Templates give a ready layout, but no devices are selected in them. Select the devices in every block, fill in the notification texts, save and enable the automation. Built in templates are **Light on motion**, **Leak alarm**, **Window and heating**, **Lights at sunset**, **Plug cycle, 5 min on, 10 off**, **Device offline**. Installed extensions add their own templates, they are marked with the extension identifier.

## Editor

On the left is the block palette grouped by kind, in the center the canvas, on the right a panel with the **Block**, **Check**, **Runs** and **Versions** tabs. The top bar holds the name, the mode, the **enabled** toggle and the **Test**, **Run** and **Save** buttons.

1. Press a block in the palette, it appears on the canvas
2. Select the block on the canvas and set its parameters in the **Block** tab
3. Connect blocks by dragging from the output on the right of one block to the input on the left of another. The editor refuses an incompatible connection
4. Press **Save**

Conditions have two outputs, **yes** and **no**. If the **no** output is not connected, execution stops there. One output can be connected to several blocks, then all of them run.

Ctrl+Z undoes, Ctrl+Shift+Z redoes, Ctrl+C and Ctrl+V copy blocks with their links, Ctrl+D duplicates. Select several blocks with a Shift drag box. A block is removed with the Delete key or the **Remove block** button.

## Blocks

Triggers start the automation
- **State change**. A device capability changed, the new and previous value can be set
- **Threshold**. A numeric value crossed the threshold upwards (above) or downwards (below)
- **Device button**. A press of a button or remote, a specific action can be set
- **Schedule**. A time in five field cron format in the home time zone, for example `0 7 * * 1-5` at 07:00 on weekdays, `*/15 * * * *` every 15 minutes
- **Sun**. Sunrise or sunset for the home coordinates with an offset in minutes. **Fallback time** is used when the sun does not rise or set
- **MQTT message**. A message in a topic, the `+` and `#` wildcards are allowed
- **Manual**. Started only with the **Run** button
- **Log event**. A log entry of the given type and level, for example `device.offline`, `*` is allowed
- **Camera event**. A camera reported motion or a detected object (person, car, animal), at the start or at the end of the event

Conditions check the situation
- **Compare**. The value of a device capability is compared with a given one
- **Time window**. The current time is inside the window, the window may cross midnight
- **Weekday**. Today is one of the selected days
- **State held**. The value has matched the given one for at least the given number of minutes
- **Expression**. A formula, for example `state("0xa4c138f5b29d372e", "leak") == True and hour >= 22`. Available are `state("device", "capability")`, `value`, `hour`, `minute`, `weekday` (1 is Monday), `min`, `max`, `abs`, `round`, `low_battery()`, `offline()`, `alarms()`. The device identifier is shown in the address of its page, for Zigbee devices it is the IEEE address
- **Device is online**. If no device is selected, the device from the event is used

Logic controls the flow
- **Branch**. Output **case 1** or **case 2** by the capability value, otherwise the **else** output
- **Delay**. A pause for the given number of seconds
- **Wait**. Waits until the capability takes a value. Output **done**, or **timeout** if the waiting time ran out
- **Debounce**. Passes on only the last event of a series, once events have stopped arriving for the given time
- **Counter**. Passes on when the event repeated the given number of times within a window in minutes

Actions change the home
- **Command**. Sets values on a device, for example power or brightness
- **Scene**. Applies a scene
- **Notification**. Creates a notification in the notification center with the level info, warning or critical. **Send externally** passes it to external channels, for example Telegram, regardless of the levels in the home settings
- **MQTT publish**. Sends a message to a topic, it can be retained on the broker
- **Log entry**. Adds an entry to the log
- **Camera snapshot**. Saves a snapshot of the selected camera or of the camera from the event and gives the `{snapshot}` variable with a link to it
- **Camera clip**. Records a clip of the given duration, 30 seconds by default. More about cameras in [Cameras](/docs/cameras)

Data
- **Math**. Computes a new value from a formula with `value`. At present its output is compatible only with the input of another **Math** block

Extensions add their own blocks, in the palette they are marked "ext". The list of an extension's blocks is shown in its card on the Extensions page.

## Notification text

In the text of the **Notification** block and in text parameters of extension blocks the event variables are substituted: `{device}`, `{name}`, `{room}`, `{cap}`, `{value}`, `{old}`, `{unit}`, `{time}`, `{date}`, `{flow}`, `{home}`, `{event}`, for camera events `{label}` and `{snapshot}`, and the lists `{low_battery}`, `{offline}`, `{alarms}`. An unknown variable stays in the text as is.

As long as the notification from a block is not dismissed in the notification center, a repeated firing updates it but does not send it externally again.

## Run mode

The mode matters when the previous run has not finished yet, for example it is waiting in a **Delay**, **Wait** or **Debounce** block.

- **single**. A new event is skipped while the previous run is going
- **restart**. The previous run is cancelled and a new one starts. Suits light on motion, the countdown starts over
- **queued**. A new event waits and runs after the previous run ends
- **parallel**. Runs go at the same time, no more than 10, extra ones are skipped

## Test, run and result

**Test** performs a dry run without commands. It takes the current layout from the editor, even unsaved, and starts from the selected trigger or from the first trigger. Conditions are checked against the current state of the home, while commands, scenes, notifications, publishing, delays and waits are skipped. The **Check** tab shows the trace, which path execution took and why, the links passed are highlighted.

**Run** executes the automation for real, starting from the **Manual** block or from the first trigger. The button is available when the automation is enabled and saved.

Run result
- **ok**, execution reached the end
- **condition not met**, a condition stopped execution and no action was performed
- **waiting**, the run is waiting in a delay or wait
- **failed**, a block ended with an error. A notification about the automation failure is created

The **Runs** tab keeps the real runs with the trace of each, dry runs are not stored there. The **Versions** tab keeps earlier versions of the layout, each save with a changed layout creates a new version, the **Restore** button brings back the selected one.

## Missing block

The **missing block** mark means the automation contains a block of an extension that is not installed, disabled or not running. Such an automation is started neither by events nor by the button, testing is unavailable as well. It works again by itself when the extension runs again. If the extension is no longer needed, remove its blocks from the automation.

Removing a device does not mark the automation. A block with the removed device stays in the layout, at run time the command to it ends with an error, so after removing a device check the automations where it was used.

## Example: leak

Goal: on a leak in the bathroom send an urgent notification and switch off the washing machine plug.

1. **New automation**, template **Leak alarm**, **Create**
2. In the **State change** trigger select the leak sensor, capability **Leak**, new value **yes**
3. In the **Notification** block write a text, for example `Leak: {device}, {room}, {time}`. Level critical, **Send externally** on
4. In the **Command** block select the washing machine plug and the value **Power** no
5. **Test**, the trace should contain the notification and the command marked as not sent in test
6. **Save** and enable the automation

In the demo environment a leak can be triggered with the command `./valo demo ctl bath-leak water_leak=true`.

## Example: evening lights

1. Create the scene "Evening" with the lamps you need, see [Scenes](/docs/scenes)
2. **New automation**, template **Lights at sunset**
3. In the **Sun** trigger keep sunset and the offset `-15`, the light turns on 15 minutes before sunset
4. In the **Scene** block select "Evening"
5. If you like, insert a **Weekday** or **Time window** condition between them
6. **Save** and enable the automation

Automations are created and changed by an administrator, run and tested by a resident and above. Role permissions are described in [System](/docs/system).
