#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-022}
CONFIG_DIR=${CONFIG_DIR:-/config}
LOG_DIR=${LOG_DIR:-/config/logs}

groupmod -o -g "$PGID" boomarr >/dev/null 2>&1
usermod -o -u "$PUID" -g "$PGID" boomarr >/dev/null 2>&1

umask "$UMASK"

mkdir -p "$CONFIG_DIR"
chown -R boomarr:boomarr /app "$CONFIG_DIR"

boomarr paths --config-dir "$CONFIG_DIR" 2>/dev/null | while IFS= read -r dir; do
    mkdir -p "$dir"
    chown boomarr:boomarr "$dir"
done

exec gosu boomarr "$@"
