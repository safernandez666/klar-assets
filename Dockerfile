# ── Stage 1: Build frontend ──────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python app ─────────────────────────────────────────
FROM python:3.13-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY .git/ ./.git/
COPY src/ ./src/
COPY main.py scheduler.py ./
COPY images/ ./images/

# Version info from git (no build-args needed)
RUN GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown") && \
    BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") && \
    echo "APP_VERSION=${GIT_COMMIT}" >> /app/.env.build && \
    echo "APP_BUILD_DATE=${BUILD_DATE}" >> /app/.env.build && \
    rm -rf .git

# Frontend build output
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Data dir
RUN mkdir -p data

EXPOSE 8080

CMD ["python", "main.py"]
