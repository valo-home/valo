# Cameras

The **Cameras** section shows live video from the home cameras, snapshots, clips and motion events. Video does not go to a cloud, Valo connects to the cameras in the local network itself and keeps recordings on its own disk. Automations run on camera events.

## What a camera is in Valo

- A **camera** is a device of the camera kind. It is listed in [Devices](/docs/devices), it can be placed in a room and used in automations. A camera has the **Motion** capability (`occ`), so it also works as a motion sensor
- A **driver** is an extension that knows how to work with cameras of a certain make. The driver checks the camera when it is added and reports its video streams, snapshot addresses, motion events and availability
- A **camera event** is something the camera noticed. An event has a start and an end, a label (motion, person, car, animal or a custom label of a detection extension), a confidence score, a source (driver or extension), a snapshot and a clip
- A **recording** is a snapshot or a clip saved on disk. A recording is linked to a camera and, if there is one, to an event, and remembers what created it: an event, an automation, a user by hand or an extension

The **Cameras** section, video, snapshots and recordings are available to residents and higher. Guests do not see the section. A user whose access is limited to some rooms sees only the cameras of those rooms. Adding, changing and deleting cameras, storage settings and deleting recordings are for administrators.

## Drivers

- **Thingino cameras** for cameras on the open Thingino firmware, for example Sonoff CAM Slim Gen2 and CAM-PT2. Reports motion from the camera itself
- **RTSP camera** for any IP camera with an RTSP stream. Gives live view, snapshots and recording, it has no motion detection of its own
- **Device simulator** in the demo environment creates cameras with a test picture and reports motion on them from time to time

A driver is installed from the catalog on the [Extensions](/docs/extensions) page. If no driver is installed, the **Cameras** page offers to open the catalog. When a driver is removed, its cameras are removed too.

## Adding a camera

1. Install a driver from the catalog
2. Open **Cameras** and press **Add camera**
3. Choose the **Driver**, enter the **Name** and choose the **Room**
4. Fill in the driver fields described below
5. Press **Add**

Valo connects to the camera and checks the address, user and password before saving. If the check fails, the dialog shows the reason, for example a wrong password or a camera that does not answer, and the camera is not added.

### Thingino camera

1. Open the camera web UI in a browser at its address
2. In **Settings**, **Web UI** press **Generate** and copy the API key
3. Motion detection (Motion Guard) must be enabled. After the camera is added, it can be enabled and tuned in Valo on the **Camera** tab of the camera settings
4. In Valo choose the **Thingino cameras** driver and fill in **Camera address** (IP or network name, for example `192.168.0.105`), **Stream user** (`thingino` by default), **Stream password** and **API key**
5. **Main stream** `ch0` (1080p) and **Sub stream** `ch1` (360p) usually do not need changes

Valo asks the camera for its model through the camera agent API and checks the stream password. A second camera, for example Sonoff CAM-PT2, is added the same way.

### RTSP camera

1. Find the RTSP stream address in the manufacturer documentation, for example `rtsp://192.168.0.50:554/stream1`
2. Choose the **RTSP camera** driver
3. In **Main stream** enter the `rtsp://` address without the password
4. In **Sub stream** you may enter a low quality stream for tiles
5. Fill in **User** and **Password**
6. If the camera serves a JPEG snapshot at an `http://` address, enter it in **Snapshot address**. Without it the frame is taken from the stream

Valo checks the address, user and password with an RTSP DESCRIBE request without reading video. The driver checks the camera availability once a minute.

## Cameras page

Cameras are shown as 16:9 tiles. The snapshot on a tile refreshes every 10 seconds while the tile is visible. Badges on a tile show motion now, continuous recording and the reason if the camera is unavailable, for example **Camera does not answer** or **No video**. A tap on a tile opens the camera page. Administrators see the **Storage** and **Add camera** buttons.

## Camera page

At the top is live video with a delay under a second.

- **HD** and **SD** switch between the main and the sub stream if the camera has a sub stream
- the sound button turns sound on and off, sound is off by default
- **Full screen** expands the video
- if the camera is unavailable, instead of endless connecting the video area shows the reason and since when

Buttons above the video

- **Snapshot** saves a frame to the recordings
- **30 s clip** records a 30 second clip, it appears in the recordings when it is finished
- **Camera settings** opens a separate settings page

