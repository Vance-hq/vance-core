"""
Custom "Hey Vance" wake word trainer.

OpenWakeWord supports training custom wake words using:
  1. Text-to-speech generated positive samples (automated)
  2. Your own recorded samples (optional, improves accuracy)

Run this script ONCE to generate a custom "hey_vance" model.
Output: wake_word/models/hey_vance.onnx

Requirements: ~30 minutes, internet connection for TTS generation.
The generated model drops false positive rate significantly vs the
"hey_jarvis" fallback.

Usage:
  python -m vance.core.voice.wake_word.trainer
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def train_hey_vance() -> None:
    """
    Train a custom wake word model for "Hey Vance".

    OpenWakeWord's training pipeline:
    1. Generates ~5000 TTS samples of "Hey Vance" using various TTS voices
    2. Generates negative samples (other phrases, background noise)
    3. Fine-tunes the base model on these samples
    4. Exports to ONNX format
    """
    try:
        from openwakeword.train import train_model
    except ImportError:
        print(
            "Training requires openwakeword[train] extras.\n"
            "Install with: pip install openwakeword[train]\n"
            "Or use the fallback 'hey_jarvis' model until you're ready to train."
        )
        return

    output_dir = Path(__file__).parent / "models"
    output_dir.mkdir(exist_ok=True)

    logger.info("Starting 'Hey Vance' wake word training...")
    logger.info("This will take ~20-30 minutes and requires internet for TTS sample generation.")

    train_model(
        target_phrase="hey vance",
        output_dir=str(output_dir),
        model_name="hey_vance",
        n_samples=5000,
        false_positive_rate=0.5,
    )

    logger.info(f"Custom wake word model saved to: {output_dir}/hey_vance.onnx")
    logger.info("Update config.yaml: wake_word.model = 'hey_vance'")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train_hey_vance()
