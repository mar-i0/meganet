"""
MegaNet Network Simulator

Manages all nodes in a registry, routes messages through LoRa,
broadcasts blocks, and simulates churn/partitions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from meganet.lora.simulator import LoRaSimulator

if TYPE_CHECKING:
    from meganet.blockchain.block import Block
    from meganet.node.node import MegaNetNode


class NetworkSimulator:
    def __init__(self, lora_seed: int | None = None):
        self.nodes: dict[str, "MegaNetNode"] = {}   # addr_hex → node
        self.lora = LoRaSimulator(seed=lora_seed)
        self._partitioned: set[str] = set()          # addr_hex of isolated nodes

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_node(self, node: "MegaNetNode") -> None:
        self.nodes[node.addr_hex] = node

    def remove_node(self, addr_hex: str) -> "MegaNetNode | None":
        """Simulate churn: disconnect a node."""
        return self.nodes.pop(addr_hex, None)

    def partition(self, addrs: list[str]) -> None:
        """Isolate a set of nodes (simulates geographic/network split)."""
        for addr in addrs:
            self._partitioned.add(addr)
            if addr in self.nodes:
                self.nodes[addr].set_partitioned(True)

    def heal_partition(self) -> None:
        """Restore full connectivity."""
        for addr in self._partitioned:
            if addr in self.nodes:
                self.nodes[addr].set_partitioned(False)
        self._partitioned.clear()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_all(self) -> None:
        """Have every node create a NODE_REGISTER tx and sync registries."""
        for node in self.nodes.values():
            node.register()

    def sync_blockchain(self) -> None:
        """
        Simple sync: pick the longest chain and propagate to all nodes.
        Then propagate mempool transactions across nodes.
        """
        if not self.nodes:
            return

        # Find longest chain
        best = max(self.nodes.values(), key=lambda n: n.blockchain.height)
        best_chain = best.blockchain.chain

        for node in self.nodes.values():
            if node is best:
                continue
            if node.blockchain.height < best.blockchain.height:
                # Try to replace chain
                node.blockchain.replace_chain(best_chain)

        # Propagate mempool across all nodes
        all_pending = []
        for node in self.nodes.values():
            all_pending.extend(node.blockchain.mempool.get_pending())

        for node in self.nodes.values():
            for tx in all_pending:
                node.blockchain.add_transaction(tx)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def route_message(
        self,
        sender_addr: str,
        receiver_addr: str,
        plaintext: bytes,
        sf: int = 7,
    ) -> bool:
        """
        Send an encrypted message from sender to receiver via LoRa simulation.
        Returns True if message was delivered.
        """
        sender = self.nodes.get(sender_addr)
        receiver = self.nodes.get(receiver_addr)
        if not sender or not receiver:
            return False
        if sender_addr in self._partitioned or receiver_addr in self._partitioned:
            return False

        # Reset LoRa dedup state for a fresh message
        self.lora.reset_seen()

        # Send
        result = sender.send_message(receiver_addr, plaintext, self.lora, sf)
        if result is None:
            return False

        # Collect all received packets from gateways
        packets = self.lora.collect_packets()

        # Deliver to receiver
        receiver.receive_packets(packets, self.lora)

        return len(receiver.inbox) > 0

    # ------------------------------------------------------------------
    # Block broadcast
    # ------------------------------------------------------------------

    def broadcast_block(self, block: "Block", sender_addr: str) -> int:
        """
        Propagate a mined block to all reachable nodes.
        Returns number of nodes that accepted it.
        """
        accepted = 0
        for addr, node in self.nodes.items():
            if addr == sender_addr:
                continue
            if addr in self._partitioned or sender_addr in self._partitioned:
                continue
            if node.apply_block(block):
                accepted += 1
        return accepted

    def mine_and_broadcast(self, miner_addr: str, difficulty: int = 2) -> "Block | None":
        """Mine a block at `miner_addr` and broadcast to the network."""
        miner = self.nodes.get(miner_addr)
        if not miner:
            return None
        block = miner.mine_block(difficulty)
        if block:
            self.broadcast_block(block, miner_addr)
        return block

    # ------------------------------------------------------------------
    # Bulk operations for demo
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        """
        Full bootstrap sequence:
        1. All nodes register
        2. Sync mempool across nodes
        3. Mine registration block
        4. Broadcast to all
        5. Update routing tables
        """
        self.register_all()
        self.sync_blockchain()

        # Pick first node as initial miner
        if not self.nodes:
            return
        first_addr = next(iter(self.nodes))
        block = self.mine_and_broadcast(first_addr)

        if block:
            # Sync state after block
            self.sync_blockchain()
            for node in self.nodes.values():
                node.update_routing_table_from_blockchain()
