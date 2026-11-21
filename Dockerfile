FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig*.json frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm test && npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
COPY pyproject.toml README.md ./
COPY dsn_agent ./dsn_agent
RUN pip install --no-cache-dir .
COPY config ./config
COPY --from=frontend /frontend/dist ./frontend/dist
RUN useradd --uid 10001 --create-home appuser
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn dsn_agent.api:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1 --no-proxy-headers"]
