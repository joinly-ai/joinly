FROM ghcr.io/astral-sh/uv:latest AS uv

FROM mcr.microsoft.com/vscode/devcontainers/base:bookworm

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
    ffmpeg \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV XDG_RUNTIME_DIR=/home/vscode/.xdg_runtime
RUN mkdir -p $XDG_RUNTIME_DIR && chown vscode: $XDG_RUNTIME_DIR

COPY --from=uv --chown=vscode: /uv /uvx /bin/
