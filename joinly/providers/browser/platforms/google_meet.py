import re
from typing import ClassVar

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController


class GoogleMeetBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Google Meet browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:www\.)?meet\.google\.com/"
    )
