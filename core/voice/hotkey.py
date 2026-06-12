"""
Push-to-talk fallback — triggers recording on keyboard shortcut.
Runs in a background thread alongside the wake word detector.
Useful when: environment is noisy, wake word misfires, or faster response needed.
"""

import logging
import threading
from typing import Callable

from keyboard import add_hotkey, wait

logger = logging.getLogger(__name__)


class HotkeyListener:
    def __init__(self, config: dict, on_triggered: Callable[[float], None]):
        """
        Args:
            config: hotkey section of config.yaml
            on_triggered: callback to fire when hotkey pressed (same as wake word callback)
        """
        self.key_combo = config["key_combo"]
        self.on_triggered = on_triggered
        self.enabled = config["enabled"]

    def start(self) -> None:
        if not self.enabled:
            return

        def _listen() -> None:
            logger.info(f"PTT hotkey active — press {self.key_combo} to activate Vance")
            add_hotkey(self.key_combo, lambda: self.on_triggered(1.0))
            wait()

        thread = threading.Thread(target=_listen, daemon=True)
        thread.start()
