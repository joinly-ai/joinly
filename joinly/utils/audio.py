import numpy as np

from joinly.types import AudioFormat, IncompatibleAudioFormatError

BYTE_DEPTH_16 = 2
BYTE_DEPTH_32 = 4


def convert_audio_format(
    data: bytes, source_format: AudioFormat, target_format: AudioFormat
) -> bytes:
    """Convert audio data from one format to another.

    Args:
        data: A byte string representing the audio data.
        source_format: An AudioFormat object representing the source format.
        target_format: An AudioFormat object representing the target format.

    Returns:
        bytes: The audio data converted to the target format.

    Raises:
        IncompatibleAudioFormatError: If the source and target formats are incompatible.
    """
    if source_format.sample_rate != target_format.sample_rate:
        msg = (
            f"Incompatible sample rates: source={source_format.sample_rate}, "
            f"target={target_format.sample_rate}. "
            "Sample rate conversion is not supported."
        )
        raise IncompatibleAudioFormatError(msg)

    if source_format.byte_depth == target_format.byte_depth:
        return data

    if (
        source_format.byte_depth == BYTE_DEPTH_32
        and target_format.byte_depth == BYTE_DEPTH_16
    ):
        floats = np.frombuffer(data, dtype=np.float32)
        ints = np.clip(floats * 32767.0, -32768, 32767).astype(np.int16)
        return ints.tobytes()

    if (
        source_format.byte_depth == BYTE_DEPTH_16
        and target_format.byte_depth == BYTE_DEPTH_32
    ):
        ints = np.frombuffer(data, dtype=np.int16)
        floats = ints.astype(np.float32) / 32767.0
        return floats.tobytes()

    msg = (
        f"Incompatible byte depths: source={source_format.byte_depth}, "
        f"target={target_format.byte_depth}. "
        "Only conversion between 16-bit and 32-bit PCM is supported."
    )
    raise IncompatibleAudioFormatError(msg)


def calculate_audio_duration_ns(byte_size: int, audio_format: AudioFormat) -> int:
    """Calculate the duration of audio data in nanoseconds.

    Args:
        byte_size: The size of the audio data in bytes.
        audio_format: An AudioFormat object containing sample rate and byte depth.

    Returns:
        int: The duration of the audio data in nanoseconds.
    """
    return (
        byte_size // audio_format.byte_depth * 1_000_000_000 // audio_format.sample_rate
    )


def calculate_audio_duration(byte_size: int, audio_format: AudioFormat) -> float:
    """Calculate the duration of audio data in seconds.

    Args:
        byte_size: The size of the audio data in bytes.
        audio_format: An AudioFormat object containing sample rate and byte depth.

    Returns:
        float: The duration of the audio data in seconds.
    """
    return byte_size / (audio_format.sample_rate * audio_format.byte_depth)
