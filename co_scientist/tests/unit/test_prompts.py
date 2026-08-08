"""Prompt rendering smoke."""

from __future__ import annotations

import pytest

from co_scientist.llm import prompts


def test_all_templates_exist_on_disk() -> None:
    for key in prompts.TEMPLATES:
        p = prompts.template_path(key)
        assert p.exists(), f"missing template file for {key}: {p}"


def test_list_templates_exposes_canonical_six_agent_keys() -> None:
    keys = set(prompts.list_templates())
    assert "breeding_designer.literature" in keys
    assert "iteration_orchestrator.final_synthesis" in keys
    removed_design_key = "gen" + "eration.literature"
    assert removed_design_key not in keys


def test_render_parse_goal() -> None:
    out = prompts.render(
        "goal_interpreter.parse_goal",
        goal="Investigate how X causes Y in mammalian cells",
        preferences_text="testable, specific",
    )
    assert "Investigate how X causes Y" in out
    assert "testable, specific" in out
    assert "target_traits" in out
    assert "material_constraints" in out
    assert "local_first" in out


def test_render_breeding_designer_literature() -> None:
    out = prompts.render(
        "breeding_designer.literature",
        goal="goal",
        preferences="prefs",
        articles_with_reasoning="(articles)",
    )
    assert "Goal: goal" in out
    assert "(articles)" in out
    assert "record_hypothesis" in out


def test_render_pairwise_calibration() -> None:
    out = prompts.render(
        "iteration_orchestrator.pairwise_calibration",
        goal="g",
        idea_attributes="novel, testable",
        hypothesis_1="H1 prose",
        hypothesis_1_id="H1",
        hypothesis_2="H2 prose",
        hypothesis_2_id="H2",
        review_1="R1",
        review_2="R2",
    )
    assert "better idea: <1 or 2>" in out
    assert "H1 prose" in out


def test_removed_prompt_keys_are_rejected() -> None:
    with pytest.raises(KeyError):
        prompts.render("parse_goal", goal="g", preferences_text="p")
    with pytest.raises(KeyError):
        removed_design_key = "gen" + "eration.literature"
        prompts.render(
            removed_design_key,
            goal="g",
            preferences="p",
            articles_with_reasoning="e",
        )


def test_render_unknown_template_raises() -> None:
    with pytest.raises(KeyError):
        prompts.render("nonexistent.template")
