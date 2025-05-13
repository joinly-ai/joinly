import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Self

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)

_CDP_RE = re.compile(r"DevTools listening on (ws://.*)")


class BrowserSession:
    """A class to represent a browser session using Playwright."""

    def __init__(self, *, env: dict[str, str] | None = None, cdp_port: int = 0) -> None:
        """Initialize the browser params.

        Args:
            env: Environment variables to set for the browser (default: None)
            cdp_port (int): The port for the CDP connection (default: 0, auto-assign)
        """
        self._env: dict[str, str] = env if env is not None else os.environ.copy()
        self._cdp_port: int = cdp_port

        self._proc: asyncio.subprocess.Process | None = None
        self._profile_dir: Path | None = None
        self._playwright: Playwright | None = None
        self._pw_browser: PlaywrightBrowser | None = None
        self._pw_context: BrowserContext | None = None
        self._default_page: Page | None = None
        self._pages = list[Page]()

    async def __aenter__(self) -> Self:
        """Start and connect to the Playwright browser."""
        self._env["XDG_SESSION_TYPE"] = "x11"

        self._pw = await async_playwright().start()

        bin_path = Path(self._pw.chromium.executable_path)
        logger.info("Chromium binary path: %s", bin_path)
        if not bin_path.exists():
            msg = "Chromium binary not found"
            logger.error(msg)
            raise RuntimeError(msg)

        self._profile_dir = Path(tempfile.mkdtemp(prefix="pw-profile-"))
        logger.info("Profile directory created at: %s", self._profile_dir)

        logger.info("Launching Chromium browser.")
        self._proc = await asyncio.create_subprocess_exec(
            str(bin_path),
            f"--remote-debugging-port={self._cdp_port}",
            f"--user-data-dir={self._profile_dir}",
            f"--alsa-output-device={self._env.get('SINK_NAME')}",
            "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-extensions",
            "--alsa-input-device=pulse",
            "--allow-http-screen-capture",
            "--auto-select-desktop-capture-source=screen",
            "--enable-usermedia-screen-capturing",
            "--enable-features=WebRTCPipeWireCapturer",
            "--ozone-platform=x11",
            "--disable-features=UseOzonePlatform,PermissionsPolicyDisplayCapture",
            "--disable-gpu",
            "--disable-focus-on-load",
            "--window-size=1280,720",
            "--lang=en-US",
            "--test-type",
            "--no-sandbox",  # required for docker
            "--disable-dev-shm-usage",
            "--disable-gpu-sandbox",
            "--disable-setuid-sandbox",
            "--no-xsmh",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        logger.info("Chromium browser launched.")

        while line := await self._proc.stderr.readline():  # type: ignore[attr-defined]
            logger.debug("[chromium] %s", line.decode().strip())
            m = _CDP_RE.search(line.decode())
            if m:
                cdp_endpoint = m.group(1)
                break
        else:
            self._proc.terminate()
            msg = "Could not find DevTools URL in stderr"
            logger.error(msg)
            raise RuntimeError(msg)
        logger.info("DevTools URL: %s", cdp_endpoint)
        self._env["CDP_ENDPOINT"] = cdp_endpoint

        self._pw_browser = await self._pw.chromium.connect_over_cdp(cdp_endpoint)
        self._pw_context = self._pw_browser.contexts[0]
        self._default_page = (
            self._pw_context.pages[0] if self._pw_context.pages else None
        )

        logger.info("Playwright started.")

        return self

    async def __aexit__(self, *exc: object) -> None:
        """Stop the Playwright."""
        logger.info("Stopping Playwright.")

        for page in self._pages:
            if not page.is_closed():
                await page.close()
        if self._pw_browser:
            await self._pw_browser.close()
        if self._playwright:
            await self._playwright.stop()

        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Browser process did not terminate, killing it.")
                self._proc.kill()
                await self._proc.wait()

        if self._profile_dir is not None and self._profile_dir.exists():
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            logger.info("Profile directory removed: %s", self._profile_dir)

        self._pw_context = None
        self._pw_browser = None
        self._playwright = None
        self._proc = None
        self._profile_dir = None
        self._default_page = None
        self._pages = []
        self._env.pop("CDP_ENDPOINT", None)

        logger.info("Playwright stopped.")

    async def get_page(self) -> Page:
        """Get a new page in the browser context."""
        if self._pw_context is None:
            msg = "Playwright context is not initialized."
            raise RuntimeError(msg)

        if not self._pages and self._default_page is not None:
            page = self._default_page
            logger.info("Retrieving default page from the browser context.")
        else:
            page = await self._pw_context.new_page()
            logger.info("New page created in the browser context.")

        page.on(
            "console", lambda msg: logger.debug("[console][%s] %s", msg.type, msg.text)
        )
        self._pages.append(page)

        return page
