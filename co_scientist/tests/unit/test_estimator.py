"""Tests for the pre-flight cost estimator."""

from __future__ import annotations

from co_scientist.config import Config
from co_scientist.llm.estimator import estimate


def test_estimate_emits_warning_when_budget_too_low() -> None:
    cfg = Config()
    cfg.run.budget_usd = 1.0
    est = estimate(cfg)
    assert est.total_usd > cfg.run.budget_usd
    assert est.warning is not None and "exceeds" in est.warning


def test_estimate_no_warning_when_budget_generous() -> None:
    cfg = Config()
    cfg.run.budget_usd = 9999.0
    est = estimate(cfg)
    assert est.warning is None


def test_estimate_rows_include_all_phases() -> None:
    cfg = Config()
    est = estimate(cfg)
    labels = {r.label for r in est.rows}
    assert {
        "Goal Interpreter",
        "Breeding Designer",
        "Risk Reviewer evidence review",
        "Pairwise calibration",
        "Final breeding synthesis",
    } <= labels


def test_estimate_scales_with_max_ideas() -> None:
    cfg = Config()
    small = estimate(cfg, max_ideas=10, max_pairwise_checks_per_hypothesis=4)
    big = estimate(cfg, max_ideas=100, max_pairwise_checks_per_hypothesis=12)
    assert big.total_usd > small.total_usd * 5


def test_estimate_uses_pairwise_check_limit_name() -> None:
    cfg = Config()
    cfg.run.max_pairwise_checks_per_hypothesis = 2

    renamed = estimate(cfg, max_ideas=20)
    explicit_override = estimate(
        cfg,
        max_ideas=20,
        max_pairwise_checks_per_hypothesis=20,
    )

    assert explicit_override.total_usd > renamed.total_usd
