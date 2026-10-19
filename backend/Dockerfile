# Production image for the API and the job worker (same image, different command).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Headless Chromium (+ its OS libraries) for rendering JavaScript-only sites.
RUN .venv/bin/python -m playwright install --with-deps chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 aeo && chown -R aeo /app /ms-playwright
USER aeo
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# Apply migrations, then serve. --proxy-headers trusts X-Forwarded-For from the frontend proxy only
# (the API is not published to the internet in docker-compose.yml).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
