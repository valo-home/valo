## What it does

Recognises people, cars, animals, bicycles, motorcycles, trucks and buses in camera frames. It runs on the Valo node processor, no cloud or internet is needed. Analysis runs only while the camera reports motion and a few seconds after, the rest of the time the extension does not load the processor.

Every found object creates a camera event with a label, for example **Person**, with a confidence score and a box. A snapshot with the box drawn is saved for the first frame of the event. These events appear on the camera page, record a clip by the camera recording rules and start flows with the camera event trigger.

## One time setup

1. Turn on motion detection in the camera, recognition starts on the camera motion signal
2. Install the extension and confirm the permissions **Camera video for analysis**, **Detection events on cameras**, **Save snapshots and clips** and **Read device state**
3. Open **Cameras**, the camera page, then **Settings**, the recognition section
4. Turn recognition on, choose labels and the confidence threshold, draw zones if needed and save

## Zones

A zone is a polygon on the frame. Points are placed with a click or a tap, they can be dragged, a double click on a point removes it. An object belongs to a zone by the bottom middle of its box, that is where it stands.
- **Include**. If there is at least one such zone, events appear only for objects inside them
- **Ignore**. Objects in these zones are not counted, for example the street behind the fence

## Settings

- **Frames per second during motion**. 1 by default, more gives faster reaction and more load
- **Event ends after disappearing**. How many seconds an object must be absent for the event to end, 6 by default
- **Longest analysis per motion**. Protection against endless motion, 300 seconds by default

## Model

YOLOX tiny (Apache 2.0 license) runs through onnxruntime on the processor. One frame of the sub stream takes about 0.1 second on one core. The model file is part of the package and its checksum is verified at start. Acceleration on Intel integrated graphics is not used yet, the image has no OpenCL runtime for it.
