"""Shared test doubles for time."""

from __future__ import annotations


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class RecordingSleeper:
    """Records every sleep and advances the paired clock instead of sleeping."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.clock.now += seconds
