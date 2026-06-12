"""
Records audio after wake word detection.
Uses WebRTC VAD to detect when the user has stopped speaking.
Returns raw PCM audio bytes ready for transcription.
"""

import logging

import pyaudio
import webrtcvad

logger = logging.getLogger(__name__)


class AudioCapture:
    def __init__(self, config: dict):
        self.sample_rate = config["sample_rate"]         # Must be 16000
        self.silence_threshold_ms = config["silence_threshold_ms"]
        self.max_duration_s = config["max_record_duration_s"]
        self.chunk_duration_ms = config["chunk_duration_ms"]

        # VAD aggressiveness: 0=least aggressive, 3=most aggressive
        # 2 works well for office environments
        self.vad = webrtcvad.Vad(2)

        self.chunk_samples = int(self.sample_rate * self.chunk_duration_ms / 1000)
        self.silence_chunks = int(self.silence_threshold_ms / self.chunk_duration_ms)

    def record(self) -> bytes | None:
        """
        Record until silence detected or max duration reached.
        Returns raw PCM audio bytes (16-bit, mono, 16kHz), or None on error.
        """
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=self.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.chunk_samples,
        )

        logger.info("Recording...")
        frames = []
        silent_chunks = 0
        max_chunks = int(self.max_duration_s * 1000 / self.chunk_duration_ms)

        try:
            for _ in range(max_chunks):
                chunk = stream.read(self.chunk_samples, exception_on_overflow=False)
                frames.append(chunk)

                # webrtcvad requires exactly 10, 20, or 30ms frames at 16kHz
                is_speech = self.vad.is_speech(chunk, self.sample_rate)

                if not is_speech:
                    silent_chunks += 1
                    if silent_chunks >= self.silence_chunks:
                        logger.info(
                            f"Silence detected — stopping ({len(frames)} chunks recorded)"
                        )
                        break
                else:
                    silent_chunks = 0

        except Exception as e:
            logger.error(f"Audio capture error: {e}")
            return None
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        return b"".join(frames) if frames else None
