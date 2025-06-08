import contextlib
import mimetypes
from collections.abc import AsyncGenerator
from pathlib import Path

import aiofiles
import aiohttp.web


def _create_mockup_meeting_html() -> str:
    """Create the HTML template for audio playback."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
    <input id="name" type="text" placeholder="Enter your name">
    <button id="join">Join</button>
    <button id="leave">Leave</button>
    <audio id="audio" src="/speech_audio"></audio>
    <script>
      document.getElementById('join').addEventListener('click', () => {
        document.getElementById('audio').play().catch(() => {{}});
      });
    </script>
    </body>
    </html>
    """


@contextlib.asynccontextmanager
async def serve_mockup_browser_meeting(
    speech_file_path: Path,
) -> AsyncGenerator[str, None]:
    """Start a temporary HTTP server serving a meeting page mockup for testing purposes.

    This function creates a temporary HTTP server that serves two endpoints:
    - Root ("/") serves an HTML page with an audio player and mockup buttons
    - "/speech_audio" serves the audio file content

    Args:
        speech_file_path (Path): Path to the audio file to be served

    Yields:
        str: URL of the temporary server (e.g., "http://127.0.0.1:{port}/")

    Raises:
        ValueError: If the specified speech file is not found
    """
    mime_type, _ = mimetypes.guess_type(speech_file_path)
    if mime_type is None or not mime_type.startswith("audio/"):
        msg = f"Unsupported file type: {speech_file_path}"
        raise ValueError(msg)

    try:
        async with aiofiles.open(speech_file_path, "rb") as f:
            speech_data = await f.read()
    except FileNotFoundError as err:
        msg = f"Speech file not found: {speech_file_path}"
        raise ValueError(msg) from err

    app = aiohttp.web.Application()

    async def handle_index(_request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.Response(
            text=_create_mockup_meeting_html(), content_type="text/html"
        )

    async def handle_speech(_request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.Response(body=speech_data, content_type=mime_type)

    app.router.add_get("/", handle_index)
    app.router.add_get("/speech_audio", handle_speech)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()

    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    host, port = runner.addresses[0]
    url = f"http://{host}:{port}/"

    try:
        yield url
    finally:
        await runner.cleanup()
