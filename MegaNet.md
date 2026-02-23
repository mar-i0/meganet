# MegaNet MVP — Technical Report
## Internet Paralela Descentralizada
**Version:** 1.0 MVP
**Date:** 2026-02-23
**Stack:** Python 3.13 · cryptography 42+ · LoRaWAN EU868 simulation

---

## 1. Executive Summary

MegaNet is a proof-of-concept implementation of Kim Dotcom's vision of a parallel,
decentralised internet that does not rely on the traditional IP address space.
Key properties:

- **Public-key addressing** — nodes are identified by `SHA3-256(ed25519_pub)[:20]`,
  a 160-bit address derived from cryptographic identity, not from a registry or ISP allocation.
- **LoRaWAN radio simulation** — a physics-accurate propagation model (log-distance,
  path-loss exponent 2.7) replaces real radio hardware for the MVP.
- **Own lightweight blockchain** — Proof-of-Work blockchain (SHA3-256, difficulty 2)
  used for node registration, routing updates, delivery receipts, and content anchoring.
- **End-to-end encryption** — X25519 ECDH key exchange + ChaCha20-Poly1305 AEAD,
  optimised for IoT/LoRa constrained environments.
- **Homeless data** — messages fragmented into 203-byte chunks distributed across
  the network, content-addressed by SHA3-256 hash (no central server).
- **Kademlia DHT routing** — 160-bucket routing table with XOR distance metric (k=20).

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        MegaNetNode                               │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  Crypto  │  │ Blockchain │  │LoRa PHY  │  │ Kademlia DHT │  │
│  │  Layer   │  │  (local)   │  │Simulator │  │RoutingTable  │  │
│  └────┬─────┘  └─────┬──────┘  └────┬─────┘  └──────┬───────┘  │
│       │               │              │                │           │
│       └───────────────┴──────────────┴────────────────┘           │
│                          Integration                              │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 Module Map

| Module | File | Responsibility |
|--------|------|----------------|
| **Crypto** | `meganet/crypto/keys.py` | Key generation, ECDH, ChaCha20-Poly1305, Ed25519 |
| **Transaction** | `meganet/blockchain/transaction.py` | 4 TX types, canonical JSON signing |
| **Block** | `meganet/blockchain/block.py` | PoW mining, genesis, serialisation |
| **Chain** | `meganet/blockchain/chain.py` | State indices, fork resolution, mempool |
| **LoRa Packet** | `meganet/lora/packet.py` | 19-byte header, SF7-SF12 parameters |
| **Gateway** | `meganet/lora/gateway.py` | Duty-cycle tracker (1%/hr), RX queue |
| **LoRa Sim** | `meganet/lora/simulator.py` | Path loss, sigmoid delivery prob, 5 gateways |
| **Routing Table** | `meganet/routing/table.py` | Kademlia k-buckets (160-bit XOR space) |
| **DHT** | `meganet/routing/dht.py` | Fragmentation, reassembly, content store |
| **Network Sim** | `meganet/network/simulator.py` | Topology, churn, partition/heal |
| **Node** | `meganet/node/node.py` | Central integration, send/receive pipeline |

---

## 3. Cryptographic Design

### 3.1 Node Identity & Addressing

Each node generates two key pairs at startup:

```
Ed25519  ─── identity / signature
X25519   ─── Diffie-Hellman key exchange (ephemeral per session)

Address = SHA3-256(ed25519_public_key_raw_bytes)[:20]   → 160-bit
```

The address is **never registered with a central authority**. It is published
on-chain via a `NODE_REGISTER` transaction so peers can look up the X25519 key
needed to encrypt messages to that node.

### 3.2 Message Encryption (A → B)

```
shared_secret = X25519(A.x25519_priv, B.x25519_pub)       # 32 bytes
aad           = A.addr_bytes + B.addr_bytes                 # 40 bytes
nonce         = os.urandom(12)                              # 96-bit random
ciphertext    = ChaCha20-Poly1305.encrypt(shared_secret, plaintext, aad, nonce)
wire          = A.addr(20B) + nonce(12B) + ciphertext
```

The AAD (Additional Authenticated Data) binds the ciphertext to the sender-receiver
pair; tampering with either address causes authentication to fail.

### 3.3 Signature Scheme

All blockchain transactions are signed with Ed25519:

