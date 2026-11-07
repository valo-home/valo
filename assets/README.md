# Assets

Screenshots and images for the README of this repository, the organisation page and the other repositories of [valo-home](https://github.com/valo-home). Everything here is taken from the built-in demo with simulated devices, no real home and no real camera is shown.

## Screenshots

All screenshots are 2880 by 1800 pixels (a 1440 by 900 window at double density) in WebP, phone screenshots are 390 by 844 at double density.

| File | Page | Used in |
| --- | --- | --- |
| `screenshots/dashboard.webp` | dashboard, dark theme | valo README (top), organisation page, social preview |
| `screenshots/dashboard-light.webp` | the same dashboard, light theme | valo README |
| `screenshots/home.webp` | overview with the floor plan | valo README, organisation page |
| `screenshots/energy.webp` | energy dashboard | valo README |
| `screenshots/flow-editor.webp` | visual automation editor | valo README, organisation page |
| `screenshots/flows.webp` | automations and scenes | valo README |
| `screenshots/camera-timeline.webp` | camera page with the recording timeline | valo README, organisation page |
| `screenshots/camera-media.webp` | camera recordings by day | valo README |
| `screenshots/devices.webp` | device list | valo README |
| `screenshots/device.webp` | device page with history | valo README |
| `screenshots/zigbee-network.webp` | Zigbee network map | valo README, organisation page |
| `screenshots/catalog.webp` | extension catalog | valo README, extension-template README |
| `screenshots/ext-weather.webp` | page of the Open-Meteo weather extension | valo README, extension-template README |
| `screenshots/assistant.webp` | AI assistant | valo README |
| `screenshots/setup.webp` | setup wizard, Zigbee coordinator step | valo README |
| `screenshots/phones.webp` | four phone screens side by side | valo README, app README |

## Images

| File | Purpose |
| --- | --- |
| `social/valo-preview.png` | link preview, 1280 by 640. Set in the repository Settings, General, Social preview |
| `social/avatar.png` | organisation avatar, 512 by 512. Set in the organisation Settings, Profile picture |

## Taking new screenshots

1. Start the demo with English names on an empty demo database: `MOCKS_LANG=en ./valo demo up`
2. Let it run for half an hour so cameras collect clips and the energy counters fill
3. `cd web && node scripts/screenshots.mjs http://localhost:3000 /tmp/shots`, a list of names after the folder takes only those pages
4. The setup wizard needs a hub without an owner: `SHOTS_SETUP=1 node scripts/screenshots.mjs <address> /tmp/shots`
5. Convert to WebP, for example `convert dashboard.png -quality 90 -define webp:method=6 dashboard.webp`, and replace the files here

Keep the file names, the README files of all repositories link to them.
