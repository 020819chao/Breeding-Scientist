"""Structural-eval tests (no judge calls)."""

from __future__ import annotations

import pytest

from co_scientist.config import Config
from co_scientist.evals.rubrics import BREEDING_DESIGNER_RUBRIC, weighted_total
from co_scientist.evals.runner import _check_structure, run_agent


def test_pairwise_calibration_structural_check_requires_better_idea() -> None:
    bad = _check_structure("pairwise_calibration", "no verdict here", {})
    assert any("better idea" in e for e in bad)
    good = _check_structure("pairwise_calibration", "...\nbetter idea: 1", {})
    assert good == []


def test_breeding_designer_structural_check_finds_missing_sections() -> None:
    errs = _check_structure(
        "breeding_designer",
        "just a paragraph with no required sections",
        {},
    )
    assert any("mechanism" in e or "entit" in e for e in errs)


def test_risk_reviewer_evidence_structural_check_requires_citations() -> None:
    errs = _check_structure(
        "risk_reviewer_evidence",
        "review text without URLs",
        {"must_cite_at_least": 2},
    )
    assert any("URL" in e for e in errs)


def test_weighted_total_simple() -> None:
    scores = [
        {"name": "novelty", "score": 5, "rationale": ""},
        {"name": "specificity", "score": 3, "rationale": ""},
        {"name": "citation_grounding", "score": 4, "rationale": ""},
        {"name": "testability", "score": 4, "rationale": ""},
    ]
    w = weighted_total(BREEDING_DESIGNER_RUBRIC, scores)
    # (5+3+4+4) / (5*4) = 0.8
    assert w == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_offline_run_uses_no_judge_call() -> None:
    cfg = Config()
    # pairwise_calibration.jsonl is bundled; offline=True must not call the API.
    result = await run_agent(cfg, "pairwise_calibration", offline=True)
    assert result["n_fixtures"] >= 1
    # offline → no `mean_weighted`
    assert result["mean_weighted"] is None
