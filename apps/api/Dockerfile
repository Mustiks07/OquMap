# Build context: repository root (docker compose sets it).
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/apps/api

COPY apps/api/requirements.lock.txt ./requirements.lock.txt
# Optional extra CA bundle for TLS-intercepting proxies (see docker-compose.ca.yml); absent by default.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --require-hashes -r requirements.lock.txt

COPY apps/api/ ./
COPY data/ /app/data/
COPY scripts/docker-entrypoint.sh /usr/local/bin/oqumap-entrypoint
# Defensive: strip CR if a CRLF checkout slipped through, then fail the build if the shebang is still wrong.
RUN sed -i 's/\r$//' /usr/local/bin/oqumap-entrypoint \
    && head -n 1 /usr/local/bin/oqumap-entrypoint | grep -qx '#!/bin/sh' \
    && chmod +x /usr/local/bin/oqumap-entrypoint && useradd --create-home --uid 10001 oqumap \
    && mkdir -p /app/storage && chown -R oqumap /app/storage /app/data
USER oqumap

ENV OQUMAP_STORAGE_DIR=/app/storage
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=60s --retries=30 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).status == 200 else 1)" || exit 1
ENTRYPOINT ["oqumap-entrypoint"]
CMD ["api"]
