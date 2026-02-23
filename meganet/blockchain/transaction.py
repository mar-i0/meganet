"""
MegaNet Blockchain Transactions

4 transaction types:
  NODE_REGISTER   - publish ed25519 + x25519 public keys
  ROUTING_UPDATE  - announce up to 10 known peers
  MESSAGE_RECEIPT - non-repudiable delivery proof
  DATA_ANCHOR     - anchor content hash + fragment count
"""
from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from meganet.crypto.keys import sign


class TxType(str, Enum):
    NODE_REGISTER = "NODE_REGISTER"
    ROUTING_UPDATE = "ROUTING_UPDATE"
    MESSAGE_RECEIPT = "MESSAGE_RECEIPT"
    DATA_ANCHOR = "DATA_ANCHOR"


class Transaction:
    def __init__(
        self,
        tx_type: TxType,
        sender_addr: str,        # 40-char hex
        payload: dict[str, Any],
        signature: bytes,
        sender_pub: bytes,       # raw Ed25519 pub (32B) for verification
    ):
        self.tx_type = tx_type
        self.sender_addr = sender_addr
        self.payload = payload
        self.signature = signature
        self.sender_pub = sender_pub
        self.timestamp = payload.get("timestamp", time.time())

        # tx_id computed from canonical form
        self.tx_id = self._compute_id()

    def _canonical(self) -> bytes:
        """Deterministic JSON serialization for signing/hashing."""
        obj = {
            "tx_type": self.tx_type.value,
            "sender_addr": self.sender_addr,
            "payload": self.payload,
        }
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

    def _compute_id(self) -> str:
        return hashlib.sha3_256(self._canonical()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "tx_type": self.tx_type.value,
            "sender_addr": self.sender_addr,
            "payload": self.payload,
            "signature": self.signature.hex(),
            "sender_pub": self.sender_pub.hex(),
        }

    def serialized_size(self) -> int:
        return len(json.dumps(self.to_dict(), separators=(",", ":")).encode())

    def verify_signature(self) -> bool:
        from meganet.crypto.keys import verify
        return verify(self.sender_pub, self._canonical(), self.signature)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            tx_type=TxType(d["tx_type"]),
            sender_addr=d["sender_addr"],
            payload=d["payload"],
            signature=bytes.fromhex(d["signature"]),
            sender_pub=bytes.fromhex(d["sender_pub"]),
        )


def _make_tx(
    tx_type: TxType,
    sender_addr: str,
    sender_pub_bytes: bytes,
    ed25519_priv: Ed25519PrivateKey,
    payload: dict,
) -> Transaction:
    payload["timestamp"] = time.time()
    canonical_obj = {
        "tx_type": tx_type.value,
        "sender_addr": sender_addr,
        "payload": payload,
    }
    canonical = json.dumps(canonical_obj, sort_keys=True, separators=(",", ":")).encode()
    sig = sign(ed25519_priv, canonical)
    return Transaction(tx_type, sender_addr, payload, sig, sender_pub_bytes)


def make_node_register(
    sender_addr: str,
    ed25519_pub_bytes: bytes,
    x25519_pub_bytes: bytes,
    ed25519_priv: Ed25519PrivateKey,
) -> Transaction:
    payload = {
        "ed25519_pub": ed25519_pub_bytes.hex(),
        "x25519_pub": x25519_pub_bytes.hex(),
    }
    return _make_tx(TxType.NODE_REGISTER, sender_addr, ed25519_pub_bytes, ed25519_priv, payload)


def make_routing_update(
    sender_addr: str,
    sender_pub_bytes: bytes,
    ed25519_priv: Ed25519PrivateKey,
    peers: list[str],          # up to 10 addr_hex strings
) -> Transaction:
    payload = {"peers": peers[:10]}
    return _make_tx(TxType.ROUTING_UPDATE, sender_addr, sender_pub_bytes, ed25519_priv, payload)


def make_message_receipt(
    sender_addr: str,
    sender_pub_bytes: bytes,
    ed25519_priv: Ed25519PrivateKey,
    msg_id: str,               # hex string
    receiver_addr: str,
) -> Transaction:
    payload = {"msg_id": msg_id, "receiver": receiver_addr}
    return _make_tx(TxType.MESSAGE_RECEIPT, sender_addr, sender_pub_bytes, ed25519_priv, payload)


def make_data_anchor(
    sender_addr: str,
    sender_pub_bytes: bytes,
    ed25519_priv: Ed25519PrivateKey,
    content_hash: str,         # hex string
    frag_count: int,
    ttl: int = 86400,
) -> Transaction:
    payload = {"content_hash": content_hash, "frag_count": frag_count, "ttl": ttl}
    return _make_tx(TxType.DATA_ANCHOR, sender_addr, sender_pub_bytes, ed25519_priv, payload)
