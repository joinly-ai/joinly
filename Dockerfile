FROM python:3.12-slim AS builder
ENV UV_LINK_MODE="copy"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-editable

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1

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

RUN groupadd --gid 1001 app && \
    useradd --uid 1001 --gid 1001 -m app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app entrypoint.sh /entrypoint
RUN chmod +x /entrypoint

USER app
WORKDIR /app

# TODO fix this, wont work with finding playwright
RUN /app/.venv/bin/python -m scripts.bootstrap_assets

ENTRYPOINT ["/entrypoint"]
