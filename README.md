# MegaNet MVP

> **A working prototype of Kim Dotcom's vision of a parallel, decentralised internet.**
> No IP addresses. No DNS. No censorship. End-to-end encrypted by default.

```
Alice: 546608dd173bd4818642a0169a626de189311e24
Bob:   eed64e9db75d520135216c157b9dbfa2c4ec2954

[✓] Alice sends encrypted message → Bob receives exact plaintext
[✓] Message receipt anchored on blockchain (immutable proof)
[✓] Partitioned node receives nothing
[✓] 42/42 unit tests pass in 0.16 s
```

---

## What is MegaNet?

The current internet has a structural problem: every device needs an IP address assigned by a government registry or ISP, routes traffic through blockable DNS servers, and runs over cables that can be physically cut. Any of these layers can be targeted to censor, monitor, or deplatform.

MegaNet replaces all of them:

| Layer | Traditional Internet | MegaNet |
|-------|---------------------|---------|
| **Identity** | IP address (ISP-assigned) | `SHA3-256(ed25519_pub)[:20]` — self-sovereign |
| **Naming** | DNS (centralised, blockable) | Blockchain registry (distributed, immutable) |
| **Transport** | TCP/IP over ISP cables | LoRaWAN radio (unlicensed, no ISP needed) |
| **Privacy** | Unencrypted by default | E2E encrypted always (ChaCha20-Poly1305) |
| **Censorship** | Single points of control | No central entity can block nodes |
| **Data storage** | Centralised servers | "Homeless" fragments, content-addressed |

This repository is a **fully functional MVP** written in pure Python. It simulates the radio layer (no hardware required) so every component can be verified and tested on any laptop.

---

## Quick Start

```bash
# 1. Clone and enter the directory
git clone https://github.com/YOUR_USERNAME/meganet.git
cd meganet

# 2. Create a virtual environment and install the single dependency
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run the unit test suite (42 tests, ~0.16 s)
.venv/bin/pytest tests/ -v

# 4. Run the end-to-end demo
.venv/bin/python main.py
```

**Requirements:** Python 3.10+ · `cryptography >= 42.0.0` (only external dependency)

---

## Demo Output

```
════════════════════════════════════════════════════════════
   MegaNet MVP — Internet Paralela Descentralizada
   Kim Dotcom's Vision | Python Prototype
════════════════════════════════════════════════════════════

  1. Node Creation
  Alice: 546608dd173bd4818642a0169a626de189311e24
  Bob:   eed64e9db75d520135216c157b9dbfa2c4ec2954
  Carol: e3152fff55b3d8ffa343862aee04020f9a5e974a
  Dave:  de1d4364decfba7f57cbcbd8851bc3bd7ec453c0
  Eve:   0a459bc29759b8d926faa1804879dc1130f09c62
  [✓ PASS] All addresses are 40 hex chars
  [✓ PASS] All addresses are unique

  2. Network Bootstrap (Register + Mine Block)
  Chain height: 1  |  Registered nodes: 5
  [✓ PASS] Chain height ≥ 1 after bootstrap
  [✓ PASS] node_registry has 5 entries

  3. Encrypted Message: Alice → Bob
  Fragments transmitted: 1
  [✓ PASS] Bob received correct plaintext
  Message: 'Hello Bob! This is a secret message over MegaNet.'

  4. Mine & Broadcast Message Receipt Block
  Chain height: 2
  [✓ PASS] Chain grew to ≥ 2
  [✓ PASS] message_receipts has at least 1 entry

  5. Partition Test: Eve isolated
  [✓ PASS] Partitioned node (Eve) received nothing

  7. Kademlia Routing Table
  [✓ PASS] Alice has ≥ 4 contacts

  8. DHT Fragment Store
  Data size: 500B → 3 fragments
  [✓ PASS] Reassembly correct  |  Content hash is 20 bytes

  9. LoRa Radio Model
  RSSI @  1km: -98.0 dBm
  RSSI @  5km: -116.9 dBm   ← ≈ -117 dBm as per LoRa Alliance spec
  RSSI @ 10km: -125.0 dBm
  RSSI @ 15km: -129.8 dBm
  [✓ PASS] RSSI @ 5km in range [-127, -107] dBm

  DEMO COMPLETE — All checks passed
```

