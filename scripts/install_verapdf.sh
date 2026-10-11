#!/usr/bin/env bash
# Install the pinned veraPDF command-line validator locally (no Docker).
#
#   scripts/install_verapdf.sh          # -> vendor-bin/verapdf (+ vendor-bin/verapdf-lib/)
#
# veraPDF (https://verapdf.org, GPLv3+ / MPLv2+) is the PDF Association's
# reference validator. This resolves org.verapdf.apps:greenfield-apps at one
# pinned version from Maven Central and writes a small launcher. check_pdf.py
# uses the launcher when present (VERAPDF_BIN, then vendor-bin/verapdf, then
# `verapdf` on PATH) and otherwise falls back to the pinned Docker image.
# Needs Java 11+ and Maven. veraPDF validates files offline.
set -euo pipefail
cd "$(dirname "$0")/.."

VERAPDF_VERSION="${VERAPDF_VERSION:-1.28.2}"
OUT_DIR="${OUT_DIR:-$PWD/vendor-bin}"
LIB_DIR="$OUT_DIR/verapdf-lib"

command -v java >/dev/null 2>&1 || { echo "java not found: install a Java 11+ runtime" >&2; exit 1; }
command -v mvn >/dev/null 2>&1 || { echo "mvn not found: install Maven" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cat > "$work/pom.xml" <<POM
<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
  <groupId>local.hub</groupId><artifactId>verapdf-cli</artifactId><version>1</version>
  <dependencies><dependency>
    <groupId>org.verapdf.apps</groupId><artifactId>greenfield-apps</artifactId><version>${VERAPDF_VERSION}</version>
  </dependency></dependencies>
</project>
POM
rm -rf "$LIB_DIR"
mkdir -p "$LIB_DIR"
(cd "$work" && mvn -q -B dependency:copy-dependencies -DoutputDirectory="$LIB_DIR")

cat > "$OUT_DIR/verapdf" <<'LAUNCHER'
#!/usr/bin/env bash
# veraPDF CLI launcher written by scripts/install_verapdf.sh.
here="$(cd "$(dirname "$0")" && pwd)"
exec java -cp "$here/verapdf-lib/*" org.verapdf.apps.GreenfieldCliWrapper "$@"
LAUNCHER
chmod 0755 "$OUT_DIR/verapdf"
echo "veraPDF ${VERAPDF_VERSION} -> $OUT_DIR/verapdf"
