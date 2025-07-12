import asyncio
import logging
import re
from typing import Any, ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController
from joinly.settings import get_settings
from joinly.types import MeetingChatHistory, MeetingChatMessage, MeetingParticipant

logger = logging.getLogger(__name__)


class TeamsBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Teams browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:[a-z0-9-]+\.)?(?:teams\.microsoft\.com|teams\.live\.com)/"
    )

    def __init__(self) -> None:
        """Initialize the Teams browser platform controller."""
        self._state: dict[str, Any] = {}

    @property
    def active_speaker(self) -> str | None:
        """Get the name of the active speaker in the Teams meeting."""
        return self._state.get("active_speaker")

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the Teams meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Teams meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        await page.goto(url, wait_until="load", timeout=20000)

        async def _dismiss_dialog(page: Page) -> None:
            await page.click('div[role="dialog"] button', timeout=0)

        dismiss_dialog = asyncio.create_task(_dismiss_dialog(page))

        try:
            name_field = page.get_by_placeholder(re.compile("name", re.IGNORECASE))
            await name_field.fill(name, timeout=20000)

            join_btn = page.get_by_role(
                "button", name=re.compile(r"join", re.IGNORECASE)
            )
            await join_btn.click(timeout=1000)

        finally:
            if not dismiss_dialog.done():
                dismiss_dialog.cancel()

        if not await self._check_joined(page):
            msg = "Join check failed: Failed to join the Teams meeting."
            raise RuntimeError(msg)

        await self._setup_active_speaker_observer(page)

    async def leave(self, page: Page) -> None:
        """Leave the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        leave_btn = page.get_by_role("button", name=re.compile(r"leave", re.IGNORECASE))
        if not await leave_btn.is_visible():
            msg = "Leave button not found or not visible."
            raise RuntimeError(msg)
        await leave_btn.click(timeout=1000)
        await page.wait_for_timeout(500)

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in the Teams meeting.

        Args:
            page: The Playwright page instance.
            message: The message to send.
        """
        await self._open_chat(page)

        chat_input = page.locator("div[contenteditable='true']")
        if not await chat_input.is_visible():
            msg = "Chat input not found or not visible."
            raise RuntimeError(msg)
        await chat_input.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

    async def get_chat_history(self, page: Page) -> MeetingChatHistory:
        """Get the chat history from the Teams meeting.

        Args:
            page: The Playwright page instance.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        await self._open_chat(page)

        messages: list[MeetingChatMessage] = []

        chat_items = await page.locator('[data-tid="chat-pane-item"]').all()
        for el in chat_items:
            content_el = el.locator('[data-tid="chat-pane-message"]')
            if not await content_el.count():
                continue
            text = (await content_el.first.inner_text()).strip()
            ts = await el.locator("time[datetime]").first.get_attribute("datetime")
            author_locator = el.locator('[data-tid="message-author-name"]').first
            sender_text = await author_locator.text_content() or ""
            sender = sender_text.strip() or None
            messages.append(MeetingChatMessage(text=text, timestamp=ts, sender=sender))

        return MeetingChatHistory(messages=messages)

    async def get_participants(self, page: Page) -> list[MeetingParticipant]:
        """Get the list of participants in the Teams meeting.

        Args:
            page: The Playwright page instance.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        participants_list = page.locator('div[aria-label="Attendees"][role="tree"]')
        is_participant_list_visible = await participants_list.is_visible()

        if not is_participant_list_visible:
            participants_button = page.get_by_role(
                "button", name=re.compile(r"^people", re.IGNORECASE)
            )
            if not await participants_button.is_visible():
                msg = "Participants button not found or not visible."
                raise RuntimeError(msg)
            await participants_button.click()
            await page.wait_for_timeout(1000)
            if not await participants_list.is_visible():
                await page.wait_for_timeout(1000)

        participants: list[MeetingParticipant] = []
        for item in await participants_list.locator(
            "[data-cid='roster-participant'][aria-label]"
        ).all():
            if aria_label := await item.get_attribute("aria-label"):
                labels = aria_label.split(", ")
                name = labels[0].strip()
                infos = labels[1:] if len(labels) > 1 else []
                participants.append(MeetingParticipant(name=name, infos=infos))

        return participants

    async def mute(self, page: Page) -> None:
        """Mute the participant in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        mute_btn = page.get_by_role("button", name=re.compile(r"^mute", re.IGNORECASE))
        if await mute_btn.is_visible():
            await mute_btn.click(timeout=1000)
        elif not await page.get_by_role(
            "button", name=re.compile(r"^unmute", re.IGNORECASE)
        ).is_visible():
            msg = "Mute button not found or not visible."
            raise RuntimeError(msg)

    async def unmute(self, page: Page) -> None:
        """Unmute the participant in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        unmute_btn = page.get_by_role(
            "button", name=re.compile(r"^unmute", re.IGNORECASE)
        )
        if await unmute_btn.is_visible():
            await unmute_btn.click(timeout=1000)
        elif not await page.get_by_role(
            "button", name=re.compile(r"^mute", re.IGNORECASE)
        ).is_visible():
            msg = "Unmute button not found or not visible."
            raise RuntimeError(msg)

    async def _check_joined(self, page: Page, timeout: float = 10) -> bool:  # noqa: ASYNC109
        """Check if the Teams meeting has been joined successfully.

        Args:
            page: The Playwright page instance.
            timeout: The timeout in seconds for checking the join status.

        Returns:
            bool: True if joined, False otherwise.
        """
        locators = [
            page.locator("span >> text=/please wait/i"),
            page.locator("span >> text=/will let you in/i"),
            page.get_by_role("button", name=re.compile(r"leave", re.IGNORECASE)),
        ]

        tasks = [
            asyncio.create_task(loc.wait_for(state="visible", timeout=0))
            for loc in locators
        ]

        try:
            done, _ = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED, timeout=timeout
            )
            return any(not task.exception() for task in done)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _open_chat(self, page: Page) -> None:
        """Open the chat in the Teams meeting."""
        chat_input = page.locator("div[contenteditable='true']")
        is_chat_visible = await chat_input.is_visible()

        if not is_chat_visible:
            chat_button = page.get_by_role(
                "button", name=re.compile(r"^chat", re.IGNORECASE)
            )
            if not await chat_button.is_visible():
                msg = "Chat button not found or not visible."
                raise RuntimeError(msg)
            await chat_button.click()
            await page.wait_for_timeout(1000)
            if not await chat_input.is_visible():
                await page.wait_for_timeout(2000)

    async def _setup_active_speaker_observer(self, page: Page) -> None:
        """Setup the active speaker observer for Teams."""
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
                        const t of document.querySelectorAll(
                            'div[data-tid="stage-layout"] div[role="menuitem"]'
                        )
                    ) {
                        if (!!t.querySelector(
                            'div[data-tid="voice-level-stream-outline"].vdi-frame-occlusion'
                        )) {
                            let el = t.querySelector(
                                'div[data-tid="participant-info-nametag"]'
                            );
                            if (!el) {
                                el = t.querySelector('div:not(:has(*)):not(:empty)');
                            }
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
                        attributeFilter: ['class']
                    }
                );
                emit(find());
            }
            """,
            get_settings().name,
        )
