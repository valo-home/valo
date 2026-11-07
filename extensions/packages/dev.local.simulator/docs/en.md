## What it does

Creates virtual sensors to debug flows without hardware. Development and demo only.

## One-time setup

Install and adjust the update **Period** in seconds if needed.

## How to use

Use the virtual sensors like real devices. The **Simulate** block injects a test event. Not needed in a live installation.

## Demo cameras

In the demo environment the extension also works as a camera driver. Open **Cameras**, press **Add camera**, choose the **Device simulator** driver and the **Test picture** `yard` or `door`. The camera shows a test video, and at random intervals of one to two and a half minutes the extension reports motion on it for a few seconds. This way events, clips, storage and camera automations can be tested without a real camera, see [Cameras](/docs/cameras).
