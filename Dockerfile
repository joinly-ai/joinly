# Stage 1: Build environment
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE="copy" \
    UV_COMPILE_BYTECODE=1

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies using uv and lock files
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --no-editable

# Copy app source code
COPY . /app

# Install application into .venv (non-editable mode)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Stage 2: Runtime image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    JOINLY_SERVER_HOST="0.0.0.0" \
    JOINLY_SERVER_PORT=8000 \
    JOINLY_LOGGING_PLAIN=1

EXPOSE 8000

# Install system dependencies (for audio, video, browser, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxcomposite1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    x11vnc \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/* /tmp/*

# Create non-root user
RUN groupadd --gid 1001 app && \
    useradd --uid 1001 --gid 1001 -m app

# Copy virtual environment from builder and set permissions
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Set user and working directory
USER app
WORKDIR /app

# Run download assets script to package all required assets
# Note: this makes the image size very large, but has all assets on startup
RUN --mount=type=bind,source=scripts/download_assets.py,target=download_assets.py \
    PATH="/app/.venv/bin:${PATH}" \
    /app/.venv/bin/python download_assets.py \
    --assets playwright whisper silero kokoro \
    --whisper-model base

# Set entrypoint
ENTRYPOINT ["/app/.venv/bin/joinly"]
