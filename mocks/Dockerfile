FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH \
    MOCKS_STATE=/data/state.json
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --uid 1000 valo && mkdir -p /data && chown valo:valo /data
COPY valo_mocks ./valo_mocks
USER valo
CMD ["python", "-m", "valo_mocks", "all"]
