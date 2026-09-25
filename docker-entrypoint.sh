#!/bin/sh
set -eu

CONFIG_DIR=${CONFIG_DIR:-/config}

# Rootless mode: the container was started with --user / runAsUser (e.g. on
# Kubernetes or Podman). We cannot and need not switch users; just make sure
# the config directory is usable and run the command as-is.
if [ "$(id -u)" != "0" ]; then
    umask "${UMASK:-022}"
    mkdir -p "$CONFIG_DIR" 2>/dev/null || true
    exec "$@"
fi

PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-022}

if [ "$PUID" = "0" ]; then
    echo "WARNING: PUID=0 runs Boomarr as root. Set PUID/PGID to your media user." >&2
fi

groupmod -o -g "$PGID" boomarr
usermod -o -u "$PUID" -g "$PGID" boomarr

umask "$UMASK"

mkdir -p "$CONFIG_DIR"

# Create writable directories referenced by the config (log dir, database
# dir, output paths) and hand them to the boomarr user. Output paths are
# not chowned recursively so existing libraries are never touched.
boomarr paths --config-dir "$CONFIG_DIR" 2>/dev/null | while IFS= read -r dir; do
    [ -n "$dir" ] || continue
    mkdir -p "$dir"
    chown boomarr:boomarr "$dir"
done

# The config directory itself (config, database, logs) belongs to boomarr.
chown -R boomarr:boomarr "$CONFIG_DIR"

exec gosu boomarr:boomarr "$@"
