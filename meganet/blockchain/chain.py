"""
MegaNet Blockchain + Mempool

State indices maintained:
  node_registry[addr_hex]      → {ed25519_pub, x25519_pub}
  message_receipts[msg_id]     → {sender, receiver, block}
  data_anchors[content_hash]   → {frag_count, ttl, anchor_block}

Fork resolution: longest valid chain wins.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import TYPE_CHECKING

from .block import Block, MAX_BLOCK_BYTES
from .transaction import Transaction, TxType

if TYPE_CHECKING:
    pass

MEMPOOL_MAX = 50


class Mempool:
    def __init__(self):
        self._txs: OrderedDict[str, Transaction] = OrderedDict()

    def add(self, tx: Transaction) -> bool:
        """Add transaction; returns False if duplicate. Evicts oldest if full."""
        if tx.tx_id in self._txs:
            return False
        if len(self._txs) >= MEMPOOL_MAX:
            # FIFO eviction
            oldest_key = next(iter(self._txs))
            del self._txs[oldest_key]
        self._txs[tx.tx_id] = tx
        return True

    def remove(self, tx_id: str) -> None:
        self._txs.pop(tx_id, None)

    def get_pending(self) -> list[Transaction]:
        return list(self._txs.values())

    def __len__(self) -> int:
        return len(self._txs)

    def clear_committed(self, txs: list[Transaction]) -> None:
        for tx in txs:
            self.remove(tx.tx_id)


class Blockchain:
    def __init__(self):
        genesis = Block.genesis()
        self.chain: list[Block] = [genesis]
        self.mempool = Mempool()

        # State indices
        self.node_registry: dict[str, dict] = {}
        self.message_receipts: dict[str, dict] = {}
        self.data_anchors: dict[str, dict] = {}

    @property
    def height(self) -> int:
        return len(self.chain) - 1

    @property
    def latest_block(self) -> Block:
        return self.chain[-1]

    def add_transaction(self, tx: Transaction) -> bool:
        return self.mempool.add(tx)

    def mine_block(self, miner_addr: str, difficulty: int = 2) -> Block | None:
        """Select transactions from mempool (greedy ≤ MAX_BLOCK_BYTES), mine block."""
        pending = self.mempool.get_pending()
        selected: list[Transaction] = []
        total_bytes = 0

        for tx in pending:
            size = tx.serialized_size()
            if total_bytes + size <= MAX_BLOCK_BYTES - 300:  # 300B header overhead
                selected.append(tx)
                total_bytes += size

        block = Block(
            index=self.height + 1,
            transactions=selected,
            previous_hash=self.latest_block.hash,
            miner=miner_addr,
            difficulty=difficulty,
        )
        block.mine()

        if self._append_block(block):
            self.mempool.clear_committed(selected)
            return block
        return None

    def _apply_transaction(self, tx: Transaction, block_index: int) -> None:
        """Update state indices from a confirmed transaction."""
        if tx.tx_type == TxType.NODE_REGISTER:
            self.node_registry[tx.sender_addr] = {
                "ed25519_pub": tx.payload["ed25519_pub"],
                "x25519_pub": tx.payload["x25519_pub"],
            }
        elif tx.tx_type == TxType.MESSAGE_RECEIPT:
            msg_id = tx.payload["msg_id"]
            self.message_receipts[msg_id] = {
                "sender": tx.sender_addr,
                "receiver": tx.payload["receiver"],
                "block": block_index,
            }
        elif tx.tx_type == TxType.DATA_ANCHOR:
            ch = tx.payload["content_hash"]
            self.data_anchors[ch] = {
                "frag_count": tx.payload["frag_count"],
                "ttl": tx.payload.get("ttl", 86400),
                "anchor_block": block_index,
            }
        # ROUTING_UPDATE doesn't update persistent state here

    def _append_block(self, block: Block) -> bool:
        """Validate and append a block to the chain."""
        if not self._validate_block(block, self.latest_block):
            return False
        self.chain.append(block)
        for tx in block.transactions:
            self._apply_transaction(tx, block.index)
        return True

    def _validate_block(self, block: Block, prev: Block) -> bool:
        if block.index != prev.index + 1:
            return False
        if block.previous_hash != prev.hash:
            return False
        if not block.is_valid():
            return False
        return True

    def _validate_chain(self, chain: list[Block]) -> bool:
        if not chain:
            return False
        # Check genesis
        expected_genesis = Block.genesis()
        if chain[0].hash != expected_genesis.hash:
            return False
        for i in range(1, len(chain)):
            if not self._validate_block(chain[i], chain[i - 1]):
                return False
        return True

    def replace_chain(self, new_chain: list[Block]) -> bool:
        """Fork resolution: accept new_chain if it's longer and valid."""
        if len(new_chain) <= len(self.chain):
            return False
        if not self._validate_chain(new_chain):
            return False

        # Rebuild state from scratch
        self.chain = [new_chain[0]]
        self.node_registry.clear()
        self.message_receipts.clear()
        self.data_anchors.clear()

        for block in new_chain[1:]:
            self.chain.append(block)
            for tx in block.transactions:
                self._apply_transaction(tx, block.index)

        return True

    def get_block_by_index(self, index: int) -> Block | None:
        if 0 <= index < len(self.chain):
            return self.chain[index]
        return None
