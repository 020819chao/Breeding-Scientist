"""Tests for pairwise-ranking verdict parsing and mode selection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from co_scientist.agents.iteration_orchestrator_ranking import (
    IterationOrchestratorRankingStage,
    _parse_better_idea,
)
from co_scientist.config import Config
from co_scientist.models import Hypothesis

# ----------------------------- verdict parser ----------------------------- #

def test_parse_better_idea_basic() -> None:
    assert _parse_better_idea("blah\nbetter idea: 1") == 1
    assert _parse_better_idea("blah\nbetter idea: 2") == 2


def test_parse_better_idea_trailing_marker_wins() -> None:
    text = "An earlier mention: better idea: 1\n\nFinal verdict.\nbetter idea: 2"
    assert _parse_better_idea(text) == 2


def test_parse_better_idea_handles_case_and_punctuation() -> None:
    assert _parse_better_idea("...\nBetter Idea: 2.") == 2
    assert _parse_better_idea("...\n**better idea**: 1") == 1


def test_parse_better_idea_returns_none_when_missing() -> None:
    assert _parse_better_idea("no verdict here") is None
    assert _parse_better_idea("") is None


def test_parse_better_idea_handles_qualifier_words() -> None:
    """Regression: the prior 'in tail.split()[0:1]' check rejected these."""
    assert _parse_better_idea("better idea: option 1") == 1
    assert _parse_better_idea("better idea: hypothesis 2") == 2
    assert _parse_better_idea("better idea: hyp 1") == 1


def test_parse_better_idea_word_boundary_excludes_12() -> None:
    """'better idea: 12 because...' must NOT be read as '1'."""
    # `12` should not match `[12]\b`.
    assert _parse_better_idea("better idea: 12 because of context") is None


# ----------------------------- mode selection ----------------------------- #

def _h(*, calibration_score: float, matches: int, hid: str = "hyp_x") -> Hypothesis:
    return Hypothesis(
        id=hid, session_id="ses", created_at=datetime.now(UTC),
        created_by="breeding_designer", strategy="literature",
        title="t", summary="s", full_text="f",
        artifact_path=f"artifacts/ses/hypotheses/{hid}.json",
        calibration_score=calibration_score, pairwise_calibrations_played=matches, state="calibration_pool",
    )


def _agent() -> IterationOrchestratorRankingStage:
    deps = MagicMock()
    deps.cfg = Config()
    return IterationOrchestratorRankingStage(deps)


def test_pairwise_calibration_config_uses_semantic_names() -> None:
    cfg = Config()
    cfg.pairwise_calibration.pairwise_calibration_initial = 1300
    cfg.pairwise_calibration.debate_when_pairwise_calibration_delta_lt = 80
    cfg.pairwise_calibration.debate_when_pairwise_calibrations_lt = 4

    assert cfg.pairwise_calibration.effective_pairwise_calibration_initial == 1300
    assert cfg.pairwise_calibration.effective_debate_when_pairwise_calibration_delta_lt == 80
    assert cfg.pairwise_calibration.effective_debate_when_pairwise_calibrations_lt == 4


def test_pairwise_calibration_config_respects_zero_threshold() -> None:
    cfg = Config()
    cfg.pairwise_calibration.debate_when_pairwise_calibration_delta_lt = 0
    cfg.pairwise_calibration.debate_when_pairwise_calibrations_lt = 0

    assert cfg.pairwise_calibration.effective_debate_when_pairwise_calibration_delta_lt == 0
    assert cfg.pairwise_calibration.effective_debate_when_pairwise_calibrations_lt == 0


def test_mode_debate_when_either_player_has_few_matches() -> None:
    a = _h(hid="a", calibration_score=1500, matches=0)
    b = _h(hid="b", calibration_score=1500, matches=10)
    assert _agent()._select_mode(a, b) == "debate"


def test_mode_debate_when_calibration_score_gap_is_small() -> None:
    a = _h(hid="a", calibration_score=1500, matches=5)
    b = _h(hid="b", calibration_score=1520, matches=5)
    assert _agent()._select_mode(a, b) == "debate"


def test_mode_pairwise_when_warm_and_large_gap() -> None:
    a = _h(hid="a", calibration_score=1500, matches=10)
    b = _h(hid="b", calibration_score=1300, matches=10)
    assert _agent()._select_mode(a, b) == "pairwise"


# ----------------------------- nearest calibration helper ----------------------------- #

def test_nearest_calibration_score_picks_closest() -> None:
    target = _h(hid="t", calibration_score=1300, matches=0)
    pool = [
        _h(hid="a", calibration_score=1000, matches=5),
        _h(hid="b", calibration_score=1310, matches=5),    # closest
        _h(hid="c", calibration_score=1500, matches=5),
    ]
    agent = _agent()
    nearest = agent._nearest_calibration_score(target, pool)
    assert nearest is not None and nearest.id == "b"
    assert agent._nearest_calibration_score(target, pool) is nearest


def test_nearest_calibration_score_empty_pool() -> None:
    target = _h(hid="t", calibration_score=1300, matches=0)
    assert _agent()._nearest_calibration_score(target, []) is None


