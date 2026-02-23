"""
MegaNet Block with Proof-of-Work

- PoW: SHA3-256 hash must start with `difficulty` hex zeros
- difficulty=2 → ~256 iterations → ~1ms per block
- Max block data: 4096 bytes
- Genesis block is deterministic (prev_hash = "0"*64)
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transaction import Transaction

MAX_BLOCK_BYTES = 4096


class Block:
    def __init__(
        self,
        index: int,
        transactions: list["Transaction"],
        previous_hash: str,
        miner: str,           # addr_hex of miner
        difficulty: int = 2,
        timestamp: float | None = None,
        nonce: int = 0,
    ):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.miner = miner
        self.difficulty = difficulty
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.nonce = nonce
        self.hash = self._compute_hash()

    def _header_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "previous_hash": self.previous_hash,
            "miner": self.miner,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
        }

    def _compute_hash(self) -> str:
        raw = json.dumps(self._header_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha3_256(raw).hexdigest()

    def mine(self) -> None:
        """Increment nonce until hash starts with `difficulty` hex zeros."""
        prefix = "0" * self.difficulty
        while not self.hash.startswith(prefix):
            self.nonce += 1
            self.hash = self._compute_hash()

    def is_valid(self) -> bool:
        prefix = "0" * self.difficulty
        return self.hash == self._compute_hash() and self.hash.startswith(prefix)

    def to_dict(self) -> dict:
        d = self._header_dict()
        d["hash"] = self.hash
        return d

    @classmethod
    def genesis(cls) -> "Block":
        """Deterministic genesis block (block 0)."""
        b = cls(
            index=0,
            transactions=[],
            previous_hash="0" * 64,
            miner="0" * 40,
            difficulty=2,
            timestamp=0.0,
            nonce=0,
        )
        b.mine()
        return b

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        from .transaction import Transaction
        txs = [Transaction.from_dict(t) for t in d["transactions"]]
        b = cls(
            index=d["index"],
            transactions=txs,
            previous_hash=d["previous_hash"],
            miner=d["miner"],
            difficulty=d["difficulty"],
            timestamp=d["timestamp"],
            nonce=d["nonce"],
        )
        b.hash = d["hash"]
        return b
