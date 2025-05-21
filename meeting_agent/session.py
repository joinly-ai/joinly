import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Self

from meeting_agent.browser.browser_agent import BrowserAgent
from meeting_agent.browser.browser_meeting_controller import BrowserMeetingController
from meeting_agent.browser.browser_session import BrowserSession
from meeting_agent.devices.pulse_server import PulseServer
from meeting_agent.devices.virtual_display import VirtualDisplay
from meeting_agent.devices.virtual_microphone import VirtualMicrophone
from meeting_agent.devices.virtual_speaker import VirtualSpeaker
from meeting_agent.speech.audio_transcriber import AudioTranscriber
from meeting_agent.speech.speech_controller import SpeechController
from meeting_agent.speech.tts_service import TTSService
from meeting_agent.speech.vad_service import VADService
from meeting_agent.types import Transcript

logger = logging.getLogger(__name__)

"""
TODO:
- interrupt vs interruptable, send good message back
- settings
- event bus or similar?
- add additional streaming endpoint for events? does that work with mcp?
- optional dependencies, lazy import (e.g., for langchain, providers, etc.)
- subclass to allow different providers (transcription, tts, vad)
- improve transcription: stream input directly and use context
- improve latency of entire system
- add transcription class, maybe with vad timestamps? maybe already
    with multiple speaker support?
- (?) add playbook executor and playbooks for gmeet, teams, zoom
- (?) maybe replace playwright-mcp with agent working directly on playbook syntax?
    -> allows it to pick up history better and produce playbook from actions
- add meeting chat functionality + chat events
- participant detection, joining events etc.
- add status cam
- add screen sharing
- speaker diarization
"""


@dataclass(frozen=True)
class MeetingSessionConfig:
    """Configuration for the meeting session.

    Attributes:
        meeting_url: The URL of the meeting to join.
        participant_name: The name of the participant.
        headless: Whether to run in headless mode
        vnc_server: Whether to use a VNC server.
        vnc_server_port: The port for the VNC server.
        pulse_server: Whether to use a dedicated PulseAudio server.
        browser_agent: Whether to use a browser agent.
        browser_agent_port: The port for the browser agent.
        env: Environment variables to set for the session.
    """

    meeting_url: str | None = None
    participant_name: str | None = None
    headless: bool = True
    vnc_server: bool = False
    vnc_server_port: int | None = None
    pulse_server: bool = True
    browser_agent: bool = False
    browser_agent_port: int | None = None
    env: dict[str, str] | None = None


DEFAULT_CONFIG = MeetingSessionConfig()


class MeetingSession:
    """A class to represent a meeting session."""

    def __init__(self, config: MeetingSessionConfig = DEFAULT_CONFIG) -> None:
        """Initialize a meeting session."""
        self._meeting_url = config.meeting_url
        self._participant_name = config.participant_name or "joinly"
        self._session_env = os.environ.copy() | (config.env or {})
        self._exit_stack: AsyncExitStack = AsyncExitStack()

        self._pulse_server = (
            PulseServer(env=self._session_env) if config.pulse_server else None
        )
        self._virtual_speaker = VirtualSpeaker(env=self._session_env)
        self._vad_service = VADService(self._virtual_speaker)
        self._audio_transcriber = AudioTranscriber(self._vad_service)
        self._virtual_microphone = VirtualMicrophone(env=self._session_env)
        self._tts_service = TTSService()
        self._speech_controller = SpeechController(
            mic=self._virtual_microphone,
            tts=self._tts_service,
            no_speech_event=self._vad_service.no_speech_event,
        )
        self._virtual_display = (
            VirtualDisplay(
                env=self._session_env,
                use_vnc_server=config.vnc_server,
                vnc_port=config.vnc_server_port,
            )
            if config.headless
            else None
        )
        self._browser_session = BrowserSession(env=self._session_env)
        self._browser_agent = (
            BrowserAgent(env=self._session_env, mcp_port=config.browser_agent_port)
            if config.browser_agent
            else None
        )
        self._meeting_controller = BrowserMeetingController(
            browser_session=self._browser_session,
            browser_agent=self._browser_agent,
        )

    async def __aenter__(self) -> Self:
        """Enter the meeting session context."""
        try:
            for svc in [
                self._pulse_server,
                self._virtual_speaker,
                self._vad_service,
                self._audio_transcriber,
                self._virtual_microphone,
                self._tts_service,
                self._speech_controller,
                self._virtual_display,
                self._browser_session,
                self._browser_agent,
                self._meeting_controller,
            ]:
                if svc is not None:
                    await self._exit_stack.enter_async_context(svc)

            if self._meeting_url is not None:
                await self.join_meeting(
                    meeting_url=self._meeting_url,
                    participant_name=self._participant_name,
                )
        except Exception:
            await self._exit_stack.aclose()
            raise

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the meeting session context."""
        if self._meeting_url is not None:
            with contextlib.suppress(Exception):
                await self.leave_meeting()
        await self._exit_stack.aclose()

    @property
    def transcript(self) -> Transcript:
        """Return the current transcript of the meeting."""
        return self._audio_transcriber.transcript

    def add_transcription_listener(
        self, listener: Callable[[str, str], Awaitable[None]]
    ) -> Callable[[], None]:
        """Add a listener for transcription events.

        Args:
            listener: A callable that takes an event (chunk or segment)
                and text as arguments.

        Returns:
            A callable to remove the listener.
        """
        return self._audio_transcriber.add_listener(listener)

    async def join_meeting(
        self, meeting_url: str, participant_name: str | None
    ) -> None:
        """Join a meeting using the provided URL.

        Args:
            meeting_url (str): The URL of the meeting to join.
            participant_name (str | None): The name of the participant.
                Defaults to the sessions participant name.
        """
        name = (
            participant_name if participant_name is not None else self._participant_name
        )
        await self._meeting_controller.join(meeting_url, name)

    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
        await self._meeting_controller.leave()

    async def speak_text(
        self,
        text: str,
        *,
        wait: bool = True,
        interrupt: bool = False,
        interruptable: bool = True,
    ) -> None:
        """Speak the provided text using TTS.

        Args:
            text (str): The text to be spoken.
            wait (bool): Whether to block until the speech is finished (default: True).
            interrupt (bool): Whether to interrupt detected speech (default: False).
            interruptable (bool): Whether this speech can be interrupted
                (default: True).
        """
        await self._speech_controller.speak_text(
            text, wait=wait, interrupt=interrupt, interruptable=interruptable
        )

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message (str): The message to be sent.
        """
        await self._meeting_controller.send_chat_message(message)

    async def start_screen_sharing(self) -> None:
        """Start screen sharing in the meeting."""
        await self._meeting_controller.start_screen_sharing()
