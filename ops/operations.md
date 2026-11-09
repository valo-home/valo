# Valo operations

How to install, run, update and maintain a Valo node. User documentation is inside the product, section Documentation.

## Requirements

- a computer that stays on: mini PC, old laptop or server, x86_64 or arm64
- Ubuntu 22.04 or 24.04 (other Linux with Docker works too)
- 4 GB RAM minimum (Valo uses about 1.7 GB when idle), 8 GB recommended with cameras and recognition
- 10 GB free disk for the system, plus space for camera recordings
- a Zigbee USB coordinator, for example Sonoff Zigbee 3.0 USB Dongle Plus V2 (ember) or Dongle-P (zstack). Valo works without one, only Zigbee is missing then

## Install with one command

On a clean Ubuntu

```
curl -fsSL https://raw.githubusercontent.com/valo-home/valo/main/install.sh | sudo bash
```

The script installs Docker Engine and the compose plugin from the official Docker repository, puts Valo into `/opt/valo`, starts it and prints the address, for example `http://192.168.1.20`. Running the same command again updates the installation.

Options are environment variables before `bash`, for example `curl ... | sudo VALO_DIR=/srv/valo WEB_PORT=8080 bash`

- `VALO_DIR` installation folder, default `/opt/valo`
- `VALO_VERSION` image tag, default `latest`
- `WEB_PORT` web port, default `80`, the script picks 8080 if 80 is busy

## Install with Docker compose

If Docker is already installed

```
git clone https://github.com/valo-home/valo.git
cd valo
docker compose up -d
```

No variables file is needed. On the first start the `init` service creates random passwords for the database, broker and sessions in the `secrets` volume. Images are pulled from `ghcr.io/valo-home`. To build from source instead, run `docker compose up -d --build`.

## First start in the browser

Open the address of the node. The setup wizard asks for

1. the home: name, location, time zone, currency
2. connections: broker and Zigbee. Plug the coordinator in and choose it in the list, Valo detects the firmware type from the name
3. the owner account: name, login, password
4. summary

Then add rooms, pair Zigbee devices (Add device, Zigbee, Open network), add cameras and install extensions from the catalog.

## Settings

Optional settings go into `.env` next to `docker-compose.yml`. Without it everything works with defaults.

| Variable | Default | Meaning |
| --- | --- | --- |
| `WEB_PORT` | `80` | web interface port |
| `WEB_BIND` | `0.0.0.0` | address of the web port |
| `MQTT_PORT`, `MQTT_BIND` | `1883`, `0.0.0.0` | broker for MQTT devices and remote extensions |
| `MEDIA_ROOT` | `./media` | camera recordings root on the host, the folder inside it is chosen in the interface |
| `BACKUP_MIRROR_HOST` | `./backups` | second copy of daily backups, better on another disk |
| `TZ` | `Europe/Helsinki` | time zone of the containers, the home time zone is set in the interface |
| `NTP_BIND`, `VALO_NTP_ADDR` | off | time service for cameras without internet, for example `0.0.0.0:123` and the LAN address of the node |
| `ZIGBEE_ADAPTER`, `ZIGBEE_ADAPTER_TYPE` | empty | fix the coordinator in the file instead of choosing it in the interface |
| `EDGE_TRUSTED_PROXIES` | Docker networks | addresses of an external TLS proxy |
| `CAMERAS_BUFFER_SIZE` | `512m` | memory for the last seconds of video of all cameras |

Secrets can also be given as variables (`POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`, `JWT_SECRET`, `MQTT_PASSWORD`, `Z2M_MQTT_PASSWORD`). A given value replaces the stored one on the next start.

## HTTPS

Valo serves plain HTTP inside the home network. For access from outside put a TLS proxy in front (Caddy, nginx, a router or a tunnel) and add its address to `EDGE_TRUSTED_PROXIES`. The session cookie gets the Secure flag automatically when the page is opened over https.

## Update

```
cd /opt/valo
git pull
docker compose pull
docker compose up -d
```

or run the install command again. Database migrations run automatically on every start.

## Backups

Valo makes a daily backup of the database and settings into the `data` volume and copies it to `BACKUP_MIRROR_HOST`. Backups are listed, downloaded and restored in System, Backups.

## Power loss and restarts

All services have `restart: unless-stopped`, Docker starts them on boot. After a power cut or reboot

- extensions reconnect to the broker by themselves
- cameras are reconnected, a camera that got a new address from the router is found again by its identifier
- a camera without connection for longer than the set time raises a notification

## Services

| Service | Role |
| --- | --- |
| `init` | creates secrets once, then exits |
| `migrator` | applies database migrations, then exits |
| `backend` | REST API |
| `ws` | Socket.IO for live updates |
| `mqtt` | the only broker subscriber, parses device messages |
| `ext` | runs extensions |
| `agent` | AI assistant |
| `worker`, `scheduler` | background tasks and schedules |
| `cameras` | video (go2rtc, ffmpeg), recordings, camera time service |
| `web` | web interface |
| `edge` | Caddy, single entry point on `WEB_PORT` |
| `postgres`, `redis`, `rabbitmq`, `mosquitto` | storage, cache, task queue, MQTT broker |
| `zigbee2mqtt` | Zigbee coordinator, waits until the adapter is chosen. The wrapper restarts Zigbee2MQTT when the process is alive but has held no adapter port for 30 s, which happens when the adapter fails and the process hangs while stopping |

## Diagnostics

| Symptom | Where to look |
| --- | --- |
| page does not open | `docker compose ps`, all services must be healthy or running, `docker compose logs edge web backend` |
| Zigbee shows offline | `docker compose logs zigbee2mqtt`: waiting for the adapter means it is not chosen, check that the coordinator is plugged in |
| no camera video | camera settings, Maintenance, Check now; `docker compose logs cameras` |
| extension does not start | its card in Extensions shows the log |
| errors | System, Errors collects error records of all services |

## Development

The repository contains the `./valo` script that runs two environments side by side as separate compose projects: `./valo demo up` with simulated devices on port 3000 and `./valo real up` with real hardware on port 3100. See CONTRIBUTING.md.

The demo home has Russian names by default. `MOCKS_LANG=en ./valo demo up` fills it with English names, the variable works on the first start of the demo, when its database is empty.

Screenshots for the README come from the English demo: `cd web && node scripts/screenshots.mjs http://localhost:3000 <folder>` takes every page in the list, `SHOTS_SETUP=1` against a hub without an owner takes the setup wizard.
