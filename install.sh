#!/usr/bin/env bash
# Valo installer for Ubuntu and Debian.
#   curl -fsSL https://raw.githubusercontent.com/valo-home/valo/main/install.sh | sudo bash
# Installs Docker Engine with the compose plugin, puts Valo into VALO_DIR and starts it.
# Running it again updates the installation. Settings stay in VALO_DIR/.env, data in Docker volumes.
#
# Options (environment variables):
#   VALO_DIR      installation folder, default /opt/valo
#   VALO_REPO     git repository, default https://github.com/valo-home/valo.git
#   VALO_BRANCH   branch or tag, default main
#   VALO_VERSION  image tag, default latest
#   VALO_BUILD    1 builds images from source instead of pulling them
#   WEB_PORT      web port for a new installation, default 80 or 8080 if 80 is busy
set -euo pipefail

VALO_DIR="${VALO_DIR:-/opt/valo}"
VALO_REPO="${VALO_REPO:-https://github.com/valo-home/valo.git}"
VALO_BRANCH="${VALO_BRANCH:-main}"
VALO_VERSION="${VALO_VERSION:-latest}"
VALO_BUILD="${VALO_BUILD:-}"
WAIT_SECONDS="${WAIT_SECONDS:-600}"

say() { printf '\033[1;33mvalo\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mvalo\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: curl -fsSL .../install.sh | sudo bash"
[ -r /etc/os-release ] || die "cannot detect the operating system"
. /etc/os-release
case "${ID:-}" in
  ubuntu | debian) DISTRO="$ID" ;;
  *) case " ${ID_LIKE:-} " in
       *" ubuntu "*) DISTRO=ubuntu ;;
       *" debian "*) DISTRO=debian ;;
       *) die "supported systems are Ubuntu and Debian, found ${PRETTY_NAME:-unknown}. Install Docker yourself and run docker compose up -d in the repository" ;;
     esac ;;
esac
case "$(uname -m)" in
  x86_64 | aarch64 | arm64) ;;
  *) die "supported processors are x86_64 and arm64, found $(uname -m)" ;;
esac

free_kb=$(df -Pk "$(dirname "$VALO_DIR")" | awk 'NR == 2 {print $4}')
[ "${free_kb:-0}" -gt $((8 * 1024 * 1024)) ] || say "warning: less than 8 GB free on $(dirname "$VALO_DIR")"

apt_install() {
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@" > /dev/null
}

install_docker() {
  say "installing Docker Engine from download.docker.com"
  apt-get update -qq
  apt_install ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$DISTRO/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  local codename="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
  [ -n "$codename" ] || die "cannot detect the release codename"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$DISTRO $codename stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

if ! command -v docker > /dev/null 2>&1; then
  install_docker
elif ! docker compose version > /dev/null 2>&1; then
  say "Docker found without the compose plugin"
  install_docker
else
  say "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo found)"
fi
systemctl enable --now docker containerd > /dev/null 2>&1 || true
docker info > /dev/null 2>&1 || die "Docker does not run, see: systemctl status docker"

command -v git > /dev/null 2>&1 || { apt-get update -qq; apt_install git; }
command -v curl > /dev/null 2>&1 || apt_install curl

if [ -d "$VALO_DIR/.git" ]; then
  say "updating $VALO_DIR"
  git -C "$VALO_DIR" fetch --quiet origin "$VALO_BRANCH"
  git -C "$VALO_DIR" checkout --quiet -B "$VALO_BRANCH" FETCH_HEAD \
    || die "local changes in $VALO_DIR block the update, check git -C $VALO_DIR status"
else
  [ ! -e "$VALO_DIR" ] || [ -z "$(ls -A "$VALO_DIR")" ] || die "$VALO_DIR exists and is not a Valo installation"
  say "downloading Valo into $VALO_DIR"
  git clone --quiet --depth 1 --branch "$VALO_BRANCH" "$VALO_REPO" "$VALO_DIR"
fi
cd "$VALO_DIR"

lan_ip() {
  ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' | head -1
}
port_busy() { ss -Hltn "sport = :$1" 2>/dev/null | grep -q .; }
udp_busy() { ss -Hlun "sport = :$1" 2>/dev/null | grep -q .; }

IP="$(lan_ip || true)"
if [ ! -f .env ]; then
  port="${WEB_PORT:-}"
  if [ -z "$port" ]; then
    port=80
    port_busy 80 && port=8080
  fi
  tz="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
  {
    echo "# Valo settings. Secrets are not here, they live in the Docker volume valo_secrets"
    echo "VALO_VERSION=$VALO_VERSION"
    echo "WEB_PORT=$port"
    echo "TZ=$tz"
    echo "MEDIA_ROOT=$VALO_DIR/media"
    echo "BACKUP_MIRROR_HOST=$VALO_DIR/backups"
    if [ -n "$IP" ] && ! udp_busy 123; then
      echo "NTP_BIND=0.0.0.0:123"
      echo "VALO_NTP_ADDR=$IP"
    fi
  } > .env
  chmod 644 .env
  say "settings written to $VALO_DIR/.env"
fi
port="$(sed -n 's/^WEB_PORT=//p' .env | tail -1)"
port="${port:-80}"

if [ -n "$VALO_BUILD" ]; then
  say "building images from source, this takes a while"
  docker compose build
else
  say "pulling images"
  docker compose pull --quiet
fi
say "starting"
docker compose up -d --remove-orphans

url="http://${IP:-localhost}"
[ "$port" = 80 ] || url="$url:$port"
end=$((SECONDS + WAIT_SECONDS))
until curl -fsS -m 5 "http://127.0.0.1:$port/api/v1/health" > /dev/null 2>&1; do
  [ $SECONDS -lt $end ] || die "Valo did not answer in $WAIT_SECONDS s, see: cd $VALO_DIR && docker compose ps"
  sleep 3
done
say "ready: open $url and finish the setup in the browser"
