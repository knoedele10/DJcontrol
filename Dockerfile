# ---------- Frontend build ----------
FROM node:22-bookworm-slim AS frontend
ARG PNPM_VERSION=12.15.0
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN npm install -g pnpm@${PNPM_VERSION}
WORKDIR /build
COPY Template/package.json Template/pnpm-lock.yaml Template/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY Template/ ./
RUN pnpm build

# ---------- Backend dependencies ----------
FROM python:3.12-slim AS backend-deps
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY Backend/Requirements.txt Backend/Constraints.txt ./
RUN pip install -r Requirements.txt

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PPT_APP=powerpoint \
    PLAYER_CONTROLLER=mock \
    DB_PATH=/app/Backend/Data/dashboard.db \
    FRONTEND_DIST=/app/Template/dist \
    API_UPSTREAM=

COPY --from=backend-deps /opt/venv /opt/venv

WORKDIR /app/Backend
COPY Backend/ ./
RUN rm -rf Tests Data && mkdir -p Data

COPY --from=frontend /build/dist /app/Template/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# SQLite and the single PPT COM worker require one process.
CMD ["uvicorn", "Main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]