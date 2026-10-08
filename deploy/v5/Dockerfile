# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CHROME_BINARY=/usr/bin/chromium CHROMEDRIVER_PATH=/usr/bin/chromedriver
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -s /run/secrets/proxy_ca ]; then \
      apt-get -o Acquire::https::CaInfo=/run/secrets/proxy_ca update; \
    else apt-get update; fi && apt-get install -y --no-install-recommends \
    chromium chromium-driver ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -s /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY --chown=10001:10001 core ./core
COPY --chown=10001:10001 lite ./lite
COPY --chown=10001:10001 browser_dom.py monitoring.py watcher.py ./
RUN groupadd --gid 10001 lite && useradd --uid 10001 --gid lite --create-home lite \
    && mkdir -p /data && chown lite:lite /data && chmod 700 /data
USER lite
CMD ["python", "-m", "lite", "serve"]
