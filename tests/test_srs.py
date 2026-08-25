from datetime import UTC, datetime, timedelta

import pytest

from vocabapp.services import srs

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def test_new_card_graduates_on_good():
    state = srs.review(srs.new_state(NOW), srs.GOOD, NOW)

    assert state.interval_days == pytest.approx(1.0)
    assert state.due_at == NOW + timedelta(days=1)
    assert state.reps == 1
    assert state.lapses == 0


def test_new_card_easy_jumps_ahead_and_raises_ease():
    state = srs.review(srs.new_state(NOW), srs.EASY, NOW)

    assert state.interval_days == pytest.approx(4.0)
    assert state.ease_factor > 2.5


def test_new_card_hard_stays_in_learning():
    state = srs.review(srs.new_state(NOW), srs.HARD, NOW)

    assert state.interval_days == 0.0
    assert state.due_at < NOW + timedelta(hours=1)


def test_good_grows_the_interval_by_the_ease_factor():
    first = srs.review(srs.new_state(NOW), srs.GOOD, NOW)
    second = srs.review(first, srs.GOOD, NOW)

    assert second.interval_days == pytest.approx(first.interval_days * first.ease_factor)
    assert second.due_at > first.due_at


def test_again_resets_to_learning_and_penalises_ease():
    mature = srs.SrsState(due_at=NOW, interval_days=20, ease_factor=2.5, reps=5)
    lapsed = srs.review(mature, srs.AGAIN, NOW)

    assert lapsed.interval_days == 0.0
    assert lapsed.lapses == 1
    assert lapsed.ease_factor == pytest.approx(2.3)
    assert lapsed.due_at < NOW + timedelta(minutes=2)


def test_ease_factor_never_falls_below_the_floor():
    state = srs.SrsState(due_at=NOW, interval_days=10, ease_factor=srs.MIN_EASE)
    for _ in range(5):
        state = srs.review(state, srs.AGAIN, NOW)

    assert state.ease_factor == pytest.approx(srs.MIN_EASE)


def test_hard_shortens_relative_to_good_on_a_review_card():
    base = srs.SrsState(due_at=NOW, interval_days=10, ease_factor=2.5, reps=3)

    hard = srs.review(base, srs.HARD, NOW)
    good = srs.review(base, srs.GOOD, NOW)
    easy = srs.review(base, srs.EASY, NOW)

    assert hard.interval_days < good.interval_days < easy.interval_days


def test_invalid_ease_rejected():
    with pytest.raises(ValueError):
        srs.review(srs.new_state(NOW), 5, NOW)
