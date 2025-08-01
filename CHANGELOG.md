
# Changelog

## v0.3.3 - 2025-07-31

### Improvements

- add health check endpoint to MCP server (#66)
- improve default voice selection for ElevenLabs TTS (#68)
- adapt logging levels for less noise in the logs (#69)
- update release workflow pipeline and update cuda image tag (#70)
- add lite image variant without local model weights (#71)

### Fixed

- mark zoom waiting room as a successful join to fix potential timeouts (#67)

## v0.3.2 - 2025-07-14

### Improvements

- allow setting session-specific settings from the client (e.g., which STT/TTS), this will be further improved in the next release with client improvements (#57)
- remove redundant leave on exit (#59, #62)
- remove browser agent (#56)

### Fixed

- zoom additional passcode handling (#61)
- deepgram misses first word (#60)
- resource subscribe flow (#58)
- enforce maximum message length (#55)
- make opening menu panels more robust and remove deprecated timeout (#54)
- change last segment timing to start in example (#53)
- simplify chat timestamps (#52)
- await meeting provider join before initializing transcript (#51)

## v0.3.1 - 2025-07-02

### Added

- ElevenLabs TTS support via `--tts elevenlabs` (#47)
- new setting `--lang <language_code>` to set the language for TTS and STT (depends on support of services) (#46)

### Improvements

- streamline speech controller implementation (#41)
- improve error handling and interrupts in speech controller (#41)
- force leave by closing page on failed leave action (#35)
- auto leave on session tear down (#38)
- set docker logging to plain format (#39)

### Fixed

- handle exceptions during agent invocation (#45)
- log speech-to-text exceptions (#44)
- ensure aligned segment timestamps in transcript (#40)
- fail on failed deepgram connection (#37)
- propagate ProviderNotSupportedError (#36)
- stop adding a segment for an interrupted speech without any spoken text (#48)
- fix no new segment error due to compact transcript after interruption (#49)

## v0.3.0 - 2025-06-28

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