---

## Architecture

```
meganet/
├── crypto/
│   └── keys.py          Ed25519 identity + X25519 ECDH + ChaCha20-Poly1305
├── blockchain/
│   ├── transaction.py   4 TX types: NODE_REGISTER · ROUTING_UPDATE ·
│   │                                MESSAGE_RECEIPT · DATA_ANCHOR
│   ├── block.py         SHA3-256 Proof-of-Work · genesis · serialisation
│   └── chain.py         State indices · mempool (max 50) · fork resolution
├── lora/
│   ├── packet.py        19-byte header · SF7–SF12 parameters · time-on-air
│   ├── gateway.py       EU868 duty-cycle tracker (1 %/hr) · RX queue
│   └── simulator.py     Log-distance path loss · sigmoid delivery prob · 5 GWs
├── routing/
│   ├── table.py         Kademlia: 160 k-buckets · k=20 · XOR distance
│   └── dht.py           fragment_message · reassemble_message · ContentStore
├── network/
│   └── simulator.py     Topology · churn · partition / heal
└── node/
    └── node.py          Central integration point
```

### Message Flow (A → B)

```
 Alice                     LoRa Gateways                     Bob
   │                            │                              │
   │ 1. lookup B.x25519_pub     │                              │
   │    in blockchain           │                              │
   │ 2. X25519 ECDH             │                              │
   │    → 32-byte shared secret │                              │
   │ 3. ChaCha20-Poly1305       │                              │
   │    encrypt(plaintext, aad) │                              │
   │ 4. wire = addr+nonce+ct    │                              │
   │ 5. fragment (≤ 203 B each) │                              │
   │ 6. LoRaPacket ─────────── →│ path loss + sigmoid prob     │
   │                            │──────────────────────────── →│
   │                            │                              │ 7. reassemble
   │                            │                              │ 8. decrypt
   │                            │                              │ → inbox ✓
   │ 9. MESSAGE_RECEIPT tx      │                              │
   │    → mempool → mine_block()│                              │
   │    → broadcast to all nodes│                              │
   │ 10. on-chain proof         │                              │
```

---

## Key Design Decisions

### Addressing — no IP, no registry

```python
address = SHA3-256(ed25519_public_key_bytes)[:20]   # 160 bits
```

A node's address is derived purely from its public key. No government body, ISP, or cloud provider can revoke or reassign it.

### Encryption — optimised for constrained devices

```
X25519 ECDH  →  32-byte shared secret
ChaCha20-Poly1305(secret, plaintext, aad=sender_addr+receiver_addr)
```

ChaCha20-Poly1305 was chosen over AES-GCM because it delivers equivalent security without requiring AES hardware acceleration — critical for IoT/LoRa devices.

### Transport — LoRaWAN EU868

| Parameter | Value | Reason |
|-----------|-------|--------|
| Spreading factor | SF7–SF12 | Trade range for data rate |
| Fragment size | **203 B** | SF7 payload (222 B) − 19 B header |
| Duty cycle | **1 % / hour** | EU868 ISM band regulation |
| Path-loss model | n = 2.7, PL₀ = 112 dB | Rural/suburban EU868 (practical) |
| RSSI @ 5 km | ≈ −117 dBm | Above SF7 sensitivity (−123 dBm) |
| Gateway grid | 5 GWs / 20 × 20 km | 4 corners + centre |

### Blockchain — lightweight PoW

| Parameter | Value | Reason |
|-----------|-------|--------|
| Hash function | SHA3-256 | Quantum-resistant candidate |
| Difficulty | 2 hex zeros | ≈ 256 iterations ≈ 1 ms (demo) |
| Block size | 4 096 B | ≈ 20 SF7 fragments per broadcast |
| Mempool | 50 txs (FIFO) | Memory-constrained devices |
| Fork resolution | Longest valid chain wins | Classic Nakamoto rule |

### Routing — Kademlia DHT

