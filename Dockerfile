# Job Hunter: one container, FastAPI + SQLite (constitution I).
FROM python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS build
# pinned 2026-10-05 (python:3.12-slim, 3.12.15)
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock README.md* ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

# Claude Code CLI (feature 005): installed with npm in a throwaway stage; it ships a native
# binary, so Node is not needed at runtime. Version pinned; auto-update disabled below.
FROM node@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS claude
# pinned 2026-10-05 (node:22-bookworm-slim, 22.23.3)
RUN npm install -g --omit=dev @anthropic-ai/claude-code@2.1.290

FROM python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
# pinned 2026-10-05 (python:3.12-slim, 3.12.15)
COPY --from=claude /usr/local/lib/node_modules/@anthropic-ai/claude-code /opt/claude-code
RUN ln -s /opt/claude-code/bin/claude.exe /usr/local/bin/claude
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations/ migrations/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/jobhunter.db \
    APP_TIMEZONE=America/Edmonton \
    CLAUDE_CONFIG_DIR=/data/claude \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
# Runs as uid/gid 1000 (sam on the host) so ./data stays owned by sam.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health').read()"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn jobhunter.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
