# Accessibility Hub staging service with the full document toolchain.
#
# Stage 1 builds the pinned PdfCraft CLI (storytold/pdfcraft, MIT OR
# Apache-2.0). Stage 2 is the runtime: Python, WeasyPrint's pango and fonts,
# poppler (page images), qpdf, and tesseract, so reviews disclose fewer
# skipped checks and accessible copies can be produced.
#
# To move the Render service onto this image (a billing decision): set
# `runtime: docker` and `dockerfilePath: ./Dockerfile` in render.yaml, and
# attach a persistent disk mounted at /var/data (HUB_DATA_DIR) so records
# survive deploys. Docker builds are not exercised in CI yet.

FROM rust:1.90-bookworm AS pdfcraft
WORKDIR /build
COPY scripts/build_pdfcraft.sh scripts/build_pdfcraft.sh
RUN apt-get update && apt-get install -y --no-install-recommends git clang && rm -rf /var/lib/apt/lists/* \
 && OUT_DIR=/build/vendor-bin PDFCRAFT_SRC=/build/pdfcraft-src scripts/build_pdfcraft.sh

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HUB_DATA_DIR=/var/data
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core poppler-utils qpdf tesseract-ocr \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 hub && mkdir -p /var/data && chown hub /var/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=hub . .
COPY --from=pdfcraft --chown=hub /build/vendor-bin/pdfcraft-cli /app/vendor-bin/pdfcraft-cli
USER hub
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} service.wsgi:application"]
