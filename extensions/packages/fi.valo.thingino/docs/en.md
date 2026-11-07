## What it does

Connects cameras on the open Thingino firmware, for example Sonoff CAM Slim Gen2 and CAM-PT2. Valo gets video, snapshots and motion events from the camera directly in the local network, no cloud is needed. Every camera appears in the **Cameras** section and in the device list with the **Motion** capability.

When a camera is added, the extension reads the camera model and firmware through the camera agent API and checks the stream password. The driver gets motion from the event stream of the camera agent. On firmware without that stream, for example the 2026-08-14 build, the driver subscribes to ONVIF events (PullPoint, the MotionAlarm and CellMotionDetector topics). Camera availability is checked by the camera heartbeat.

## One-time setup

1. Connect the camera with Thingino firmware to the network and find its address, for example in the client list of the router
2. Open the camera web UI, in **Settings**, **Web UI** press **Generate** and copy the API key
3. Enable motion detection (Motion Guard) in the camera, otherwise there will be no motion events
4. Install the extension and confirm the **Connect its own cameras** permission and outbound requests to the local network
5. Open **Cameras**, press **Add camera** and choose the **Thingino cameras** driver
6. Enter a name, choose a room and fill in the fields below, then press **Add**

Camera fields
- **Camera address**. IP or network name, for example `192.168.0.105`
- **Stream user**. The RTSP and ONVIF user, `thingino` by default
- **Stream password**. The password of that user
- **API key**. The key from the camera web UI, needed for snapshots and motion
- **Main stream**. `ch0` by default, 1080p for viewing and recording
- **Sub stream**. `ch1` by default, 360p for tiles and detection

If the address, key or password is wrong, the dialog shows the reason and the camera is not added. A second camera, for example CAM-PT2, is added the same way.

## How to use

- Live video, events, snapshots, clips and recording settings are on the camera page, see [Cameras](/docs/cameras)
- The password and key can be changed with the **Edit** button on the camera page. Empty password fields keep the saved values
- The **Process log** of the extension card shows how the driver gets motion. The line `events connected` means the agent event stream, the line `ONVIF events subscribed` means ONVIF events

## Control from Valo

- Camera settings on the **Camera** tab of the settings: motion detection and its sensitivity, day and night, privacy, image, stream quality, time
- **Reboot camera** and **Restart stream** on the **Maintenance** tab
- Step by step diagnostics: network, API key, RTSP streams, ONVIF, uptime, camera CPU and memory, clock
- If the router gives the camera another address, the driver finds it in the network by its identifier and saves the new address
- CAM-PT2 pan and tilt with arrows and by the picture, presets and calibration

## Limitations

- The microphone on firmware 2026-08-14 is only shown, newer firmware can switch it
- Without motion detection on, video and snapshots work, but there are no events and no event clips. It can be turned on in Valo on the **Camera** tab
- Firmware updates are done in the camera web interface
