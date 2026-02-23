"""
MegaNetNode — Central integration point

Integrates:
  - Cryptography (Ed25519 + X25519)
  - Blockchain (local copy + mempool)
  - LoRa routing table (Kademlia DHT)
  - Content store (fragment buffer)
  - Reassembly buffer per msg_id
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from meganet.blockchain.chain import Blockchain
from meganet.blockchain.transaction import (
    make_data_anchor,
    make_message_receipt,
    make_node_register,
)
from meganet.crypto.keys import (
    KeyPair,
    decrypt,
    derive_shared_secret,
    encrypt,
    generate_keypair,
)
from meganet.routing.dht import ContentStore, Fragment, fragment_message
from meganet.routing.table import Contact, RoutingTable

if TYPE_CHECKING:
    from meganet.blockchain.block import Block
    from meganet.lora.packet import LoRaPacket
    from meganet.lora.simulator import LoRaSimulator


class MegaNetNode:
    def __init__(self, x_km: float = 10.0, y_km: float = 10.0):
        self.keypair: KeyPair = generate_keypair()
        self.x_km = x_km
        self.y_km = y_km

        self.blockchain = Blockchain()
        self.routing_table = RoutingTable(self.keypair.address)
        self.content_store = ContentStore()

        # inbox: delivered plaintext messages (bytes)
        self.inbox: list[bytes] = []

        # Reassembly buffer: msg_id_int → {frag_idx: Fragment}
        self._reassembly: dict[int, dict[int, Fragment]] = {}

        # Partitioned flag: if True, node won't route/receive
        self._partitioned = False

    @property
    def addr(self) -> bytes:
        return self.keypair.address

    @property
    def addr_hex(self) -> str:
        return self.keypair.address_hex

    def register(self) -> None:
        """Create NODE_REGISTER transaction and add to local mempool."""
        tx = make_node_register(
            sender_addr=self.addr_hex,
            ed25519_pub_bytes=self.keypair.ed25519_public_bytes,
            x25519_pub_bytes=self.keypair.x25519_public_bytes,
            ed25519_priv=self.keypair.ed25519_private,
        )
        self.blockchain.add_transaction(tx)

    def send_message(
        self,
        receiver_addr_hex: str,
        plaintext: bytes,
        lora_sim: "LoRaSimulator",
        sf: int = 7,
    ) -> tuple[bytes, list[Fragment]] | None:
        """
        Encrypt and fragment a message for `receiver_addr_hex`.
        Transmits fragments via LoRa simulator.
        Returns (content_hash, fragments) or None if receiver unknown.
        """
        # 1. Lookup receiver's X25519 public key in blockchain
        reg = self.blockchain.node_registry.get(receiver_addr_hex)
        if reg is None:
            return None

        their_x25519_pub = bytes.fromhex(reg["x25519_pub"])

        # 2. ECDH shared secret
        shared_secret = derive_shared_secret(self.keypair.x25519_private, their_x25519_pub)

        # 3. Authenticated encryption
        aad = self.addr + bytes.fromhex(receiver_addr_hex)
        nonce, ciphertext = encrypt(shared_secret, plaintext, aad)

        # 4. Wire format: sender_addr(20B) + nonce(12B) + ciphertext
        wire = self.addr + nonce + ciphertext

        # 5. Fragment
        content_hash, fragments = fragment_message(wire)

        # 6. Transmit each fragment via LoRa
        from meganet.lora.packet import LoRaPacket, PacketType

        msg_id_int = fragments[0].msg_id_int
        total = len(fragments)
        dev_eui = int.from_bytes(self.addr[:8], "big")

        for frag in fragments:
            pkt = LoRaPacket(
                dev_eui=dev_eui,
                msg_id=msg_id_int,
                frag_idx=frag.frag_idx,
                total_frags=total,
                pkt_type=PacketType.DATA,
                sf=sf,
                payload=frag.data,
            )
            lora_sim.transmit(pkt, self.x_km, self.y_km)

        # 7. Create DATA_ANCHOR transaction
        anchor_tx = make_data_anchor(
            sender_addr=self.addr_hex,
            sender_pub_bytes=self.keypair.ed25519_public_bytes,
            ed25519_priv=self.keypair.ed25519_private,
            content_hash=content_hash.hex(),
            frag_count=total,
        )
        self.blockchain.add_transaction(anchor_tx)

        return content_hash, fragments

    def receive_packets(
        self,
        packets: list["LoRaPacket"],
        lora_sim: "LoRaSimulator",
    ) -> None:
        """
        Process incoming LoRa packets.
        Buffer fragments; when complete, attempt decrypt and deliver to inbox.
        """
        if self._partitioned:
            return

        for pkt in packets:
            msg_id = pkt.msg_id
            if msg_id not in self._reassembly:
                self._reassembly[msg_id] = {}

            # Store fragment
            frag = Fragment(
                content_hash=b"\x00" * 20,  # placeholder; recalculated on reassembly
                msg_id=msg_id.to_bytes(4, "big"),
                frag_idx=pkt.frag_idx,
                total_frags=pkt.total_frags,
                data=pkt.payload,
            )
            self._reassembly[msg_id][pkt.frag_idx] = frag

            # Check if complete
            if len(self._reassembly[msg_id]) == pkt.total_frags:
                ordered = [self._reassembly[msg_id][i] for i in range(pkt.total_frags)]
                wire = b"".join(f.data for f in ordered)
                self._try_decrypt_wire(wire, pkt.msg_id, lora_sim)
                del self._reassembly[msg_id]

    def _try_decrypt_wire(
        self,
        wire: bytes,
        msg_id_int: int,
        lora_sim: "LoRaSimulator",
    ) -> None:
        """
        Attempt to decrypt a reassembled wire payload.
        wire = sender_addr(20B) + nonce(12B) + ciphertext
        If successful, deliver to inbox and create MESSAGE_RECEIPT.
        """
        if len(wire) < 32:
            return

        sender_addr_bytes = wire[:20]
        sender_addr_hex = sender_addr_bytes.hex()
        nonce = wire[20:32]
        ciphertext = wire[32:]

        # Look up sender's X25519 pub key
        reg = self.blockchain.node_registry.get(sender_addr_hex)
        if reg is None:
            return

        their_x25519_pub = bytes.fromhex(reg["x25519_pub"])
        shared_secret = derive_shared_secret(self.keypair.x25519_private, their_x25519_pub)
        aad = sender_addr_bytes + self.addr

        try:
            from cryptography.exceptions import InvalidTag
            plaintext = decrypt(shared_secret, nonce, ciphertext, aad)
            self.inbox.append(plaintext)

            # Create MESSAGE_RECEIPT
            receipt_tx = make_message_receipt(
                sender_addr=self.addr_hex,
                sender_pub_bytes=self.keypair.ed25519_public_bytes,
                ed25519_priv=self.keypair.ed25519_private,
                msg_id=f"{msg_id_int:08x}",
                receiver_addr=self.addr_hex,
            )
            self.blockchain.add_transaction(receipt_tx)
        except Exception:
            pass  # not for us, or tampered

    def mine_block(self, difficulty: int = 2) -> "Block | None":
        """Mine a block from local mempool."""
        return self.blockchain.mine_block(self.addr_hex, difficulty)

    def apply_block(self, block: "Block") -> bool:
        """Accept a block from the network (broadcast)."""
        if self._partitioned:
            return False
        # Simple append if it extends our chain
        return self.blockchain._append_block(block)

    def update_routing_table_from_blockchain(self) -> None:
        """Populate DHT from node_registry state index."""
        for addr_hex, info in self.blockchain.node_registry.items():
            contact = Contact(
                addr=bytes.fromhex(addr_hex),
                addr_hex=addr_hex,
                metadata=info,
            )
            self.routing_table.add_contact(contact)

    def set_partitioned(self, partitioned: bool) -> None:
        self._partitioned = partitioned
