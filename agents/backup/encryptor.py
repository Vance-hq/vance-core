"""AES-256-GCM encrypt/decrypt for backup files."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12  # 96-bit nonce for GCM


class BackupEncryptor:
    """
    Wraps AESGCM (AES-256-GCM) for backup file encryption.

    Key must be 32 bytes, base64-encoded, stored in BACKUP_ENCRYPTION_KEY.
    Output format: nonce (12 bytes) || ciphertext (includes 16-byte GCM tag).
    """

    def __init__(self, key_b64: str) -> None:
        raw = base64.b64decode(key_b64)
        if len(raw) != 32:
            raise ValueError(f"Encryption key must be 32 bytes, got {len(raw)}")
        self._aesgcm = AESGCM(raw)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, ciphertext_blob: bytes) -> bytes:
        nonce = ciphertext_blob[:_NONCE_BYTES]
        ciphertext = ciphertext_blob[_NONCE_BYTES:]
        return self._aesgcm.decrypt(nonce, ciphertext, None)
