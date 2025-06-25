import logging
import re
from datetime import UTC, datetime
from typing import Any, ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController
from joinly.settings import get_settings
from joinly.types import MeetingChatHistory, MeetingChatMessage

logger = logging.getLogger(__name__)

_TIME_RX = re.compile(r"^\d{1,2}:\d{2}(?:\s*[AP]M)?$", re.IGNORECASE)


class ZoomBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Zoom browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:[a-z0-9-]+\.)?zoom\.us/"
    )

    def __init__(self) -> None:
        """Initialize the Zoom browser platform controller."""
        self._state: dict[str, Any] = {}

    @property
    def active_speaker(self) -> str | None:
        """Get the name of the active speaker in the Zoom meeting."""
        return self._state.get("active_speaker")

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,
    ) -> None:
        """Join the Zoom meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Zoom meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        # Convert the standard join URL to the web client format
        if re.search(r"/j/\d+", url):
            url = re.sub(r"/j/(\d+)", r"/wc/join/\1", url)
            logger.info(f"Rewrote Zoom join URL to web client format: {url}")  # noqa: G004

        await page.goto(url, wait_until="load", timeout=20000)

        # Accept cookies and agree to terms
        await page.click("button:has-text('ACCEPT COOKIES')", timeout=5000)
        await page.click("button:has-text('I Agree')", timeout=5000)

        # Wait for and fill in the name field
        name_field = page.locator("#input-for-name, input[placeholder*='Name']")
        await name_field.fill(name, timeout=10000)

        # Click the "Join" button
        await page.click("button:has-text('Join')", timeout=5000)

        # If the Join button is still visible, click it again
        try:
            join_button = page.locator("button:has-text('Join')")
            if await join_button.is_visible(timeout=2000):
                logger.debug("Join button still present, clicking again.")
                await join_button.click(timeout=5000)
                await join_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Join button found or error occurred: {e}")  # noqa: G004

        try:
            join_button = page.locator("button:has-text('Join')")
            meeting_passcode = page.locator(
                "#input-for-passcode, input[placeholder*='Passcode']"
            )
            if await meeting_passcode.is_visible(timeout=2000):
                logger.info("Meeting passcode required.")
                if passcode is not None:
                    await meeting_passcode.fill(passcode, timeout=10000)
                    await join_button.click(timeout=5000)
                else:
                    logger.error("Passcode is required but not provided.")
        except Exception as e:  # noqa: BLE001
            logger.debug(
                f"No additional Passcode required button found or error occurred: {e}"  # noqa: G004
            )

        await self._setup_active_speaker_observer(page)

    async def leave(self, page: Page) -> None:
        """Leave the Zoom meeting using the icon-based button."""
        await self._activate_controls(page)

        # Step 2: Click the Leave button based on its label
        await page.click("button:has-text('Leave')")

        # Attempt a second click if the button is still visible
        try:
            leave_button = page.locator("button:has-text('Leave')")
            if await leave_button.is_visible(timeout=2000):
                logger.debug("Leave button still present, clicking again.")
                await leave_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Leave button found or error occurred: {e}")  # noqa: G004

        # Confirm leaving the meeting
        await page.click(
            "button:has-text('Leave meeting')",
            timeout=5000,
        )

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in Zoom."""
        await self._open_chat(page)
        chat_input = page.locator("div[contenteditable='true']")

        # Focus the chat input (important for ProseMirror-based editors)
        await chat_input.click()
        await page.wait_for_timeout(200)

        # Type the message (using fill for DOM compatibility)
        await chat_input.fill(message)
        await page.wait_for_timeout(200)

        # Send the message
        await page.keyboard.press("Enter")

    async def get_chat_history(self, page: Page) -> MeetingChatHistory:
        """Return a Zoom in-meeting chat history.

        Args:
            page: The Playwright page instance.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        await self._open_chat(page)

        messages: list[MeetingChatMessage] = []

        panel = page.locator('div[role="application"][aria-label="Chat Message List"]')
        rows = await panel.locator('[role="row"][aria-label]').all()

        for row in rows:
            aria = await row.get_attribute("aria-label") or ""
            parts = [p.strip() for p in aria.split(",")]

            sender: str | None = None
            ts: float | None = None

            if parts:
                first = parts[0]
                sender = (
                    (first.split(" to ")[0].strip() or None)
                    if " to " in first
                    else (first or None)
                )

            if len(parts) >= 2:  # noqa: PLR2004
                raw_time = re.sub(r"[\u00A0\u202F]", "", parts[1]).strip()
                if _TIME_RX.fullmatch(raw_time):
                    if raw_time[-2:].upper() in {"AM", "PM"}:
                        fmt = "%I:%M %p" if " " in raw_time else "%I:%M%p"
                    else:
                        fmt = "%H:%M"
                    clean_time = raw_time.upper().strip()
                    t = datetime.strptime(clean_time, fmt).replace(tzinfo=UTC)
                    today = datetime.now(UTC).date()
                    t = t.replace(year=today.year, month=today.month, day=today.day)
                    ts = t.timestamp()

            text_el = row.locator(":scope p").first
            if await text_el.count():
                text = (await text_el.inner_text()).strip()
            else:
                text = ",".join(parts[2:]).strip() if len(parts) >= 3 else ""  # noqa: PLR2004

            if text:
                messages.append(
                    MeetingChatMessage(text=text, timestamp=ts, sender=sender)
                )

        return MeetingChatHistory(messages=messages)

    async def mute(self, page: Page) -> None:
        """Mute the microphone in Zoom."""
        await self._activate_controls(page)

        try:
            mic_button = page.locator(
                "button:has-text('Mute'):not(:has-text('Unmute'))"
            )
            if await mic_button.is_visible(timeout=500):
                logger.debug("Mute button found, clicking it.")
                await mic_button.click(timeout=500)
            else:
                logger.debug("Mute button not found or not visible.")
        except Exception:  # noqa: BLE001
            logger.debug("Could not find the Mute button.")

    async def unmute(self, page: Page) -> None:
        """Unmute the microphone in Zoom."""
        await self._activate_controls(page)

        try:
            mic_button = page.locator("button:has-text('Unmute')")
            if await mic_button.is_visible(timeout=500):
                logger.debug("Unmute button found, clicking it.")
                await mic_button.click(timeout=500)
                if await mic_button.is_visible(timeout=500):
                    logger.debug("Unmute button still present, clicking again.")
                    await mic_button.click(timeout=500)
            else:
                logger.debug("Unmute button not found or not visible.")
        except Exception:  # noqa: BLE001
            logger.debug("Could not find the Unmute button.")

    async def start_screen_sharing(self, page: Page) -> None:
        """Start screen sharing in Zoom."""
        await self._activate_controls(page)

        # Click the Share Screen button
        share_btn = page.get_by_role(
            "button", name=re.compile(r"Share Screen", re.IGNORECASE)
        )
        await share_btn.click(timeout=2000)
        await page.wait_for_timeout(500)

        # Click the option to share a specific screen (like "Screen 1" or "Entire Screen")  # noqa: E501
        screen_option = page.get_by_role(
            "button", name=re.compile(r"Screen 1|Entire Screen", re.IGNORECASE)
        )
        await screen_option.click(timeout=2000)
        await page.wait_for_timeout(500)

    async def _activate_controls(self, page: Page) -> None:
        """Activate control bar."""
        await page.mouse.click(640, 360)
        await page.wait_for_timeout(100)

    async def _open_chat(self, page: Page) -> None:
        """Open the chat in the Zoom meeting."""
        chat_input = page.locator("div[contenteditable='true']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            await self._activate_controls(page)
            await page.wait_for_selector(
                "button[aria-label='open the chat panel']", timeout=2000
            )
            await page.click("button[aria-label='open the chat panel']")
            await page.click("button[aria-label='open the chat panel']")
            await page.wait_for_timeout(1000)

    async def _setup_active_speaker_observer(self, page: Page) -> None:
        """Setup the active speaker observer for Zoom."""
        await page.expose_binding(
            "report",
            lambda _, name: self._state.update({"active_speaker": name}),
        )
        await page.evaluate(
            """
            (nameArg) => {
                const emit = n => window.report(n);
                const find = () => {
                    const selectors = [
                        'div.speaker-active-container__video-frame span',
                        'div.speaker-bar-container__video-frame--active span',
                        'div.speaker-bar-container__video-frame span',
                    ];

                    const name = selectors
                        .flatMap(sel => Array.from(document.querySelectorAll(sel)))
                        .map(el => el?.textContent?.trim())
                        .find(text => text && text.length > 0 && text !== nameArg);
                    return name || null;
                };

                let last = null, cur;
                new MutationObserver(() => {
                    cur = find();
                    if (cur !== last) { last = cur; emit(cur); }
                }).observe(
                    document,
                    {
                        subtree: true,
                        childList: true,
                        attributes: true,
                        attributeFilter: ['class']
                    }
                );
                emit(find());
            }
            """,
            get_settings().name,
        )