The side card shows the connection state, motion, the last event, the recording mode, the video bitrate and codecs, the camera address and the **Camera as a device** link. If the camera is unavailable, an administrator sees the **Reconnect**, **Find camera**, **Restart stream**, **Reboot camera** and **Diagnostics** buttons there, depending on the reason.

Under the video there is a row of days with recordings and a date picker. The selected day filters events and recordings on all tabs, **All days** removes the filter.

- The **Events** tab lists events with a thumbnail, label, confidence, time and duration. Events can be filtered by type (motion, person and other labels). **Play** opens the event clip. An administrator deletes an event with the trash button, its snapshot and clip are deleted with it, the press must be confirmed
- The **Recordings** tab shows snapshots and clips as a grid, the **All**, **Videos**, **Photos** switch filters by kind. A tap opens the viewer: arrows page through the recordings, **Download**, **Keep** and **Delete**
- The **Timeline** tab shows the 24 hours of the selected day: bars of continuous recording and ticks of events. A tap on a bar opens the recording from that minute

### Deleting recordings

- one recording: open it and press **Delete**, then **Confirm deletion**
- several: **Select**, mark the recordings (or **Select all**), then **Delete**. In the same place **Download** packs the selected recordings into a zip archive up to 2 GB and **Keep** protects them from rotation
- for a day: choose the day and press **Delete the day**, recordings and finished events of that day are deleted
- all recordings of the camera: with **All days** the **Delete all recordings** button

Bulk deletion is confirmed in a separate dialog. Recordings marked **Keep** stay when a day or everything is deleted, they can be deleted only one by one or by selection. Deleting recordings is for administrators.

### Protection from rotation

The **Keep** mark (a lock icon on the thumbnail) forbids rotation to delete the recording, and such a recording does not count towards the **Size limit**. The mark is removed in the same place with the **Unkeep** button.

## Camera settings

The **Camera settings** page opens with a button on the camera page. At the top is the connection state, on the left are tabs, each is saved separately. Settings can be changed by administrators, residents can view them.

- **General**: name, room and tile order (a smaller number comes first)
- **Connection**: driver fields. **Test** connects to the camera with the entered values without saving and shows the result. **Save** checks again and saves. Empty password fields keep the saved values
- **Recording**: mode, margin before and after the event, longest clip, which events record a clip (motion, person, car, animal), the stream to record HD or SD, sound, event snapshots, schedule, retention of continuous recording and the notification about an offline camera, details below
- **Camera**: settings of the camera itself, the driver reads and changes them, details below
- **Detection and zones**: enabling detection, labels, threshold and zones on the frame
- **Pan and tilt**: presets and calibration, only for pan and tilt cameras
- **Maintenance**: diagnostics, actions and camera information
- **Removal**: delete the camera and keep the recordings, or delete it together with the recordings

Every save goes to the [log](/docs/log) with the list of changed settings, for example **Camera Yard settings changed: Recording off, Event snapshots off**.

### Settings of the camera itself

The **Camera** tab shows what the driver and the firmware support, so the set differs between makes. For Thingino

- **Motion detection** (Motion Guard): on or off, **Sensitivity** from 1 to 8 and **Pause between triggers** in seconds. Detection must be on, otherwise Valo receives no motion events and records no clips
- **Day and night**: mode **Auto**, **Day** or **Night**, whether it is day or night now and whether the IR light is on
- **Privacy**: the camera hides the picture
- **Image**: brightness, contrast, saturation, sharpness, anti flicker 50 or 60 Hz, mirror and flip
- **Sound**: microphone. On Thingino firmware 2026-08-14 it can only be viewed, newer firmware can switch it
- **Stream quality**: resolution and format, frames per second and bitrate of the main and the sub stream. A change restarts the stream on the camera for a few seconds
- **Time**: the camera time zone, the time server and the clock difference between the camera and Valo. **Sync time** sets the home time zone and the Valo time server on the camera if the time service is enabled, otherwise the NTP pool. pool.ntp.org stays as a fallback server, and after a change of the home time zone or of the Valo hub address the online cameras are set up again by themselves, usually within a minute

Changed fields are applied with the **Apply changes** button. If the camera did not accept a value, the field is highlighted and the reason is shown under it. **Read from camera** refreshes the values, for example if they were changed in the camera web UI.

## Connectivity, power outages and reboots

Valo is designed for the computer, router, cameras and sensors to go off in any order. After power returns everything recovers by itself

