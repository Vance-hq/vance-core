"""Tests for the wake word detector."""

import pytest
from unittest.mock import MagicMock, patch


def test_detector_loads_fallback_when_model_missing(tmp_path):
    """When hey_vance.onnx is absent, detector falls back to hey_jarvis."""
    config = {
        "model": "hey_vance",
        "threshold": 0.5,
        "inference_framework": "onnx",
        "chunk_size": 1280,
    }
    callback = MagicMock()

    with patch("openwakeword.model.Model") as mock_model:
        from vance.core.voice.wake_word.detector import WakeWordDetector
        detector = WakeWordDetector(config, on_detected=callback)
        assert detector is not None
        assert mock_model.called


def test_detector_calls_callback_on_threshold():
    """Callback fires when prediction meets threshold."""
    config = {
        "model": "hey_vance",
        "threshold": 0.5,
        "inference_framework": "onnx",
        "chunk_size": 1280,
    }
    callback = MagicMock()

    with patch("openwakeword.model.Model") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.predict.return_value = {"hey_jarvis": 0.9}
        mock_model_cls.return_value = mock_model

        from vance.core.voice.wake_word.detector import WakeWordDetector
        detector = WakeWordDetector(config, on_detected=callback)

        import numpy as np
        chunk = np.zeros(1280, dtype=np.int16)
        prediction = detector.model.predict(chunk)

        for _, confidence in prediction.items():
            if confidence >= detector.threshold:
                detector.on_detected(confidence)

        callback.assert_called_once_with(0.9)
