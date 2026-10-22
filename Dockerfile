# Match requirements-hosted.txt to the browsers included in this image.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    ACCESSPROOF_HOST=0.0.0.0 \
    PORT=10000 \
    ACCESSPROOF_REQUIRE_DEMO_AUTH=true \
    ACCESSPROOF_DATA_DIR=/var/lib/accessproof/data \
    ACCESSPROOF_ARTIFACTS_DIR=/var/lib/accessproof/artifacts

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-hosted.txt ./
RUN python -m pip install -r requirements-hosted.txt

RUN groupadd --gid 10001 accessproof \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin accessproof \
    && mkdir -p /var/lib/accessproof/data /var/lib/accessproof/artifacts \
    && chown -R 10001:10001 /var/lib/accessproof

COPY backend ./backend
COPY static ./static
COPY scripts ./scripts
COPY LICENSE ./LICENSE

USER 10001:10001
EXPOSE 10000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "scripts/run.py"]
