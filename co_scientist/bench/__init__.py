"""Model bench: cross-model pairwise calibration for LLM providers / models.

Given one research goal and a list of `(label, provider, model)` candidates,
the bench:

1. Runs the hypothesis-design pipeline N times for each candidate under a per-candidate Config
   override (its own provider + model + API key resolution).
2. Drops all produced hypotheses into shared pairwise calibration checks
   judged by ONE fixed `judge_provider` / `judge_model` so the comparison
   is fair (no echo-judge bias and no per-side judge drift).
3. Aggregates per-candidate stats: mean calibration score, top calibration
   score, win-rate, $/hyp,
   latency, dollars spent.
4. Persists everything to bench_runs / bench_candidates / bench_matches
   and writes a JSON artifact summary.

This is a *separate* code path from Supervisor / sessions — bench runs do
NOT create a `sessions` row, do NOT enter the main task queue, and do NOT
share calibration state with regular sessions. They reuse the underlying
the current design-step implementation and pairwise-calibration math.
"""

from .goldset import (
    GOLDSETS,
    MINOR_GRAIN_DROUGHT_DEMO,
    MINOR_GRAIN_RESOURCE_DEMO,
    GoldEntity,
    GoldSet,
    HitRecord,
)
from .presets import PRESETS, get_preset
from .runner import BenchCandidate, BenchOutcome, run_bench

__all__ = [
    "GOLDSETS",
    "MINOR_GRAIN_DROUGHT_DEMO",
    "MINOR_GRAIN_RESOURCE_DEMO",
    "PRESETS",
    "BenchCandidate",
    "BenchOutcome",
    "GoldEntity",
    "GoldSet",
    "HitRecord",
    "get_preset",
    "run_bench",
]
