# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

joinly is a Python middleware that enables AI agents to join and participate in video meetings (Google Meet, Zoom, Teams). It exposes a FastMCP server providing meeting tools (join, leave, speak, transcribe, chat, snapshot, screen share) that any MCP-compatible AI client can use.

## Build & Development Commands

```bash
# Install all dependencies (run from repo root)
uv sync --frozen

# Download required ML models (Silero VAD, Whisper, Kokoro TTS)
uv run scripts/download_assets.py

# Lint (ruff checks all rules by default)
uv run ruff check .
uv run ruff check --fix .    # autofix

# Format
uv run ruff format .

# Type check
uv run pyright

# Run tests (skips manual tests by default)
uv run pytest

# Run a single test
uv run pytest tests/test_meeting_transcription.py::TestTranscription::test_mcp_transcription -v

# Run manual/e2e tests (requires JOINLY_TEST_MEETING_URL env var)
uv run pytest -m manual

# Start as MCP server
uv run joinly --port 8000

# Start as client (built-in agent joins a meeting directly)
uv run joinly --client <MeetingURL>
```

## Workspace Structure

This is a **uv workspace** with three packages:

| Package | Directory | PyPI name | Purpose |
|---|---|---|---|
| `joinly` | `joinly/` | `joinly` | Main MCP server + meeting automation |
| `joinly-client` | `client/joinly_client/` | `joinly-client` | Python client library + LLM conversational agent |
| `joinly-common` | `common/joinly_common/` | `joinly-common` | Shared Pydantic types used by both |

Workspace sources are linked locally via `[tool.uv.sources]`. Each sub-package has its own `pyproject.toml` and is versioned/released independently (tags: `v*`, `client-v*`, `common-v*`).

## Architecture

### Core Design Patterns

- **Protocol-based DI**: All major components (`STT`, `TTS`, `VAD`, `MeetingProvider`, controllers) are defined as `Protocol` classes in `joinly/core.py`. `SessionContainer` (`joinly/container.py`) resolves short string tokens (e.g. `"whisper"`) to implementations by convention (`joinly.services.stt.whisper.WhisperSTT`).
- **ContextVar per-session state**: `Settings` and `Usage` live in `ContextVar` so each MCP client connection gets isolated configuration. Settings can be overridden per-connection via the `joinly-settings` HTTP header.
- **EventBus pub/sub**: Two event types (`"segment"`, `"utterance"`) in `joinly/utils/events.py` loosely couple the transcription pipeline to MCP resource subscriptions.
- **MCP as the public API**: All meeting capabilities are MCP tools/resources defined in `joinly/server.py`. The client package connects via `StreamableHttpTransport` or directly to a `FastMCP` instance.

### Audio Pipeline

`AudioReader` → format conversion → `VAD.stream()` → utterance boundary detection → `STT.stream()` → `Transcript`. The `no_speech_event` (asyncio.Event) flows from `TranscriptionController` to `SpeechController` to enable barge-in/interruption.

### Key Modules

- **`joinly/server.py`** — MCP tool/resource definitions, health endpoint, session lifespan
- **`joinly/session.py`** — `MeetingSession` orchestrates provider + controllers
- **`joinly/container.py`** — DI container, builds `MeetingSession` from `Settings`
- **`joinly/settings.py`** — `Settings` (pydantic-settings, `JOINLY_` env prefix)
- **`joinly/controllers/`** — `DefaultTranscriptionController` (VAD→STT pipeline), `DefaultSpeechController` (text chunking→TTS→audio output with interruption support)
- **`joinly/services/`** — STT (`whisper`, `deepgram`, `google`), TTS (`kokoro`, `elevenlabs`, `deepgram`, `google`, `resemble`), VAD (`silero`, `webrtc`, `hybrid`)
- **`joinly/providers/browser/`** — Virtual AV stack: PulseAudio, Xvfb, Playwright Chromium. Platform controllers for Google Meet, Zoom, Teams match URLs via `url_pattern` regex.
- **`client/joinly_client/agent.py`** — `ConversationalToolAgent` built on `pydantic-ai` model_request, manages rolling message history and parallel tool execution
- **`client/joinly_client/prompts.py`** — System prompt templates (dyadic vs multi-party)
- **`common/joinly_common/types.py`** — `TranscriptSegment`, `Transcript`, `VideoSnapshot`, `MeetingParticipant`, `Usage`, etc.

## Code Style & Conventions

- **Ruff**: `select = ["ALL"]` with specific ignores. Google docstring convention. Line length 88.
- **Pyright**: `typeCheckingMode = "standard"` across all packages.
- **Pre-commit hooks**: `ruff` (lint+fix), `ruff-format`, `uv-lock` (keeps lockfile in sync).
- **Tests**: pytest with `asyncio_mode = "auto"`, session-scoped event loop. Tests marked `manual` require a real meeting URL. Integration tests use a mockup browser meeting serving pre-recorded audio.
- **Commit style**: Conventional commits (e.g. `feat(client):`, `fix:`, `refactor:`, `test:`).