- **160-bit XOR** distance metric (matches the 20-byte address space)
- **160 k-buckets**, k = 20 contacts each
- Content-addressed fragments: `store_key = SHA3-256(content_hash ∥ frag_idx)[:20]`

---

## Technical Parameters

| Parameter | Value |
|-----------|-------|
| Address space | 160 bits (`SHA3-256[:20]`) |
| Signature scheme | Ed25519 (64-byte signatures) |
| Key exchange | X25519 ECDH (32-byte secret) |
| AEAD cipher | ChaCha20-Poly1305 |
| Fragment size | 203 B (SF7) |
| Header size | 19 B (`>QIHHBBB`) |
| PoW difficulty | 2 hex zeros |
| Block size limit | 4 096 B |
| Duty cycle | 1 % / rolling hour |
| DHT bucket count | 160 |
| DHT bucket size (k) | 20 |

---

## Test Coverage

```
tests/
├── test_crypto.py      11 tests — ECDH symmetry, encrypt/decrypt round-trip,
│                                  tamper detection (InvalidTag), Ed25519 sign/verify
├── test_blockchain.py  17 tests — genesis determinism, PoW validity, mempool FIFO
│                                  eviction, fork resolution, state index updates
└── test_lora.py        14 tests — packet serialisation, RSSI @ 5 km ≈ −117 dBm,
                                   duty-cycle enforcement, sigmoid delivery prob,
                                   gateway deduplication
```

Run with:

```bash
.venv/bin/pytest tests/ -v
# 42 passed in 0.16s
```

---

## Project Files

```
meganet/                        Core Python package (~2 300 lines)
tests/                          42 unit tests
main.py                         End-to-end CLI demo
requirements.txt                cryptography>=42.0.0  (only external dep)
generate_docs.py                Generates PDF report + conference PPTX
generate_exec_ppt.py            Generates executive PPTX (14 slides, charts)
MegaNet.md                      Full technical report (Markdown)
MegaNet_Technical_Report.pdf   Technical report (PDF)
MegaNet_Conference.pptx        Technical conference presentation (13 slides)
MegaNet_Executive.pptx         Executive presentation (14 slides, visuals/charts)
```

### Generating the documents

```bash
# Install extra deps (fpdf2 + python-pptx)
.venv/bin/pip install fpdf2 python-pptx

# Technical PDF + conference PPTX
.venv/bin/python generate_docs.py

# Executive PPTX (network maps, charts, roadmap, competitive matrix)
.venv/bin/python generate_exec_ppt.py
```

---

## Security Notes

This is a **research prototype**, not a production system. Known limitations:

- PoW difficulty = 2 is intentionally trivial (increase to ≥ 6 for any real deployment)
- No key revocation mechanism yet
- No incentive layer for fragment relay
- No store-and-forward for offline nodes
- LoRa simulation uses a simplified sigmoid model; real radio environments are more complex

---

## Roadmap

| Phase | Target | Milestone |
|-------|--------|-----------|
| **MVP** ✅ | Q1 2026 | Pure Python simulation, 42 tests, full E2E demo |
| **Hardware** | Q3 2026 | SX1276/SX1278 driver, Raspberry Pi + ESP32 nodes |
| **Protocol hardening** | Q1 2027 | Key revocation, PoW scaling, store-and-forward |
| **Incentive layer** | Q3 2027 | Token rewards for relay, proof-of-bandwidth |
| **Application layer** | 2028+ | Browser extension, mobile app, MegaNet DNS |

---

## References

- [Kim Dotcom — MegaNet announcement](https://twitter.com/KimDotcom) — original vision
- [Kademlia DHT paper](https://pdos.csail.mit.edu/~petar/papers/maymounkov-kademlia-lncs.pdf) — Maymounkov & Mazières, 2002
- [LoRaWAN specification](https://lora-alliance.org/resource_hub/lorawan-specification-v1-0-3/) — LoRa Alliance EU868
- [ChaCha20-Poly1305 RFC 8439](https://www.rfc-editor.org/rfc/rfc8439) — IETF
- [X25519 RFC 7748](https://www.rfc-editor.org/rfc/rfc7748) — IETF
- [Ed25519 RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) — IETF

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built with Python 3.13 · cryptography 42 · No hardware required*
