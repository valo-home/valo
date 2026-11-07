# Security

Valo runs inside your home network and controls real devices, so security reports matter a lot.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub private vulnerability reporting:
https://github.com/valo-home/valo/security/advisories/new

Include the version or commit, what an attacker can do, and steps to reproduce. You will get an answer
within a week. Fixes are released as soon as possible and credited unless you prefer otherwise.

## Scope

- the core API, web interface, Socket.IO, MQTT access control, extension supervisor, video service
- the installer `install.sh` and `docker-compose.yml`
- official extensions in `extensions/packages`

## Known limits

- Valo serves plain HTTP. Use a TLS proxy for access from outside the home network.
- Extensions run as separate processes with memory and CPU limits, but share the user of the
  extension container. Install community extensions you trust.
- RTSP from cameras is not encrypted. Keep cameras in a separate network without internet access.
