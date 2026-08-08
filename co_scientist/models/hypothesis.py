"""Hypothesis model — the central artifact."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HypothesisState = Literal[
    "draft",
    "reviewed",
    "calibration_pool",
    "pinned",
    "rejected",
    "quarantined",
    "retired",
]
CALIBRATION_POOL_STATE = "calibration_pool"
CALIBRATION_POOL_STATES = (CALIBRATION_POOL_STATE,)
RANKABLE_HYPOTHESIS_STATES = (*CALIBRATION_POOL_STATES, "pinned")

HypothesisStrategy = Literal[
    "literature", "debate", "combine", "simplify", "out_of_box", "feasibility", "assumption",
    "feedback_driven",
]
HypothesisOrigin = Literal["breeding_designer"]


class CitedPaper(BaseModel):
    title: str
    url: str
    excerpt: str | None = None
    doi: str | None = None
    year: int | None = None


class Hypothesis(BaseModel):
    id: str
    session_id: str
    created_at: datetime
    created_by: HypothesisOrigin
    strategy: HypothesisStrategy
    parent_ids: list[str] = Field(default_factory=list)
    title: str
    summary: str                 # ~3 sentences; embedded for semantic deduplication
    full_text: str               # detailed markdown for domain experts
    citations: list[CitedPaper] = Field(default_factory=list)
    artifact_path: str           # relative under data_dir
    calibration_score: float | None = None
    pairwise_calibrations_played: int = 0
    state: HypothesisState = "draft"
    dedup_cluster: str | None = None
