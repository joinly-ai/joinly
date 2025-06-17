
# Changelog

## v0.2.0 - 2025-06-17

### Added

- add CUDA support for Whisper models and respective Docker build, which can significantly speed up transcription and allows usage of models like `distil-large-v3` (default for `cuda`) (#10)
- add MCP tool `get_chat_history` for accessing the current meeting chat (#13)

### Improvements

- change default Whisper model for CPU to `base.en` for better quality while stying near real-time (#11)
- change MCP tool response on detected interruptions while `speak_text` to a text response instead of an error (#12)

## v0.1.1 - 2025-06-15

### Fixed

- fix stuck whisper initialization (#4)
- fix no-speech event set on start, which caused a `speak_text` before any audio to be stuck (#7)
- fix and add missing `mute`/`unmute` actions (#5)
- fix action errors in google meet with multiple participants (#6)

## v0.1.0 - 2025-06-14

Initial release.
