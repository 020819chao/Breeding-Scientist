"""Built-in breeding bench candidate presets."""

from __future__ import annotations

from dataclasses import dataclass

from .goldset import MINOR_GRAIN_DROUGHT_DEMO, GoldSet
from .runner import BenchCandidate


@dataclass(frozen=True)
class BenchPreset:
    name: str
    description: str
    candidates: tuple[BenchCandidate, ...]
    suggested_judge: str
    default_goal: str | None = None
    goldset: GoldSet | None = None


_BASELINE_CANDIDATES: tuple[BenchCandidate, ...] = (
    BenchCandidate(
        label="gemini-flash",
        provider="openrouter",
        model="google/gemini-3-flash-preview",
    ),
    BenchCandidate(
        label="gemini-pro",
        provider="openrouter",
        model="google/gemini-3.1-pro-preview",
    ),
    BenchCandidate(
        label="gpt-5",
        provider="openrouter",
        model="openai/gpt-5",
    ),
    BenchCandidate(
        label="claude-haiku-4.5",
        provider="openrouter",
        model="anthropic/claude-haiku-4.5",
    ),
)


_FRONTIER_CANDIDATES: tuple[BenchCandidate, ...] = (
    BenchCandidate(
        label="claude-opus-4.7",
        provider="openrouter",
        model="anthropic/claude-opus-4.7",
    ),
    BenchCandidate(
        label="gpt-5",
        provider="openrouter",
        model="openai/gpt-5",
    ),
    BenchCandidate(
        label="gemini-3-pro",
        provider="openrouter",
        model="google/gemini-3.1-pro-preview",
    ),
    BenchCandidate(
        label="gemini-3-flash",
        provider="openrouter",
        model="google/gemini-3-flash-preview",
    ),
)


_MINOR_GRAIN_DROUGHT_DEMO_GOAL = (
    "Design minor-grain breeding hypotheses for improving drought tolerance "
    "and stay-green performance under arid or water-limited target environments. "
    "Use foxtail millet as the current demo crop pack when the goal does not "
    "specify another minor grain. Each hypothesis should name plausible germplasm "
    "or parent classes, candidate genes/QTL/markers when available, a concrete "
    "crossing or selection route, local evidence or KG/RAG clues to verify, and "
    "a first-cycle validation plan with go/no-go thresholds."
)


def _vs_direct(candidates: tuple[BenchCandidate, ...]) -> tuple[BenchCandidate, ...]:
    """Run every candidate once through the pipeline and once as a direct call."""
    out: list[BenchCandidate] = []
    for c in candidates:
        out.append(BenchCandidate(
            label=f"{c.label}[pipe]", provider=c.provider, model=c.model,
            mode="pipeline",
        ))
        out.append(BenchCandidate(
            label=f"{c.label}[direct]", provider=c.provider, model=c.model,
            mode="direct",
        ))
    return tuple(out)


PRESETS: dict[str, BenchPreset] = {
    "baseline": BenchPreset(
        name="baseline",
        description=(
            "Compare a small provider-agnostic model panel on an arbitrary "
            "breeding goal using pairwise calibration only."
        ),
        candidates=_BASELINE_CANDIDATES,
        suggested_judge="openrouter:google/gemini-3-flash-preview",
    ),
    "minor-grain": BenchPreset(
        name="minor-grain",
        description=(
            "Minor-grain drought-tolerance benchmark with a bundled breeding "
            "goal. The current demo crop pack uses foxtail millet marker, "
            "mechanism, and validation-route clues."
        ),
        candidates=_BASELINE_CANDIDATES,
        suggested_judge="openrouter:google/gemini-3-flash-preview",
        default_goal=_MINOR_GRAIN_DROUGHT_DEMO_GOAL,
        goldset=MINOR_GRAIN_DROUGHT_DEMO,
    ),
    "minor-grain-vs-direct": BenchPreset(
        name="minor-grain-vs-direct",
        description=(
            "Same minor-grain demo benchmark, but each model runs once through "
            "the full six-agent pipeline and once as a direct single-call design."
        ),
        candidates=_vs_direct(_BASELINE_CANDIDATES),
        suggested_judge="openrouter:google/gemini-3-flash-preview",
        default_goal=_MINOR_GRAIN_DROUGHT_DEMO_GOAL,
        goldset=MINOR_GRAIN_DROUGHT_DEMO,
    ),
    "frontier-minor-grain-vs-direct": BenchPreset(
        name="frontier-minor-grain-vs-direct",
        description=(
            "Minor-grain demo pipeline-vs-direct benchmark using stronger "
            "frontier models, useful for checking whether the six-agent harness "
            "still adds value as base models improve."
        ),
        candidates=_vs_direct(_FRONTIER_CANDIDATES),
        suggested_judge="openrouter:google/gemini-3-flash-preview",
        default_goal=_MINOR_GRAIN_DROUGHT_DEMO_GOAL,
        goldset=MINOR_GRAIN_DROUGHT_DEMO,
    ),
}


def get_preset(name: str) -> BenchPreset:
    try:
        return PRESETS[name]
    except KeyError as e:
        names = ", ".join(sorted(PRESETS))
        raise KeyError(f"unknown bench preset {name!r}; available: {names}") from e
