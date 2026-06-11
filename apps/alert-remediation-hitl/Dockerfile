FROM python:3.14-alpine@sha256:c5c72336b2060db658391424c48466341838860a9f30efee9280ee53580d9537

# Run as non-root (UID 65534 = nobody on Alpine).
ARG UID=65534
ARG GID=65534

RUN apk add --no-cache curl ca-certificates \
 && addgroup -g ${GID} -S app || true \
 && adduser -u ${UID} -G app -S -h /app app || true

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

USER ${UID}:${GID}

EXPOSE 8080

# State path is configurable via STATE_DB_PATH; default points at the PVC mount.
ENV STATE_DB_PATH=/var/lib/hitl/state.db \
    PORT=8080 \
    HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# uvicorn workers=1 — multi-process SQLite on Longhorn RWO is undefined behavior.
# Concurrency is async via FastAPI event loop.
CMD ["uvicorn", "alert_remediation_hitl.main:app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "1", \
     "--log-level", "info", "--no-access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1
