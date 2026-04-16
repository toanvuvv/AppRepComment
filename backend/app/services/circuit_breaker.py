"""Per-nick circuit breaker for LLM call failures.

Tracks a rolling window of successes/failures for each nick. When the
failure rate exceeds a threshold the circuit OPENs and callers are told
to short-circuit. After a cooldown the circuit moves to HALF_OPEN and
allows a single probe; success closes it, failure re-opens it.

Single-loop FastAPI assumption: all mutation happens on the event loop,
so no locks are needed.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_MIN_SAMPLES_FOR_TRIP: int = 10


class NickCircuit:
    """A rolling-window circuit breaker for a single nick."""

    def __init__(
        self,
        window_size: int = 20,
        error_threshold: float = 0.5,
        open_duration_sec: float = 60.0,
    ) -> None:
        self._window_size: int = int(window_size)
        self._error_threshold: float = float(error_threshold)
        self._open_duration: float = float(open_duration_sec)
        self._samples: deque[bool] = deque(maxlen=self._window_size)
        self._state: CircuitState = CircuitState.CLOSED
        self._opened_at: float | None = None

    # --- recording -----------------------------------------------------

    def record_success(self) -> None:
        if self._state is CircuitState.HALF_OPEN:
            # Probe succeeded — fully close and clear history.
            self._samples.clear()
            self._state = CircuitState.CLOSED
            self._opened_at = None
            logger.info("NickCircuit: probe succeeded, state -> CLOSED")
            return

        self._samples.append(True)
        # A success in CLOSED shouldn't cause a transition; in OPEN we
        # ignore stray records (shouldn't normally happen).

    def record_failure(self) -> None:
        if self._state is CircuitState.HALF_OPEN:
            # Probe failed — re-open with a fresh cooldown.
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning("NickCircuit: probe failed, state -> OPEN")
            return

        self._samples.append(False)
        self._maybe_trip()

    # --- queries -------------------------------------------------------

    def can_attempt(self) -> bool:
        """True if callers may attempt an LLM call right now."""
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.HALF_OPEN:
            return True
        # OPEN — check cooldown.
        if self._opened_at is None:
            # Defensive: treat as CLOSED if somehow missing timestamp.
            self._state = CircuitState.CLOSED
            return True
        if (time.monotonic() - self._opened_at) >= self._open_duration:
            self._state = CircuitState.HALF_OPEN
            logger.info("NickCircuit: cooldown elapsed, state -> HALF_OPEN")
            return True
        return False

    def state(self) -> CircuitState:
        # Lazily promote OPEN -> HALF_OPEN if cooldown elapsed so that
        # readers (like the health endpoint) see the current state.
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and (time.monotonic() - self._opened_at) >= self._open_duration
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    # --- introspection -------------------------------------------------

    def snapshot(self) -> dict:
        successes = sum(1 for s in self._samples if s)
        failures = len(self._samples) - successes
        return {
            "state": self.state().value,
            "failures": failures,
            "successes": successes,
        }

    # --- internal ------------------------------------------------------

    def _maybe_trip(self) -> None:
        if self._state is not CircuitState.CLOSED:
            return
        if len(self._samples) < _MIN_SAMPLES_FOR_TRIP:
            return
        failures = sum(1 for s in self._samples if not s)
        rate = failures / len(self._samples)
        if rate > self._error_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "NickCircuit tripped: failure_rate=%.2f over %d samples, state -> OPEN",
                rate,
                len(self._samples),
            )


class CircuitBreakerRegistry:
    """Lazy per-nick registry of NickCircuit instances."""

    def __init__(self) -> None:
        self._circuits: dict[int, NickCircuit] = {}

    def for_nick(self, nick_live_id: int) -> NickCircuit:
        circuit = self._circuits.get(nick_live_id)
        if circuit is None:
            circuit = NickCircuit()
            self._circuits[nick_live_id] = circuit
        return circuit

    def snapshot(self) -> dict[int, dict]:
        """Snapshot for a health endpoint."""
        return {nick_id: c.snapshot() for nick_id, c in self._circuits.items()}


# Module-level singleton.
circuit_registry: CircuitBreakerRegistry = CircuitBreakerRegistry()
