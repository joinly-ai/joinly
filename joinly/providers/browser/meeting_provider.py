import os
from contextlib import AsyncExitStack
from typing import Self

from joinly.core import MeetingProvider
from joinly.providers.browser.browser_session import BrowserSession
from joinly.providers.browser.devices.pulse_server import PulseServer
from joinly.providers.browser.devices.virtual_display import VirtualDisplay
from joinly.providers.browser.devices.virtual_microphone import VirtualMicrophone
from joinly.providers.browser.devices.virtual_speaker import VirtualSpeaker
from joinly.providers.browser.meeting_controller import BrowserMeetingController


class BrowserMeetingProvider(MeetingProvider):
    """A meeting provider that uses a web browser to join meetings."""

    def __init__(self) -> None:
        """Initialize the browser meeting provider."""
        env = os.environ.copy()
        pulse_server = PulseServer(env=env)
        virtual_speaker = VirtualSpeaker(env=env)
        virtual_microphone = VirtualMicrophone(env=env)
        virtual_display = VirtualDisplay(env=env)
        browser_session = BrowserSession(env=env)
        self._services = [
            pulse_server,
            virtual_speaker,
            virtual_microphone,
            virtual_display,
            browser_session,
        ]
        self._stack = AsyncExitStack()

        self.meeting_controller = BrowserMeetingController(
            browser_session=browser_session,
            browser_agent=None,
        )
        self.audio_reader = virtual_speaker
        self.audio_writer = virtual_microphone

    async def __aenter__(self) -> Self:
        """Enter the context manager."""
        try:
            for service in self._services:
                await self._stack.enter_async_context(service)
        except Exception:
            await self._stack.aclose()
            raise

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context."""
        await self._stack.aclose()
