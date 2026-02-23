"""Unit tests for meganet.lora"""
import math
import pytest

from meganet.lora.gateway import DutyCycleTracker, LoRaGateway
from meganet.lora.packet import (
    HEADER_SIZE,
    SF_DATA_MAX,
    SF_MAX_PAYLOAD,
    SF_SENSITIVITY,
    LoRaPacket,
    PacketType,
    compute_time_on_air_ms,
)
from meganet.lora.simulator import (
    LoRaSimulator,
    delivery_probability,
    rssi_dbm,
    path_loss_db,
)


# ── Packet ────────────────────────────────────────────────────────────────────

def test_header_size():
    assert HEADER_SIZE == 19


def test_packet_roundtrip():
    pkt = LoRaPacket(
        dev_eui=0xDEADBEEFCAFEBABE,
        msg_id=0x01020304,
        frag_idx=0,
        total_frags=3,
        pkt_type=PacketType.DATA,
        sf=7,
        payload=b"hello world",
    )
    raw = pkt.to_bytes()
    restored = LoRaPacket.from_bytes(raw)
    assert restored.dev_eui == pkt.dev_eui
    assert restored.msg_id == pkt.msg_id
    assert restored.frag_idx == pkt.frag_idx
    assert restored.total_frags == pkt.total_frags
    assert restored.pkt_type == pkt.pkt_type
    assert restored.sf == pkt.sf
    assert restored.payload == pkt.payload


def test_sf_data_max():
    # SF7 data max = 222 - 19 = 203
    assert SF_DATA_MAX[7] == 203
    assert SF_DATA_MAX[9] == 115 - 19


def test_time_on_air_positive():
    for sf in range(7, 13):
        toa = compute_time_on_air_ms(sf, 50)
        assert toa > 0


def test_packet_id_uniqueness():
    p1 = LoRaPacket(1, 100, 0, 2, PacketType.DATA, 7, b"a")
    p2 = LoRaPacket(1, 100, 1, 2, PacketType.DATA, 7, b"b")
    p3 = LoRaPacket(1, 200, 0, 2, PacketType.DATA, 7, b"c")
    assert p1.packet_id != p2.packet_id
    assert p1.packet_id != p3.packet_id


# ── Propagation model ─────────────────────────────────────────────────────────

def test_rssi_at_5km():
    """At 5km, practical LoRa EU868 model gives ≈ -117 dBm (±5 dBm tolerance)."""
    r = rssi_dbm(5.0)
    assert -122 < r < -112, f"RSSI at 5km = {r:.1f} dBm, expected ≈ -117 dBm"


def test_rssi_decreases_with_distance():
    r1 = rssi_dbm(1.0)
    r5 = rssi_dbm(5.0)
    r10 = rssi_dbm(10.0)
    assert r1 > r5 > r10


def test_delivery_probability_above_threshold():
    """Well above sensitivity → high probability."""
    prob = delivery_probability(-100, 7)  # SF7 sens = -123 dBm, so -100 is well above
    assert prob > 0.99


def test_delivery_probability_below_threshold():
    """Well below sensitivity → near-zero probability."""
    prob = delivery_probability(-150, 7)  # SF7 sens = -123 dBm
    assert prob < 0.01


def test_delivery_probability_at_threshold():
    """At threshold → ~50% probability."""
    threshold = SF_SENSITIVITY[7]
    prob = delivery_probability(threshold, 7)
    assert 0.4 < prob < 0.6


# ── Duty cycle ────────────────────────────────────────────────────────────────

def test_duty_cycle_allows_under_budget():
    tracker = DutyCycleTracker(budget_ms=1000)
    assert tracker.can_transmit(500)
    assert tracker.record_transmission(500)
    assert tracker.can_transmit(499)


def test_duty_cycle_blocks_over_budget():
    tracker = DutyCycleTracker(budget_ms=1000)
    tracker.record_transmission(900)
    assert not tracker.can_transmit(200)
    assert not tracker.record_transmission(200)


def test_duty_cycle_remaining():
    tracker = DutyCycleTracker(budget_ms=36000)
    tracker.record_transmission(1000)
    assert abs(tracker.remaining_ms() - 35000) < 1


# ── Simulator ─────────────────────────────────────────────────────────────────

def test_simulator_deduplication():
    """A packet transmitted once should appear at most once per gateway."""
    sim = LoRaSimulator(seed=42)
    pkt = LoRaPacket(1, 999, 0, 1, PacketType.DATA, 7, b"dedup test")
    sim.transmit(pkt, 10.0, 10.0)  # centre of grid → all gateways in range
    collected = sim.collect_packets()
    # All collected should be unique by packet_id
    ids = [p.packet_id for p in collected]
    assert len(ids) == len(set(ids))


def test_simulator_close_node_receives():
    """Node at 1km from centre gateway should almost always deliver."""
    sim = LoRaSimulator(seed=123)
    received = 0
    for _ in range(20):
        sim.reset_seen()
        pkt = LoRaPacket(1, _ + 1, 0, 1, PacketType.DATA, 7, b"x")
        result = sim.transmit(pkt, 10.5, 10.5)  # 0.5km from centre gw4
        if result:
            received += 1
    assert received >= 15  # at least 75% success rate at short range


def test_simulator_far_node_low_delivery():
    """Node >14km from all gateways at SF7 (sensitivity -123 dBm) should mostly fail.
    RSSI at 14km ≈ -129 dBm < -123 dBm → sigmoid prob < 5% → rarely received."""
    sim = LoRaSimulator(seed=999)
    received = 0
    for _ in range(20):
        sim.reset_seen()
        pkt = LoRaPacket(1, _ + 1, 0, 1, PacketType.DATA, 7, b"x")
        result = sim.transmit(pkt, -10.0, -10.0)  # ~14.14 km from nearest gateway
        if result:
            received += 1
    # At SF7, node 14+ km away should almost never succeed
    assert received <= 5, f"Expected ≤5/20 successes from 14km, got {received}"


def test_gateway_receive_drain():
    gw = LoRaGateway("test_gw", 0.0, 0.0)
    pkt = LoRaPacket(1, 1, 0, 1, PacketType.DATA, 7, b"test")
    gw.receive(pkt)
    drained = gw.drain()
    assert len(drained) == 1
    assert gw.drain() == []  # already drained
