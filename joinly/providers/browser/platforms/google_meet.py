import contextlib
import re
from datetime import UTC, datetime
from typing import Any, ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController
from joinly.settings import get_settings
from joinly.types import MeetingChatHistory, MeetingChatMessage, MeetingParticipant

_TIME_RX = re.compile(r"^\d{1,2}:\d{2}(?:[AP]M)?$", re.IGNORECASE)


class GoogleMeetBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Google Meet browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:www\.)?meet\.google\.com/"
    )

    def __init__(self) -> None:
        """Initialize the Google Meet browser platform controller."""
        self._state: dict[str, Any] = {}

    @property
    def active_speaker(self) -> str | None:
        """Get the name of the active speaker in the Google Meet meeting."""
        return self._state.get("active_speaker")

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the Google Meet meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Google Meet meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        await page.goto(url, wait_until="load", timeout=20000)

        # Wait for and fill in the name field
        name_field = page.locator("#input-for-name, input[placeholder*='Your name']")
        await name_field.fill(name)

        # Click the "Join" button
        await page.locator(
            "button:has-text('Join now'), button:has-text('Ask to join')"
        ).click()

        await self._setup_active_speaker_observer(page)

    async def leave(self, page: Page) -> None:
        """Leave the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        await self._dismiss_dialog(page)

        leave_btn = page.get_by_role(
            "button", name=re.compile(r"^leave", re.IGNORECASE)
        )
        await leave_btn.click(timeout=1000)
        await page.wait_for_timeout(500)

    async def mute(self, page: Page) -> None:
        """Mute the participant in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        await self._dismiss_dialog(page)

        mute_btn = page.get_by_role(
            "button", name=re.compile(r"^turn off mic", re.IGNORECASE)
        )
        if await mute_btn.is_visible(timeout=2000):
            await mute_btn.click(timeout=2000)

    async def unmute(self, page: Page) -> None:
        """Unmute the participant in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        await self._dismiss_dialog(page)

        unmute_btn = page.get_by_role(
            "button", name=re.compile(r"^turn on mic", re.IGNORECASE)
        )
        if await unmute_btn.is_visible(timeout=2000):
            await unmute_btn.click(timeout=2000)

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
            message: The message to send.
        """
        await self._open_chat(page)

        chat_input = page.locator("textarea[placeholder*='Send a message']")
        await chat_input.wait_for(timeout=2000)
        await chat_input.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

    async def get_chat_history(self, page: Page) -> MeetingChatHistory:
        """Get the chat history from a Google Meet meeting."""
        await self._open_chat(page)

        messages: list[MeetingChatMessage] = []

        chat_panel = page.locator('aside[aria-label="Side panel"]')
        blobs = await chat_panel.locator("div:has(> div > div[data-message-id])").all()

        for blob in blobs:
            header = blob.locator(":scope > div").first
            inner_text = await header.inner_text()
            parts = [p.strip() for p in inner_text.splitlines() if p.strip()]

            sender: str | None = None
            ts: float | None = None
            for part in parts:
                clean = re.sub(r"[\u00A0\u202F]", "", part).strip()

                if _TIME_RX.fullmatch(clean):
                    fmt = "%I:%M%p" if clean[-2:].upper() in ("AM", "PM") else "%H:%M"
                    t = datetime.strptime(clean.upper(), fmt).replace(tzinfo=UTC)
                    today = datetime.now(UTC).date()
                    t = t.replace(year=today.year, month=today.month, day=today.day)
                    ts = t.timestamp()
                elif sender is None:
                    sender = clean or None

            bubbles = await blob.locator("div[data-message-id]").all()
            for bubble in bubbles:
                raw = (await bubble.inner_text()).splitlines()
                text = next((ln.strip() for ln in raw if ln.strip()), "")
                if text:
                    messages.append(
                        MeetingChatMessage(text=text, timestamp=ts, sender=sender)
                    )

        return MeetingChatHistory(messages=messages)

    async def get_participants(self, page: Page) -> list[MeetingParticipant]:
        """Get the list of participants in the Google Meet meeting.

        Args:
            page: The Playwright page instance.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        await self._dismiss_dialog(page)

        participants_list = page.locator('div[aria-label="Participants"][role="list"]')
        is_participant_list_visible = await participants_list.is_visible(timeout=1000)

        if not is_participant_list_visible:
            participants_button = page.get_by_role(
                "button", name=re.compile(r"^people", re.IGNORECASE)
            )
            await participants_button.wait_for(timeout=2000)
            await participants_button.click()
            await page.wait_for_timeout(1000)

        participants: list[MeetingParticipant] = []
        for item in await participants_list.locator("div[role='listitem']").all():
            name = await item.get_attribute("aria-label")
            infos = []
            if await item.locator('span:has-text("(You)")').count() > 0:
                infos.append("You")
            if await item.locator('div:has-text("Meeting host")').count() > 0:
                infos.append("Meeting host")
            if name:
                participants.append(MeetingParticipant(name=name, infos=infos))

        return participants

    async def _dismiss_dialog(self, page: Page) -> None:
        """Dismiss any popups that may appear."""
        action_btn = page.locator("div[role='dialog'] [data-mdc-dialog-action]")
        with contextlib.suppress(Exception):
            if await action_btn.first.is_visible(timeout=100):
                await action_btn.first.click()

    async def _open_chat(self, page: Page) -> None:
        """Open the chat in the Google Meet meeting."""
        await self._dismiss_dialog(page)

        chat_input = page.locator("textarea[placeholder*='Send a message']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            chat_button = page.get_by_role(
                "button", name=re.compile(r"^chat", re.IGNORECASE)
            )
            await chat_button.wait_for(timeout=2000)
            await chat_button.click()
            await page.wait_for_timeout(1000)

    async def _setup_active_speaker_observer(self, page: Page) -> None:
        """Setup the active speaker observer for Google Meet."""
        await page.expose_binding(
            "report",
            lambda _, name: self._state.update({"active_speaker": name}),
        )
        await page.evaluate(
            """
            (nameArg) => {
                const emit = n => window.report(n);
                const find = () => {
                    for (
                        const t of document.querySelectorAll('div[data-participant-id]')
                    ) {
                        if (![...t.querySelectorAll('div')].some(d =>
                                !d.children.length &&
                                getComputedStyle(d).display === 'none' &&
                                parseFloat(getComputedStyle(d).borderTopWidth) > 3
                            ))
                        {
                            const el = t.querySelector('span.notranslate')
                            const name = el?.textContent.trim();
                            if (name && name.length > 0 && name !== nameArg)
                                return name;
                        }
                    }
                    return null;
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
                        attributeFilter: ['style', 'class']
                    }
                );
                emit(find());
            }
            """,
            get_settings().name,
        )
