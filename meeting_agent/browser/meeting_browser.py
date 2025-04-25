import contextlib
import logging
import os
from typing import Self

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)


class MeetingBrowser:
    """A class to represent a meeting browser using Playwright."""

    def __init__(
        self, meeting_url: str, participant_name: str, audio_sink_name: str
    ) -> None:
        """Initialize the meeting browser with required parameters.

        Args:
            meeting_url: URL of the meeting to join
            participant_name: Name to display in the meeting
            audio_sink_name: Name of the audio sink to use
        """
        self._meeting_url: str = meeting_url
        self._participant_name: str = participant_name
        self._audio_sink_name: str = audio_sink_name

        self._playwright: Playwright | None = None
        self._pw_browser: PlaywrightBrowser | None = None
        self._pw_context: BrowserContext | None = None
        self._pw_page: Page | None = None

    async def __aenter__(self) -> Self:
        """Start the Playwright browser."""
        self._playwright = await async_playwright().start()
        self._pw_browser = await self._playwright.chromium.launch(
            headless=False,
            args=[
                "--use-fake-ui-for-media-stream",
                "--alsa-output-device=pulse",
            ],
            env={
                **dict(os.environ),
                "PULSE_SINK": self._audio_sink_name,
            },
        )
        self._pw_context = await self._pw_browser.new_context()
        self._pw_page = await self._pw_context.new_page()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Stop the Playwright browser."""
        if self._pw_page:
            await self.leave()
            await self._pw_page.close()
        if self._pw_context:
            await self._pw_context.close()
        if self._pw_browser:
            await self._pw_browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._pw_page = None
        self._pw_context = None
        self._pw_browser = None
        self._playwright = None

    async def join(self) -> None:
        """Join the meeting by clicking the join button."""
        if not self._pw_page:
            msg = "Playwright browser is not started."
            raise RuntimeError(msg)

        await self._pw_page.goto(self._meeting_url)

        # wait for an input field where placeholder contains "name" (case-insensitive)
        await self._pw_page.wait_for_selector(
            "input[placeholder*='name' i]", timeout=10000
        )
        await self._pw_page.fill("input[placeholder*='name' i]", self._participant_name)

        # click the join button by finding a button containing "join"
        await self._pw_page.wait_for_selector(
            "button:has-text('join')", timeout=1000, state="visible"
        )
        await self._pw_page.click("button:has-text('join')")

    async def leave(self) -> None:
        """Leave the meeting."""
        if self._pw_page is None or self._pw_page.is_closed():
            return

        with contextlib.suppress(TimeoutError):
            await self._pw_page.click("button:has-text('leave')", timeout=1000)
