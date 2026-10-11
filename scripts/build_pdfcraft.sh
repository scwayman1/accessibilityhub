#!/usr/bin/env bash
# Build the pinned PdfCraft command-line tool used as the Hub's second-opinion
# checker, tagged-PDF semantics fixer, and page renderer.
#
#   scripts/build_pdfcraft.sh            # -> vendor-bin/pdfcraft-cli
#   PDFCRAFT_SRC=/path/to/pdfcraft scripts/build_pdfcraft.sh
#
# PdfCraft (https://github.com/storytold/pdfcraft) is MIT OR Apache-2.0. The
# Hub pins one reviewed commit; bump PDFCRAFT_REV deliberately, re-run the
# real-binary tests (tests/test_pdfcraft.py), and record the bump in
# docs/progress-ledger.md. Needs Rust >= 1.94 (the pinned lockfile's
# dependencies need it, though PdfCraft declares 1.90) and a C compiler.
# The tool itself never touches the network once built.
set -euo pipefail
cd "$(dirname "$0")/.."

PDFCRAFT_REPO="${PDFCRAFT_REPO:-https://github.com/storytold/pdfcraft}"
PDFCRAFT_REV="${PDFCRAFT_REV:-bbbe60015c571ebfc39708ee07777b89e267122a}"
PDFCRAFT_SRC="${PDFCRAFT_SRC:-$PWD/.pdfcraft-src}"
OUT_DIR="${OUT_DIR:-$PWD/vendor-bin}"

command -v cargo >/dev/null 2>&1 || { echo "cargo not found: install Rust >= 1.94 (https://rustup.rs)" >&2; exit 1; }

if [ ! -d "$PDFCRAFT_SRC/.git" ]; then
  git init -q "$PDFCRAFT_SRC"
  git -C "$PDFCRAFT_SRC" remote add origin "$PDFCRAFT_REPO"
fi
if [ "$(git -C "$PDFCRAFT_SRC" rev-parse HEAD 2>/dev/null || true)" != "$PDFCRAFT_REV" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git -C "$PDFCRAFT_SRC" fetch -q --depth 1 origin "$PDFCRAFT_REV"
  git -C "$PDFCRAFT_SRC" checkout -q --detach FETCH_HEAD
fi

(cd "$PDFCRAFT_SRC" && cargo build --release --locked -p pdfcraft-cli)

mkdir -p "$OUT_DIR"
install -m 0755 "$PDFCRAFT_SRC/target/release/pdfcraft-cli" "$OUT_DIR/pdfcraft-cli"
echo "pdfcraft-cli @ ${PDFCRAFT_REV:0:12} -> $OUT_DIR/pdfcraft-cli"
