"""
MegaNet Cryptographic Primitives
- Identity: Ed25519 (sign/verify)
- Key exchange: X25519 ECDH
- Encryption: ChaCha20-Poly1305
- Address: SHA3-256(ed25519_pub_raw)[:20]
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.exceptions import InvalidTag  # re-exported for callers


@dataclass
class KeyPair:
    ed25519_private: Ed25519PrivateKey
    ed25519_public: Ed25519PublicKey
    x25519_private: X25519PrivateKey
    x25519_public: X25519PublicKey
    address: bytes        # 20-byte node address
    address_hex: str      # 40-char hex string

    # Convenience: raw public key bytes for serialization
    @property
    def ed25519_public_bytes(self) -> bytes:
        return self.ed25519_public.public_bytes(Encoding.Raw, PublicFormat.Raw)

    @property
    def x25519_public_bytes(self) -> bytes:
        return self.x25519_public.public_bytes(Encoding.Raw, PublicFormat.Raw)


def generate_keypair() -> KeyPair:
    """Generate a fresh Ed25519+X25519 key pair with a MegaNet address."""
    ed_priv = Ed25519PrivateKey.generate()
    ed_pub = ed_priv.public_key()
    x_priv = X25519PrivateKey.generate()
    x_pub = x_priv.public_key()

    ed_pub_raw = ed_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    addr = node_address_from_public_key(ed_pub_raw)

    return KeyPair(
        ed25519_private=ed_priv,
        ed25519_public=ed_pub,
        x25519_private=x_priv,
        x25519_public=x_pub,
        address=addr,
        address_hex=addr.hex(),
    )


def node_address_from_public_key(pub_bytes: bytes) -> bytes:
    """Derive a 20-byte node address from a raw Ed25519 public key."""
    return hashlib.sha3_256(pub_bytes).digest()[:20]


def derive_shared_secret(
    our_x25519_priv: X25519PrivateKey,
    their_x25519_pub_bytes: bytes,
) -> bytes:
    """X25519 ECDH → 32-byte shared secret."""
    their_pub = X25519PublicKey.from_public_bytes(their_x25519_pub_bytes)
    return our_x25519_priv.exchange(their_pub)


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """
    ChaCha20-Poly1305 encrypt.
    Returns (nonce_12B, ciphertext_with_tag).
    """
    nonce = os.urandom(12)
    chacha = ChaCha20Poly1305(key)
    ciphertext = chacha.encrypt(nonce, plaintext, aad or None)
    return nonce, ciphertext


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    """
    ChaCha20-Poly1305 decrypt.
    Raises cryptography.exceptions.InvalidTag if authentication fails.
    """
    chacha = ChaCha20Poly1305(key)
    return chacha.decrypt(nonce, ciphertext, aad or None)


def sign(ed25519_priv: Ed25519PrivateKey, data: bytes) -> bytes:
    """Ed25519 sign → 64-byte signature."""
    return ed25519_priv.sign(data)


def verify(ed25519_pub_bytes: bytes, data: bytes, sig: bytes) -> bool:
    """Ed25519 verify. Returns False on bad signature instead of raising."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(ed25519_pub_bytes)
        pub.verify(sig, data)
        return True
    except Exception:
        return False
