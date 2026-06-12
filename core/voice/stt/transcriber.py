"""
Speech-to-text using faster-whisper.
faster-whisper is a 4x faster reimplementation of OpenAI Whisper using CTranslate2.
On CPU with base model: ~1-2 seconds for a 5-second utterance.
On GPU with large-v3: real-time or faster.
"""

import logging

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, config: dict):
        model_size = config["model_size"]
        device = config["device"]
        compute_type = config["compute_type"]

        logger.info(f"Loading Whisper model: {model_size} on {device} ({compute_type})")
        # Model downloads automatically on first run to ~/.cache/huggingface/
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.language = config["language"]
        self.beam_size = config["beam_size"]
        self.vad_filter = config["vad_filter"]
        logger.info("Whisper model loaded and ready")

    def transcribe(self, audio_bytes: bytes) -> str | None:
        """
        Transcribe raw PCM audio bytes to text.

        Args:
            audio_bytes: raw 16-bit mono 16kHz PCM audio

        Returns:
            Transcribed text string, or None if nothing detected
        """
        if not audio_bytes:
            return None

        # Convert raw PCM to float32 array (faster-whisper expects this)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_np,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        text_parts = [segment.text.strip() for segment in segments]
        full_text = " ".join(text_parts).strip()

        if not full_text:
            logger.debug("Transcription returned empty string")
            return None

        logger.info(
            f"Transcribed: '{full_text}' "
            f"(lang: {info.language}, prob: {info.language_probability:.2f})"
        )
        return full_text
