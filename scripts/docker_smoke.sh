#!/usr/bin/env bash
# Smoke-test a built Accessibility Hub image: every document tool is present,
# the service answers, and an accessible copy can be produced and validated
# inside the container.
#
#   docker build -t accessibility-hub:ci . && scripts/docker_smoke.sh accessibility-hub:ci
set -euo pipefail
IMAGE="${1:?usage: scripts/docker_smoke.sh <image>}"
NAME="hub-smoke-$$"

echo "== toolchain inside the image"
docker run --rm "$IMAGE" python -m service.toolchain
# Each check must print its marker line, so a check that silently ran nothing
# (for example, stdin not reaching the container) fails the smoke test.
out="$(docker run --rm -i "$IMAGE" python - <<'PY'
from service.toolchain import toolchain_versions
versions = toolchain_versions()
missing = [name for name in ("qpdf", "tesseract", "pdftoppm", "pdfcraft", "verapdf") if not versions.get(name)]
assert not missing, f"tools missing from the image: {missing}"
print("all document tools present:", ", ".join(sorted(versions)))
PY
)"
echo "$out"
grep -q "all document tools present" <<<"$out"

echo "== produce and validate an accessible copy inside the image"
out="$(docker run --rm -i "$IMAGE" python - <<'PY'
import tempfile
from pathlib import Path

import check_pdf
from tina.author import AccessiblePackageProducer

model = {
    "version": "tina-docmodel/v1", "title": "Smoke test", "language": "en-US",
    "blocks": [
        {"kind": "heading", "level": 1, "text": "Smoke test"},
        {"kind": "paragraph", "text": "Course site: https://example.edu/course",
         "links": [{"text": "https://example.edu/course", "href": "https://example.edu/course"}]},
        {"kind": "table", "caption": "Weights", "header_rows": 1, "rows": [["Item", "Weight"], ["Essay", "40%"]]},
    ],
}
package = AccessiblePackageProducer.with_builtin_tools().produce(model)
check = package["self_check"]
assert not check["needs_attention"], check["needs_attention"]
assert check["second_opinion"]["available"], "PdfCraft second opinion did not run"
failed = [r["rule"] for r in check["second_opinion"]["results"] if r["status"] == "failed"]
assert not failed, f"PdfCraft failures on our own output: {failed}"
assert check["verapdf"]["runner"] == "local" and not check["verapdf"]["failed_rules"], check["verapdf"]
print("produced copy: no Needs-attention, no PdfCraft failures, no failed veraPDF UA-1 clauses")
PY
)"
echo "$out"
grep -q "produced copy: no Needs-attention" <<<"$out"

echo "== service answers /healthz"
docker run -d --name "$NAME" -p 18000:8000 -e HUB_ENV=development \
  -e HUB_STAGING_ACCESS_CODE=smoke -e HUB_SESSION_SECRET="$(head -c 48 /dev/urandom | base64)" "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18000/healthz >/tmp/hub-healthz.json 2>/dev/null; then break; fi
  sleep 1
done
docker exec "$NAME" stat -c %U /proc/1 | grep -qx hub \
  || { echo "gunicorn is not running as the unprivileged hub user" >&2; exit 1; }
echo "web server runs as the unprivileged hub user"
python3 - <<'PY'
import json
payload = json.load(open("/tmp/hub-healthz.json"))
assert payload["ok"] is True, payload
assert all(payload["toolchain"].values()), payload["toolchain"]
print("healthz ok; toolchain:", payload["toolchain"])
PY
echo "docker smoke: all checks passed"
