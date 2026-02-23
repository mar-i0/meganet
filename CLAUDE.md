# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview
MegaNet MVP: prototype of Kim Dotcom's parallel decentralised internet.
Non-IP addressed, LoRaWAN-simulated radio, own blockchain (PoW), E2E encryption,
Kademlia DHT routing. Pure Python, single external dependency: `cryptography`.

## Commands

```bash
# Create venv & install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run all unit tests (3 test files, 42+ tests)
.venv/bin/pytest tests/ -v

# Run a single test file or test
.venv/bin/pytest tests/test_crypto.py -v
.venv/bin/pytest tests/test_blockchain.py::test_mine_block_valid -v

# Run end-to-end demo
.venv/bin/python main.py

# Generate PDF report + conference PPTX (requires fpdf2, python-pptx)
.venv/bin/python generate_docs.py
.venv/bin/python generate_exec_ppt.py
```

## Architecture

```
meganet/
├── crypto/keys.py          Ed25519 identity + X25519 ECDH + ChaCha20-Poly1305
├── blockchain/
│   ├── transaction.py      4 tx types: NODE_REGISTER, ROUTING_UPDATE, MESSAGE_RECEIPT, DATA_ANCHOR
│   ├── block.py            Block + SHA3-256 PoW (difficulty=2)
│   └── chain.py            Blockchain + Mempool (max 50 txs, FIFO eviction)
├── lora/
│   ├── packet.py           LoRaPacket (19B header + payload), SF7-SF12 + SF_SENSITIVITY table
│   ├── gateway.py          DutyCycleTracker (1%/hr sliding window) + LoRaGateway
│   └── simulator.py        Log-distance path loss (n=2.7, PL0=112dB) + sigmoid delivery prob
│                           5 default gateways on a 20×20 km grid (4 corners + centre)
├── routing/
│   ├── table.py            Kademlia RoutingTable (160 buckets, k=20)
│   └── dht.py              fragment_message / reassemble_message / ContentStore
├── network/simulator.py    NetworkSimulator: topology, churn, partition/heal
└── node/node.py            MegaNetNode: integration point (crypto+blockchain+lora+dht)
```

## Key Design Parameters

| Parameter       | Value                                      |
|-----------------|--------------------------------------------|
| Address space   | SHA3-256(ed25519_pub)[:20] = 160-bit       |
| Fragment size   | 203 B (SF7: 222B payload - 19B header)     |
| Duty cycle      | 1% / 1-hour sliding window (EU868)         |
| PoW difficulty  | 2 hex zeros (~256 iterations, ~1ms)        |
| Block limit     | 4096 bytes                                 |
| Path loss       | n=2.7, PL0=112 dB @ 1km (EU868 practical) |
| Encryption      | X25519 ECDH -> ChaCha20-Poly1305           |

## Blockchain State Indices

`Blockchain` maintains three in-memory dicts rebuilt from the chain on each accepted block:
- `node_registry`: `addr_hex → {ed25519_pub, x25519_pub, position, ...}` — populated by NODE_REGISTER txs; used by `send_message` to look up recipient X25519 keys.
- `message_receipts`: `msg_id → {receiver, block_index, ...}` — populated by MESSAGE_RECEIPT txs.
- `data_anchors`: `content_hash → {frag_count, sender, block_index, ...}` — populated by DATA_ANCHOR txs.

## Data Flow (A->B message)
1. Lookup B.x25519_pub in blockchain.node_registry
2. ECDH: shared_secret = derive(A.x25519_priv, B.x25519_pub)
3. Encrypt: (nonce, ct) = ChaCha20-Poly1305(shared_secret, plaintext, aad=A.addr+B.addr)
4. wire = A.addr(20B) + nonce(12B) + ct
5. fragment_message(wire) -> chunks <=203B
6. LoRaPacket per chunk -> LoRaSimulator.transmit() -> path loss -> gateways
7. B.receive_packets() -> reassembly buffer -> decrypt -> B.inbox
8. MESSAGE_RECEIPT tx -> mempool -> mine_block() -> broadcast -> on-chain proof

## NetworkSimulator Bootstrap Sequence

`net.bootstrap()` performs: register_all() → sync_blockchain() (mempool propagation) → mine_and_broadcast(first_node) → sync_blockchain() → update_routing_table_from_blockchain() on all nodes. Always call `bootstrap()` before sending messages; `send_message` will return `None` if the receiver is not in `node_registry`.
