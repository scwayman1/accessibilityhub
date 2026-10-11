#!/bin/sh
# Container entrypoint. Render attaches the persistent disk at start-up, owned
# by root, so the data directory cannot be prepared at build time. Started as
# root, this hands the directory to the unprivileged `hub` user and drops to
# it before the web server starts; started as any other user, it just runs.
set -eu
DATA_DIR="${HUB_DATA_DIR:-/var/data}"
SERVER="gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} service.wsgi:application"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R hub:hub "$DATA_DIR"
  # setpriv replaces this process (no root parent stays behind).
  # shellcheck disable=SC2086
  exec env HOME=/home/hub setpriv --reuid=hub --regid=hub --init-groups $SERVER
fi
# shellcheck disable=SC2086
exec $SERVER
