#!/usr/bin/env bash
# One-command local demo with the FULL document toolchain, in Docker.
#
#   scripts/demo_docker.sh            # build once (~10 min, compiles PdfCraft), then run
#   scripts/demo_docker.sh --rebuild  # rebuild the image after pulling new code
#   HUB_PORT=9000 scripts/demo_docker.sh
#
# Runs the workspace in development mode on this computer only
# (127.0.0.1): the demo educator sign-in, real PDF upload, accessible HTML +
# tagged PDF downloads, OCR review, PdfCraft, and veraPDF all work. Uploaded
# files stay in a local Docker volume (hub-demo-data); remove it with
#   docker volume rm hub-demo-data
# Ctrl+C stops the demo.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${HUB_IMAGE:-accessibility-hub:local}"
PORT="${HUB_PORT:-8787}"
command -v docker >/dev/null 2>&1 || { echo "Docker is not installed: get Docker Desktop, or use scripts/demo_up.sh instead." >&2; exit 1; }

if [ "${1:-}" = "--rebuild" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE (first build compiles PdfCraft; about 10 minutes)…"
  docker build -t "$IMAGE" .
fi

CODE="${HUB_STAGING_ACCESS_CODE:-demo-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
SECRET="$(od -An -N48 -tx1 /dev/urandom | tr -d ' \n')"

echo
echo "Accessibility Hub — local demo (full toolchain)"
echo "  URL:         http://127.0.0.1:${PORT}/login"
echo "  Sign in:     'Sign in with your Coastline Microsoft account' (demo, no account contacted)"
echo "  Access code: ${CODE}   (the classic access-code workspace)"
echo "  Data:        Docker volume hub-demo-data (stays on this computer)"
echo

exec docker run --rm -it --name hub-demo \
  -p "127.0.0.1:${PORT}:8000" \
  -e HUB_ENV=development \
  -e HUB_STAGING_ACCESS_CODE="$CODE" \
  -e HUB_SESSION_SECRET="$SECRET" \
  -v hub-demo-data:/var/data \
  "$IMAGE"
