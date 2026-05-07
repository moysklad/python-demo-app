from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DIR_MODE = 0o700
ENCRYPT_PREFIX = "enc:v1:"


def ensure_private_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    try:
        directory.chmod(DIR_MODE)
    except OSError:
        pass


def encrypt_sensitive(plain_text: str, raw_key: str) -> str:
    key = derive_encryption_key(raw_key)
    iv = os.urandom(12)
    encrypted = AESGCM(key).encrypt(iv, plain_text.encode("utf-8"), None)
    payload, tag = encrypted[:-16], encrypted[-16:]
    return f"{ENCRYPT_PREFIX}{_b64url(iv)}:{_b64url(payload)}:{_b64url(tag)}"


def decrypt_sensitive(cipher_text_or_plain: str, raw_key: str) -> str:
    if not cipher_text_or_plain.startswith(ENCRYPT_PREFIX):
        return cipher_text_or_plain

    encoded = cipher_text_or_plain[len(ENCRYPT_PREFIX):]
    parts = encoded.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted payload format")

    iv = _unb64url(parts[0])
    payload = _unb64url(parts[1])
    tag = _unb64url(parts[2])
    decrypted = AESGCM(derive_encryption_key(raw_key)).decrypt(iv, payload + tag, None)
    return decrypted.decode("utf-8")


def derive_encryption_key(raw_key: str) -> bytes:
    normalized = raw_key.strip()
    if len(normalized) != 64:
        raise ValueError("APP_ENCRYPT_KEY must be 64 hex characters")
    return bytes.fromhex(normalized)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
