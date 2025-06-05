import os
from contextlib import AsyncExitStack
from typing import Self

from joinly.core import MeetingProvider
from joinly.providers.browser.browser_agent import BrowserAgent
from joinly.providers.browser.browser_session import BrowserSession
from joinly.providers.browser.devices.pulse_server import PulseServer
from joinly.providers.browser.devices.virtual_display import VirtualDisplay
from joinly.providers.browser.devices.virtual_microphone import VirtualMicrophone
from joinly.providers.browser.devices.virtual_speaker import VirtualSpeaker
from joinly.providers.browser.meeting_controller import BrowserMeetingController


class BrowserMeetingProvider(MeetingProvider):
    """A meeting provider that uses a web browser to join meetings."""

    def __init__(
        self,
        *,
        vnc_server: bool = False,
        browser_agent: bool = False,
        model_name: str = "gpt-4o",
        model_provider: str | None = None,
    ) -> None:
        """Initialize the browser meeting provider.

        Args:
            vnc_server (bool): Whether to start a VNC server for the virtual display.
            browser_agent (bool): Whether to use a browser agent for the meeting
                controller.
            model_name (str): The name of the model to use for the browser agent.
            model_provider (str | None): The provider of the model, otherwise it is
                automatically determined.
        """
        env = os.environ.copy()
        pulse_server = PulseServer(env=env)
        virtual_speaker = VirtualSpeaker(env=env)
        virtual_microphone = VirtualMicrophone(env=env)
        virtual_display = VirtualDisplay(env=env, use_vnc_server=vnc_server)
        browser_session = BrowserSession(env=env)
        self._services = [
            pulse_server,
            virtual_speaker,
            virtual_microphone,
            virtual_display,
            browser_session,
        ]

        browser_agent_service = (
            BrowserAgent(env=env, model_name=model_name, model_provider=model_provider)
            if browser_agent
            else None
        )
        if browser_agent_service:
            self._services.append(browser_agent_service)

        self._stack = AsyncExitStack()

        self.meeting_controller = BrowserMeetingController(
            browser_session=browser_session,
            browser_agent=browser_agent_service,
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
