# Zigbee

Zigbee is a wireless network for sensors, lamps, plugs and buttons. The network is run by the coordinator, a USB stick on the hub. The Zigbee2MQTT program works with the stick, and Valo receives devices and state from it through the MQTT broker. The **Zigbee** page in the System section is available to an administrator.

## How the network works

- The **Coordinator** is the stick, the center of the network
- A **Router** is a mains powered device, for example a plug or a relay. It passes the signal of other devices further
- An **End device** usually runs on a battery and connects to the coordinator or the nearest router

The more routers spread evenly around the home, the more reliable the link of distant sensors.

**Link quality** (LQI) is a number from 0 to 255. From 120 the link is good, from 60 to 119 medium, below 60 weak. A router near weak devices helps to fix them.

## Adding a device

1. Press **Add device** in the top bar, a dialog opens on the Zigbee tab
2. In the **Join through** field keep **any router** or select a router near the place where the device will be
3. Press **Open network for 254 s**. The countdown "network open for N s" appears
4. Put the device into pairing mode as its manual says, usually with a long button press or by switching power several times. Keep it near the stick or a router
5. The dialog shows the steps **Device joined**, **Interview started** and **Interview complete**. During the interview Zigbee2MQTT learns the model and capabilities of the device
6. Press **Configure** next to the new device, set its name and room, see [Devices](/docs/devices)

The **Extend to 254 s** button extends the countdown, **Close network** closes the network early, the press must be confirmed. If the dialog was opened from a room panel, the new device is placed into that room by itself.

Until the interview is complete, the device may be shown without capabilities. After the interview it gets a name from its model unless you have already renamed it.

## Page tabs

At the top of the page are the number of devices and routers, the channel, the Zigbee2MQTT state and a summary of devices, routers, weak signal, offline and firmware updates.

### Network map

The map shows which devices are linked through which. Press **Scan**, building takes up to two minutes. The legend below the map explains the colors of roles (coordinator, router, end device) and of link quality. Pressing a node shows its IEEE address, network role, link quality and parent node, the **Open device** button leads to its page.

### Device health

A table of all Zigbee devices with role, link quality, battery charge or power source, firmware version, available update and the time of the last contact. An offline device is marked. Pressing a row opens the device.

### Coordinator and channel

Adapter type, coordinator IEEE address, port, Zigbee2MQTT version, PAN ID and channel. The owner sees the channel choice here. Changing the channel requires a Zigbee2MQTT restart, and some devices may need to be paired again, so the channel is not changed without a clear reason.

## Actions on the device page

The page of a Zigbee device has a Zigbee block with addresses, role, power source, link quality, model and firmware. An administrator has the buttons
- **Check for update** and **Update** when new firmware is available. Installation progress is shown in percent
- **Reconfigure** sends the reporting setup to the device again
- **Re-interview** reads the device capabilities again. It helps if the device joined without capabilities or after a converter was installed

Removing a device on its page sends it a command to leave the network. If the device does not respond, tick **Force if the device does not respond**.

## If a device does not pair

1. Make sure the network was open during the whole attempt and the countdown did not end
2. Reset the device as its manual says and put it into pairing mode again. Many devices leave pairing mode after a short time
3. Bring the device closer to the stick or select a router near it in **Join through**
4. Replace the battery, with a weak battery the interview often fails
5. If **Interview failed** appears, pair again. If the device is already in the list, press **Re-interview** on its page
6. If the device joined but is marked as unsupported, look for a converter for it in the extension catalog, see [Extensions](/docs/extensions)
7. Check the [Log](/docs/log). If Zigbee2MQTT is offline, tell the hub administrator, errors are shown in System, the Errors tab

If not a single step appears in the pairing dialog, the stick has not received a single request from the device. Most often the device did not enter pairing mode. The hub administrator can turn on the detailed Zigbee2MQTT log, it shows any join attempt, even a rejected one.

Devices that connect over Wi-Fi and MQTT rather than Zigbee are described in [MQTT](/docs/mqtt).
