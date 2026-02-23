"""
LoRa Radio Propagation Simulator

Path loss model: log-distance (exponent 2.7, EU868 rural/suburban)
  RSSI(d) = P_tx - PL(d)
  PL(d)   = PL_d0 + 10*n*log10(d/d0)
  P_tx    = 14 dBm (EU868 max)
  PL_d0   = 20*log10(4*pi*d0*f/c)  @ d0=1km, f=868MHz → ~91.2 dB

Delivery probability: sigmoid centred at SF sensitivity threshold.

5 default gateways: 4 corners + centre of 20×20 km grid.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from .gateway import LoRaGateway
from .packet import LoRaPacket, SF_SENSITIVITY

if TYPE_CHECKING:
    pass

# Physical constants
TX_POWER_DBM = 14.0          # EU868 max
PATH_LOSS_EXPONENT = 2.7
D0_KM = 1.0                  # reference distance (km)
# Practical path loss at d0=1km for 868 MHz LoRa in rural/suburban environments.
# Free-space only gives ~91 dB/km; real deployments with terrain, buildings and
# a 6 dB system margin yield ~112 dB at 1 km (gives RSSI ≈ -117 dBm at 5 km,
# matching the LoRa Alliance EU868 link budget specification).
PL_D0_DB = 112.0
SIGMOID_SLOPE = 0.5          # steepness of the delivery probability curve (dB^-1)


def path_loss_db(dist_km: float) -> float:
    """Log-distance path loss in dB (practical LoRa EU868 model)."""
    if dist_km <= 0:
        return 0.0
    return PL_D0_DB + 10 * PATH_LOSS_EXPONENT * math.log10(dist_km / D0_KM)


def rssi_dbm(dist_km: float) -> float:
    """Estimated RSSI at receiver."""
    return TX_POWER_DBM - path_loss_db(dist_km)


def delivery_probability(rssi: float, sf: int) -> float:
    """
    Sigmoid delivery probability centred at SF sensitivity.
    P = 1 / (1 + exp(-k*(rssi - threshold)))
    """
    threshold = SF_SENSITIVITY[sf]
    return 1.0 / (1.0 + math.exp(-SIGMOID_SLOPE * (rssi - threshold)))


def _default_gateways() -> list[LoRaGateway]:
    """5 gateways: 4 corners + centre of 20×20 km grid."""
    positions = [
        ("gw0",  0.0,  0.0),
        ("gw1", 20.0,  0.0),
        ("gw2",  0.0, 20.0),
        ("gw3", 20.0, 20.0),
        ("gw4", 10.0, 10.0),
    ]
    return [LoRaGateway(gid, x, y) for gid, x, y in positions]


class LoRaSimulator:
    def __init__(self, gateways: list[LoRaGateway] | None = None, seed: int | None = None):
        self.gateways = gateways if gateways is not None else _default_gateways()
        self._rng = random.Random(seed)
        # Maps gateway_id → set of (msg_id, frag_idx) already received (dedup)
        self._seen: dict[str, set[tuple[int, int]]] = {gw.gateway_id: set() for gw in self.gateways}

    def transmit(
        self,
        packet: LoRaPacket,
        tx_x_km: float,
        tx_y_km: float,
    ) -> list[tuple[LoRaGateway, float, float]]:
        """
        Simulate packet transmission from (tx_x_km, tx_y_km).
        Returns list of (gateway, rssi, snr) for each gateway that received the packet.
        Also delivers the packet to those gateways (deduplicating repeats).
        """
        received_by = []
        pkt_id = packet.packet_id

        for gw in self.gateways:
            dist = math.sqrt((tx_x_km - gw.x_km) ** 2 + (tx_y_km - gw.y_km) ** 2)
            if dist < 0.001:
                dist = 0.001  # floor to avoid log(0)

            r = rssi_dbm(dist)
            # SNR: difference between RSSI and noise floor (-174 + 10*log10(BW) + NF)
            # noise floor at 125kHz, NF=6dB ≈ -174+51+6 = -117 dBm
            noise_floor = -117.0
            snr = r - noise_floor

            prob = delivery_probability(r, packet.sf)
            if self._rng.random() < prob:
                # Check duty cycle before accepting at gateway (gateway TX budget only for uplink)
                # RX at gateway is passive – no duty cycle constraint on receive
                # Deduplicate
                if pkt_id not in self._seen[gw.gateway_id]:
                    self._seen[gw.gateway_id].add(pkt_id)
                    gw.receive(packet)
                received_by.append((gw, r, snr))

        return received_by

    def collect_packets(self) -> list[LoRaPacket]:
        """Drain all gateways and return deduplicated received packets."""
        seen_ids: set[tuple[int, int]] = set()
        packets = []
        for gw in self.gateways:
            for pkt in gw.drain():
                if pkt.packet_id not in seen_ids:
                    seen_ids.add(pkt.packet_id)
                    packets.append(pkt)
        return packets

    def reset_seen(self) -> None:
        """Clear the deduplication state (e.g. between message transmissions)."""
        for gw in self.gateways:
            self._seen[gw.gateway_id].clear()
