import asyncio
import logging
from typing import Self

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from meeting_agent.browser.browser_agent import BrowserAgent
from meeting_agent.browser.browser_session import BrowserSession

logger = logging.getLogger(__name__)


class BrowserMeetingController:
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

    async def __aenter__(self) -> Self:
        """Start the meeting session."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave the meeting session."""
        self._page = None

    async def join(self, meeting_url: str, participant_name: str) -> None:
        """Join the meeting by clicking the join button."""
        if self._page is not None:
            msg = "Meeting already joined, leave before joining again."
            logger.error(msg)
            raise RuntimeError(msg)

        self._page = await self._browser_session.get_page()

        logger.info("Joining the meeting: %s as %s", meeting_url, participant_name)

        try:
            await self._page.goto(meeting_url, wait_until="load", timeout=20000)
        except PlaywrightError as e:
            msg = "Failed to navigate to the meeting URL"
            logger.exception(msg)
            raise RuntimeError(msg) from e

        if self._browser_agent is not None:
            await asyncio.sleep(5)
            await self._browser_agent.run(
                f"Join the meeting which is opened with the name {participant_name}."
            )
            return

        try:
            # wait for an input field where placeholder contains "name"
            await self._page.wait_for_selector(
                "input[placeholder*='name' i]", timeout=20000
            )
            await self._page.fill("input[placeholder*='name' i]", participant_name)

            # click the join button by finding a button containing "join"
            await self._page.wait_for_selector(
                "button:has-text('join')", timeout=1000, state="visible"
            )
            await self._page.click("button:has-text('join')")
        except PlaywrightError as e:
            msg = "Failed to join the meeting"
            logger.exception(msg)
            raise RuntimeError(msg) from e

        logger.info(
            "Joined the meeting: %s as %s",
            meeting_url,
            participant_name,
        )

    async def leave(self) -> None:
        """Leave the meeting."""
        if self._page is None or self._page.is_closed():
            msg = "Meeting not joined or already left."
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Leaving the meeting.")

        if self._browser_agent is not None:
            await self._browser_agent.run(
                "Leave the meeting you are currently in but leave the page open."
            )
            return

        try:
            await self._page.click("button:has-text('leave')", timeout=1000)
        except PlaywrightError as e:
            msg = "Failed to leave the meeting"
            logger.exception(msg)
            raise RuntimeError(msg) from e
        else:
            logger.info("Left the meeting.")

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message: The message to send.
        """
        if self._page is None or self._page.is_closed():
            msg = "Meeting not joined or already left."
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Sending chat message: %s", message)

        try:
            input_field = await self._page.query_selector("div[contenteditable='true']")

            if input_field is None:
                await self._page.wait_for_selector(
                    "button:has-text('chat')", timeout=2000
                )
                await self._page.click("button:has-text('chat')")
                await self._page.wait_for_timeout(2000)

            await self._page.wait_for_selector(
                "div[contenteditable='true']", timeout=2000
            )
            await self._page.fill("div[contenteditable='true']", message)
            await self._page.keyboard.press("Enter")
        except PlaywrightError as e:
            msg = "Failed to send chat message"
            logger.exception(msg)
            raise RuntimeError(msg) from e
        else:
            logger.info("Chat message sent.")

    async def start_screen_sharing(self) -> None:
        """Start screen sharing in the meeting."""
        if self._page is None or self._page.is_closed():
            msg = "Meeting not joined or already left."
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Starting screen sharing.")

        try:
            await self._page.click("button:has-text('Share')", timeout=1000)
            await self._page.click("button:has-text('Screen')", timeout=1000)
        except PlaywrightError:
            logger.exception("Failed to start screen sharing")
        else:
            logger.info("Screen sharing started.")
