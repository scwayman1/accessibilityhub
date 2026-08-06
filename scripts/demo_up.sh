#!/usr/bin/env bash
# One-command local demo of the Accessibility Hub staging workspace.
#
#   scripts/demo_up.sh            # starts on http://127.0.0.1:8787
#   HUB_PORT=9000 scripts/demo_up.sh
#
# Generates a session secret, prints the access code, and launches the
# synthetic-only service in development mode. Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3.11}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python3

export HUB_ENV=development
export PORT="${HUB_PORT:-8787}"
export HUB_STAGING_ACCESS_CODE="${HUB_STAGING_ACCESS_CODE:-demo-$($PYTHON -c 'import secrets; print(secrets.token_hex(4))')}"
export HUB_SESSION_SECRET="${HUB_SESSION_SECRET:-$($PYTHON -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export HUB_DATA_DIR="${HUB_DATA_DIR:-$PWD/.hub-staging}"

"$PYTHON" -m service.toolchain
echo
echo "Accessibility Hub — local demo"
echo "  URL:         http://127.0.0.1:${PORT}/login"
echo "  Access code: ${HUB_STAGING_ACCESS_CODE}"
echo "  Data dir:    ${HUB_DATA_DIR} (synthetic records only; safe to delete)"
echo
echo "Smoke test (in another terminal):"
echo "  $PYTHON scripts/staging_smoke.py --base-url http://127.0.0.1:${PORT} --access-code '${HUB_STAGING_ACCESS_CODE}'"
echo
exec "$PYTHON" -m service
