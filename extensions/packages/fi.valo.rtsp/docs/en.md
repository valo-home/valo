## What it does

Connects any IP camera with an RTSP stream. Valo shows live video, takes snapshots and records clips with the button, from automations and on events from detection extensions. The camera appears in the **Cameras** section and in the device list.

When a camera is added, the extension checks the address, login and password with an RTSP DESCRIBE request without reading video. Once a minute the driver checks the camera availability the same way. The driver has no motion detection of its own.

## One-time setup

1. Find the RTSP stream address in the camera documentation or web UI, for example `rtsp://192.168.0.50:554/stream1`. Many cameras have a second low quality stream
2. If the camera allows it, create a separate view only user on it
3. Install the extension and confirm the **Connect its own cameras** permission and outbound requests to the local network
4. Open **Cameras**, press **Add camera** and choose the **RTSP camera** driver
5. Enter a name, choose a room and fill in the fields below, then press **Add**

Camera fields
- **Main stream**. An `rtsp://` or `rtsps://` address without the password, required
- **Sub stream**. A low quality stream for tiles, optional
- **User** and **Password**. Valo inserts them into the stream addresses itself, the password is stored encrypted
- **Snapshot address**. An `http://` or `https://` address where the camera serves a JPEG. Stored as a secret because it may contain a password. Without it the frame is taken from the stream

If the address does not answer, the stream is not found or the password is wrong, the dialog shows the reason and the camera is not added.

## How to use

- Live video, events, snapshots, clips and recording settings are on the camera page, see [Cameras](/docs/cameras)
- To record a clip on motion, place a motion sensor next to the camera and create an automation with the **State change** trigger of that sensor and the **Camera clip** action
- Person, car or animal events on such a camera come from a detection extension with the **Detection events on cameras** permission

## Limitations

- The **On events** recording mode gets no events without a detection extension, clips are recorded with the button and automations
- RTSP does not encrypt video and the password. Keep the camera in a separate network and give it its own password
- Clips are recorded without sound for now, live video has sound
