import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Self

from joinly.core import AudioReader, AudioWriter
from joinly.providers.base import BaseMeetingProvider
from joinly.providers.browser.agents import BrowserAgent, PlaywrightMcpBrowserAgent
from joinly.providers.browser.browser_session import BrowserSession
from joinly.providers.browser.devices.pulse_server import PulseServer
from joinly.providers.browser.devices.virtual_display import VirtualDisplay
from joinly.providers.browser.devices.virtual_microphone import VirtualMicrophone
from joinly.providers.browser.devices.virtual_speaker import VirtualSpeaker
from joinly.providers.browser.platforms import (
    BrowserPlatformController,
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
)
from joinly.settings import get_settings
from joinly.types import MeetingChatHistory

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

PLATFORMS: list[type[BrowserPlatformController]] = [
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
]

AGENTS: dict[str, type[BrowserAgent]] = {
    "playwright-mcp": PlaywrightMcpBrowserAgent,
}


class BrowserMeetingProvider(BaseMeetingProvider):
    """A meeting provider that uses a web browser to join meetings."""

    def __init__(
        self,
        *,
        vnc_server: bool = False,
        vnc_server_port: int = 5900,
        browser_agent: str | None = None,
        browser_agent_args: dict | None = None,
    ) -> None:
        """Initialize the browser meeting provider.

        Args:
            vnc_server (bool): Whether to start a VNC server for the virtual display.
            vnc_server_port (int): The port to use for the VNC server.
            browser_agent (str | None): The agent string to use for the browser
                controller, e.g., "playwright-mcp". If None, no browser agent is used.
            browser_agent_args (dict | None): Additional arguments for the browser
                agent.
        """
        self._env = os.environ.copy()
        pulse_server = PulseServer(env=self._env)
        virtual_display = VirtualDisplay(
            env=self._env, use_vnc_server=vnc_server, vnc_port=vnc_server_port
        )
        self._virtual_speaker = VirtualSpeaker(env=self._env)
        self._virtual_microphone = VirtualMicrophone(env=self._env)
        self._browser_session = BrowserSession(env=self._env)
        self._services = [
            pulse_server,
            virtual_display,
            self._virtual_speaker,
            self._virtual_microphone,
            self._browser_session,
        ]

        self._browser_agent_name = browser_agent
        self._browser_agent_args = browser_agent_args or {}

        self._page: Page | None = None
        self._platform_controller: BrowserPlatformController | None = None
        self._browser_agent: BrowserAgent | None = None
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

    @property
    def audio_reader(self) -> AudioReader:
        """Get the audio reader."""
        return self._virtual_speaker

    @property
    def audio_writer(self) -> AudioWriter:
        """Get the audio writer."""
        return self._virtual_microphone

    async def __aenter__(self) -> Self:
        """Enter the context manager."""
        try:
            for service in self._services:
                await self._stack.enter_async_context(service)
            self._browser_agent = await self._get_browser_agent(
                self._browser_agent_name, self._browser_agent_args
            )
        except Exception:
            await self._stack.aclose()
            raise

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context."""
        try:
            if self._browser_agent is not None:
                await self._browser_agent.close()
                self._browser_agent = None
        finally:
            await self._stack.aclose()

    async def _get_platform_controller(
        self, url: str
    ) -> BrowserPlatformController | None:
        """Get the platform-specific meeting controller based on the URL.

        Args:
            url: The URL of the meeting.

        Returns:
            The platform-specific meeting controller, or None if not found.
        """
        for platform_controller_type in PLATFORMS:
            if platform_controller_type.url_pattern.match(url):
                return platform_controller_type()

        logger.info("No matching platform controller found for URL: %s", url)
        return None

    async def _get_browser_agent(
        self, agent_name: str | None = None, agent_args: dict | None = None
    ) -> BrowserAgent | None:
        """Get the browser agent based on the provided agent name.

        Args:
            agent_name: The name of the browser agent to use. If None, uses the default
                agent.
            agent_args: Additional arguments for the browser agent.

        Returns:
            The browser agent instance, or None if no agent is specified.
        """
        if agent_name is None:
            return None

        if agent_name not in AGENTS:
            logger.error("Unsupported browser agent: %s", agent_name)
            return None

        if self._browser_session.cdp_url is None:
            logger.error("Browser session is not connected. Cannot create agent.")
            return None

        agent = AGENTS[agent_name](**agent_args or {})
        await agent.connect(self._browser_session.cdp_url)
        return agent

    async def _invoke_action(
        self,
        action: str,
        prompt: str | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Invoke an action using the platform controller or browser agent.

        This method is used to perform actions in the browser. First tries to use the
        platform controller if available, otherwise falls back to the browser agent.
        Raise an error if neither is available or failed to perform the action.

        Args:
            action: The action to invoke.
            prompt: The prompt for the action. If None, no browser agent is used.
            *args: Positional arguments for the action.
            **kwargs: Keyword arguments for the action.

        Raises:
            RuntimeError: If neither the platform controller nor the browser agent is
                initialized, or if the action fails.
        """
        if self._page is None or self._page.is_closed():
            msg = "Meeting not joined or already left."
            logger.error(msg)
            raise RuntimeError(msg)

        async with self._lock:
            if self._platform_controller is not None:
                logger.info(
                    "Using platform controller %s to perform action '%s'.",
                    self._platform_controller.__class__.__name__,
                    action,
                )
                try:
                    await getattr(self._platform_controller, action)(
                        self._page, *args, **kwargs
                    )
                except Exception:
                    logger.exception(
                        "Failed to perform action '%s' using platform controller.",
                        action,
                    )
                else:
                    logger.info(
                        "Action '%s' performed successfully using platform controller.",
                        action,
                    )
                    return

            if self._browser_agent is not None and prompt is not None:
                try:
                    response = await self._browser_agent.run(prompt)
                except Exception:
                    logger.exception(
                        "Failed to perform action '%s' using browser agent.", action
                    )
                else:
                    if response.success:
                        logger.info(
                            "Action '%s' performed successfully using "
                            "browser agent: %s",
                            action,
                            response.message,
                        )
                        return
                    logger.error(
                        "Action '%s' failed using browser agent: %s",
                        action,
                        response.message,
                    )

        if self._platform_controller is None and self._browser_agent is None:
            logger.error(
                "Neither platform controller nor browser agent is available. "
                "Cannot perform action: %s.",
                action,
            )

        msg = f"Failed to perform action '{action}'."
        raise RuntimeError(msg)

    async def join(
        self,
        url: str | None = None,
        name: str | None = None,
        passcode: str | None = None,
    ) -> None:
        """Join a meeting.

        Args:
            url: The URL of the meeting to join.
            name: The name of the participant. If None, uses the default name from
                settings.
            passcode: The password or passcode for the meeting (if required).
        """
        if url is None:
            msg = "Meeting URL is required to join a meeting."
            logger.error(msg)
            raise ValueError(msg)

        if self._page is None or self._page.is_closed():
            self._page = await self._browser_session.get_page()
            self._platform_controller = await self._get_platform_controller(url)
        else:
            msg = "Meeting already joined. Leave the meeting before joining a new one."
            logger.error(msg)
            raise RuntimeError(msg)

        if name is None:
            name = get_settings().name

        prompt = f"Join the meeting at {url} as {name}."
        if passcode:
            prompt += f" If asked, use the passcode: {passcode}."
        await self._invoke_action("join", prompt, url=url, name=name, passcode=passcode)

    async def leave(self) -> None:
        """Leave the current meeting."""
        prompt = "Leave the meeting."
        await self._invoke_action("leave", prompt)
        self._platform_controller = None
        if self._page is not None and not self._page.is_closed():
            await self._page.close()
            self._page = None

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message: The message to send.
        """
        prompt = f"Send the following message in the meeting chat: {message}"
        await self._invoke_action("send_chat_message", prompt, message=message)

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat history from the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        prompt = "Get the chat history from the meeting."
        return await self._invoke_action("get_chat_history", prompt, MeetingChatHistory)

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        prompt = "Mute yourself."
        await self._invoke_action("mute", prompt)

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        prompt = "Unmute yourself."
        await self._invoke_action("unmute", prompt)
