"""
LoRaWAN EU868 Packet

Physical parameters:
  SF7-SF12, 125 kHz BW, coding rate 4/5
  Max payload per SF (after 19B header subtracted from LoRa limit):
    SF7:  222B payload  (222B raw - 0B — actually we use 203B for data = 222-19)
    SF8:  222B payload
    SF9:  115B payload
    SF10:  51B payload
    SF11:  51B payload
    SF12:  51B payload

Header layout (19 bytes, big-endian struct ">QIHHBBB"):
  dev_eui      8B   uint64
  msg_id       4B   uint32
  frag_idx     2B   uint16
  total_frags  2B   uint16
  pkt_type     1B   uint8
  sf           1B   uint8  (7-12)
  payload_len  1B   uint8
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import ClassVar

HEADER_FORMAT = ">QIHHBBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 19 bytes

# Maximum payload bytes per SF (LoRaWAN max - header)
SF_MAX_PAYLOAD: dict[int, int] = {
    7: 222,
    8: 222,
    9: 115,
    10: 51,
    11: 51,
    12: 51,
}

# Receiver sensitivity thresholds (dBm)
SF_SENSITIVITY: dict[int, int] = {
    7: -123,
    8: -126,
    9: -129,
    10: -132,
    11: -134,
    12: -137,
}

# Max data bytes per SF after subtracting our 19-byte header
SF_DATA_MAX: dict[int, int] = {sf: v - HEADER_SIZE for sf, v in SF_MAX_PAYLOAD.items()}

# LoRaWAN symbol durations (ms) and time-on-air approximations at 125kHz BW, CR 4/5
# ToA ≈ (preamble + payload_symbols) * symbol_time
# symbol_time = 2^SF / BW ms
def compute_time_on_air_ms(sf: int, payload_bytes: int) -> float:
    """Approximate LoRa Time-on-Air in milliseconds."""
    bw_hz = 125_000
    symbol_time_ms = (2 ** sf) / bw_hz * 1000  # ms per symbol
    preamble_symbols = 8
    # payload symbols (simplified Semtech formula, CR=4/5, IH=0, CRC=1)
    de = 1 if sf >= 11 else 0  # low data rate optimization
    payload_sym_nb = max(
        8,
        8
        + max(
            int(
                (8 * (payload_bytes + HEADER_SIZE) - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))
            )
            * 5,
            0,
        ),
    )
    total_symbols = preamble_symbols + 4.25 + payload_sym_nb
    return total_symbols * symbol_time_ms


class PacketType(IntEnum):
    DATA = 0
    ACK = 1
    BEACON = 2
    ROUTE = 3


@dataclass
class LoRaPacket:
    dev_eui: int          # 8-byte device EUI as integer
    msg_id: int           # 4-byte message ID as integer
    frag_idx: int         # fragment index (0-based)
    total_frags: int      # total number of fragments
    pkt_type: PacketType  # packet type
    sf: int               # spreading factor (7-12)
    payload: bytes        # data payload (≤ SF_DATA_MAX[sf])

    # Computed on transmit
    time_on_air_ms: float = field(init=False)

    def __post_init__(self):
        self.time_on_air_ms = compute_time_on_air_ms(self.sf, len(self.payload))

    def to_bytes(self) -> bytes:
        header = struct.pack(
            HEADER_FORMAT,
            self.dev_eui,
            self.msg_id,
            self.frag_idx,
            self.total_frags,
            int(self.pkt_type),
            self.sf,
            len(self.payload),
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "LoRaPacket":
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} < {HEADER_SIZE}")
        (dev_eui, msg_id, frag_idx, total_frags, pkt_type, sf, payload_len) = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE]
        )
        payload = data[HEADER_SIZE : HEADER_SIZE + payload_len]
        return cls(
            dev_eui=dev_eui,
            msg_id=msg_id,
            frag_idx=frag_idx,
            total_frags=total_frags,
            pkt_type=PacketType(pkt_type),
            sf=sf,
            payload=payload,
        )

    @property
    def packet_id(self) -> tuple[int, int]:
        """Unique identifier for deduplication: (msg_id, frag_idx)."""
        return (self.msg_id, self.frag_idx)
