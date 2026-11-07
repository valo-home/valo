FROM python:3.14-slim AS core
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
COPY --from=arigaio/atlas:0.38.0-community /atlas /usr/local/bin/atlas
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home valo && mkdir -p /data && chown valo:valo /data
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH \
    EXT_CATALOG=/app/extensions/catalog.json EXT_SDK_PATH=/app/extensions/sdk EXT_DIR=/data/extensions BACKUP_DIR=/data/backups
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY migrations ./migrations
COPY --from=extensions . ./extensions
COPY --from=docs operations.md ./docs/
COPY --from=help . ./help/
USER valo
EXPOSE 8000 8001
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "app.server.app:app"]

FROM core AS media
COPY --from=alexxit/go2rtc:1.9.15 /usr/local/bin/go2rtc /usr/local/bin/go2rtc
COPY --from=mwader/static-ffmpeg:7.1.1 /ffmpeg /ffprobe /usr/local/bin/
ENV CAMERAS_BUFFER=/buffer
EXPOSE 1984 8554
CMD ["python", "-m", "app.cameras.main"]
