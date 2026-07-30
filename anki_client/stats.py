import time
from collections import Counter
from itertools import combinations

from .client import AnkiClient
from .models import DeckStats


class StatsClient:
    def __init__(self, client: AnkiClient | None = None):
        self._c = client or AnkiClient()

    # ------------------------------------------------------------------
    # Deck stats
    # ------------------------------------------------------------------

    def get_deck_stats(self, deck_names: list[str]) -> list[DeckStats]:
        result = self._c._request("getDeckStats", decks=deck_names)
        return [
            DeckStats(
                deck_id=v["deck_id"],
                name=v["name"],
                new_count=v["new_count"],
                learn_count=v["learn_count"],
                review_count=v["review_count"],
                total_in_deck=v["total_in_deck"],
            )
            for v in result.values()
        ]

    # ------------------------------------------------------------------
    # Study time
    # ------------------------------------------------------------------

    def get_total_study_hours(self, deck: str) -> float:
        """Sum of all review time for every card in the deck, in hours."""
        card_ids = self._c.find_cards(f'deck:"{deck}"')
        if not card_ids:
            return 0.0
        reviews = self._c._request("getReviewsOfCards", cards=card_ids)
        total_ms = sum(r["time"] for rlist in reviews.values() for r in rlist)
        return total_ms / 1_000 / 3_600

    # ------------------------------------------------------------------
    # Retention rate
    # ------------------------------------------------------------------

    def get_retention_rate(self, deck: str, days: int = 30) -> float:
        """Percentage of reviews answered correctly (ease > 1) in the last N days."""
        card_ids = self._c.find_cards(f'deck:"{deck}"')
        if not card_ids:
            return 0.0
        cutoff_ms = (time.time() - days * 86_400) * 1_000
        reviews = self._c._request("getReviewsOfCards", cards=card_ids)
        total = correct = 0
        for rlist in reviews.values():
            for r in rlist:
                if r["id"] >= cutoff_ms:
                    total += 1
                    if r["ease"] > 1:
                        correct += 1
        return round(correct / total * 100, 1) if total else 0.0

    # ------------------------------------------------------------------
    # Hard / leech cards
    # ------------------------------------------------------------------

    def get_hard_cards(
        self, deck: str, min_lapses: int = 3, limit: int = 20
    ) -> list[dict]:
        """Cards sorted by lapse count descending."""
        card_ids = self._c.find_cards(f'deck:"{deck}" prop:lapses>={min_lapses}')
        if not card_ids:
            return []
        infos = self._c._request("cardsInfo", cards=card_ids)
        infos.sort(key=lambda x: x["lapses"], reverse=True)

        def _field(info: dict, *names: str) -> str:
            for name in names:
                val = info.get("fields", {}).get(name, {}).get("value", "")
                if val:
                    return val
            return ""

        return [
            {
                "card_id": i["cardId"],
                "note_id": i["note"],
                "traditional": _field(i, "Traditional"),
                "pinyin": _field(i, "Pinyin.1", "Pinyin", "pinyin"),
                "meaning": _field(i, "Meaning"),
                "lapses": i["lapses"],
                "reps": i["reps"],
                "interval_days": i["interval"],
            }
            for i in infos[:limit]
        ]

    # ------------------------------------------------------------------
    # Review forecast
    # ------------------------------------------------------------------

    def get_review_forecast(self, deck: str) -> dict:
        """Cards due today, in the next 7 days, and new available."""
        due_today = self._c.find_cards(f'deck:"{deck}" is:due')
        # prop:due<=6 means due within the next 7 days (0=today, 6=6 days from now)
        due_week = self._c.find_cards(f'deck:"{deck}" prop:due<=6')
        new_available = self._c.find_cards(f'deck:"{deck}" is:new')
        return {
            "due_today": len(due_today),
            "due_next_7_days": len(due_week),
            "new_available": len(new_available),
        }

    # ------------------------------------------------------------------
    # New cards added
    # ------------------------------------------------------------------

    def get_new_cards_added(self, deck: str, days: int = 7) -> int:
        """Number of cards added to the deck in the last N days."""
        return len(self._c.find_cards(f'deck:"{deck}" added:{days}'))

    # ------------------------------------------------------------------
    # Confusion / co-failure analysis
    # ------------------------------------------------------------------

    def get_confused_pairs(
        self,
        deck: str,
        session_gap_minutes: int = 30,
        min_co_failures: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """Find card pairs failed together in the same study session.

        Cards that repeatedly fail within the same session are strong
        candidates for cards you're mixing up with each other.
        """
        card_ids = self._c.find_cards(f'deck:"{deck}"')
        if not card_ids:
            return []

        reviews = self._c._request("getReviewsOfCards", cards=card_ids)

        # Collect all failures as (timestamp_ms, card_id)
        failures: list[tuple[int, int]] = []
        for card_id_str, rlist in reviews.items():
            for r in rlist:
                if r["ease"] == 1:
                    failures.append((r["id"], int(card_id_str)))

        if not failures:
            return []

        failures.sort()

        # Split into sessions by gap
        gap_ms = session_gap_minutes * 60 * 1_000
        sessions: list[set[int]] = []
        current: set[int] = {failures[0][1]}
        prev_ts = failures[0][0]

        for ts, card_id in failures[1:]:
            if ts - prev_ts > gap_ms:
                sessions.append(current)
                current = set()
            current.add(card_id)
            prev_ts = ts
        sessions.append(current)

        # Count how many sessions each pair co-failed in
        pair_counts: Counter = Counter()
        for session_cards in sessions:
            if len(session_cards) >= 2:
                for a, b in combinations(sorted(session_cards), 2):
                    pair_counts[(a, b)] += 1

        top_pairs = [
            (pair, count)
            for pair, count in pair_counts.most_common(limit)
            if count >= min_co_failures
        ]
        if not top_pairs:
            return []

        # Fetch card info for all cards appearing in top pairs
        unique_ids = list({cid for pair, _ in top_pairs for cid in pair})
        infos = self._c._request("cardsInfo", cards=unique_ids)
        card_info: dict[int, dict] = {i["cardId"]: i for i in infos}

        def _field(info: dict, *names: str) -> str:
            for name in names:
                val = info.get("fields", {}).get(name, {}).get("value", "")
                if val:
                    return val
            return ""

        def _summarise(card_id: int) -> dict:
            i = card_info.get(card_id, {})
            return {
                "card_id": card_id,
                "traditional": _field(i, "Traditional"),
                "meaning": _field(i, "Meaning"),
                "lapses": i.get("lapses", 0),
            }

        return [
            {
                "co_failures": count,
                "card_a": _summarise(pair[0]),
                "card_b": _summarise(pair[1]),
            }
            for pair, count in top_pairs
        ]
