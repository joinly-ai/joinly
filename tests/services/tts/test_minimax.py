"""Unit and integration tests for the MiniMax TTS service."""
import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from joinly.services.tts.minimax import MinimaxTTS
from joinly.types import AudioFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hex_audio(n_bytes: int = 64) -> str:
    """Return a hex string representing *n_bytes* bytes of fake PCM data."""
    return (b"\x00\x01" * (n_bytes // 2)).hex()


def _make_api_response(
    hex_audio: str | None = None,
    status_code: int = 0,
    status_msg: str = "success",
) -> dict:
    """Build a minimal MiniMax TTS API response dict."""
    return {
        "base_resp": {"status_code": status_code, "status_msg": status_msg},
        "data": {"audio": hex_audio or _make_hex_audio()},
    }


def _make_mock_session(resp_mock: AsyncMock) -> AsyncMock:
    """Wrap a response mock in a fake aiohttp.ClientSession."""
    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=resp_mock)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


async def _make_success_resp(hex_audio: str | None = None) -> AsyncMock:
    """Return a mock aiohttp response that simulates a 200 OK TTS reply."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=_make_api_response(hex_audio))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestMinimaxTTSInit:
    """Tests for MinimaxTTS initialisation."""

    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MinimaxTTS must raise ValueError when MINIMAX_API_KEY is not set."""
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MINIMAX_API_KEY"):
            MinimaxTTS()

    def test_default_audio_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default audio_format should be 32 kHz 16-bit PCM."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        tts = MinimaxTTS()
        assert tts.audio_format == AudioFormat(sample_rate=32000, byte_depth=2)

    def test_custom_sample_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom sample_rate is reflected in audio_format."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        tts = MinimaxTTS(sample_rate=24000)
        assert tts.audio_format.sample_rate == 24000

    def test_default_voice_english(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default voice for English should be English_Graceful_Lady."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        monkeypatch.setenv("JOINLY_LANGUAGE", "en")
        tts = MinimaxTTS()
        assert tts._voice_id == "English_Graceful_Lady"

    def test_custom_voice_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit voice_id overrides the language default."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        tts = MinimaxTTS(voice_id="Deep_Voice_Man")
        assert tts._voice_id == "Deep_Voice_Man"

    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default model should be speech-02-hd."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        tts = MinimaxTTS()
        assert tts._model == "speech-02-hd"

    def test_turbo_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """speech-02-turbo model can be selected."""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        tts = MinimaxTTS(model="speech-02-turbo")
        assert tts._model == "speech-02-turbo"


class TestMinimaxTTSStream:
    """Tests for MinimaxTTS.stream()."""

    @pytest.fixture
    def tts(self, monkeypatch: pytest.MonkeyPatch) -> MinimaxTTS:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        return MinimaxTTS()

    async def _collect(self, ait: AsyncIterator[bytes]) -> bytes:
        """Collect all chunks from an async iterator into bytes."""
        chunks = []
        async for chunk in ait:
            chunks.append(chunk)
        return b"".join(chunks)

    async def test_stream_returns_pcm_bytes(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should yield bytes decoded from the hex audio field."""
        hex_audio = _make_hex_audio(128)
        expected = bytes.fromhex(hex_audio)
        resp = await _make_success_resp(hex_audio)
        with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
            result = await self._collect(tts.stream("Hello world"))
        assert result == expected

    async def test_stream_chunks_large_audio(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Audio larger than chunk_size_bytes should be yielded in multiple chunks."""
        hex_audio = _make_hex_audio(8192)
        resp = await _make_success_resp(hex_audio)
        chunks = []
        with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
            async for chunk in tts.stream("Big text"):
                chunks.append(chunk)
        # With chunk_size_bytes=4096 and 8192 bytes input we expect ≥ 2 chunks
        assert len(chunks) >= 2
        assert b"".join(chunks) == bytes.fromhex(hex_audio)

    async def test_stream_raises_on_http_error(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should raise RuntimeError on non-200 HTTP status."""
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)),
            pytest.raises(RuntimeError, match="401"),
        ):
            async for _ in tts.stream("Hello"):
                pass

    async def test_stream_raises_on_api_error(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should raise RuntimeError when base_resp.status_code != 0."""
        error_response = {
            "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
            "data": {"audio": ""},
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=error_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)),
            pytest.raises(RuntimeError, match="1004"),
        ):
            async for _ in tts.stream("Hello"):
                pass

    async def test_stream_empty_audio_yields_nothing(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the API returns an empty audio field, stream() yields no chunks."""
        empty_response = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"audio": ""},
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=empty_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        with patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)):
            result = await self._collect(tts.stream("Silence"))
        assert result == b""

    async def test_stream_raises_on_network_error(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should raise RuntimeError when a network error occurs."""
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(
                side_effect=aiohttp.ServerConnectionError("Connection refused")
            ),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            pytest.raises(RuntimeError, match="HTTP request failed"),
        ):
            async for _ in tts.stream("Error"):
                pass

    async def test_stream_sends_correct_payload(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should POST the correct JSON payload to the MiniMax API."""
        hex_audio = _make_hex_audio(32)
        resp = await _make_success_resp(hex_audio)
        mock_session = _make_mock_session(resp)
        post_mock = mock_session.post
        with patch("aiohttp.ClientSession", return_value=mock_session):
            async for _ in tts.stream("Test payload"):
                pass
        _, kwargs = post_mock.call_args
        assert kwargs["json"]["text"] == "Test payload"
        assert kwargs["json"]["audio_setting"]["format"] == "pcm"
        assert kwargs["json"]["model"] == "speech-02-hd"
        assert "voice_setting" in kwargs["json"]
        assert "Authorization" in kwargs["headers"]

    async def test_stream_voice_setting_structure(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should use voice_setting object with voice_id, speed, vol, pitch."""
        hex_audio = _make_hex_audio(32)
        resp = await _make_success_resp(hex_audio)
        mock_session = _make_mock_session(resp)
        post_mock = mock_session.post
        with patch("aiohttp.ClientSession", return_value=mock_session):
            async for _ in tts.stream("Voice setting check"):
                pass
        _, kwargs = post_mock.call_args
        vs = kwargs["json"]["voice_setting"]
        assert vs["voice_id"] == "English_Graceful_Lady"
        assert vs["speed"] == 1.0
        assert vs["vol"] == 1.0
        assert vs["pitch"] == 0

    async def test_stream_uses_bearer_auth(
        self, tts: MinimaxTTS, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stream() should send an Authorization: Bearer header."""
        hex_audio = _make_hex_audio(32)
        resp = await _make_success_resp(hex_audio)
        mock_session = _make_mock_session(resp)
        post_mock = mock_session.post
        with patch("aiohttp.ClientSession", return_value=mock_session):
            async for _ in tts.stream("Auth check"):
                pass
        _, kwargs = post_mock.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"


# ---------------------------------------------------------------------------
# Integration tests (skipped unless MINIMAX_API_KEY is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("MINIMAX_API_KEY"),
    reason="MINIMAX_API_KEY not set; skipping live integration test",
)
class TestMinimaxTTSIntegration:
    """Live integration tests against the MiniMax TTS API."""

    @pytest.fixture
    def tts(self) -> MinimaxTTS:
        return MinimaxTTS()

    async def test_live_stream_returns_audio(self, tts: MinimaxTTS) -> None:
        """Live API call should return non-empty PCM audio bytes."""
        chunks = []
        async for chunk in tts.stream("Hello, this is a MiniMax TTS test."):
            chunks.append(chunk)
        audio = b"".join(chunks)
        assert len(audio) > 0

    async def test_live_stream_audio_format(self, tts: MinimaxTTS) -> None:
        """Live audio should match the declared audio_format (16-bit PCM)."""
        chunks = []
        async for chunk in tts.stream("Audio format check."):
            chunks.append(chunk)
        audio = b"".join(chunks)
        # PCM 16-bit: total bytes must be a multiple of byte_depth
        assert len(audio) % tts.audio_format.byte_depth == 0

    async def test_live_turbo_model(self) -> None:
        """Turbo model should also return valid audio."""
        tts = MinimaxTTS(model="speech-02-turbo")
        chunks = []
        async for chunk in tts.stream("Turbo speed test."):
            chunks.append(chunk)
        assert len(b"".join(chunks)) > 0
