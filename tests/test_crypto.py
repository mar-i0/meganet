"""Unit tests for meganet.crypto.keys"""
import pytest
from cryptography.exceptions import InvalidTag

from meganet.crypto.keys import (
    decrypt,
    derive_shared_secret,
    encrypt,
    generate_keypair,
    node_address_from_public_key,
    sign,
    verify,
)


def test_generate_keypair():
    kp = generate_keypair()
    assert len(kp.address) == 20
    assert len(kp.address_hex) == 40
    assert kp.address == bytes.fromhex(kp.address_hex)


def test_address_derivation():
    kp = generate_keypair()
    expected = node_address_from_public_key(kp.ed25519_public_bytes)
    assert kp.address == expected


def test_ecdh_symmetric():
    """Both sides of ECDH must produce the same shared secret."""
    alice = generate_keypair()
    bob = generate_keypair()

    s_ab = derive_shared_secret(alice.x25519_private, bob.x25519_public_bytes)
    s_ba = derive_shared_secret(bob.x25519_private, alice.x25519_public_bytes)
    assert s_ab == s_ba
    assert len(s_ab) == 32


def test_encrypt_decrypt_roundtrip():
    kp = generate_keypair()
    other = generate_keypair()
    key = derive_shared_secret(kp.x25519_private, other.x25519_public_bytes)

    plaintext = b"Hello, MegaNet!"
    aad = b"test-aad"
    nonce, ciphertext = encrypt(key, plaintext, aad)

    assert len(nonce) == 12
    result = decrypt(key, nonce, ciphertext, aad)
    assert result == plaintext


def test_encrypt_decrypt_no_aad():
    kp = generate_keypair()
    other = generate_keypair()
    key = derive_shared_secret(kp.x25519_private, other.x25519_public_bytes)

    plaintext = b"No AAD message"
    nonce, ciphertext = encrypt(key, plaintext)
    result = decrypt(key, nonce, ciphertext)
    assert result == plaintext


def test_tamper_detection_raises():
    """Modifying ciphertext must raise InvalidTag."""
    kp = generate_keypair()
    other = generate_keypair()
    key = derive_shared_secret(kp.x25519_private, other.x25519_public_bytes)

    plaintext = b"Secret data"
    aad = b"aad"
    nonce, ciphertext = encrypt(key, plaintext, aad)

    # Tamper with a byte in the ciphertext
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    with pytest.raises(InvalidTag):
        decrypt(key, nonce, bytes(tampered), aad)


def test_tamper_aad_raises():
    """Modifying AAD must raise InvalidTag."""
    kp = generate_keypair()
    other = generate_keypair()
    key = derive_shared_secret(kp.x25519_private, other.x25519_public_bytes)

    plaintext = b"Secret"
    nonce, ciphertext = encrypt(key, plaintext, b"original-aad")
    with pytest.raises(InvalidTag):
        decrypt(key, nonce, ciphertext, b"different-aad")


def test_sign_verify():
    kp = generate_keypair()
    data = b"Sign this message"
    sig = sign(kp.ed25519_private, data)
    assert len(sig) == 64
    assert verify(kp.ed25519_public_bytes, data, sig)


def test_verify_wrong_key():
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    data = b"Message"
    sig = sign(kp1.ed25519_private, data)
    assert not verify(kp2.ed25519_public_bytes, data, sig)


def test_verify_tampered_data():
    kp = generate_keypair()
    data = b"Original"
    sig = sign(kp.ed25519_private, data)
    assert not verify(kp.ed25519_public_bytes, b"Tampered", sig)


def test_unique_addresses():
    """Every keypair must produce a unique address."""
    addrs = {generate_keypair().address_hex for _ in range(20)}
    assert len(addrs) == 20
