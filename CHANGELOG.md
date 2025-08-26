
# Changelog

## v0.5.0 - 2025-08-26

### Added

- new tool to access screenshares and video snapshots inside the meeting for vision-enabled models (#128, #131)
- client changes to allow multimodal tool results (see below)

### Improvements

- reduce deepgram transcription latency (#132)
- add speech event delay to avoid unwanted interruptions (#133)
- improve hybrid VAD (#134)

### joinly-client (v0.1.15)

- new and more detailed system prompt and instructions (#116, #135)
- support for google as LLM provider (#118)
- `include` option for tool loading (#120)
- custom post tool-call callbacks (#123, #125)
- improved tool result parsing including capabilities for multimodal results (#126)
- message history filtering for large tool results (#127)
- update README example (#130)

## v0.4.2 - 2025-08-16

### Improvements

- reduce audio format conversions in pipeline (#113)
- hybrid VAD implementation between webrtc and silero (#114)

### Fixed

- unmute automatically on start (#112)
- round start/end times in transcript for consistency (#109)
- keep webrtc package in lite build (#111)

### joiny-client (v0.1.8)

- add direct `list_tools` and `session` access to joinly client (#104)
- split system prompt and custom instructions (#105)
- use one mcp cient per server, instead of stateless proxy (#106)
- add message history limit to reduce token usage (#107)
- change date formatting to ISO (#108)

### Others

- refactor to use type keyword (#103)

## v0.4.1 - 2025-08-08

### Improvements

- upgrade kokoro-onnx to 0.4.9 (#88)
- add model improvemet program opt-out for deepgram (#90, #97)
- default to `--client` if meeting url is given (#93)
- set default logging to info level for cli (#96)
- remove suffix for platform error messages (#98)

### Fixed

- fix missing links in google meet chat (#86)
- get headers to load settings for fastmcp>=2.11 (#89)

### joinly-client (v0.1.7)

- fix openai issues with openai>=1.99.2 (#91)
- fix gpt-5 usage by disabling sampling settings (#94)
- wrap tool calls for direct usage with client (#99)
- add debug logging for agent (#100)
- improve agent for gpt-5 (#101)

### Others

- update environment names in release workflow (#87)

## v0.4.0 - 2025-08-04

### New: joinly-client (v0.1.5)

- complete rewrite of all client functionality, now using a single `joinly-client` package (#84)
- support for usage in code and via cli

### Added

- LLM token usage tracking for a session (#75)
- STT/TTS API usage tracking, characters or audio minutes (#80)
- setting session configurations via `joinly-client`

### Improvements

- event bus for transcript updates (#65)
- live segment transcription at segment level (#63)
- improve lite image by removing unnecessary dependencies (#79)
- unify logging of live segments (#82)
- `--env-file` cli option to specify a custom environment file (#74)

### Fixed

- set explicit logging level only for own logger (#78)
- correctly fail on unsupported meeting platforms (#77)
- fix fatal server crash on session errors (#64)

### Others

- add docker-outside-of-docker to devcontainer (#76)
- improve release workflow (#70, #73)
- cleanup repository root files (#72)

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
