import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Self

from playwright.async_api import Page

from joinly.core import AudioReader, AudioWriter
from joinly.providers.base import BaseMeetingProvider
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
from joinly.types import (
    AudioChunk,
    MeetingChatHistory,
    MeetingParticipant,
    ProviderNotSupportedError,
)

logger = logging.getLogger(__name__)

PLATFORMS: list[type[BrowserPlatformController]] = [
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
]


class _SpeakerInjectedAudioReader(AudioReader):
    """Audio reader that injects audio into the virtual speaker."""

    def __init__(
        self, reader: AudioReader, get_reader: Callable[[], str | None]
    ) -> None:
        """Initialize the audio reader with the virtual speaker."""
        self._reader = reader
        self._get_reader = get_reader
        self.audio_format = reader.audio_format

    async def read(self) -> AudioChunk:
        """Read audio data and inject it into the virtual speaker."""
        chunk = await self._reader.read()
        return AudioChunk(
            data=chunk.data,
            time_ns=chunk.time_ns,
            speaker=self._get_reader(),
        )


class BrowserMeetingProvider(BaseMeetingProvider):
    """A meeting provider that uses a web browser to join meetings."""

    def __init__(
        self,
        *,
        vnc_server: bool = False,
        vnc_server_port: int = 5900,
    ) -> None:
        """Initialize the browser meeting provider.

        Args:
            vnc_server (bool): Whether to start a VNC server for the virtual display.
            vnc_server_port (int): The port to use for the VNC server.
        """
        self._env = os.environ.copy()
        pulse_server = PulseServer(env=self._env)
        virtual_display = VirtualDisplay(
            env=self._env, use_vnc_server=vnc_server, vnc_port=vnc_server_port
        )
        virtual_speaker = VirtualSpeaker(env=self._env)
        self._virtual_microphone = VirtualMicrophone(env=self._env)
        self._browser_session = BrowserSession(env=self._env)
        self._services = [
            pulse_server,
            virtual_display,
            virtual_speaker,
            self._virtual_microphone,
            self._browser_session,
        ]

        self._page: Page | None = None
        self._platform_controller: BrowserPlatformController | None = None
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

        self._audio_reader = _SpeakerInjectedAudioReader(
            virtual_speaker,
            lambda: (
                self._platform_controller.active_speaker
                if self._platform_controller
                else None
            ),
        )

    @property
    def audio_reader(self) -> AudioReader:
        """Get the audio reader."""
        return self._audio_reader

    @property
    def audio_writer(self) -> AudioWriter:
        """Get the audio writer."""
        return self._virtual_microphone

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
        try:
            if self._page is not None and not self._page.is_closed():
                await self.leave()
        finally:
            await self._stack.aclose()

    @asynccontextmanager
    async def _action_guard(
        self, action: str
    ) -> AsyncIterator[tuple[Page, BrowserPlatformController]]:
        """Context manager to guard actions with a lock and error handling.

        Args:
            action: The action being guarded, for logging (e.g., "join", "leave", etc.).

        Yields:
            A tuple containing the current Page and the platform-specific controller.
        """
        if (
            self._page is None
            or self._page.is_closed()
            or self._platform_controller is None
        ):
            msg = f"Failed to perform '{action}'. Currently not in a meeting."
            logger.error(msg)
            raise RuntimeError(msg)

        async with self._lock:
            try:
                yield self._page, self._platform_controller
            except Exception as e:
                msg = f"Failed to perform '{action}'."
                logger.exception(msg)
                if isinstance(e, (ProviderNotSupportedError, ValueError)):
                    raise
                raise RuntimeError(msg) from None
            else:
                logger.info("Successfully performed '%s'.", action)

    async def _get_platform_controller(self, url: str) -> BrowserPlatformController:
        """Get the platform-specific meeting controller based on the URL.

        Args:
            url: The URL of the meeting.

        Returns:
            The platform-specific meeting controller.

        Raises:
            RuntimeError: If no matching platform controller is found for the URL.
        """
        for platform_controller_type in PLATFORMS:
            if platform_controller_type.url_pattern.match(url):
                return platform_controller_type()

        msg = (
            f"No supported platform found for URL: {url}. "
            "Supported platforms: "
            f"{', '.join(pc.__name__ for pc in PLATFORMS)}."
        )
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
        if not url:
            msg = "Meeting URL is required to join a meeting."
            logger.error(msg)
            raise ValueError(msg)

        if self._page is not None and not self._page.is_closed():
            msg = "Meeting already joined. Leave the meeting before joining a new one."
            logger.error(msg)
            raise RuntimeError(msg)

        self._page = await self._browser_session.get_page()
        try:
            self._platform_controller = await self._get_platform_controller(url)
        except RuntimeError:
            await self._page.close()
            self._page = None
            raise

        if name is None:
            name = get_settings().name

        async with self._action_guard("join") as (page, controller):
            try:
                await controller.join(page, url, name=name, passcode=passcode)
            except Exception:
                await self._page.close()
                self._page = None
                self._platform_controller = None
                raise

    async def leave(self) -> None:
        """Leave the current meeting."""
        async with self._action_guard("leave") as (page, controller):
            try:
                await controller.leave(page)
            except RuntimeError:
                logger.warning(
                    "Failed to leave the meeting, forcing page close.", exc_info=True
                )
            finally:
                self._platform_controller = None
                if self._page is not None and not self._page.is_closed():
                    await self._page.close()
                self._page = None

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message: The message to send.
        """
        async with self._action_guard("send_chat_message") as (page, controller):
            await controller.send_chat_message(page, message)

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat history from the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        async with self._action_guard("get_chat_history") as (page, controller):
            return await controller.get_chat_history(page)

    async def get_participants(self) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        async with self._action_guard("get_participants") as (page, controller):
            return await controller.get_participants(page)

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        async with self._action_guard("mute") as (page, controller):
            await controller.mute(page)

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        async with self._action_guard("unmute") as (page, controller):
            await controller.unmute(page)
