import importlib
import re
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
)
from typing import Any, TypeVar

from joinly.session import MeetingSession
from joinly.settings import Settings, get_settings

T = TypeVar("T")


def _resolve(spec: str | type[T], *, base: str, suffix: str) -> type[T]:
    """Turn direct type, dotted path, or short token into a class object.

    Discovers paths by convention:
    - if `spec` is a type, return it directly.
    - if `spec` is a dotted path, import the module and return the class.
    - if `spec` is a short token, map to
        `<base>.<token_lowercase>.<token_camelcase><suffix>`.
    """
    if isinstance(spec, type):
        return spec

    if "." in spec:
        # fully qualified
        mod, _, cls = spec.rpartition(".")
    else:
        # short token
        if spec.lower().endswith(suffix.lower()):
            base_name = spec[: -len(suffix)]
        else:
            base_name = "".join(p.capitalize() for p in re.split(r"[_\- ]+", spec))
        mod = f"{base}.{base_name.lower()}"
        cls = base_name + suffix

    try:
        module = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name == mod:
            msg = f"Module '{mod}' not found."
        else:
            msg = (
                f"Missing dependency '{e.name}' when importing module '{mod}'. "
                "You may need to install optional dependencies for this component."
            )
        raise ImportError(msg) from e

    try:
        return getattr(module, cls)
    except AttributeError as e:
        msg = f"Cannot resolve class '{cls}' in module '{mod}'"
        raise ImportError(msg) from e


class SessionContainer:
    """Container for the Meeting Session."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the session container."""
        self._settings = settings or get_settings()
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> MeetingSession:
        """Enter the context manager and create a meeting session."""
        try:
            vad = await self._build(
                self._settings.vad,
                "joinly.services.vad",
                "VAD",
                self._settings.vad_args,
            )
            stt_extra_args = (
                {
                    "finalize_silence": max(
                        0.1,
                        float(
                            self._settings.transcription_controller_args.get(
                                "utterance_tail_seconds",
                                0.6,
                            )
                        )
                        - 0.225,
                    )
                }
                if _resolve(
                    self._settings.stt,
                    base="joinly.services.stt",
                    suffix="STT",
                ).__name__
                == "DeepgramSTT"
                else {}
            )
            stt = await self._build(
                self._settings.stt,
                "joinly.services.stt",
                "STT",
                stt_extra_args | self._settings.stt_args,
            )
            tts = await self._build(
                self._settings.tts,
                "joinly.services.tts",
                "TTS",
                self._settings.tts_args,
            )

            provider_extra_args = (
                {
                    "reader_byte_depth": vad.audio_format.byte_depth,
                    "writer_byte_depth": tts.audio_format.byte_depth,
                }
                if _resolve(
                    self._settings.meeting_provider,
                    base="joinly.providers",
                    suffix="MeetingProvider",
                ).__name__
                == "BrowserMeetingProvider"
                else {}
            )
            meeting_provider = await self._build(
                self._settings.meeting_provider,
                "joinly.providers",
                "MeetingProvider",
                provider_extra_args | self._settings.meeting_provider_args,
            )

            transcription_controller = await self._build(
                self._settings.transcription_controller,
                "joinly.controllers.transcription",
                "TranscriptionController",
                self._settings.transcription_controller_args,
            )
            speech_controller = await self._build(
                self._settings.speech_controller,
                "joinly.controllers.speech",
                "SpeechController",
                self._settings.speech_controller_args,
            )

            transcription_controller.reader = meeting_provider.audio_reader
            transcription_controller.vad = vad
            transcription_controller.stt = stt

            speech_controller.writer = meeting_provider.audio_writer
            speech_controller.tts = tts
            speech_controller.no_speech_event = transcription_controller.no_speech_event

            meeting_session = MeetingSession(
                meeting_provider=meeting_provider,
                transcription_controller=transcription_controller,
                speech_controller=speech_controller,
                video_reader=meeting_provider.video_reader,
            )
        except:
            await self._stack.aclose()
            raise

        return meeting_session

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context and clean up resources."""
        await self._stack.aclose()

    async def _build(
        self, spec: str | type[T], base: str, suffix: str, args: dict[str, Any]
    ) -> T:
        """Build an instance of the specified class."""
        cls = _resolve(spec, base=base, suffix=suffix)
        instance = cls(**args)
        if isinstance(instance, AbstractAsyncContextManager):
            return await self._stack.enter_async_context(instance)
        if isinstance(instance, AbstractContextManager):
            return self._stack.enter_context(instance)
        return instance
