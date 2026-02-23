"""
Kademlia-style Routing Table

- 160 k-buckets (one per bit of the 160-bit address space)
- k = 20 (max contacts per bucket)
- Bucket ordering: LRS (least-recently seen) at front, MRS at back
- XOR metric for distance
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

K = 20          # bucket size
ADDR_BITS = 160 # address space


@dataclass
class Contact:
    addr: bytes       # 20-byte address
    addr_hex: str
    metadata: dict    # arbitrary: position, public keys, etc.

    def __hash__(self):
        return hash(self.addr)

    def __eq__(self, other):
        return isinstance(other, Contact) and self.addr == other.addr


def xor_distance(a: bytes, b: bytes) -> int:
    """Compute XOR distance between two 20-byte addresses as integer."""
    return int.from_bytes(a, "big") ^ int.from_bytes(b, "big")


def bucket_index(our_addr: bytes, their_addr: bytes) -> int:
    """Which k-bucket (0-159) does `their_addr` fall into?"""
    dist = xor_distance(our_addr, their_addr)
    if dist == 0:
        return -1   # self
    return dist.bit_length() - 1  # 0..159


class KBucket:
    """Ordered dict bucket: LRS at front, MRS at back."""

    def __init__(self, k: int = K):
        self.k = k
        self._contacts: OrderedDict[bytes, Contact] = OrderedDict()

    def add(self, contact: Contact) -> bool:
        """
        Add or update a contact.
        Returns True if added/updated, False if bucket full and contact is new.
        """
        addr = contact.addr
        if addr in self._contacts:
            # Move to end (most-recently seen)
            self._contacts.move_to_end(addr)
            self._contacts[addr] = contact
            return True
        if len(self._contacts) < self.k:
            self._contacts[addr] = contact
            return True
        # Bucket full: Kademlia would ping LRS node here; we just drop
        return False

    def remove(self, addr: bytes) -> None:
        self._contacts.pop(addr, None)

    def get_all(self) -> list[Contact]:
        return list(self._contacts.values())

    def __len__(self) -> int:
        return len(self._contacts)

    def __contains__(self, addr: bytes) -> bool:
        return addr in self._contacts


class RoutingTable:
    """Full 160-bucket Kademlia routing table."""

    def __init__(self, our_addr: bytes):
        self.our_addr = our_addr
        self.our_addr_hex = our_addr.hex()
        self.buckets: list[KBucket] = [KBucket() for _ in range(ADDR_BITS)]

    def add_contact(self, contact: Contact) -> bool:
        if contact.addr == self.our_addr:
            return False   # don't add self
        idx = bucket_index(self.our_addr, contact.addr)
        if idx < 0:
            return False
        return self.buckets[idx].add(contact)

    def remove_contact(self, addr: bytes) -> None:
        idx = bucket_index(self.our_addr, addr)
        if idx >= 0:
            self.buckets[idx].remove(addr)

    def find_closest(self, target: bytes, count: int = K) -> list[Contact]:
        """Return the `count` closest contacts to `target` by XOR distance."""
        all_contacts: list[Contact] = []
        for bucket in self.buckets:
            all_contacts.extend(bucket.get_all())

        all_contacts.sort(key=lambda c: xor_distance(c.addr, target))
        return all_contacts[:count]

    def all_contacts(self) -> list[Contact]:
        result = []
        for bucket in self.buckets:
            result.extend(bucket.get_all())
        return result

    def __len__(self) -> int:
        return sum(len(b) for b in self.buckets)