```
canonical_bytes = JSON({"tx_type":..., "sender_addr":..., "payload":...}, sort_keys=True)
signature       = Ed25519.sign(ed25519_private, canonical_bytes)
tx_id           = SHA3-256(canonical_bytes).hex()
```

---

## 4. Blockchain

### 4.1 Block Structure

```
Block {
  index          : int
  timestamp      : float (Unix seconds)
  transactions   : List[Transaction]   (≤ 4096 bytes total)
  previous_hash  : str (64-char SHA3-256 hex)
  miner          : str (40-char addr hex)
  difficulty     : int (2 for MVP)
  nonce          : int
  hash           : SHA3-256(canonical JSON)  must start with "00"
}
```

### 4.2 Proof of Work

```python
while not hash.startswith("00"):
    nonce += 1
    hash = SHA3-256(block_header_json)
```

With difficulty=2 (2 leading hex zeros), expected iterations ≈ 256, latency ≈ 1ms.

### 4.3 Transaction Types

| Type | Purpose | Key Fields |
|------|---------|------------|
| `NODE_REGISTER` | Publish public keys | ed25519_pub, x25519_pub |
| `ROUTING_UPDATE` | Announce up to 10 peers | peers[] |
| `MESSAGE_RECEIPT` | Non-repudiable delivery proof | msg_id, receiver |
| `DATA_ANCHOR` | Pin content hash | content_hash, frag_count, ttl |

### 4.4 State Indices

Three in-memory indices are rebuilt from chain data:

```
node_registry[addr_hex]    → {ed25519_pub, x25519_pub}
message_receipts[msg_id]   → {sender, receiver, block_index}
data_anchors[content_hash] → {frag_count, ttl, anchor_block}
```

### 4.5 Mempool & Fork Resolution

- Mempool: max 50 transactions, FIFO eviction, deduplication by `tx_id`.
- Fork resolution: **longest valid chain wins** — `replace_chain()` validates
  every block before replacing the local chain and rebuilds state indices.

---

## 5. LoRa Radio Simulation

### 5.1 Physical Parameters (EU868)

| Spreading Factor | Max Payload | Data (after header) | Sensitivity |
|-----------------|-------------|---------------------|-------------|
| SF7 | 222 B | **203 B** | −123 dBm |
| SF8 | 222 B | 203 B | −126 dBm |
| SF9 | 115 B | 96 B | −129 dBm |
| SF10 | 51 B | 32 B | −132 dBm |
| SF11 | 51 B | 32 B | −134 dBm |
| SF12 | 51 B | 32 B | −137 dBm |

### 5.2 Propagation Model

```
PL(d) = PL₀ + 10·n·log₁₀(d / d₀)

PL₀ = 112 dB  (practical EU868 reference at d₀=1 km, includes shadowing margin)
n   = 2.7     (path-loss exponent, rural/suburban)
RSSI(d) = P_tx − PL(d) = 14 dBm − PL(d)
```

Sample values:

| Distance | RSSI | SF7 Reachable? |
|----------|------|----------------|
| 1 km | −98 dBm | Yes (margin +25 dB) |
| 5 km | −117 dBm | Yes (margin +6 dB) |
| 10 km | −125 dBm | Marginal (−2 dB below SF7) |
| 15 km | −130 dBm | Fails SF7, needs SF11/12 |

### 5.3 Delivery Probability

```
P(delivery | RSSI, SF) = sigmoid(RSSI − sensitivity_threshold)
                       = 1 / (1 + exp(−0.5·(RSSI − threshold)))
```

At threshold: P ≈ 50%. Well above: P → 1. Well below: P → 0.

### 5.4 Gateway Topology

5 gateways on a 20×20 km grid (4 corners + centre). Each gateway has a
`DutyCycleTracker` enforcing EU868 1% duty cycle via a 1-hour sliding window
(budget: 36,000 ms/hour).

---

## 6. Kademlia DHT

### 6.1 Address Space & Buckets

- 160-bit XOR metric (matches 20-byte address)
- 160 k-buckets, bucket index = `(our_id XOR their_id).bit_length() − 1`
- Each bucket: max k=20 contacts, LRS (least-recently seen) evicted first

### 6.2 Lookup Algorithm

`find_closest(target, count=20)` iterates all buckets, collects all contacts,
sorts by XOR distance to target, returns top-k.

