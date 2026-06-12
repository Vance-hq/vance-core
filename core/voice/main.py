"""
Vance Voice Layer — main entry point.

Loop:
  1. Listen for wake word ("Hey Vance") continuously
  2. On detection: play chime, start recording
  3. Recording stops on silence or max duration
  4. Transcribe audio → raw text
  5. Parse raw text → VoiceIntent
  6. Dispatch VoiceIntent to orchestrator
  7. Receive spoken_response from orchestrator
  8. Synthesize and play response via TTS
  9. Return to step 1

Runs as a persistent local process. Never deployed to Contabo.
Start with: python -m vance.core.voice.main
"""

import logging
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("vance.voice")

CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


def load_chime() -> np.ndarray | None:
    if not CONFIG["feedback"]["activation_sound"]:
        return None
    chime_path = Path(__file__).parent / CONFIG["feedback"]["activation_sound_file"]
    if chime_path.exists():
        import wave
        with wave.open(str(chime_path)) as wf:
            frames = wf.readframes(wf.getnframes())
            return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return None


# Re-export for import as a module (used by __init__.py)
class VoiceLayer:
    """Thin wrapper so other modules can reference the voice layer type."""
    pass


def main() -> None:
    from .wake_word.detector import WakeWordDetector
    from .capture.audio_capture import AudioCapture
    from .stt.transcriber import Transcriber
    from .intent.parser import IntentParser
    from .tts.synthesizer import Synthesizer
    from .dispatcher import VoiceDispatcher
    from .hotkey import HotkeyListener

    logger.info("=" * 50)
    logger.info("  VANCE VOICE LAYER STARTING")
    logger.info("=" * 50)

    capture = AudioCapture(CONFIG["audio"])
    transcriber = Transcriber(CONFIG["stt"])
    parser = IntentParser(CONFIG["intent"])
    synthesizer = Synthesizer(CONFIG["tts"])
    dispatcher = VoiceDispatcher(CONFIG["orchestrator"])

    session_context: list[dict] = []
    chime = load_chime()
    is_processing = threading.Event()

    def on_wake_word_detected(confidence: float) -> None:
        if is_processing.is_set():
            logger.debug("Already processing — ignoring activation")
            return

        is_processing.set()
        try:
            if chime is not None:
                sd.play(chime, samplerate=16000)
                sd.wait()

            logger.info("Activated — listening...")

            audio_bytes = capture.record()
            if not audio_bytes:
                synthesizer.speak("I didn't catch that.")
                return

            raw_text = transcriber.transcribe(audio_bytes)
            if not raw_text:
                synthesizer.speak("I didn't catch that.")
                return

            logger.info(f"Heard: '{raw_text}'")

            intent = parser.parse(raw_text, session_context)

            if intent.confidence_level.value == "low":
                synthesizer.speak(
                    f"I heard '{raw_text}' but I'm not sure what you want. Can you rephrase?"
                )
                return

            spoken_response = dispatcher.dispatch(intent)

            session_context.append(
                {
                    "raw_text": raw_text,
                    "intent": intent.intent,
                    "product": intent.product,
                    "timestamp": intent.timestamp.isoformat(),
                }
            )
            if len(session_context) > CONFIG["intent"]["max_context_turns"]:
                session_context.pop(0)

            synthesizer.speak(spoken_response)

        except Exception as e:
            logger.error(f"Voice loop error: {e}", exc_info=True)
            synthesizer.speak("Something went wrong. Check the logs.")
        finally:
            is_processing.clear()

    detector = WakeWordDetector(CONFIG["wake_word"], on_detected=on_wake_word_detected)

    hotkey = HotkeyListener(CONFIG["hotkey"], on_triggered=on_wake_word_detected)
    hotkey.start()

    synthesizer.speak("Vance is ready.")
    logger.info("Voice layer ready. Say 'Hey Vance' or press Ctrl+Shift+V.")

    try:
        detector.start()
    except KeyboardInterrupt:
        logger.info("Voice layer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
