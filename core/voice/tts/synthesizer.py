"""
Text-to-speech using Coqui TTS with XTTS-v2.

XTTS-v2 is a multilingual TTS model that supports voice cloning from a short
audio sample. Place a clean 6-second WAV of your chosen voice in:
  vance/core/voice/tts/voice_samples/vance.wav

Recording instructions for voice sample:
  - 6-10 seconds of clear speech
  - No background noise
  - Normal speaking pace
  - 22050 Hz or higher sample rate
  - Mono or stereo both work

If no sample is provided, XTTS-v2 uses a default built-in voice.

On first run: XTTS-v2 model (~2GB) downloads automatically.
Subsequent runs: loaded from cache, ~3-4 seconds startup time.
"""

import logging
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from TTS.api import TTS

logger = logging.getLogger(__name__)


class Synthesizer:
    def __init__(self, config: dict):
        self.config = config
        self.speaker_wav: str | None = None

        sample_path = Path(__file__).parent / "voice_samples" / "vance.wav"
        if sample_path.exists():
            self.speaker_wav = str(sample_path)
            logger.info(f"Voice cloning enabled — using sample: {sample_path}")
        else:
            logger.warning(
                "No voice sample found at tts/voice_samples/vance.wav. "
                "Using default XTTS-v2 voice. Add a 6-second WAV to enable voice cloning."
            )

        logger.info("Loading XTTS-v2 model (first run downloads ~2GB)...")
        self.tts = TTS(model_name=config["model"], gpu=config["use_gpu"])
        logger.info("TTS model ready")

        self.language = config["language"]
        self.speed = config["speed"]

    def speak(self, text: str) -> None:
        """
        Synthesize text and play audio immediately.
        Blocks until audio playback completes.
        """
        if not text or not text.strip():
            return

        logger.info(f"Speaking: '{text[:80]}{'...' if len(text) > 80 else ''}'")

        try:
            kwargs = {"text": text, "language": self.language, "speed": self.speed}
            if self.speaker_wav:
                kwargs["speaker_wav"] = self.speaker_wav

            audio = self.tts.tts(**kwargs)

            # XTTS-v2 returns float32 at 24kHz
            audio_np = np.array(audio, dtype=np.float32)
            sd.play(audio_np, samplerate=24000)
            sd.wait()

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")

    def speak_async(self, text: str) -> threading.Thread:
        """Non-blocking version — returns immediately, audio plays in background."""
        thread = threading.Thread(target=self.speak, args=(text,), daemon=True)
        thread.start()
        return thread
