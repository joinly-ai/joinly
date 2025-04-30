import asyncio
from contextlib import AsyncExitStack

import jiwer

from meeting_agent.browser.meeting_browser import MeetingBrowser
from meeting_agent.capture.audio_capturer import AudioCapturer
from meeting_agent.capture.audio_sink import AudioSink
from meeting_agent.transcription.audio_transcriber import AudioTranscriber
from meeting_agent.transcription.vad_chunker import VADChunker


def _calculate_wer(
    transcription: str,
    ground_truth_transcription: str,
) -> float:
    """Calculates Word Error Rate between transcription and ground truth.

    Args:
        transcription: The transcription to compare.
        ground_truth_transcription: The expected transcription.

    Returns:
        The Word Error Rate (lower is better, 0 is perfect).
    """
    return jiwer.wer(ground_truth_transcription.lower(), transcription.lower())


async def run_meeting_transcription_test(
    meeting_url: str,
    ground_truth_transcription: str,
    duration_seconds: int = 30,
    max_wer_threshold: float = 0.1,
) -> None:
    """Executes a meeting transcription test by joining a meeting and processing audio.

    This function sets up a test environment with browser, audio capture, VAD chunking,
    and transcription components to verify the audio transcription pipeline.

    Args:
        meeting_url: URL for the meeting to join
        ground_truth_transcription: Expected text in the transcription
        duration_seconds: How long to collect transcriptions (in seconds)
        max_wer_threshold: Maximum acceptable Word Error Rate (default 0.1 or 10%)
    """
    audio_sink = AudioSink()
    audio_capturer = AudioCapturer(audio_sink.sink_name)
    vad_chunker = VADChunker(audio_capturer)
    audio_transcriber = AudioTranscriber(vad_chunker)

    meeting_browser = MeetingBrowser(
        meeting_url=meeting_url,
        participant_name="Test Participant",
        audio_sink_name=audio_sink.sink_name,
        headless=True,
    )

    services = [
        audio_sink,
        audio_capturer,
        vad_chunker,
        audio_transcriber,
        meeting_browser,
    ]

    transcription_agg = []
    async with AsyncExitStack() as stack:
        for svc in services:
            await stack.enter_async_context(svc)

        await meeting_browser.join()

        try:
            async with asyncio.timeout(duration_seconds):
                async for text in audio_transcriber:
                    transcription_agg.append(text)  # noqa: PERF401
        except TimeoutError:
            pass

    assert transcription_agg, "No transcription received"
    transcription = " ".join(transcription_agg)

    wer = _calculate_wer(transcription, ground_truth_transcription)
    assert wer <= max_wer_threshold, (
        f"Transcription quality below threshold. WER: {wer:.2f}, "
        f"Max allowed: {max_wer_threshold:.2f}\n"
        f'Transcription: "{transcription}"\n'
        f'Ground truth: "{ground_truth_transcription}"'
    )
