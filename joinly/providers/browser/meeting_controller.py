import asyncio
import logging
from typing import TYPE_CHECKING

from joinly.providers.base import BaseMeetingController
from joinly.providers.browser.browser_agent import BrowserAgent
from joinly.providers.browser.browser_session import BrowserSession
from joinly.providers.browser.platforms.base import BrowserPlatformController
from joinly.providers.browser.platforms.google_meet import (
    GoogleMeetBrowserPlatformController,
)
from joinly.providers.browser.platforms.teams import TeamsBrowserPlatformController
from joinly.providers.browser.platforms.zoom import ZoomBrowserPlatformController
from joinly.settings import get_settings

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

PLATFORMS: list[type[BrowserPlatformController]] = [
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
]


class BrowserMeetingController(BaseMeetingController):
    """A class to represent a browser meeting controller."""

    def __init__(
        self,
        browser_session: BrowserSession,
        browser_agent: BrowserAgent | None = None,
    ) -> None:
        """Initialize the browser meeting controller.

        Args:
            browser_session: The browser session
            browser_agent: The browser agent
        """
        self._browser_session: BrowserSession = browser_session
        self._browser_agent: BrowserAgent | None = browser_agent
        self._page: Page | None = None
        self._platform_controller: BrowserPlatformController | None = None
        self._lock = asyncio.Lock()

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

    async def _invoke_action(
        self,
        action: str,
        prompt: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Invoke an action using the platform controller or browser agent.

        This method is used to perform actions in the browser. First tries to use the
        platform controller if available, otherwise falls back to the browser agent.
        Raise an error if neither is available or failed to perform the action.

        Args:
            action: The action to invoke.
            prompt: The prompt for the action.
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
                    logger.info("Action '%s' performed successfully.", action)
                    return

            if self._browser_agent is not None:
                try:
                    await self._browser_agent.run(self._page, prompt)
                except Exception:
                    logger.exception(
                        "Failed to perform action '%s' using browser agent.", action
                    )
                else:
                    logger.info("Action '%s' performed successfully.", action)
                    return

        if self._platform_controller is None and self._browser_agent is None:
            logger.error(
                "Neither platform controller nor browser agent is available. "
                "Cannot perform action: %s.",
                action,
            )

        msg = f"Failed to perform action '{action}'."
        raise RuntimeError(msg)

    async def join(self, url: str | None = None, name: str | None = None) -> None:
        """Join a meeting.

        Args:
            url: The URL of the meeting to join.
            name: The name of the participant. If None, uses the default name from
                settings.
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
        await self._invoke_action("join", prompt, url=url, name=name)

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
