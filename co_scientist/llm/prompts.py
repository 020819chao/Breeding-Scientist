"""Jinja2-based prompt loader.

Templates live in `config/prompts/*.md`. Runtime code uses canonical six-agent
prompt keys.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

from ..config import PROJECT_ROOT

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"


# Canonical six-agent prompt keys.
CANONICAL_TEMPLATES = {
    "goal_interpreter.parse_goal": "goal_interpreter_parse_goal.md",
    "breeding_designer.literature": "breeding_designer_literature.md",
    "breeding_designer.debate": "breeding_designer_debate.md",
    "risk_reviewer.evidence_review": (
        "risk_reviewer_evidence_review.md"
    ),
    "risk_reviewer.verification_review": (
        "risk_reviewer_verification_review.md"
    ),
    "risk_reviewer.observation_review": (
        "risk_reviewer_observation_review.md"
    ),
    "iteration_orchestrator.pairwise_calibration": (
        "iteration_orchestrator_pairwise_calibration.md"
    ),
    "iteration_orchestrator.calibration_debate": (
        "iteration_orchestrator_calibration_debate.md"
    ),
    "breeding_designer.feasibility": "breeding_designer_route_feasibility.md",
    "breeding_designer.combine": "breeding_designer_route_combine.md",
    "breeding_designer.simplify": "breeding_designer_route_simplify.md",
    "breeding_designer.out_of_box": "breeding_designer_route_out_of_box.md",
    "iteration_orchestrator.system_feedback": "iteration_orchestrator_system_feedback.md",
    "iteration_orchestrator.final_synthesis": "iteration_orchestrator_final_synthesis.md",
}

TEMPLATES = CANONICAL_TEMPLATES


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        autoescape=select_autoescape(disabled_extensions=("md",), default=False),
        undefined=ChainableUndefined,    # missing vars → falsy in {% if %}, "" elsewhere
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render(template_key: str, **variables: Any) -> str:
    """Render a template by its prompt key.

    Variables not used by the template are silently ignored. Variables referenced
    by the template but not supplied raise an error — use the `default(...)`
    filter in the template for genuinely optional fields.
    """
    if template_key not in TEMPLATES:
        raise KeyError(f"unknown prompt template: {template_key!r}")
    template = _env().get_template(TEMPLATES[template_key])
    return template.render(**variables)


def list_templates() -> list[str]:
    """For introspection; returns canonical six-agent prompt keys."""
    return sorted(CANONICAL_TEMPLATES.keys())


def template_path(key: str) -> Path:
    return PROMPTS_DIR / TEMPLATES[key]
