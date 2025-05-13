import asyncio
import contextlib
import logging
from typing import Self

from meeting_agent.devices.virtual_microphone import VirtualMicrophone
from meeting_agent.speech.tts_service import TTSService

logger = logging.getLogger(__name__)

_SENTINEL = object()


class SpeechFlowController:
    """A class to manage the speech flow."""

    def __init__(
        self,
        mic: VirtualMicrophone,
        tts: TTSService,
        no_speech_event: asyncio.Event,
        *,
        sample_rate: int = 24000,
        frames_per_chunk: int = 2048,
    ) -> None:
        """Initialize the SpeechFlowController.

        Args:
            mic (VirtualMicrophone): The virtual microphone to use for audio input.
            tts (TTSService): The text-to-speech service to use for audio output.
            no_speech_event (asyncio.Event): An event to signal when no speech is
                detected.
            sample_rate (int): The sample rate for audio processing (default is 24000).
            frames_per_chunk (int): The number of frames per chunk (default is 512).
        """
        self._mic = mic
        self._tts = tts
        self._no_speech_event = no_speech_event
        self.sample_rate = sample_rate
        self._chunk_bytes = frames_per_chunk * 4
        self._queue: asyncio.Queue[bytes | object] | None = None
        self._queue_task: asyncio.Task[None] | None = None
        self._speak_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Set up the audio stream and queue."""
        if self._queue is not None:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        self._queue = asyncio.Queue()
        self._queue_task = asyncio.create_task(self._drain_queue())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        if self._queue is not None:
            await self._queue.put(_SENTINEL)
            if self._queue_task is not None:
                try:
                    await asyncio.wait_for(self._queue_task, timeout=5)
                except TimeoutError:
                    logger.warning("Audio queue task did not terminate, cancelling it.")
                    self._queue_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._queue_task

    async def speak_text(self, text: str) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
        """
        logger.info("Speaking text: %s", text)
        async with self._speak_lock:
            async for chunk in self._tts.tts(text):
                if len(chunk) > self._chunk_bytes:
                    for i in range(0, len(chunk), self._chunk_bytes):
                        await self._enqueue_audio(chunk[i : i + self._chunk_bytes])
                else:
                    await self._enqueue_audio(chunk)

    async def _enqueue_audio(self, item: bytes) -> None:
        """Process the incoming audio chunk.

        Args:
            item (bytes): Audio data in f32le format to be processed.
        """
        if self._queue is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        await self._queue.put(item)

    async def _drain_queue(self) -> None:
        """Drain the audio queue and write to the virtual microphone."""
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)

        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break

            await self._no_speech_event.wait()
            await self._mic.write_frames(item)  # type: ignore[arg-type]

            await asyncio.sleep(len(item) // 4 / self.sample_rate)  # type: ignore[arg-type]
