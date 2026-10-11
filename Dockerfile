# Accessibility Hub staging service with the full document toolchain.
#
# Stage 1 builds the pinned PdfCraft CLI (storytold/pdfcraft, MIT OR
# Apache-2.0); stage 2 resolves the pinned veraPDF CLI from Maven Central.
# The runtime stage has Python, WeasyPrint's pango and fonts, poppler (page
# images), qpdf, tesseract, and a headless Java for veraPDF, so reviews
# disclose fewer skipped checks and accessible copies can be produced and
# validated.
#
# To move the Render service onto this image (a billing decision): set
# `runtime: docker` and `dockerfilePath: ./Dockerfile` in render.yaml, and
# attach a persistent disk mounted at /var/data (HUB_DATA_DIR) so records
# survive deploys. CI builds and smoke-tests this image (.github/workflows/docker.yml).

# PdfCraft declares rust-version 1.90, but its pinned lockfile needs 1.94+
# (rten, hayro, boa); 1.97 is the version the pinned build is verified with.
# The full Rust image already carries git and a C compiler for aws-lc-sys.
FROM rust:1.97-bookworm AS pdfcraft
WORKDIR /build
COPY scripts/build_pdfcraft.sh scripts/build_pdfcraft.sh
RUN OUT_DIR=/build/vendor-bin PDFCRAFT_SRC=/build/pdfcraft-src scripts/build_pdfcraft.sh

FROM maven:3.9-eclipse-temurin-17 AS verapdf
WORKDIR /build
COPY scripts/install_verapdf.sh scripts/install_verapdf.sh
RUN OUT_DIR=/build/vendor-bin scripts/install_verapdf.sh

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HUB_DATA_DIR=/var/data
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core poppler-utils qpdf tesseract-ocr default-jre-headless \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 hub && mkdir -p /var/data && chown hub /var/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=hub . .
COPY --from=pdfcraft --chown=hub /build/vendor-bin/pdfcraft-cli /app/vendor-bin/pdfcraft-cli
COPY --from=verapdf --chown=hub /build/vendor-bin/verapdf /app/vendor-bin/verapdf
COPY --from=verapdf --chown=hub /build/vendor-bin/verapdf-lib /app/vendor-bin/verapdf-lib
USER hub
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} service.wsgi:application"]