- Docker restarts the Valo services when the computer boots
- drivers and other extensions reconnect to the broker by themselves within 1 to 30 seconds if the connection was lost, for example after the computer slept or froze
- if an extension crashed, its devices and cameras are marked **offline** instead of hanging as online
- the Thingino driver checks the camera and after recovery reports availability and motion again
- the Thingino driver checks the video service on the camera every 30 seconds and starts it again if the firmware crashed it (CAM-PT2 does this when motion detection is switched)
- the video service reopens the streams and restarts recording by itself

### Camera state

Instead of a generic **Connecting** Valo shows the reason

- **Online**
- **Connecting**: right after power on, an address change or a camera reboot
- **Camera does not answer**: nothing answers at the address. Check the camera power and Wi-Fi
- **Another device at the address**: the router gave the camera address to another device
- **Wrong API key** and **Wrong stream password**: the camera answers but does not accept the key or the password, they must be entered on the **Connection** tab
- If video works but the camera refuses snapshots with the saved API key or password, Valo takes snapshots from the video stream and shows the notification **Camera refuses snapshots with the saved key or password**. It clears by itself after the first successful snapshot from the camera. The key of a Thingino camera is checked in its web UI, **Settings**, **Web UI**
- **No video**: the camera is online, but no video has arrived for more than 30 seconds. **Restart stream** usually helps. If it lasts 3 minutes, Valo restarts the stream on the camera by itself, or reconnects the video if the driver cannot do that. At most once in 15 minutes, each time with an entry in the log
- **Camera driver stopped**: the camera extension is disabled or has crashed

### The camera changed its address

If the router gave the camera a different address, the Thingino driver, after several failed checks in a row, searches for the camera in the /24 network of the previous address. It probes port 80 and recognizes Thingino cameras by their page, sends the API key only to the Thingino cameras it found and compares the camera identifier. The found address is saved automatically, and the **Camera found at the new address** event is written to the log. The search is repeated at most once in 10 minutes. It is started by hand with the **Find camera** button on the **Maintenance** tab. The most reliable option is to fix the camera address in the router (DHCP reservation by MAC address).

### Notification about an offline camera

If the camera is unavailable longer than **Notify when the camera is offline longer than, min** (5 by default, 0 turns it off), a **warning** level notification and a log entry appear. When the camera comes back, the notification is cleared and an **online again** message arrives. Notifications are also sent to Telegram for the levels chosen in [System](/docs/system).

### Diagnostics and actions

The **Maintenance** tab

- **Check now** goes through the steps: the driver in Valo, the network, whether it is the same camera, firmware, API key, main and sub RTSP stream, ONVIF, uptime, CPU load and memory of the camera, the video service on the camera, the clock, video in Valo with bitrate, the recording buffer, continuous recording and space for recordings. Each step has a mark and a value
- **Reconnect** reopens the camera streams in Valo, the camera itself is not rebooted
- **Restart stream** restarts the video service on the camera without a reboot
- **Reboot camera** must be confirmed. For about a minute there is no video and no events, then everything recovers by itself
- **Find camera** searches for the camera in the network by its identifier
- **About the camera**: model, firmware, name, address, identifier and a link to the camera web UI. Firmware updates are done there, not in Valo, so that a failed update does not leave the camera unavailable

## Recording and clips

Each camera has its own recording mode.

- **On events** (default). When an event starts, a snapshot is saved immediately, and after the event ends a clip with a margin before and after is saved
- **Continuous**. Video is recorded without breaks in 10 minute pieces, the pieces start on 10 minute boundaries of the clock. Event clips are saved too
- **Off**. No video is recorded. Camera events stay in the list, snapshots are saved for them

The **Event snapshots** switch (on by default) works in every mode. When it is off, motion events are only listed and still run flows, no snapshots are saved for them. To stop events completely, turn off motion detection on the camera itself, **Camera** tab, but then the camera stops reporting motion to flows too. Snapshots with a frame from the detection extension are not controlled by this switch, they stop when detection is turned off

How a clip is formed

- the video service keeps the last 40 seconds of video with sound in memory in 2 second pieces, without re-encoding. Nothing is written to disk while there is no event
- the clip starts **Before event** seconds before the event start (5 by default, from 0 to 30) and ends **After event** seconds after the end (10 by default, from 0 to 30)
- the event part of the clip is limited by **Longest clip** (120 by default, from 10 to 600 seconds)
- pieces are cut on keyframes, so a clip can be a few seconds longer than set
- for an instant event, for example a recognized person, the clip runs from the margin before the event to the margin after it

