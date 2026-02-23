"""
MegaNet DHT — "Homeless Data" Content Addressing

fragment_message: splits data into ≤203B chunks, content-addressed by SHA3-256[:20]
reassemble_message: rebuilds data from fragments (returns None if incomplete)
ContentStore: local fragment cache, keyed by SHA3-256(content_hash + frag_idx)[:20]
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

FRAGMENT_SIZE = 203   # SF7 max data: 222B payload - 19B header


@dataclass
class Fragment:
    content_hash: bytes   # 20-byte SHA3-256(original_data)[:20]
    msg_id: bytes         # 4-byte random ID
    frag_idx: int
    total_frags: int
    data: bytes           # up to FRAGMENT_SIZE bytes

    @property
    def msg_id_int(self) -> int:
        return int.from_bytes(self.msg_id, "big")

    @property
    def store_key(self) -> bytes:
        """Content-addressed key for storage."""
        return hashlib.sha3_256(self.content_hash + self.frag_idx.to_bytes(2, "big")).digest()[:20]


def fragment_message(data: bytes, max_size: int = FRAGMENT_SIZE) -> tuple[bytes, list[Fragment]]:
    """
    Fragment `data` into chunks ≤ max_size bytes.
    Returns (content_hash_20B, [Fragment...]).
    """
    content_hash = hashlib.sha3_256(data).digest()[:20]
    msg_id = os.urandom(4)

    chunks = [data[i : i + max_size] for i in range(0, len(data), max_size)]
    if not chunks:
        chunks = [b""]

    total = len(chunks)
    fragments = [
        Fragment(
            content_hash=content_hash,
            msg_id=msg_id,
            frag_idx=i,
            total_frags=total,
            data=chunk,
        )
        for i, chunk in enumerate(chunks)
    ]
    return content_hash, fragments


def reassemble_message(fragments: list[Fragment]) -> bytes | None:
    """
    Reassemble fragments into original data.
    Returns None if any fragment is missing.
    """
    if not fragments:
        return None

    total = fragments[0].total_frags
    by_idx: dict[int, Fragment] = {f.frag_idx: f for f in fragments}

    if len(by_idx) < total:
        return None  # incomplete

    return b"".join(by_idx[i].data for i in range(total))


class ContentStore:
    """
    Local fragment storage, indexed by store_key = SHA3-256(content_hash + frag_idx)[:20].
    Also maintains a secondary index: content_hash → set of frag_idx present.
    """

    def __init__(self):
        self._store: dict[bytes, Fragment] = {}
        self._index: dict[bytes, set[int]] = {}   # content_hash → frag indices

    def put(self, fragment: Fragment) -> None:
        key = fragment.store_key
        self._store[key] = fragment
        ch = fragment.content_hash
        if ch not in self._index:
            self._index[ch] = set()
        self._index[ch].add(fragment.frag_idx)

    def get(self, content_hash: bytes, frag_idx: int) -> Fragment | None:
        key = hashlib.sha3_256(content_hash + frag_idx.to_bytes(2, "big")).digest()[:20]
        return self._store.get(key)

    def get_all_fragments(self, content_hash: bytes) -> list[Fragment]:
        frags = []
        for idx in self._index.get(content_hash, set()):
            f = self.get(content_hash, idx)
            if f:
                frags.append(f)
        return sorted(frags, key=lambda f: f.frag_idx)

    def is_complete(self, content_hash: bytes) -> bool:
        frags = self.get_all_fragments(content_hash)
        if not frags:
            return False
        total = frags[0].total_frags
        return len(frags) == total

    def try_reassemble(self, content_hash: bytes) -> bytes | None:
        return reassemble_message(self.get_all_fragments(content_hash))

    def has_fragment(self, content_hash: bytes, frag_idx: int) -> bool:
        return frag_idx in self._index.get(content_hash, set())

    def known_content_hashes(self) -> list[bytes]:
        return list(self._index.keys())
