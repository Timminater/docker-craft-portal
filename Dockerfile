# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CRAFT_DATA_DIR=/data \
    CRAFT_PUBLIC_URL=http://localhost:8080

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 craft \
    && useradd --uid 10001 --gid craft --system --no-create-home craft \
    && mkdir -p /data \
    && chown craft:craft /data \
    && chmod 0700 /data
COPY --chown=root:root portal ./portal
# Source checkouts may use a private umask; the unprivileged runtime needs read access.
RUN chmod -R a+rX /app/portal
USER 10001:10001
EXPOSE 8080
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/healthz",timeout=3)' || exit 1
CMD ["uvicorn", "portal.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
