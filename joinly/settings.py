from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from joinly.core import (
    STT,
    TTS,
    VAD,
    MeetingProvider,
    SpeechController,
    TranscriptionController,
)


class Settings(BaseSettings):
    """Settings for the meeting agent."""

    meeting_provider: str | type[MeetingProvider] = Field(default="browser")
    meeting_provider_args: dict[str, Any] = Field(default_factory=dict)
    vad: str | type[VAD] = Field(default="silero")
    vad_args: dict[str, Any] = Field(default_factory=dict)
    stt: str | type[STT] = Field(default="whisper")
    stt_args: dict[str, Any] = Field(default_factory=dict)
    tts: str | type[TTS] = Field(default="kokoro")
    tts_args: dict[str, Any] = Field(default_factory=dict)
    transcription_controller: str | type[TranscriptionController] = Field(
        default="joinly.controllers.DefaultTranscriptionController"
    )
    transcription_controller_args: dict[str, Any] = Field(default_factory=dict)
    speech_controller: str | type[SpeechController] = Field(
        default="joinly.controllers.DefaultSpeechController"
    )
    speech_controller_args: dict[str, Any] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="JOINLY_",
        extra="forbid",
    )


DEFAULT_SETTINGS = Settings()
