from contextvars import ContextVar
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

    name: str = Field(default="joinly")

    meeting_provider: str | type[MeetingProvider] = Field(default="browser")
    vad: str | type[VAD] = Field(default="silero")
    stt: str | type[STT] = Field(default="whisper")
    tts: str | type[TTS] = Field(default="kokoro")
    transcription_controller: str | type[TranscriptionController] = Field(
        default="default"
    )
    speech_controller: str | type[SpeechController] = Field(default="default")

    meeting_provider_args: dict[str, Any] = Field(default_factory=dict)
    vad_args: dict[str, Any] = Field(default_factory=dict)
    stt_args: dict[str, Any] = Field(default_factory=dict)
    tts_args: dict[str, Any] = Field(default_factory=dict)
    transcription_controller_args: dict[str, Any] = Field(default_factory=dict)
    speech_controller_args: dict[str, Any] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="JOINLY_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )


_current_settings: ContextVar[Settings] = ContextVar("settings", default=Settings())  # noqa: B039


def get_settings() -> Settings:
    """Get the current settings."""
    return _current_settings.get()


def set_settings(settings: Settings) -> None:
    """Set the current settings."""
    _current_settings.set(settings)
