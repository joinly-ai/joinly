"""Tests for the utterance loop of the transcription controller.

The VAD flags speech late, so the first word of an utterance is partly in windows it
called silence. The controller passes the last stretch of audio before an utterance
to the STT along with it (``utterance_preroll_seconds``). These tests run the real
``BasePaddedVAD.stream`` and the real controller over a scripted call, with an STT
that keeps the windows of each utterance it is given.
"""

import asyncio
import contextlib
import struct
from collections.abc import AsyncIterator
from typing import TypedDict, Unpack

import pytest

from joinly.controllers.transcription.default import DefaultTranscriptionController
from joinly.services.stt.whisper import WhisperSTT
from joinly.services.vad.base import BasePaddedVAD
from joinly.types import (
    AudioChunk,
    AudioFormat,
    SpeechWindow,
    Transcript,
    TranscriptSegment,
)
from joinly.utils.clock import Clock
from joinly.utils.events import EventBus

RATE = 16_000
WINDOW_SAMPLES = 512
WINDOW_S = WINDOW_SAMPLES / RATE  # 32 ms
WINDOW_NS = WINDOW_SAMPLES * 1_000_000_000 // RATE
FORMAT = AudioFormat(sample_rate=RATE, byte_depth=4)
TIMEOUT_S = 5

# The call of most tests: 30 windows of silence, then 10 of speech, then a silence
# longer than the 0.6 s tail, which ends the utterance. The VAD flags window 30 as the
# first speech and holds window 29 back to mark it too: ten windows (0.32 s) of
# pre-roll are windows 19 to 28.
SILENCE_30 = (False, 30)
SPEECH_10 = (True, 10)
SILENCE_40 = (False, 40)
FIRST_SPEECH = 30
PENDING = FIRST_SPEECH - 1
DEFAULT_PREROLL_S = 0.3
PREROLL_WINDOWS = 10  # the default, in whole windows


def script(*runs: tuple[bool, int]) -> list[bool]:
    """Build the per-window speech flags of a call.

    Args:
        *runs: Pairs of (is speech, number of 32 ms windows).

    Returns:
        One flag for each window of the call.
    """
    return [speech for speech, count in runs for _ in range(count)]


def index_of(window: SpeechWindow) -> int:
    """Return the index of the call window a window carries (see ``Call``)."""
    return struct.unpack("<I", window.data[:4])[0]


def indices(windows: list[SpeechWindow]) -> list[int]:
    """Return the call-window indices of windows."""
    return [index_of(w) for w in windows]


class ControllerArgs(TypedDict, total=False):
    """The arguments of the controller the tests change."""

    utterance_preroll_seconds: float
    window_queue_size: int


class Call:
    """A scripted call, as an audio reader.

    The audio of each window is its own index, so a test can tell which windows an STT
    got. After the last window the reader waits forever, as a live call does.
    """

    audio_format = FORMAT

    def __init__(self, flags: list[bool]) -> None:
        """Initialize the call.

        Args:
            flags: Whether the VAD calls each window speech.
        """
        self.flags = flags
        self.reads = 0
        self.finished = asyncio.Event()

    async def read(self) -> AudioChunk:
        """Read the next 32 ms of the call."""
        await asyncio.sleep(0)  # a live read waits for audio
        i = self.reads
        if i >= len(self.flags):
            self.finished.set()
            await asyncio.Event().wait()
        self.reads += 1
        return AudioChunk(
            data=struct.pack("<I", i) * WINDOW_SAMPLES,
            time_ns=i * WINDOW_NS,
            speaker=f"speaker-{i}",
        )


class ScriptedVAD(BasePaddedVAD):
    """The real padded VAD, which holds one window back, with a scripted verdict."""

    audio_format = FORMAT

    def __init__(self, flags: list[bool]) -> None:
        """Initialize the VAD.

        Args:
            flags: Whether each window is speech, in order.
        """
        self._flags = iter(flags)

    @property
    def window_size_samples(self) -> int:
        """The VAD's window: 32 ms."""
        return WINDOW_SAMPLES

    async def is_speech(self, window: bytes) -> bool:  # noqa: ARG002
        """Return the scripted verdict for the next window."""
        return next(self._flags)


