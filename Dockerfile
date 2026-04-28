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

# Version info (passed as build arg)
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
ENV APP_VERSION=${GIT_COMMIT}
ENV APP_BUILD_DATE=${BUILD_DATE}

# App code
COPY src/ ./src/
COPY main.py ./

# Frontend build output
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Data dir
RUN mkdir -p data

EXPOSE 8080

CMD ["python", "main.py"]
