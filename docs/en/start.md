# Getting to know Valo

Valo is a smart home hub that runs in your home, not in the cloud. It brings Zigbee devices, MQTT devices and extension services into one interface, shows their state, keeps history and runs automations. Home data does not leave the hub without your permission.

## The interface

The menu on the left is grouped into sections.

- **Home** holds Overview, Assistant, Dashboards, Rooms and Devices
- **Automation** holds Automations, scenes live in the same section
- **Extensions** holds the extension catalog and the pages added by installed extensions
- **System** holds Zigbee and MQTT for administrators, Log and System

The bottom of the menu shows the link to the hub, the broker, the Zigbee network and extensions, the language selector and your account. The top bar has **Search and commands** (Ctrl K), the **Add device** button for administrators and the notification bell. On a phone the menu opens with the **Menu** button in the bottom bar.

## Installation

Valo is installed on a home computer that stays on: a mini PC, an old laptop or a server with Ubuntu or Debian. On a clean system one command is enough

```
curl -fsSL https://raw.githubusercontent.com/valo-home/valo/main/install.sh | sudo bash
```

The script installs Docker, starts Valo in `/opt/valo` and prints the address, for example `http://192.168.1.20`. With Docker already installed you can take the repository and run `docker compose up -d`, no settings file is needed: service passwords are created on the first start. Running the same command again updates Valo. More in the guide `ops/operations.md` of the [valo-home/valo](https://github.com/valo-home/valo) repository.

To try Valo without devices use the demo: in the repository `./valo demo up` starts a sample home with simulated devices and cameras on port 3000. The environment badge **demo** or **live** is shown in the menu and in the top bar.

## First run of the live environment

The **First run** wizard has four steps.

1. **Home**. Home name, latitude and longitude, time zone and currency. Coordinates are needed for sunrise and sunset, the time zone for schedules
2. **Connections**. A check that the core is connected to the MQTT broker and that Zigbee2MQTT is online. If the Zigbee coordinator (stick) is not chosen yet, the wizard lists the USB devices found and the firmware type guessed from the name. Choose the stick and press **Connect**, Zigbee2MQTT starts with it and creates the network by itself. Without a stick Valo works, only Zigbee devices are missing. The coordinator can be changed later on the Zigbee page, network tab
3. **Owner**. Name, username and password of the hub owner, at least six characters
4. **Done**. A review of the entered data and the **Finish setup** button

Home settings can be changed later in System, tab Home, see [System](/docs/system).

## First steps

1. Check the home settings in System, tab **Home**, especially the time zone and coordinates
2. Create rooms on the **Rooms** page with **Add room** and arrange them on the plan, see [Overview and home plan](/docs/home)
3. Pair a device with **Add device**, press **Open network for 254 s** and put the device into pairing mode, see [Zigbee](/docs/zigbee)
4. Put the device into a room on its page or in the room panel with **Choose existing**, see [Devices](/docs/devices)
5. Build a dashboard for a tablet or phone on the **Dashboards** page, see [Dashboards and widgets](/docs/boards)
6. Create a first automation, for example light on motion from a template, see [Automations](/docs/flows)

If it is easier to describe the task in words, ask the assistant, for example to build a dashboard or to assign devices to rooms, see [Assistant](/docs/assistant).

## User rights

What you see and can change depends on your role. A guest only looks, a resident controls devices and dashboards, an administrator sets up rooms, devices and automations, the owner manages the whole hub. Roles are described in [Key concepts](/docs/concepts).

## Where to get help

- Section headings have a question mark icon next to them. It opens a short explanation and a link to the detailed page of this documentation
- The assistant answers questions about the home and about how Valo works, it can search this documentation
- The log shows what happened and why, see [Log and notifications](/docs/log)
