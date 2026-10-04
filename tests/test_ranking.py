from datetime import datetime, timedelta, timezone

import pytest

from researchpilot.application import (
    DeterministicPaperRanker,
    RankPapers,
    RankingPolicy,
)
from researchpilot.domain import Interest, InterestProfile, Paper, PaperSource

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def make_paper(
    external_id: str = "2601.00001",
    *,
    title: str = "Planning for AI agents",
    abstract: str = "A language model uses planning repeatedly: planning.",
    age_days: float = 0,
) -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id=external_id,
        title=title,
        abstract=abstract,
        authors=["Ada Lovelace"],
        published_at=NOW - timedelta(days=age_days),
        url=f"https://arxiv.org/abs/{external_id}",
    )


def profile(*, exclusions: list[str] | None = None) -> InterestProfile:
    return InterestProfile(
        name="Test profile",
        interests=[
            Interest(
                name="Agents",
                keywords=["AI agents", "planning"],
                weight=2.0,
            ),
            Interest(
                name="Language models",
                keywords=["language model"],
                weight=0.5,
            ),
        ],
        exclusions=[] if exclusions is None else exclusions,
    )


def rank_one(
    paper: Paper,
    *,
    user_profile: InterestProfile | None = None,
    policy: RankingPolicy | None = None,
):
    return DeterministicPaperRanker().rank(
        [paper],
        profile() if user_profile is None else user_profile,
        RankingPolicy() if policy is None else policy,
        now=NOW,
    )[0]


def test_each_distinct_keyword_contributes_its_interest_weight_once() -> None:
    ranked = rank_one(make_paper())

    assert [(match.keyword, match.contribution) for match in ranked.matches] == [
        ("AI agents", 2.0),
        ("planning", 2.0),
        ("language model", 0.5),
    ]
    assert ranked.keyword_score == 4.5
    assert ranked.recency_bonus == 0.5
    assert ranked.score == 5.0
    assert ranked.selected is True


def test_keyword_matching_uses_term_boundaries() -> None:
    user_profile = InterestProfile(
        name="Boundaries",
        interests=[Interest(name="AI", keywords=["ai"])],
    )

    ranked = rank_one(
        make_paper(title="Training systems", abstract="Details about training."),
        user_profile=user_profile,
    )

    assert ranked.matches == []
    assert ranked.score == 0
    assert ranked.selected is False


def test_phrase_does_not_match_across_title_and_abstract_boundary() -> None:
    user_profile = InterestProfile(
        name="Field boundaries",
        interests=[Interest(name="Local models", keywords=["local LLM"])],
    )

    ranked = rank_one(
        make_paper(title="A system that runs local", abstract="LLM inference."),
        user_profile=user_profile,
    )

    assert ranked.matches == []
    assert ranked.selected is False


def test_recency_bonus_decays_linearly_and_reaches_zero() -> None:
    policy = RankingPolicy(recency_weight=1.0, recency_window_days=10)

    halfway = rank_one(make_paper(age_days=5), policy=policy)
    expired = rank_one(make_paper(age_days=11), policy=policy)

    assert halfway.recency_bonus == 0.5
    assert expired.recency_bonus == 0


def test_unmatched_paper_receives_no_recency_bonus() -> None:
    ranked = rank_one(
        make_paper(title="Unrelated topic", abstract="No configured terms."),
        policy=RankingPolicy(minimum_score=0.1, recency_weight=10),
    )

    assert ranked.keyword_score == 0
    assert ranked.recency_bonus == 0
    assert ranked.selected is False


def test_exclusion_prevents_selection_without_hiding_score() -> None:
    ranked = rank_one(
        make_paper(abstract="Planning for medical imaging with a language model."),
        user_profile=profile(exclusions=["medical imaging"]),
    )

    assert ranked.score > 0
    assert ranked.exclusions == ["medical imaging"]
    assert ranked.selected is False


def test_minimum_score_controls_selection() -> None:
    paper = make_paper(title="Planning methods", abstract="Only one match.")

    selected = rank_one(paper, policy=RankingPolicy(minimum_score=2.5))
    rejected = rank_one(paper, policy=RankingPolicy(minimum_score=2.6))

    assert selected.score == 2.5
    assert selected.selected is True
    assert rejected.selected is False


def test_results_are_deterministically_ordered() -> None:
    lower = make_paper(
        "2601.00001",
        title="Planning methods",
        abstract="One match.",
    )
    higher = make_paper(
        "2601.00002",
        title="Planning for AI agents",
        abstract="A language model.",
    )

    ranked = DeterministicPaperRanker().rank(
        [lower, higher],
        profile(),
        RankingPolicy(),
        now=NOW,
    )

    assert [item.paper.external_id for item in ranked] == [
        "2601.00002",
        "2601.00001",
    ]


def test_rank_papers_loads_papers_from_repository() -> None:
    papers = [make_paper()]

    class Repository:
        def list_all(self) -> list[Paper]:
            return papers

    ranked = RankPapers(Repository()).execute(
        profile(),
        RankingPolicy(),
        now=NOW,
    )

    assert [item.paper for item in ranked] == papers


@pytest.mark.parametrize(
    "policy",
    [
        lambda: RankingPolicy(minimum_score=-1),
        lambda: RankingPolicy(recency_weight=-1),
        lambda: RankingPolicy(recency_window_days=0),
    ],
)
def test_invalid_ranking_policy_is_rejected(policy) -> None:
    with pytest.raises(ValueError):
        policy()
