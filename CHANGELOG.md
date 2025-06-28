
# Changelog

## v0.3.0 - 2025-06-25

### Added

- add `get_transcript` tool for fetching the meeting transcript with timestamp filters (#21)
- real-time speaker attribution for the transcript, in core app and all platforms (#27)
- new tool `get_participants` to retrieve the current meeting participants with available meta-data (e.g., host, muted/unmuted) (#28)

### Improvements

- better internal meeting time measurement with more accurate start and end times (#18)
- shared meeting clock object for synchronized internal time handling (#22)
- add speech through `speak_text` tool to the meeting transcript (not included in `transcript://live` resource, but in `get_transcript`) (#23, #24)
- length-based TTS pre-chunking for better performance with long texts (#25)
- more compact transcripts by merging nearby segments of the same speaker for better LLM handling (#26)
- browser action improvements, for more robustness and some fixes (#30, #33, #34)
- teams live platform support using the existing teams platform actions (#31)

### Fixed

- fix leftover audio in deepgram TTS after interruptions (#19)
- fix rare case where a update notification without new transcript segments crashes the client (#20)
- allow `join_meeting` after failed join attempts, which previously caused issues (#32)

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
