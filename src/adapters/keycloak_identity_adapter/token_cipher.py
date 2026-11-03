from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from use_case_contracts.errors import BrowserLoginFailedError


class KeycloakTokenCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Keycloak token encryption key must be 32 bytes.")
        self._aesgcm = AESGCM(key)

    def encrypt(self, payload: dict[str, Any]) -> bytes:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, b"rtmf:keycloak:v1")
        envelope = {
            "v": 1,
            "n": _b64(nonce),
            "c": _b64(ciphertext),
        }
        return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("ascii")

    def decrypt(self, encrypted: bytes) -> dict[str, Any]:
        try:
            envelope = json.loads(encrypted.decode("ascii"))
            if envelope.get("v") != 1:
                raise ValueError("unsupported encrypted provider state")
            nonce = _unb64(envelope["n"])
            ciphertext = _unb64(envelope["c"])
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, b"rtmf:keycloak:v1")
            payload = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise BrowserLoginFailedError("Login failed.") from exc
        if not isinstance(payload, dict):
            raise BrowserLoginFailedError("Login failed.")
        return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))