Recording parameters

- **Events that record a clip**: if all labels are checked, any event records a clip. The event snapshot is always saved
- **Stream to record**: HD main or SD sub, SD takes several times less space
- **Sound in recordings**: on by default
- **Schedule**: **Always** or **By hours** from and to, for example from 22:00 to 07:00. An interval across midnight works. Outside the schedule event clips are not recorded and continuous recording pauses. Event snapshots are always saved. To switch recording on and off by other conditions, for example when nobody is home, use an automation with the **Camera setting** block
- **Keep continuous recording, days**: from 1 to 365, 7 by default. Before it is enabled, the page shows how much space a day and the whole period take at the current bitrate, and how much is free on the disk

The **30 s clip** button, automations and extensions record a clip of the requested length from the moment of the request, unless recording is off.

## Storage

The **Storage** button on the Cameras page opens the recording settings, available to administrators. The dialog shows the path of the recordings folder, free and total disk space, how much Valo uses and how many files it has.

- **Recordings folder**. A folder inside the storage root, `valo-media` by default. The root is set at installation by the `MEDIA_ROOT` variable in the environment file. When the folder changes, old recordings stay in the previous one
- **Minimum free space, GB**, 10 by default
- **Keep, days**, 30 by default, 0 means no time limit
- **Size limit, GB**, 0 by default, which means no limit

Once a minute Valo checks the storage in this order

1. deletes recordings older than the set number of days
2. deletes continuous recording pieces older than the camera retention period
3. while recordings take more than the size limit, deletes the oldest ones
4. while free space is below the minimum, deletes the oldest ones

Rotation does not touch recordings marked **Keep**. If none of its own recordings are left to delete and free space is still below the minimum, video is not recorded, continuous recording stops, snapshots are still saved. Until space is back the **Low space for recordings** notification stays active, once space is back continuous recording resumes by itself. Valo deletes only files it recorded itself, it never touches other files on the disk.

Files are stored as `<folder>/<camera>/<YYYY-MM-DD>/<HHMMSS>-<label>-<code>.jpg` for snapshots and `.mp4` for clips, continuous recording pieces as `rec-<YYYYMMDD>-<HHMMSS>.mp4`, the date and time are in the home time zone. If the video service stopped in the middle of a piece, on the next start complete pieces are kept and unfinished ones are deleted with a log entry.

## Detection and zones

The **Camera recognition** extension looks for people, cars, animals, bicycles, motorcycles, trucks and buses in frames while the camera reports motion, and for a few seconds after. It runs on the node CPU without a cloud, the model is YOLOX tiny. For each found object a camera event with a label, for example **Person**, and a snapshot with a frame around the object appear. Such events record a clip by the recording rules and start automations with the **Camera event** trigger.

Detection is enabled on the **Detection and zones** tab: labels and the confidence threshold are chosen there and zones are drawn. A zone is a polygon on the frame, points are placed with a tap and can be dragged, an object belongs to a zone by the place where it stands. An **Include** zone keeps only objects inside such zones, an **Ignore** zone drops objects in it, for example the street behind the fence. A camera has up to 8 zones and up to 16 points per zone. See the extension description for details.

Recognition does not control clips on motion detected by the camera itself. They are recorded with recognition turned off too, if **Motion** is marked in the **Recording** section, list "Events that record a clip". To record clips only for found people, cars and animals, clear this mark.

## Pan and tilt cameras

A pan and tilt camera, for example Sonoff CAM-PT2 on Thingino, gets arrows and a **To center** button on the video. Under the video

- **Aim**: after the press the frame becomes a sight, a tap on a point of the frame turns the camera there
- preset buttons turn the camera to a saved position
- **Save position** saves the current position as a named preset, this is for administrators

On the **Pan and tilt** tab of the settings presets are renamed, deleted and checked with the **Go** button, a camera has up to 16 presets. **Calibration** moves the camera to its end stops and back to the center, after it saved positions may shift. Presets are stored in Valo, so they survive a camera reset.

## Automations

Camera blocks are in the palette of the [Automations](/docs/flows) editor.

