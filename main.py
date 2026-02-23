#!/usr/bin/env python3
"""
MegaNet MVP — End-to-End Demo CLI

Demonstrates:
  1. 5 nodes with unique 40-char hex addresses
  2. Blockchain grows from height 0 → ≥ 2
  3. node_registry has 5 entries after registration block
  4. B.inbox contains the plaintext sent by A
  5. message_receipts contains msg_id after receipt block
  6. Partitioned node does not receive the message
  7. No exceptions during execution
"""
from __future__ import annotations

import sys

from meganet.node.node import MegaNetNode
from meganet.network.simulator import NetworkSimulator


SEPARATOR = "─" * 60


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def check(label: str, condition: bool) -> None:
    status = "✓ PASS" if condition else "✗ FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print("\n" + "═" * 60)
    print("   MegaNet MVP — Internet Paralela Descentralizada")
    print("   Kim Dotcom's Vision | Python Prototype")
    print("═" * 60)

    # ── 1. Create 5 nodes at different positions ──────────────────────
    section("1. Node Creation")
    positions = [(2, 2), (18, 2), (2, 18), (18, 18), (10, 10)]
    names = ["Alice", "Bob", "Carol", "Dave", "Eve"]
    nodes = [MegaNetNode(x, y) for (x, y) in positions]

    for i, (node, name) in enumerate(zip(nodes, names)):
        print(f"  {name}: {node.addr_hex}")

    addrs = [n.addr_hex for n in nodes]
    check("All addresses are 40 hex chars", all(len(a) == 40 for a in addrs))
    check("All addresses are unique", len(set(addrs)) == 5)

    # ── 2. Build network & bootstrap ─────────────────────────────────
    section("2. Network Bootstrap (Register + Mine Block)")
    net = NetworkSimulator(lora_seed=42)
    for node in nodes:
        net.add_node(node)

    alice, bob = nodes[0], nodes[1]

    # Register → mempool → mine → broadcast → sync
    net.bootstrap()

    # Verify blockchain state
    height_after_boot = alice.blockchain.height
    registry_count = len(alice.blockchain.node_registry)
    print(f"  Chain height: {height_after_boot}")
    print(f"  Registered nodes: {registry_count}")

    check("Chain height ≥ 1 after bootstrap", height_after_boot >= 1)
    check("node_registry has 5 entries", registry_count == 5)

    # ── 3. Send encrypted message A → B ──────────────────────────────
    section("3. Encrypted Message: Alice → Bob")
    plaintext = b"Hello Bob! This is a secret message over MegaNet."

    # Reset LoRa dedup and send
    net.lora.reset_seen()
    alice.send_message(bob.addr_hex, plaintext, net.lora, sf=7)

    # Collect packets from gateways
    packets = net.lora.collect_packets()
    print(f"  Fragments transmitted: {len(packets)}")

    # Deliver to Bob
    bob.receive_packets(packets, net.lora)

    print(f"  Bob inbox size: {len(bob.inbox)}")
    check("Bob's inbox has 1 message", len(bob.inbox) == 1)
    check("Bob received correct plaintext", bob.inbox[0] == plaintext)
    print(f"  Message: {bob.inbox[0].decode()!r}")

    # ── 4. Mine receipt block ─────────────────────────────────────────
    section("4. Mine & Broadcast Message Receipt Block")
    net.sync_blockchain()   # propagate receipt tx to all nodes
    receipt_block = net.mine_and_broadcast(bob.addr_hex)
    net.sync_blockchain()

    height_after_msg = alice.blockchain.height
    print(f"  Chain height: {height_after_msg}")
    check("Chain grew to ≥ 2", height_after_msg >= 2)

    # Find msg_id from Bob's receipt tx
    msg_ids = list(alice.blockchain.message_receipts.keys())
    print(f"  message_receipts keys: {msg_ids}")
    check("message_receipts has at least 1 entry", len(msg_ids) >= 1)

    # ── 5. Partition test ─────────────────────────────────────────────
    section("5. Partition Test: Eve isolated")
    eve = nodes[4]
    inbox_before = len(eve.inbox)
    net.partition([eve.addr_hex])

    net.lora.reset_seen()
    alice.send_message(eve.addr_hex, b"Can Eve receive this?", net.lora, sf=7)
    packets = net.lora.collect_packets()
    eve.receive_packets(packets, net.lora)

    inbox_after = len(eve.inbox)
    print(f"  Eve inbox before: {inbox_before}, after: {inbox_after}")
    check("Partitioned node (Eve) received nothing", inbox_after == inbox_before)

    # ── 6. Heal partition ─────────────────────────────────────────────
    section("6. Heal Partition")
    net.heal_partition()
    print("  Partition healed. Eve is back online.")

    # ── 7. Routing table ─────────────────────────────────────────────
    section("7. Kademlia Routing Table")
    for node, name in zip(nodes, names):
        count = len(node.routing_table)
        print(f"  {name}: {count} contacts in routing table")
    check(
        "Alice has ≥ 4 contacts",
        len(alice.routing_table) >= 4,
    )

    # ── 8. DHT fragment store ─────────────────────────────────────────
    section("8. DHT Fragment Store Verification")
    from meganet.routing.dht import fragment_message, reassemble_message

    data = b"X" * 500   # will produce 3 fragments at 203B each
    content_hash, frags = fragment_message(data)
    print(f"  Data size: {len(data)}B → {len(frags)} fragments")
    check("Correct fragment count", len(frags) == 3)

    reassembled = reassemble_message(frags)
    check("Reassembly correct", reassembled == data)
    check("Content hash is 20 bytes", len(content_hash) == 20)

    # ── 9. LoRa path loss check ───────────────────────────────────────
    section("9. LoRa Radio Model")
    from meganet.lora.simulator import rssi_dbm

    for dist_km in [1, 5, 10, 15]:
        r = rssi_dbm(dist_km)
        print(f"  RSSI @ {dist_km:2d}km: {r:.1f} dBm")

    r5 = rssi_dbm(5.0)
    check("RSSI @ 5km in range [-127, -107] dBm", -127 < r5 < -107)

    # ── Summary ──────────────────────────────────────────────────────
    section("DEMO COMPLETE — All checks passed")
    print(f"\n  Final blockchain height : {alice.blockchain.height}")
    print(f"  Registered nodes        : {len(alice.blockchain.node_registry)}")
    print(f"  Message receipts on-chain: {len(alice.blockchain.message_receipts)}")
    print(f"  Data anchors on-chain   : {len(alice.blockchain.data_anchors)}")
    print()


if __name__ == "__main__":
    main()
