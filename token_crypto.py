"""Simple token encryption using stdlib only (AES-like XOR cipher with HMAC)."""
import base64
import hashlib
import hmac
import os

import config


def _derive_key() -> bytes:
    return hashlib.sha256(config.SECRET_KEY.encode()).digest()


def encrypt_token(token: str) -> str:
    if not token:
        return ""
    key = _derive_key()
    token_bytes = token.encode()
    # Generate random IV
    iv = os.urandom(16)
    # XOR-based stream cipher using HMAC-derived keystream
    keystream = b""
    block = iv
    while len(keystream) < len(token_bytes):
        block = hmac.new(key, block, hashlib.sha256).digest()
        keystream += block
    encrypted = bytes(a ^ b for a, b in zip(token_bytes, keystream))
    # MAC for integrity
    mac = hmac.new(key, iv + encrypted, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(iv + encrypted + mac).decode()


def decrypt_token(token: str) -> str:
    if not token:
        return ""
    key = _derive_key()
    raw = base64.urlsafe_b64decode(token.encode())
    iv = raw[:16]
    mac = raw[-16:]
    encrypted = raw[16:-16]
    # Verify MAC
    expected_mac = hmac.new(key, iv + encrypted, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("Token integrity check failed")
    # Decrypt
    keystream = b""
    block = iv
    while len(keystream) < len(encrypted):
        block = hmac.new(key, block, hashlib.sha256).digest()
        keystream += block
    decrypted = bytes(a ^ b for a, b in zip(encrypted, keystream))
    return decrypted.decode()
