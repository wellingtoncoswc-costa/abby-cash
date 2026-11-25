FROM python:3.12.8-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app /data/storage && chown app:app /app /data/storage
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
USER app
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY --chown=app:app . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 STORAGE_DIR=/data/storage
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
