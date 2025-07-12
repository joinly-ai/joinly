from contextvars import ContextVar, Token
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
    language: str = Field(default="en")
    device: str = Field(default="cpu")

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
    """Get the current settings.

    Returns:
        Settings: The current settings.
    """
    return _current_settings.get()


def set_settings(settings: Settings) -> Token[Settings]:
    """Set the current settings.

    Args:
        settings (Settings): The settings to set.

    Returns:
        Token[Settings]: A token that can be used to reset the settings.
    """
    return _current_settings.set(settings)


def reset_settings(token: Token[Settings]) -> None:
    """Reset the current settings to the previous value.

    Args:
        token (Token[Settings]): The token returned by `set_settings`.
    """
    _current_settings.reset(token)
