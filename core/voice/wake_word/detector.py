"""
Wake word detector using OpenWakeWord.
Listens continuously on the mic. Calls callback when "Hey Vance" is detected.

OpenWakeWord uses pre-trained models for common phrases AND supports custom
trained models. To use a custom "Hey Vance" model, place the .onnx file in
wake_word/models/ and set model name in config.yaml.

For immediate use without training: OpenWakeWord includes "hey jarvis" and
"alexa" models built-in. Use "hey jarvis" as a placeholder until a custom
"hey vance" model is trained via trainer.py.
"""

import logging
from pathlib import Path
from typing import Callable

import numpy as np
import pyaudio
from openwakeword.model import Model

logger = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, config: dict, on_detected: Callable[[float], None]):
        """
        Args:
            config: wake_word section of config.yaml
            on_detected: callback fired when wake word is detected;
                         receives confidence score as argument
        """
        self.config = config
        self.on_detected = on_detected
        self.running = False

        # Load model — checks models/ dir first, falls back to built-in models
        model_path = Path(__file__).parent / "models" / f"{config['model']}.onnx"
        if model_path.exists():
            self.model = Model(
                wakeword_models=[str(model_path)],
                inference_framework=config["inference_framework"],
            )
            logger.info(f"Loaded custom wake word model: {model_path}")
        else:
            # Fallback: use OpenWakeWord's built-in "hey jarvis" until trained
            self.model = Model(
                wakeword_models=["hey_jarvis"],
                inference_framework=config["inference_framework"],
            )
            logger.warning(
                "Custom 'hey_vance' model not found in wake_word/models/. "
                "Using built-in 'hey_jarvis' as fallback. "
                "Run trainer.py to create a custom wake word."
            )

        self.chunk_size = config["chunk_size"]
        self.threshold = config["threshold"]

    def start(self) -> None:
        """Start continuous wake word listening in a blocking loop."""
        self.running = True
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=16000,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        logger.info("Wake word detector active — listening for 'Hey Vance'")

        try:
            while self.running:
                audio_chunk = np.frombuffer(
                    stream.read(self.chunk_size, exception_on_overflow=False),
                    dtype=np.int16,
                )
                prediction = self.model.predict(audio_chunk)

                for model_name, confidence in prediction.items():
                    if confidence >= self.threshold:
                        logger.info(f"Wake word detected (confidence: {confidence:.2f})")
                        self.on_detected(confidence)
                        self.model.reset()
                        break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def stop(self) -> None:
        self.running = False