class RecordingSTT:
    """An STT that keeps the windows of each utterance, and transcribes nothing."""

    audio_format = FORMAT

    def __init__(self) -> None:
        """Initialize the STT."""
        self.utterances: asyncio.Queue[list[SpeechWindow]] = asyncio.Queue()

    async def stream(
        self, windows: AsyncIterator[SpeechWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Keep the windows of one utterance."""
        self.utterances.put_nowait([w async for w in windows])
        return
        yield


@contextlib.asynccontextmanager
async def running(
    flags: list[bool], **controller_args: Unpack[ControllerArgs]
) -> AsyncIterator[tuple[Call, RecordingSTT]]:
    """Run the controller over a scripted call.

    Args:
        flags: Whether the VAD calls each window of the call speech.
        **controller_args: Arguments for the controller.

    Yields:
        The call, and the STT that gets its utterances.
    """
    call = Call(flags)
    stt = RecordingSTT()
    controller = DefaultTranscriptionController(**controller_args)
    controller.reader, controller.vad, controller.stt = call, ScriptedVAD(flags), stt
    await controller.start(Clock(), Transcript(), EventBus())
    try:
        yield call, stt
    finally:
        await controller.stop()


async def utterances(
    flags: list[bool], count: int, **controller_args: Unpack[ControllerArgs]
) -> list[list[SpeechWindow]]:
    """Return the windows of the first ``count`` utterances of a scripted call."""
    async with running(flags, **controller_args) as (_call, stt):
        async with asyncio.timeout(TIMEOUT_S):
            return [await stt.utterances.get() for _ in range(count)]


async def test_an_utterance_starts_with_the_audio_before_its_speech() -> None:
    """The STT gets 0.3 s from before the VAD's first speech, not one window.

    Without the pre-roll the STT starts at window 29, partway into the first word.
    """
    (got,) = await utterances(script(SILENCE_30, SPEECH_10, SILENCE_40), 1)

    assert PREROLL_WINDOWS * WINDOW_S >= DEFAULT_PREROLL_S
    assert indices(got)[0] == PENDING - PREROLL_WINDOWS
    # one stretch of audio, in order, with no window missing or repeated
    assert indices(got) == list(range(indices(got)[0], indices(got)[-1] + 1))


async def test_the_preroll_is_marked_as_speech_so_an_stt_starts_with_it() -> None:
    """Windows the VAD called silence are passed on as speech.

    ``WhisperSTT`` only starts its buffer on a speech window, so a pre-roll that stayed
    marked as silence would be thrown away.
    """
    (got,) = await utterances(script(SILENCE_30, SPEECH_10, SILENCE_40), 1)

    assert all(w.is_speech for w in got[: PREROLL_WINDOWS + 1 + SPEECH_10[1]])


async def test_the_preroll_keeps_each_windows_time_and_speaker() -> None:
    """A window that is passed on early is still the one that was heard.

    The segment times come from the first window, and a piece's speaker from the
    speakers of its windows.
    """
    (got,) = await utterances(script(SILENCE_30, SPEECH_10, SILENCE_40), 1)

    for window in got:
        assert window.time_ns == index_of(window) * WINDOW_NS
        assert window.speaker == f"speaker-{index_of(window)}"


async def test_a_preroll_of_zero_turns_it_off() -> None:
    """With ``utterance_preroll_seconds=0`` an utterance starts as it did before.

    That is at the window the VAD holds back and marks, one before its first speech.
    """
    (got,) = await utterances(
        script(SILENCE_30, SPEECH_10, SILENCE_40), 1, utterance_preroll_seconds=0
    )

    assert indices(got)[0] == PENDING


async def test_the_preroll_is_as_long_as_the_setting() -> None:
    """A longer pre-roll gives the STT more of the audio before the speech."""
    seconds = 2 * DEFAULT_PREROLL_S
    (got,) = await utterances(
        script(SILENCE_30, SPEECH_10, SILENCE_40),
        1,
        utterance_preroll_seconds=seconds,
    )

    lead = (PENDING - indices(got)[0]) * WINDOW_S
    assert seconds <= lead < seconds + WINDOW_S


async def test_a_call_that_starts_with_speech_has_nothing_before_it() -> None:
    """A pre-roll is the audio there is: at the start of a call, none."""
    (got,) = await utterances(script(SPEECH_10, SILENCE_40), 1)

    assert indices(got)[0] == 0


async def test_a_pause_inside_an_utterance_adds_no_preroll() -> None:
    """Speech that resumes within the 0.6 s tail is one utterance, as before.

    Its windows are the call's windows once each and in order, with the pause marked
    as the VAD said: a pre-roll in the middle would repeat audio the STT has.
    """
    pause = (False, 12)  # 0.38 s
    (got,) = await utterances(
        script(SILENCE_30, SPEECH_10, pause, SPEECH_10, SILENCE_40), 1
    )

    assert indices(got) == list(range(indices(got)[0], indices(got)[-1] + 1))
    pause_start = FIRST_SPEECH + SPEECH_10[1]
    held_back = pause_start + pause[1] - 1  # the VAD marks the window before speech
    in_pause = [w for w in got if pause_start <= index_of(w) < held_back]
    assert in_pause
    assert not any(w.is_speech for w in in_pause)


async def test_each_utterance_gets_its_own_preroll() -> None:
    """The second utterance starts 0.3 s before its speech, not at the first's end."""
    first, second = await utterances(
        script(SILENCE_30, SPEECH_10, (False, 60), SPEECH_10, SILENCE_40), 2
    )

    second_speech = FIRST_SPEECH + SPEECH_10[1] + 60
    assert indices(second)[0] == second_speech - 1 - PREROLL_WINDOWS
    assert indices(first)[-1] < indices(second)[0]


async def test_a_short_gap_does_not_reach_back_into_the_last_utterance() -> None:
    """The pre-roll is only audio the last utterance did not get.

    The first utterance ends 0.6 s after its speech. Speech resumes soon after, with
    less silence in between than a pre-roll, so the second starts exactly where the
    first stopped: every window once, none lost and none repeated.
    """
    first, second = await utterances(
        script(SILENCE_30, SPEECH_10, (False, 25), SPEECH_10, SILENCE_40), 2
    )

    second_pending = FIRST_SPEECH + SPEECH_10[1] + 25 - 1
    assert indices(second)[0] == indices(first)[-1] + 1
    assert second_pending - indices(second)[0] < PREROLL_WINDOWS  # a shorter one


async def test_a_silent_call_starts_no_utterance() -> None:
    """Keeping windows is not an utterance: nothing reaches the STT without speech."""
    async with running(script((False, 200))) as (call, stt):
        async with asyncio.timeout(TIMEOUT_S):
            await call.finished.wait()
        await asyncio.sleep(0)

        assert stt.utterances.empty()


async def test_a_queue_too_small_for_the_preroll_does_not_stop_the_controller() -> None:
    """A window queue smaller than the pre-roll takes what fits, and goes on."""
    got = await utterances(
        script(SILENCE_30, SPEECH_10, (False, 60), SPEECH_10, SILENCE_40),
        2,
        window_queue_size=3,
    )

    assert all(got)  # both utterances reached the STT


async def test_whisper_starts_its_first_piece_in_the_preroll() -> None:
    """The first piece ``WhisperSTT`` transcribes begins at the pre-roll.

    That is the point of it: the piece has the audio before the VAD's first speech.
    """
    (got,) = await utterances(script(SILENCE_30, SPEECH_10, SILENCE_40), 1)
    stt = WhisperSTT(model_name="base")  # not started: only its piece buffering runs
    pieces: asyncio.Queue = asyncio.Queue()

    async def windows() -> AsyncIterator[SpeechWindow]:
        for window in got:
            yield window

    await stt._buffer_windows(windows(), pieces)  # noqa: SLF001
    data, start, _end, _speaker = pieces.get_nowait()

    assert start == pytest.approx((PENDING - PREROLL_WINDOWS) * WINDOW_S)
    assert struct.unpack("<I", data[:4])[0] == PENDING - PREROLL_WINDOWS
