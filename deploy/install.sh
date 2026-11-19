#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

usage() {
    cat <<'EOF'
SelfX native installer for Ubuntu 24.04 with systemd (amd64 or arm64).

Usage: sudo bash deploy/install.sh [--port 8800] [--bind 127.0.0.1]

The first run installs and enables SelfX at boot. Run again to update from
the current checkout. Existing data and credentials are preserved, and
port and bind settings persist unless explicitly supplied.
EOF
}

log() { printf '[SelfX] %s\n' "$*"; }
die() { printf '[SelfX] %s\n' "$*" >&2; exit 1; }
valid_port() { [[ $1 =~ ^[1-9][0-9]{3,4}$ ]] && (( $1 >= 1024 && $1 <= 65535 )); }
valid_bind() {
    local octet
    local -a octets
    [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    IFS=. read -r -a octets <<< "$1"
    for octet in "${octets[@]}"; do
        [[ $octet =~ ^(0|[1-9][0-9]{0,2})$ ]] && (( octet <= 255 )) || return 1
    done
}

requested_port=
requested_bind=
while (( $# )); do
    case "$1" in
        --port)
            valid_port "${2:-}" || die 'Use --port with a number from 1024 to 65535.'
            requested_port=$2
            shift 2
            ;;
        --bind)
            valid_bind "${2:-}" || die 'Use --bind with an IPv4 address, such as 127.0.0.1.'
            requested_bind=$2
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument $1. Run with --help for options." ;;
    esac
done

[[ $EUID == 0 ]] || die 'Run this installer with sudo.'
[[ -r /etc/os-release ]] || die 'This installer needs Ubuntu 24.04.'
# shellcheck source=/dev/null
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || die 'This installer needs Ubuntu 24.04.'
[[ $(ps -p 1 -o comm=) == systemd ]] || die 'Start Ubuntu with systemd enabled, then run the installer again.'
case "$(dpkg --print-architecture)" in
    amd64)
        node_arch=x64
        node_sha=cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8
        ;;
    arm64)
        node_arch=arm64
        node_sha=2babb9eb5264860d540849f4b064a6fbdebcdc323657d9d382ce23d313fd5e09
        ;;
    *) die 'The installer supports 64-bit x86 and ARM systems.' ;;
esac

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f $source_dir/web/package-lock.json && -f $source_dir/server/requirements.txt ]] ||
    die 'Run the installer from a complete SelfX checkout.'

install_root=/opt/selfx
config_dir=/etc/selfx
config_file=$config_dir/selfx.env
state_dir=/var/lib/selfx
cache_dir=/var/cache/selfx
app_units=(selfx-api.service selfx-worker@default.service selfx-worker@heavy.service)

exec 9>/run/lock/selfx-install.lock
flock -n 9 || die 'Another SelfX install is already in progress.'

env_value() {
    [[ -f $config_file ]] && sed -n "s/^$1=//p" "$config_file" | tail -n 1
}

old_port=$(env_value SELFX_PORT || true)
old_bind=$(env_value SELFX_BIND_HOST || true)
port=${requested_port:-${old_port:-8800}}
bind=${requested_bind:-${old_bind:-127.0.0.1}}
valid_port "$port" || die "Invalid SELFX_PORT in $config_file."
valid_bind "$bind" || die "Invalid SELFX_BIND_HOST in $config_file."
check_port() {
    if command -v ss >/dev/null && [[ -n $(ss -H -ltn "sport = :$port") ]]; then
        if [[ $port != "$old_port" ]] || ! systemctl is-active --quiet selfx-api.service; then
            die "TCP port $port is in use. Choose a different --port."
        fi
    fi
}
check_port

if [[ -e $install_root/current && ! -L $install_root/current ]]; then
    die "$install_root/current already exists outside the SelfX release layout."
fi

log 'Installing Ubuntu runtime and build packages.'
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=3 update
if ! apt-cache show postgresql-16-pgvector 2>/dev/null | grep '^Package:' >/dev/null; then
    die 'Enable the Ubuntu universe repository, then run the installer again.'
fi
apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates curl openssl xz-utils build-essential python3-dev python3-venv \
    postgresql-16 postgresql-16-pgvector redis-server \
    ffmpeg ghostscript fonts-dejavu-core libimage-exiftool-perl libmagic1t64 \
    qpdf pandoc tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-fra \
    tesseract-ocr-nld tesseract-ocr-spa \
    libreoffice-writer libreoffice-calc libreoffice-impress libgl1 libglib2.0-0t64

if getent passwd selfx >/dev/null; then
    current_account=$(getent passwd selfx)
    if [[ $current_account != *:"$state_dir":/usr/sbin/nologin || $(id -gn selfx) != selfx || $(id -u selfx) == 0 ]]; then
        die 'A different Linux user named selfx already exists.'
    fi
