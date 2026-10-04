"""Transparent deterministic ranking for normalized research papers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from researchpilot.domain import (
    InterestProfile,
    KeywordMatch,
    Paper,
    RankedPaper,
)
from researchpilot.domain.ports import PaperRepository


@dataclass(frozen=True)
class RankingPolicy:
    """Numerical settings for deterministic paper ranking."""

    minimum_score: float = 1.0
    recency_weight: float = 0.5
    recency_window_days: int = 30

    def __post_init__(self) -> None:
        if self.minimum_score < 0:
            raise ValueError("minimum_score cannot be negative")
        if self.recency_weight < 0:
            raise ValueError("recency_weight cannot be negative")
        if self.recency_window_days < 1:
            raise ValueError("recency_window_days must be positive")


def _normalized_search_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalized_search_text(term)
    pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
    return re.search(pattern, text) is not None


class DeterministicPaperRanker:
    """Rank papers using weighted matches, exclusions, and recency."""

    def rank(
        self,
        papers: list[Paper],
        profile: InterestProfile,
        policy: RankingPolicy,
        *,
        now: datetime,
    ) -> list[RankedPaper]:
        """Return every paper in stable decision and score order."""

        if now.tzinfo is None:
            raise ValueError("ranking time must include a timezone")

        ranked = [
            self._rank_one(paper, profile, policy, now=now) for paper in papers
        ]
        return sorted(
            ranked,
            key=lambda item: (
                not item.selected,
                -item.score,
                -item.paper.published_at.timestamp(),
                item.paper.source.value,
                item.paper.external_id,
            ),
        )

    def _rank_one(
        self,
        paper: Paper,
        profile: InterestProfile,
        policy: RankingPolicy,
        *,
        now: datetime,
    ) -> RankedPaper:
        search_fields = (
            _normalized_search_text(paper.title),
            _normalized_search_text(paper.abstract),
        )
        matches = [
            KeywordMatch(
                interest_name=interest.name,
                keyword=keyword,
                contribution=interest.weight,
            )
            for interest in profile.interests
            for keyword in interest.keywords
            if any(_contains_term(field, keyword) for field in search_fields)
        ]
        exclusions = [
            exclusion
            for exclusion in profile.exclusions
            if any(_contains_term(field, exclusion) for field in search_fields)
        ]

        keyword_score = sum(match.contribution for match in matches)
        recency_bonus = self._recency_bonus(paper, policy, now) if matches else 0.0
        score = round(keyword_score + recency_bonus, 6)
        return RankedPaper(
            paper=paper,
            score=score,
            keyword_score=round(keyword_score, 6),
            recency_bonus=round(recency_bonus, 6),
            matches=matches,
            exclusions=exclusions,
            selected=not exclusions and score >= policy.minimum_score,
        )

    @staticmethod
    def _recency_bonus(
        paper: Paper,
        policy: RankingPolicy,
        now: datetime,
    ) -> float:
        age_seconds = max(
            0.0,
            (
                now.astimezone(timezone.utc)
                - paper.published_at.astimezone(timezone.utc)
            ).total_seconds(),
        )
        age_days = age_seconds / 86_400
        remaining_fraction = max(
            0.0,
            1.0 - age_days / policy.recency_window_days,
        )
        return policy.recency_weight * remaining_fraction


class RankPapers:
    """Load stored papers and apply the deterministic ranking policy."""

    def __init__(
        self,
        repository: PaperRepository,
        ranker: DeterministicPaperRanker | None = None,
    ) -> None:
        self._repository = repository
        self._ranker = DeterministicPaperRanker() if ranker is None else ranker

    def execute(
        self,
        profile: InterestProfile,
        policy: RankingPolicy,
        *,
        now: datetime,
    ) -> list[RankedPaper]:
        """Rank all locally stored papers."""

        return self._ranker.rank(
            self._repository.list_all(),
            profile,
            policy,
            now=now,
        )
