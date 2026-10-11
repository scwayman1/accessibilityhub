#!/usr/bin/env bash
# Read-only local prerequisites and Git state for an agent work cycle.
set -u
cd "$(dirname "$0")/.." || exit 1

echo "commit: $(git rev-parse HEAD)"
echo "branch: $(git branch --show-current)"
if [ -n "$(git status --porcelain)" ]; then
  echo "working tree: dirty (preserve existing changes)"
else
  echo "working tree: clean"
fi

PYTHON="${PYTHON:-$PWD/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  echo "python environment: missing ($PYTHON; create with python3.11 -m venv .venv)"
else
  echo "python: $($PYTHON --version 2>&1)"
  for module in pypdf PIL gunicorn jwt; do
    if "$PYTHON" -c "import $module" >/dev/null 2>&1; then
      echo "$module: ready"
    else
      echo "$module: unavailable"
    fi
  done
  if "$PYTHON" -c 'import weasyprint' >/dev/null 2>&1; then
    echo "weasyprint native libraries: ready"
  else
    echo "weasyprint native libraries: unavailable (check Pango/GObject installation)"
  fi
fi

for tool in docker pdftotext qpdf tesseract; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "$tool: $(command -v "$tool")"
  else
    echo "$tool: unavailable"
  fi
done
