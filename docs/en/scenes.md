# Scenes

A scene is a saved snapshot of the state several devices should be in. For example the scene "Evening" remembers that the floor lamp is on at 30 percent brightness, the ceiling light is off and the plug with the garland is on. Pressing **Apply** sends every device a command to go to the remembered state.

## How a scene differs from an automation

- A scene watches nothing and never starts by itself. It is applied by a person with a button, from a dashboard, through search or the assistant, or by an automation with the **Scene** block
- An automation reacts to events, checks conditions and performs actions step by step, see [Automations](/docs/flows)
- A scene sets only the final state of devices. Delays, conditions and notifications are not part of it

A handy rule. If you need "make it so", it is a scene. If you need "when this happens, make it so", it is an automation that applies a scene.

## Where scenes are

The **Automations** page, **Scenes** tab. Each scene is shown as a card with a name, an icon and a list of actions in the form "device: values". The card has the **Apply** and **Capture current state** buttons, and for an administrator also **Edit**.

A scene can also be applied
- on the **Overview** page in the **Scenes** block
- with the **Scenes** widget on a dashboard, see [Dashboards](/docs/boards)
- through **Search and commands** (Ctrl K), start typing the scene name
- by asking the assistant, it offers an action with a confirmation button, see [Assistant](/docs/assistant)

## How a scene remembers values

Values are not typed into a scene by hand. The scene takes them from the current state of the devices.

- When the scene is saved, for each newly ticked device all its controllable capabilities are recorded with the values the device has right now. In the dialog this is shown as the "current state" mark to the right of the device
- For devices that were already in the scene, the stored values do not change on a repeated save
- The **Capture current state** button overwrites the values of all scene devices with their current state. The set of devices and capabilities stays the same

All controllable capabilities of a device are recorded, not only power and brightness. For example the settings of a plug may also end up in the scene. The full set is shown in the action line on the scene card.

So the order of work is always the same. First bring the devices to the wanted state, then save or overwrite the scene.

## Creating a scene

1. Set up the devices by hand the way they should look in the scene, for example on the Overview or Devices page
2. Open **Automations**, the **Scenes** tab, press **New scene**
3. Enter a name and choose an **Icon**
4. In the **Scene devices** list tick the devices you need. The list contains only devices that can be controlled
5. Press **Save**

## Changing values

1. Apply the scene or bring its devices by hand to the new wanted state
2. On the scene card press **Capture current state**
3. Check the action line on the card, it already shows the new values

## Adding and removing devices

1. On the card press **Edit**
2. Tick a new device, it is recorded with its current state. Untick a device to remove it from the scene
3. Press **Save**

In the same dialog the **Delete** button deletes the scene, the press must be confirmed. Automations where this scene is selected in the **Scene** block will end with an error after deletion.

## What happens on apply

1. An entry about applying the scene is written to the log
2. A command is sent to every device of the scene, devices the user has no access to or that are already removed are skipped
3. Each command is confirmed when the device reports the new value
4. When all devices have responded, the log shows "Scene done". If some devices did not respond, a critical event "Scene partly done" appears with the list of those that did not respond

The message "Scene applied" at the bottom of the screen means the commands were sent. The result for each device is in the [Log](/docs/log). If a device did not respond, check its link on the Zigbee page, see [Zigbee](/docs/zigbee).

A scene sets the value of every recorded capability. If a device is already in the wanted state, the command is sent anyway.

## A scene in an automation

To apply a scene automatically, use the **Scene** block from the Actions group.

1. Create an automation, for example from the **Lights at sunset** template
2. In the **Scene** block select the scene from the list
3. Connect the trigger to the scene, save and enable the automation

In a dry run with the **Test** button the scene is not applied, the trace shows the entry "Scene not applied in test".

## Examples

Scene "Movie"
- floor lamp on, brightness 20 percent
- ceiling light off
- projector plug on

Dim the light and turn on the projector, then create the scene and tick these three devices.

Scene "Away"
- all lights off
- iron and heater plugs off
- radiator valves at 17 °C

Link it to an automation. Trigger **Device button** on the remote by the door, action **Scene** "Away".

Scene "Morning" on weekdays. An automation with the **Schedule** trigger `30 6 * * 1-5` and the **Scene** action "Morning".

## Permissions

Scenes can be applied by a resident and above. Scenes are created, changed, overwritten and deleted by an administrator.