- Trigger **Camera event** with the parameters **Camera**, **What happened** (motion, person, car, animal) and **Moment** (start or end)
- Action **Camera snapshot**. If no camera is selected, the camera from the event is used. Adds the `{snapshot}` variable with a link to the snapshot like `/api/v1/media/<id>/file`, it opens in Valo after sign in
- Action **Camera clip** with an optional camera and a **Duration**, 30 seconds by default
- Action **Camera setting**: **What to change** privacy, motion (detection on the camera), day and night, recording mode or recognition (turn the Camera recognition extension on and off for this camera), and **Value** (on, off, auto, day, night, on events, continuous)
- Action **Reboot camera**
- Action **Turn to preset** with the preset name
- Action **Patrol**: presets in turn, a pause at each and the number of rounds. A new patrol of the same camera interrupts the previous one

The **State change** trigger with a camera and the **Motion** capability also works, because a camera is a device with the motion capability. Notification texts can use `{label}` (the event label, for example `motion` or `person`) and `{snapshot}`.

The person, car and animal labels are set by the **Camera recognition** extension. The Thingino and RTSP drivers report motion only.

### Snapshots and clips in Telegram

Snapshots and clips can be sent to Telegram with the **Snapshot or clip to Telegram** block of the Telegram extension. It sends a camera snapshot now, a snapshot or clip from the automation, the latest camera recording, or records a clip of a given number of seconds. The camera may be left unselected, then the camera from the event is used. Sending runs in the background. Telegram accepts photos up to 10 MB and videos up to 50 MB, for larger files a text with a link to the recording arrives if the Valo address is set in the extension settings.

### Example: smoke, clip and notification

1. **New automation**, **Empty automation**
2. Trigger **State change**, the smoke sensor, capability **Smoke**, new value **yes**
3. Action **Camera clip**, choose the camera in that room, duration 30 seconds. The camera must be selected because the event did not come from a camera
4. Action **Notification** with the text `Smoke: {device}, {room}, {time}`, level critical, **Send externally** on
5. **Save** and enable the automation

### Example: a person at the door at night

1. Trigger **Camera event**, the front door camera, **What happened** person, **Moment** start. Without a detection extension choose motion
2. Condition **Time window** from 23:00 to 07:00
3. Action **Snapshot or clip to Telegram**, source camera snapshot now, text `At the door {label}, {time}`
4. **Save** and enable the automation

### Example: leaving home and at home

1. Automation **Leaving** (manual run or a presence sensor trigger): **Camera setting** actions, privacy off, motion on, recording mode continuous
2. Automation **At home**: **Camera setting**, recording mode on events, privacy on for the camera in the living room

## Widget

The **Camera** widget in the Devices group on [Dashboards](/docs/boards) shows a camera snapshot that refreshes every 10 seconds. A tap on the widget opens the camera page.

## Privacy and security

- Camera passwords and API keys are stored encrypted in the database. Stream addresses with passwords are never sent to the browser, the browser knows only the stream name
- Video reaches the browser through the same address as the interface, with a check of the session and of the access to the camera
- The recordings folder is not accessible to extension processes. An extension gets snapshots and clips only through the core and only with the **Read snapshots and clips** permission
- RTSP does not encrypt video and the password, so they can be intercepted in a shared network. Give the camera its own password that is not used anywhere else

### A separate network and time for cameras

A camera does not need the internet. It is more reliable to keep cameras in a separate router network (guest network, a separate VLAN or SSID) without internet access, reachable only from the Valo node

1. Create a separate network for cameras in the router and block its internet access
2. Allow the Valo node to reach this network, camera ports 80 (API and ONVIF) and 554 (RTSP) are needed
3. Fix an address for each camera (DHCP reservation by MAC address)
4. Connect the cameras to this network through their web UI

Without the internet a camera cannot take time from the NTP pool, and wrong time breaks the timestamps on the frame and the camera log. In the production environment the Valo node serves time over NTP on port 123 itself. The **Sync time** button on the **Camera** tab sets the home time zone and the Valo time server on the camera. The clock difference between the camera and Valo is shown there and in the diagnostics. How to enable or disable the time service is described in the Operations section.

## Limitations

- The **RTSP camera** driver has no motion detection of its own, no camera settings, no reboot and no network search. Events for such cameras come from detection extensions, clips can be recorded with the button and automations
- Detection runs on the CPU. Acceleration on the integrated Intel GPU is not supported yet: the image has no OpenCL driver, and the Intel packages would add hundreds of megabytes
- Camera firmware updates are done in its web UI, not in Valo
