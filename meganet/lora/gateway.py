"""
LoRa Gateway with EU868 duty-cycle enforcement.

DutyCycleTracker: sliding 1-hour window, max 36,000ms TX time (1% of 3600s).
LoRaGateway: positioned gateway with RX queue.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .packet import LoRaPacket

DUTY_CYCLE_WINDOW_S = 3600          # 1 hour
DUTY_CYCLE_BUDGET_MS = 36_000       # 1% of 3600s in ms


class DutyCycleTracker:
    """Sliding 1-hour window duty-cycle enforcement."""

    def __init__(self, budget_ms: float = DUTY_CYCLE_BUDGET_MS):
        self.budget_ms = budget_ms
        # Each entry: (timestamp_s, duration_ms)
        self._log: deque[tuple[float, float]] = deque()

    def _purge_old(self, now: float) -> None:
        cutoff = now - DUTY_CYCLE_WINDOW_S
        while self._log and self._log[0][0] < cutoff:
            self._log.popleft()

    def used_ms(self, now: float | None = None) -> float:
        if now is None:
            now = time.time()
        self._purge_old(now)
        return sum(d for _, d in self._log)

    def remaining_ms(self, now: float | None = None) -> float:
        return max(0.0, self.budget_ms - self.used_ms(now))

    def can_transmit(self, duration_ms: float, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        return self.used_ms(now) + duration_ms <= self.budget_ms

    def record_transmission(self, duration_ms: float, now: float | None = None) -> bool:
        """Record a transmission. Returns False if duty cycle would be exceeded."""
        if now is None:
            now = time.time()
        if not self.can_transmit(duration_ms, now):
            return False
        self._log.append((now, duration_ms))
        return True


@dataclass
class LoRaGateway:
    gateway_id: str
    x_km: float
    y_km: float
    rx_queue: list["LoRaPacket"] = field(default_factory=list)
    duty_tracker: DutyCycleTracker = field(default_factory=DutyCycleTracker)

    def receive(self, packet: "LoRaPacket") -> None:
        """Accept an incoming packet into the RX queue."""
        self.rx_queue.append(packet)

    def drain(self) -> list["LoRaPacket"]:
        """Return and clear all received packets."""
        pkts = self.rx_queue.copy()
        self.rx_queue.clear()
        return pkts

    def can_transmit(self, duration_ms: float) -> bool:
        return self.duty_tracker.can_transmit(duration_ms)

    def transmit(self, duration_ms: float) -> bool:
        """Attempt to transmit; returns False if duty cycle exceeded."""
        return self.duty_tracker.record_transmission(duration_ms)
