"""Unit tests for meganet.blockchain"""
import pytest

from meganet.blockchain.block import Block
from meganet.blockchain.chain import Blockchain, Mempool
from meganet.blockchain.transaction import (
    TxType,
    make_data_anchor,
    make_message_receipt,
    make_node_register,
    make_routing_update,
)
from meganet.crypto.keys import generate_keypair


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_register_tx(kp=None):
    if kp is None:
        kp = generate_keypair()
    return make_node_register(
        sender_addr=kp.address_hex,
        ed25519_pub_bytes=kp.ed25519_public_bytes,
        x25519_pub_bytes=kp.x25519_public_bytes,
        ed25519_priv=kp.ed25519_private,
    ), kp


# ── Genesis ─────────────────────────────────────────────────────────────────

def test_genesis_deterministic():
    g1 = Block.genesis()
    g2 = Block.genesis()
    assert g1.hash == g2.hash
    assert g1.index == 0
    assert g1.previous_hash == "0" * 64


def test_genesis_valid_pow():
    g = Block.genesis()
    assert g.hash.startswith("00")


# ── Block PoW ────────────────────────────────────────────────────────────────

def test_mine_block_valid():
    bc = Blockchain()
    kp = generate_keypair()
    tx, _ = _make_register_tx(kp)
    bc.add_transaction(tx)
    block = bc.mine_block(kp.address_hex, difficulty=2)
    assert block is not None
    assert block.hash.startswith("00")
    assert block.is_valid()
    assert block.index == 1
    assert block.previous_hash == bc.chain[0].hash


def test_mine_block_increments_height():
    bc = Blockchain()
    kp = generate_keypair()
    for _ in range(3):
        tx, _ = _make_register_tx()
        bc.add_transaction(tx)
    for i in range(3):
        block = bc.mine_block(kp.address_hex)
        assert block is not None
        assert block.index == i + 1
    assert bc.height == 3


# ── Mempool ──────────────────────────────────────────────────────────────────

def test_mempool_deduplication():
    pool = Mempool()
    tx, _ = _make_register_tx()
    assert pool.add(tx)
    assert not pool.add(tx)   # duplicate
    assert len(pool) == 1


def test_mempool_fifo_eviction():
    pool = Mempool()
    txs = []
    for _ in range(50):
        tx, _ = _make_register_tx()
        pool.add(tx)
        txs.append(tx)
    assert len(pool) == 50

    # Adding one more should evict the oldest
    extra, _ = _make_register_tx()
    pool.add(extra)
    assert len(pool) == 50
    # Original first tx should be gone
    pending_ids = {t.tx_id for t in pool.get_pending()}
    assert txs[0].tx_id not in pending_ids
    assert extra.tx_id in pending_ids


# ── Fork resolution ───────────────────────────────────────────────────────────

def test_fork_resolution_longer_chain_wins():
    bc1 = Blockchain()
    bc2 = Blockchain()
    kp = generate_keypair()

    # bc2 mines 2 blocks
    for _ in range(2):
        tx, _ = _make_register_tx()
        bc2.add_transaction(tx)
        bc2.mine_block(kp.address_hex)

    assert bc2.height == 2
    assert bc1.height == 0

    # bc1 adopts bc2's longer chain
    replaced = bc1.replace_chain(bc2.chain)
    assert replaced
    assert bc1.height == 2


def test_fork_resolution_rejects_shorter():
    bc1 = Blockchain()
    bc2 = Blockchain()
    kp = generate_keypair()

    # bc1 mines 1 block
    tx, _ = _make_register_tx()
    bc1.add_transaction(tx)
    bc1.mine_block(kp.address_hex)

    # bc2 is still at genesis — bc1 should NOT accept it
    replaced = bc1.replace_chain(bc2.chain)
    assert not replaced
    assert bc1.height == 1


def test_fork_resolution_invalid_chain_rejected():
    bc1 = Blockchain()
    bc2 = Blockchain()
    kp = generate_keypair()

    for _ in range(2):
        tx, _ = _make_register_tx()
        bc2.add_transaction(tx)
        bc2.mine_block(kp.address_hex)

    # Tamper with a block hash
    bc2.chain[1].hash = "tampered" + "0" * 57

    replaced = bc1.replace_chain(bc2.chain)
    assert not replaced


# ── State indices ─────────────────────────────────────────────────────────────

def test_node_registry_updated():
    bc = Blockchain()
    kp = generate_keypair()
    tx, _ = _make_register_tx(kp)
    bc.add_transaction(tx)
    bc.mine_block(kp.address_hex)

    assert kp.address_hex in bc.node_registry
    entry = bc.node_registry[kp.address_hex]
    assert entry["ed25519_pub"] == kp.ed25519_public_bytes.hex()
    assert entry["x25519_pub"] == kp.x25519_public_bytes.hex()


def test_message_receipt_state():
    bc = Blockchain()
    kp = generate_keypair()
    register_tx, _ = _make_register_tx(kp)
    bc.add_transaction(register_tx)

    receipt_tx = make_message_receipt(
        sender_addr=kp.address_hex,
        sender_pub_bytes=kp.ed25519_public_bytes,
        ed25519_priv=kp.ed25519_private,
        msg_id="deadbeef",
        receiver_addr=kp.address_hex,
    )
    bc.add_transaction(receipt_tx)
    bc.mine_block(kp.address_hex)

    assert "deadbeef" in bc.message_receipts


def test_data_anchor_state():
    bc = Blockchain()
    kp = generate_keypair()
    tx = make_data_anchor(
        sender_addr=kp.address_hex,
        sender_pub_bytes=kp.ed25519_public_bytes,
        ed25519_priv=kp.ed25519_private,
        content_hash="abcd1234" * 5,
        frag_count=3,
    )
    bc.add_transaction(tx)
    bc.mine_block(kp.address_hex)

    assert "abcd1234" * 5 in bc.data_anchors


# ── Transaction signature ────────────────────────────────────────────────────

def test_transaction_signature_valid():
    tx, _ = _make_register_tx()
    assert tx.verify_signature()


def test_transaction_tx_id_stable():
    tx, _ = _make_register_tx()
    assert tx.tx_id == tx._compute_id()