### 6.3 Content Addressing ("Homeless Data")

```
content_hash = SHA3-256(data)[:20]       # 20-byte content address
msg_id       = os.urandom(4)             # 4-byte random message ID

Fragment {
  content_hash  : 20B
  msg_id        : 4B
  frag_idx      : uint16
  total_frags   : uint16
  data          : ≤ 203B
  store_key     : SHA3-256(content_hash + frag_idx)[:20]   # for ContentStore
}
```

Fragments are stored and retrieved by `store_key`; the data has **no fixed home**.
Any node that received the fragments can reconstruct the original message.

---

## 7. End-to-End Message Flow

```
A.send_message(B.addr_hex, plaintext)
  ① Lookup B.x25519_pub in blockchain.node_registry
  ② shared_secret = X25519(A.x25519_priv, B.x25519_pub)
  ③ aad = A.addr + B.addr
  ④ (nonce, ct) = ChaCha20-Poly1305(shared_secret, plaintext, aad)
  ⑤ wire = A.addr(20B) + nonce(12B) + ct
  ⑥ (content_hash, frags) = fragment_message(wire, max=203B)
  ⑦ for each frag:
       pkt = LoRaPacket(dev_eui, msg_id, frag_idx, total, DATA, SF7, frag.data)
       LoRaSimulator.transmit(pkt, A.x_km, A.y_km)
         → path_loss(dist) → delivery_prob(rssi, SF7) → stochastic deliver
         → deduplicate per gateway
  ⑧ B.receive_packets(collected_packets)
       → reassembly_buffer[msg_id][frag_idx] = fragment
       → when complete: reassemble → decrypt → B.inbox.append(plaintext)
  ⑨ B creates MESSAGE_RECEIPT tx → mempool → mine_block() → broadcast
  ⑩ All nodes update message_receipts index
```

---

## 8. Security Analysis

### Threats Addressed

| Threat | Mitigation |
|--------|-----------|
| Eavesdropping | ChaCha20-Poly1305 E2E encryption |
| Impersonation | Ed25519 signatures on all transactions |
| Replay attacks | Random nonce (96-bit) per message |
| Payload tampering | Poly1305 authentication tag |
| AAD manipulation | Sender+receiver bound in AEAD AAD |
| Sybil attacks (partial) | PoW registration cost |
| IP-based censorship | No IP addresses in the protocol |

### Known Limitations (MVP)

- No key revocation mechanism
- PoW difficulty=2 is trivial (demo only; production needs difficulty ≥ 6)
- LoRa simulation uses a simple sigmoid; real radio is more complex
- No store-and-forward for offline nodes
- No incentive model for relaying (fragment storage is voluntary)

---

## 9. Test Coverage

42 unit tests across 3 test modules:

| Module | Tests | Coverage |
|--------|-------|---------|
| `test_crypto.py` | 11 | ECDH symmetry, round-trip encrypt/decrypt, tamper detection, Ed25519 sign/verify |
| `test_blockchain.py` | 17 | Genesis determinism, PoW validity, mempool eviction, fork resolution, state indices |
| `test_lora.py` | 14 | Packet serialisation, path loss, duty cycle, sigmoid probability, deduplication |

All tests pass in ~0.16 seconds (no hardware required).

---

## 10. Operational Parameters Summary

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Fragment size | 203 B | SF7 max payload − 19B header |
| Duty cycle | 1%/hr sliding | EU868 regulation |
| PoW difficulty | 2 hex zeros | ~1ms/block for demo |
| Block size limit | 4096 B | ~20 SF7 fragments |
| Address space | 160 bits | Kademlia standard |
| Path-loss exponent | 2.7 | Rural/suburban EU868 |
| Reference PL at 1km | 112 dB | Practical LoRa budget |
| k-bucket size | 20 | Kademlia standard |

---

## 11. Running the MVP

```bash
# Install (Kali/externally-managed system)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Unit tests
.venv/bin/pytest tests/ -v

# End-to-end demo
.venv/bin/python main.py
```

Expected demo output confirms all 9 verification points:
nodes with unique 40-char addresses, chain growth, 5-node registry,
correct plaintext delivery, on-chain receipt, partition isolation,
Kademlia routing, DHT fragmentation, and LoRa path-loss values.
