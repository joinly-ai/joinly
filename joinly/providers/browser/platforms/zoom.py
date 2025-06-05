import re
from typing import ClassVar

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController


class ZoomBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Zoom browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:www\.)?zoom\.us/"
    )