else
    useradd --system --user-group --home-dir "$state_dir" --shell /usr/sbin/nologin selfx
fi
install -d -m 0750 -o root -g selfx "$config_dir"
install -d -m 0755 -o root -g root "$install_root/releases" "$install_root/toolchains"
install -d -m 0700 -o selfx -g selfx "$state_dir" "$state_dir/data" "$state_dir/redis" "$cache_dir"

pg_port=$(pg_lsclusters --no-header | awk '$1 == "16" && $2 == "main" {print $3}')
[[ $pg_port =~ ^[0-9]+$ ]] || die 'Ubuntu PostgreSQL cluster 16/main is missing.'
systemctl enable --now postgresql.service
systemctl start postgresql@16-main.service
check_port

postgres() (
    cd /tmp
    runuser -u postgres -- psql -X -h /var/run/postgresql -p "$pg_port" -v ON_ERROR_STOP=1 "$@"
)

role_exists=$(postgres -Atq -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = 'selfx'")
db_owner=$(postgres -Atq -d postgres -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'selfx'")
if [[ ! -f $config_file ]]; then
    [[ -z $role_exists && -z $db_owner ]] || die 'The local PostgreSQL role or database named selfx already exists. Use a separate Ubuntu installation or restore the original SelfX configuration.'
    log 'Creating local credentials.'
    db_password=$(openssl rand -hex 24)
    secret_key=$(openssl rand -hex 32)
    admin_password=$(openssl rand -hex 16)
    temp_env=$(mktemp "$config_dir/.env-XXXXXXXX")
    cat > "$temp_env" <<EOF
SELFX_SECRET_KEY=$secret_key
SELFX_ADMIN_USER=admin
SELFX_ADMIN_PASSWORD=$admin_password
SELFX_BIND_HOST=$bind
SELFX_PORT=$port
DATABASE_URL=postgresql+psycopg://selfx:$db_password@127.0.0.1:$pg_port/selfx
REDIS_URL=unix:///run/selfx-redis/redis.sock
DATA_DIR=$state_dir/data
HF_HOME=$state_dir/huggingface
OLLAMA_URL=http://127.0.0.1:11434
GOTENBERG_URL=
EOF
    mv -T -- "$temp_env" "$config_file"
    unset secret_key admin_password
fi
chown root:root "$config_file"
chmod 0600 "$config_file"
if [[ -z $role_exists ]]; then
    database_url=$(env_value DATABASE_URL)
    if [[ $database_url =~ ^postgresql\+psycopg://selfx:([0-9a-f]{48})@127\.0\.0\.1:$pg_port/selfx$ ]]; then
        postgres -q -d postgres <<EOF
CREATE ROLE selfx LOGIN PASSWORD '${BASH_REMATCH[1]}';
EOF
    else
        die "Unable to provision the native PostgreSQL role using DATABASE_URL in $config_file."
    fi
fi
unset db_password database_url
if [[ -z $db_owner ]]; then
    postgres -q -d postgres -c 'CREATE DATABASE selfx OWNER selfx'
elif [[ $db_owner != selfx ]]; then
    die 'The PostgreSQL database selfx has a different owner.'
fi
postgres -q -d selfx -c 'CREATE EXTENSION IF NOT EXISTS vector'

build_dir=$(mktemp -d "$install_root/.build-XXXXXXXX")
release=
changed_current=0
changed_config=0
previous_release=$(readlink "$install_root/current" || true)
previous_release_path=$(readlink -f "$install_root/current" || true)

activate_release() {
    ln -s -- "$1" "$build_dir/current"
    mv -Tf -- "$build_dir/current" "$install_root/current"
}

cleanup() {
    local status=$?
    trap - EXIT
    set +e
    if (( status != 0 )); then
        if (( changed_current )); then
            log 'Activation failed. Check journalctl -u selfx-api -u selfx-worker@default -u selfx-worker@heavy -u selfx-redis.'
            if [[ -n $previous_release ]]; then
                activate_release "$previous_release"
            else
                systemctl stop "${app_units[@]}"
                rm -f -- "$install_root/current"
            fi
        fi
        if (( changed_config )); then
            install -m 0600 "$build_dir/previous.env" "$config_file"
        fi
        if (( changed_current )) && [[ -n $previous_release ]]; then
            systemctl restart "${app_units[@]}" || true
        fi
        if [[ -n $release && $(readlink "$install_root/current") != "$release" ]]; then
            rm -rf -- "$release"
        fi
    fi
    rm -rf -- "$build_dir"
    exit "$status"
}
trap cleanup EXIT

# Official release hashes from https://nodejs.org/en/blog/release/v22.23.5.
node_version=22.23.5
node_name=node-v$node_version-linux-$node_arch
node_bin=$install_root/toolchains/$node_name/bin
if [[ ! -x $node_bin/node ]]; then
    log "Downloading and verifying Node.js $node_version."
    archive=$build_dir/$node_name.tar.xz
    curl --fail --location --retry 3 --connect-timeout 10 --max-time 180 \
        --proto '=https' --proto-redir '=https' \
        --output "$archive" "https://nodejs.org/dist/v$node_version/$node_name.tar.xz"
    printf '%s  %s\n' "$node_sha" "$archive" | sha256sum --check --status ||
        die 'The Node.js download did not match its published checksum.'
    tar --no-same-owner -xf "$archive" -C "$build_dir"
    mv -T -- "$build_dir/$node_name" "$install_root/toolchains/$node_name"
fi

log 'Building SelfX and installing CPU workers.'
release=$(mktemp -d "$install_root/releases/release-XXXXXXXX")
install -d -m 0755 "$release/server" "$release/web" "$build_dir/web"
cp -R -- "$source_dir/server/app" "$source_dir/server/requirements.txt" "$release/server/"
cp -R -- "$source_dir/web/"{src,public,index.html,package.json,package-lock.json,tsconfig.json,vite.config.ts} "$build_dir/web/"
chown -hR selfx:selfx "$release" "$build_dir/web"
chmod 0755 "$release" "$build_dir"

as_selfx() {
    runuser -u selfx -- env HOME="$state_dir" XDG_CACHE_HOME="$cache_dir" "$@"
}

as_selfx python3 -m venv "$release/venv"
pip=("$release/venv/bin/python" -m pip --disable-pip-version-check)
# Seed CPU-only wheels before EasyOCR can pull the much larger default Torch builds.
as_selfx "${pip[@]}" install --index-url https://download.pytorch.org/whl/cpu torch torchvision
as_selfx "${pip[@]}" install -r "$release/server/requirements.txt"
as_selfx "${pip[@]}" check
(
    cd "$build_dir/web"
    as_selfx env PATH="$node_bin:/usr/bin:/bin" npm ci --no-audit --no-fund
    as_selfx env PATH="$node_bin:/usr/bin:/bin" npm run build
)
[[ -f $build_dir/web/dist/index.html ]] || die 'The frontend build did not produce index.html.'
cp -a -- "$build_dir/web/dist/." "$release/web/"
chown -hR root:root "$release"
touch "$release/.selfx-managed-release"

for unit in selfx-api.service selfx-worker@.service selfx-redis.service; do
    install -m 0644 "$source_dir/deploy/systemd/$unit" "/etc/systemd/system/$unit"
done
if [[ ! -f $config_dir/redis.conf ]]; then
    install -m 0640 -g selfx "$source_dir/deploy/systemd/redis.conf" "$config_dir/redis.conf"
fi
systemctl daemon-reload
systemctl enable --now selfx-redis.service
if [[ $port != "$old_port" || $bind != "$old_bind" ]]; then
    install -m 0600 "$config_file" "$build_dir/previous.env"
    temp_env=$(mktemp "$config_dir/.env-XXXXXXXX")
    awk -v port="$port" -v bind="$bind" '
        !/^SELFX_(PORT|BIND_HOST)=/ { print }
        END { print "SELFX_PORT=" port; print "SELFX_BIND_HOST=" bind }
    ' "$config_file" > "$temp_env"
    mv -T -- "$temp_env" "$config_file"
    changed_config=1
fi
activate_release "$release"
changed_current=1
systemctl restart "${app_units[@]}"

check_host=$bind
if [[ $bind == 0.0.0.0 ]]; then check_host=127.0.0.1; fi
url=http://$check_host:$port
log 'Waiting for SelfX and its data services.'
ready=0
for (( attempt=0; attempt<45; attempt++ )); do
    if curl --noproxy '*' --fail --silent --max-time 2 "$url/api/v1/healthz" >/dev/null &&
        curl --noproxy '*' --fail --silent --max-time 2 "$url/" >/dev/null &&
        systemctl is-active --quiet selfx-worker@default.service &&
        systemctl is-active --quiet selfx-worker@heavy.service; then
        ready=1
        break
    fi
    sleep 2
done
(( ready )) || die 'SelfX did not pass its startup checks.'
systemctl enable "${app_units[@]}"

# Keep one rollback release. Match only directories marked by this installer,
# and leave the active release and the previous symlink target untouched.
for candidate in "$install_root/releases"/release-????????; do
    [[ -d $candidate && ! -L $candidate ]] || continue
    [[ $candidate != "$release" && $candidate != "$previous_release_path" ]] || continue
    [[ -f $candidate/.selfx-managed-release && ! -L $candidate/.selfx-managed-release ]] || continue
    if ! rm -rf -- "$candidate"; then
        log "Could not remove the obsolete release at $candidate."
    fi
done

log "Open $url"
log "Initial login is in $config_file under SELFX_ADMIN_USER and SELFX_ADMIN_PASSWORD."
