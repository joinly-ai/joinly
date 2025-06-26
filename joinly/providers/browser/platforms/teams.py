import asyncio
import contextlib
import logging
import re
from datetime import datetime
from typing import Any, ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController
from joinly.settings import get_settings
from joinly.types import MeetingChatHistory, MeetingChatMessage, MeetingParticipant

logger = logging.getLogger(__name__)


class TeamsBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Teams browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:[a-z0-9-]+\.)?teams\.microsoft\.com/"
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

        async def _dismiss_audio_missing(page: Page) -> None:
            await page.click("button:has-text('Continue without audio')", timeout=0)

        dismiss_audio_missing = asyncio.create_task(_dismiss_audio_missing(page))

        try:
            name_field = page.get_by_placeholder(re.compile("name", re.IGNORECASE))
            await name_field.fill(name, timeout=20000)

            join_btn = page.get_by_role(
                "button", name=re.compile(r"^join", re.IGNORECASE)
            )
            await join_btn.click(timeout=3000)

        finally:
            dismiss_audio_missing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dismiss_audio_missing

        await self._setup_active_speaker_observer(page)

    async def leave(self, page: Page) -> None:
        """Leave the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        leave_btn = page.get_by_role(
            "button", name=re.compile(r"^leave", re.IGNORECASE)
        )
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
        await chat_input.wait_for(timeout=2000)
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
            dt_attr = await el.locator("time[datetime]").first.get_attribute("datetime")
            ts = (
                datetime.fromisoformat(dt_attr.rstrip("Z")).timestamp()
                if dt_attr
                else None
            )
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
        is_participant_list_visible = await participants_list.is_visible(timeout=1000)

        if not is_participant_list_visible:
            participants_button = page.get_by_role(
                "button", name=re.compile(r"^people", re.IGNORECASE)
            )
            await participants_button.wait_for(timeout=2000)
            await participants_button.click()
            await page.wait_for_timeout(1000)

        participants: list[MeetingParticipant] = []
        for item in await participants_list.locator(
            "li[data-cid='roster-participant']"
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
        if await mute_btn.is_visible(timeout=2000):
            await mute_btn.click(timeout=2000)

    async def unmute(self, page: Page) -> None:
        """Unmute the participant in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        unmute_btn = page.get_by_role(
            "button", name=re.compile(r"^unmute", re.IGNORECASE)
        )
        if await unmute_btn.is_visible(timeout=2000):
            await unmute_btn.click(timeout=2000)

    async def start_screen_sharing(self, page: Page) -> None:
        """Start screen sharing in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        screen_share_btn = page.get_by_role(
            "button", name=re.compile(r"^share", re.IGNORECASE)
        )
        await screen_share_btn.wait_for(timeout=2000)
        await screen_share_btn.click(timeout=2000)
        await page.wait_for_timeout(500)

        screen_share_btn = page.get_by_role(
            "button", name=re.compile(r"^share a screen", re.IGNORECASE)
        )
        await screen_share_btn.wait_for(timeout=2000)
        await screen_share_btn.click(timeout=2000)

    async def _open_chat(self, page: Page) -> None:
        """Open the chat in the Teams meeting."""
        chat_input = page.locator("div[contenteditable='true']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            chat_button = page.get_by_role(
                "button", name=re.compile(r"^chat", re.IGNORECASE)
            )
            await chat_button.wait_for(timeout=2000)
            await chat_button.click()
            await page.wait_for_timeout(1000)

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
                            const el = t.querySelector('div:not(:has(*)):not(:empty)');
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
