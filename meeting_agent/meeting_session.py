import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Self

from meeting_agent.browser.browser_agent import BrowserAgent
from meeting_agent.browser.browser_meeting_controller import BrowserMeetingController
from meeting_agent.browser.browser_session import BrowserSession
from meeting_agent.devices.virtual_display import VirtualDisplay
from meeting_agent.devices.virtual_microphone import VirtualMicrophone
from meeting_agent.devices.virtual_speaker import VirtualSpeaker
from meeting_agent.speech.audio_transcriber import AudioTranscriber
from meeting_agent.speech.speech_flow_controller import SpeechFlowController
from meeting_agent.speech.tts_service import TTSService
from meeting_agent.speech.vad_service import VADService

logger = logging.getLogger(__name__)

"""
TODO:
- fix need to start mic before sink?, maybe set pactl auto select off?
- fix audio microphone buffer issues (constant silence stream?)
- fix closure on ctrl-c
- optional dependencies, lazy import (e.g., for langchain, providers, etc.)
- improve transcription: stream input directly and use context
- improve latency of entire system
- subclass to allow different providers (transcription, tts, vad)
- add transcription class, maybe with vad timestamps? maybe already
    with multiple speaker support?
- add playbook executor and playbooks for gmeet, teams, zoom
- maybe replace playwright-mcp with agent working directly on playbook syntax?
    -> allows it to pick up history better and produce playbook from actions
- add meeting chat functionality + chat events
- participant detection, joining events etc.
- add status cam
- add screen sharing
- speaker diarization
"""


class MeetingSession:
    """A class to represent a meeting session."""

    def __init__(
        self,
        *,
        headless: bool = True,
        use_browser_agent: bool = False,
        browser_agent_port: int | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize a meeting session.

        Args:
            headless: Whether to run in headless mode (default: True).
            use_browser_agent: Whether to use a browser agent (default: False).
            browser_agent_port: The port for the browser agent (default: None).
            env: Environment variables to set for the session (default: None).
        """
        self.headless = headless
        self.use_browser_agent = use_browser_agent
        self.browser_agent_port = browser_agent_port
        self._session_env = env or os.environ.copy()
        self._exit_stack: AsyncExitStack = AsyncExitStack()

        self._virtual_speaker = VirtualSpeaker(env=self._session_env)
        self._vad_service = VADService(self._virtual_speaker)
        self._audio_transcriber = AudioTranscriber(self._vad_service)
        self._virtual_microphone = VirtualMicrophone(env=self._session_env)
        self._tts_service = TTSService()
        self._speech_controller = SpeechFlowController(
            mic=self._virtual_microphone,
            tts=self._tts_service,
            no_speech_event=self._vad_service.no_speech_event,
        )
        self._virtual_display = (
            VirtualDisplay(env=self._session_env) if self.headless else None
        )
        self._browser_session = BrowserSession(env=self._session_env)
        self._browser_agent = (
            BrowserAgent(env=self._session_env, mcp_port=self.browser_agent_port)
            if self.use_browser_agent
            else None
        )
        self._meeting_controller = BrowserMeetingController(
            browser_session=self._browser_session,
            browser_agent=self._browser_agent,
        )

    async def __aenter__(self) -> Self:
        """Enter the meeting session context."""
        for svc in [
            self._virtual_microphone,
            self._virtual_speaker,
            self._vad_service,
            self._audio_transcriber,
            self._tts_service,
            self._speech_controller,
            self._virtual_display,
            self._browser_session,
            self._browser_agent,
            self._meeting_controller,
        ]:
            if svc is not None:
                await self._exit_stack.enter_async_context(svc)

        # asyncio.get_running_loop().call_later(
        #    30, lambda: asyncio.create_task(self.send_chat_message("Hello!")))

        # asyncio.get_running_loop().call_later(
        #    40, lambda: asyncio.create_task(self.send_chat_message("Hello, again.")))

        # asyncio.get_running_loop().call_later(
        #    10,
        #    lambda: asyncio.create_task(speech_controller.speak_text("Hello, how are you? I am testing this meeting agent. Feel free to interrupt me. I will keep on talking for some time now. Just to give you some time to do some testing, isn't that nice? But now you really need to finish. Your last seconds are ticking.")))  # noqa: E501

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the meeting session context."""
        await self._exit_stack.aclose()

    @property
    def transcript(self) -> str:
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

    async def join_meeting(self, meeting_url: str, participant_name: str) -> None:
        """Join a meeting using the provided URL.

        Args:
            meeting_url (str): The URL of the meeting to join.
            participant_name (str): The name of the participant.
        """
        await self._meeting_controller.join(meeting_url, participant_name)

    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
        await self._meeting_controller.leave()

    async def speak_text(self, text: str) -> None:
        """Speak the provided text using TTS.

        Args:
            text (str): The text to be spoken.
        """
        await self._speech_controller.speak_text(text)

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message (str): The message to be sent.
        """
        await self._meeting_controller.send_chat_message(message)
