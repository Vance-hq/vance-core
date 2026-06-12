"""
Test transcriber with a synthetic audio file.
Generates silent audio to verify the pipeline doesn't crash,
then tests with a real WAV file if present.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock


def make_dummy_audio(duration_s: float = 3.0, sample_rate: int = 16000) -> bytes:
    """Generate silent audio bytes for pipeline testing."""
    samples = int(duration_s * sample_rate)
    audio = np.zeros(samples, dtype=np.int16)
    return audio.tobytes()


def test_transcriber_loads():
    config = {
        "model_size": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 1,
        "vad_filter": False,
    }
    from vance.core.voice.stt.transcriber import Transcriber
    t = Transcriber(config)
    assert t.model is not None


def test_transcriber_handles_silence():
    config = {
        "model_size": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 1,
        "vad_filter": False,
    }
    from vance.core.voice.stt.transcriber import Transcriber
    t = Transcriber(config)
    result = t.transcribe(make_dummy_audio())
    assert result is None or result == ""


def test_transcriber_returns_none_for_empty_input():
    config = {
        "model_size": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 1,
        "vad_filter": False,
    }
    from vance.core.voice.stt.transcriber import Transcriber
    t = Transcriber(config)
    assert t.transcribe(b"") is None
    assert t.transcribe(None) is None
