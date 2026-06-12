"""Tests for the TTS synthesizer."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def tts_config():
    return {
        "model": "tts_models/multilingual/multi-dataset/xtts_v2",
        "speaker_wav": "voice_samples/vance.wav",
        "language": "en",
        "speed": 1.05,
        "use_gpu": False,
    }


def test_synthesizer_loads(tts_config):
    with patch("TTS.api.TTS") as mock_tts_cls:
        mock_tts_cls.return_value = MagicMock()
        from vance.core.voice.tts.synthesizer import Synthesizer
        s = Synthesizer(tts_config)
        assert s.tts is not None
        assert s.language == "en"


def test_speak_skips_empty_string(tts_config):
    with patch("TTS.api.TTS") as mock_tts_cls:
        mock_tts = MagicMock()
        mock_tts_cls.return_value = mock_tts

        from vance.core.voice.tts.synthesizer import Synthesizer
        s = Synthesizer(tts_config)
        s.speak("")
        s.speak("   ")

        mock_tts.tts.assert_not_called()


def test_speak_async_returns_thread(tts_config):
    import threading
    with patch("TTS.api.TTS") as mock_tts_cls:
        mock_tts = MagicMock()
        mock_tts.tts.return_value = [0.0] * 24000  # 1 second of silence
        mock_tts_cls.return_value = mock_tts

        with patch("sounddevice.play"), patch("sounddevice.wait"):
            from vance.core.voice.tts.synthesizer import Synthesizer
            s = Synthesizer(tts_config)
            t = s.speak_async("Hello Vance.")
            assert isinstance(t, threading.Thread)
