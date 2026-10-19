# Seen dashboard image. Hooks and the CLI run on the host (Claude Code lives there);
# this image runs the local API + web build, and the test suite, in isolation.

FROM node:22.20.0-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.15-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY pricing/ pricing/
COPY packages/ packages/

FROM base AS app
RUN uv sync --frozen --no-dev --no-editable --package seen-cli
COPY --from=web /web/dist /app/web/dist
COPY docker/entrypoint.sh /usr/local/bin/seen-entrypoint
RUN useradd --uid 10001 --create-home seen && mkdir -p /data && chown seen /data && chmod 0755 /usr/local/bin/seen-entrypoint
USER seen
ENV PATH=/app/.venv/bin:$PATH SEEN_HOME=/data SEEN_WEB_DIST=/app/web/dist
EXPOSE 47821
HEALTHCHECK --interval=10s --timeout=3s --retries=12 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:47821/api/projects',timeout=2)"
ENTRYPOINT ["seen-entrypoint"]

FROM base AS test
RUN uv sync --frozen
COPY tests/ tests/
COPY scripts/ scripts/
COPY web/openapi.json web/openapi.json
COPY docs/ docs/
COPY plugin/ plugin/
RUN useradd --uid 10001 --create-home seen && chown -R seen /app
USER seen
RUN git config --global user.email test@example.com && git config --global user.name test
ENV PATH=/app/.venv/bin:$PATH
CMD ["sh", "-c", "ruff check . && mypy packages/core/src && python scripts/gen_openapi.py --check && pytest -m 'not e2e and not pg'"]
