"""A small SM-2 style scheduler for in-app study.

Intentionally simpler than Anki's FSRS: this only has to order the queue well
enough for a study session, and Anki remains the system of record once reviews
are pushed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4

MIN_EASE = 1.3
LEARNING_STEPS_MINUTES = {AGAIN: 1.0, HARD: 6.0, GOOD: 10.0}
GRADUATING_INTERVAL_DAYS = 1.0
EASY_INTERVAL_DAYS = 4.0


@dataclass
class SrsState:
    due_at: datetime
    interval_days: float = 0.0
    ease_factor: float = 2.5
    reps: int = 0
    lapses: int = 0


def new_state(now: datetime | None = None) -> SrsState:
    return SrsState(due_at=now or datetime.now(UTC))


def review(state: SrsState, ease: int, now: datetime | None = None) -> SrsState:
    """Apply a grade and return the next state."""
    if ease not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"ease must be 1-4, got {ease}")
    now = now or datetime.now(UTC)

    ease_factor = state.ease_factor
    lapses = state.lapses
    reps = state.reps + 1

    if ease == AGAIN:
        # Lapse: back to learning, ease penalised.
        interval = LEARNING_STEPS_MINUTES[AGAIN] / (24 * 60)
        ease_factor = max(MIN_EASE, ease_factor - 0.20)
        lapses += 1
        return SrsState(now + timedelta(days=interval), 0.0, ease_factor, reps, lapses)

    if state.interval_days <= 0:
        # Still learning: graduate on Good/Easy, short step on Hard.
        if ease == HARD:
            interval = LEARNING_STEPS_MINUTES[HARD] / (24 * 60)
            next_interval_days = 0.0
        elif ease == GOOD:
            interval = next_interval_days = GRADUATING_INTERVAL_DAYS
        else:
            interval = next_interval_days = EASY_INTERVAL_DAYS
            ease_factor = min(3.0, ease_factor + 0.15)
        return SrsState(
            now + timedelta(days=interval), next_interval_days, ease_factor, reps, lapses
        )

    # Review card.
    if ease == HARD:
        ease_factor = max(MIN_EASE, ease_factor - 0.15)
        interval = state.interval_days * 1.2
    elif ease == GOOD:
        interval = state.interval_days * ease_factor
    else:
        ease_factor = min(3.0, ease_factor + 0.15)
        interval = state.interval_days * ease_factor * 1.3

    interval = max(GRADUATING_INTERVAL_DAYS, round(interval, 2))
    return SrsState(now + timedelta(days=interval), interval, ease_factor, reps, lapses)
