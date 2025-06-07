import numpy as np

BYTE_DEPTH_16 = 2
BYTE_DEPTH_32 = 4


def convert_byte_depth(data: bytes, source_depth: int, target_depth: int) -> bytes:
    """Convert the byte depth of the audio data.

    Args:
        data: A byte string representing the audio data.
        source_depth: The byte depth of the source audio data.
        target_depth: The desired byte depth for the output audio data.

    Returns:
        bytes: The audio data converted to the target byte depth.

    Raises:
        ValueError: If the source and target byte depths are incompatible.
    """
    if source_depth == target_depth:
        return data

    if source_depth == BYTE_DEPTH_32 and target_depth == BYTE_DEPTH_16:
        floats = np.frombuffer(data, dtype=np.float32)
        ints = np.clip(floats * 32767.0, -32768, 32767).astype(np.int16)
        return ints.tobytes()

    if source_depth == BYTE_DEPTH_16 and target_depth == BYTE_DEPTH_32:
        ints = np.frombuffer(data, dtype=np.int16)
        floats = ints.astype(np.float32) / 32767.0
        return floats.tobytes()

    msg = (
        f"Incompatible byte depths: source={source_depth}, target={target_depth}. "
        "Only conversion between 16-bit and 32-bit PCM is supported."
    )
    raise ValueError(msg)
