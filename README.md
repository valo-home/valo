# Valo

Valo is a local smart home hub. It runs on a small computer at home, talks to Zigbee and MQTT devices and IP cameras directly, and needs no cloud.

- **Devices.** Zigbee through Zigbee2MQTT, MQTT devices, devices from extensions. Rooms, a floor plan, history and charts
- **Flows.** A visual editor for automations: triggers, conditions, delays, scenes, notifications, camera actions
- **Dashboards.** Boards of widgets for every room and for the whole home
- **Cameras.** Live video in the browser, snapshots and clips on events, continuous recording with a timeline, pan and tilt, detection of people, cars and animals with zones. Drivers for Thingino firmware cameras and any RTSP camera
- **Extensions.** A catalog of official and community extensions (weather, energy prices, Telegram, presence, timers and more) and an SDK to write your own
- **Assistant.** An optional AI assistant that knows the home and the documentation
- **Built for power cuts.** Everything restarts by itself, cameras and extensions reconnect, backups run daily
- **Seven languages.** Ukrainian, English, Russian, German, French, Spanish, Japanese

## Install

On a clean Ubuntu or Debian computer

```
curl -fsSL https://raw.githubusercontent.com/valo-home/valo/main/install.sh | sudo bash
```

The script installs Docker, starts Valo in `/opt/valo` and prints the address. Open it in a browser and the setup wizard creates the owner account, the home and connects the Zigbee coordinator.

With Docker already installed

```
git clone https://github.com/valo-home/valo.git
cd valo
docker compose up -d
```

No configuration file is needed, passwords are generated on the first start. Details, settings, updates and troubleshooting are in [ops/operations.md](ops/operations.md).

### Hardware

- any x86_64 or arm64 computer with 2 GB RAM or more (4 GB with cameras and recognition)
- a Zigbee USB coordinator, for example Sonoff Zigbee 3.0 USB Dongle Plus V2 or Dongle-P, ConBee II
- optional IP cameras: Sonoff CAM Slim Gen2 and CAM-PT2 with [Thingino](https://thingino.com) firmware, or any RTSP camera

## Try the demo

```
./valo demo up
```

starts a demo home with simulated devices and cameras on http://localhost:3000, login `mikko` / `valo-demo`.

## Architecture

Python 3.14 and Litestar for the core, SvelteKit and Svelte 5 for the web interface, PostgreSQL, Redis, RabbitMQ, Mosquitto, Zigbee2MQTT, go2rtc and ffmpeg for video, Caddy as the single entry point, all in Docker compose.

| Folder | Content |
| --- | --- |
| `backend` | core: REST API, Socket.IO, MQTT ingest, extension supervisor, video service, flows, migrations, tests |
| `web` | web interface |
| `extensions` | extension SDK, catalog and official extensions |
| `mocks` | simulated Zigbee2MQTT and demo data |
| `docs` | user documentation, shown inside Valo |
| `ops` | operations guide |

## Extensions

Extensions are small Python programs that run as separate processes with memory and CPU limits and talk to the core over MQTT. They can add devices, flow blocks, pages, dashboard widgets, camera drivers. Start from [valo-home/extension-template](https://github.com/valo-home/extension-template) and read the developer guide in the Documentation section of Valo.

## Contributing

Issues and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports go privately, see [SECURITY.md](SECURITY.md).

## License

Apache License 2.0, see [LICENSE](LICENSE). Third party components and their licenses are listed in [NOTICE](NOTICE).
