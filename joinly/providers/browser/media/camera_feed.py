"""Virtual camera feed via getUserMedia and RTCPeerConnection overrides.

Overrides ``navigator.mediaDevices.getUserMedia`` so that video
requests return a canvas-backed ``MediaStreamTrack`` instead of a
real camera, while audio requests pass through to the real device.

Also patches ``RTCPeerConnection.prototype.addTrack`` to swap any
video track with the canvas track, ensuring WebRTC negotiation
always uses our virtual feed regardless of platform behavior.

Patches ``enumerateDevices`` to include a virtual camera so
platforms that check for camera hardware still show a video toggle.

The camera canvas renders the Joinly logo directly (no CDP
screencast, no JPEG compression).  Audio amplitude drives an
equalizer effect that reacts to speech in real time.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

import numpy as np
from playwright.async_api import Page

from joinly.core import AudioWriter

_CAM_WIDTH = 1280
_CAM_HEIGHT = 720
_BAND_THROTTLE_S = 0.05
_NUM_BANDS = 7

_CAMERA_JS = (Path(__file__).parent / "static" / "camera_feed.js").read_text()


class CameraFeed:
    """Manages the virtual camera canvas and amplitude-driven glow.

    Draws the Joinly logo directly on the camera canvas (no CDP
    screencast).  Wraps an ``AudioWriter`` to extract amplitude and
    push it to the canvas render loop.
    """

    def __init__(self, writer: AudioWriter) -> None:
        """Initialize with the underlying audio writer."""
        self._meeting_page: Page | None = None
        self._last_band_time: float = 0
        self.audio_writer = _AmplitudeAudioWriter(writer, self._on_bands)

    async def install(self, meeting_page: Page) -> None:
        """Install the getUserMedia override on the meeting page."""
        self._meeting_page = meeting_page
        config_script = (
            f"window.__camConfig = {{ w: {_CAM_WIDTH},"
            f" h: {_CAM_HEIGHT}, nBands: {_NUM_BANDS} }}"
        )
        await meeting_page.add_init_script(config_script)
        await meeting_page.add_init_script(_CAMERA_JS)

    def set_effect(self, name: str | None) -> None:
        """Set the active visual effect, or None to clear."""
        page = self._meeting_page
        if page and not page.is_closed():
            safe = (name or "").replace("'", "\\'")
            task = asyncio.ensure_future(
                page.evaluate(f"window.__setStatus?.('{safe}')")
            )
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

    async def stop(self) -> None:
        """Clean up references."""
        self._meeting_page = None

    def _on_bands(self, bands: list[float]) -> None:
        now = asyncio.get_event_loop().time()
        if now - self._last_band_time < _BAND_THROTTLE_S:
            return
        self._last_band_time = now
        page = self._meeting_page
        if page and not page.is_closed():
            arr = "[" + ",".join(f"{v:.4f}" for v in bands) + "]"
            task = asyncio.ensure_future(page.evaluate(f"window.__setBands?.({arr})"))
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )


class _AmplitudeAudioWriter(AudioWriter):
    """Audio writer that computes frequency bands per chunk."""

    def __init__(
        self,
        writer: AudioWriter,
        on_bands: Callable[[list[float]], None],
    ) -> None:
        self._writer = writer
        self._on_bands = on_bands
        self.audio_format = writer.audio_format
        self.chunk_size = writer.chunk_size

    async def write(self, data: bytes) -> None:
        """Write audio and forward frequency band levels."""
        n_samples = len(data) // 2
        if n_samples < _NUM_BANDS:
            await self._writer.write(data)
            return
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        fft = np.abs(np.fft.rfft(samples))
        # Normalize: FFT magnitudes scale with n_samples and sample range
        fft /= n_samples * 32768
        # Log-spaced band edges so lower frequencies get finer resolution
        n_bins = len(fft)
        edges = np.logspace(np.log10(1), np.log10(n_bins), _NUM_BANDS + 1).astype(int)
        edges = np.clip(edges, 0, n_bins)
        bands = [
            float(np.mean(fft[edges[i] : max(edges[i + 1], edges[i] + 1)]))
            for i in range(_NUM_BANDS)
        ]
        self._on_bands(bands)
        await self._writer.write(data)
