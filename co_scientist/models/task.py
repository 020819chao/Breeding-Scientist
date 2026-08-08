"""Task queue model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskAgent = Literal[
    "evidence_curator",
    "breeding_designer",
    "iteration_orchestrator",
    "validation_planner",
    "risk_reviewer",
]
TaskAction = Literal[
    # Evidence curator
    "CurateEvidencePackage",
    # Iteration orchestrator
    "DecideIteration",
    # Validation planner
    "PlanValidation",
    # Risk reviewer
    "ReviewRisk",
    # Breeding Designer
    "DesignHypothesis",
    "DirectHypothesisDesign",         # bench-only: single LM call, no tool loop
    # Risk Reviewer: evidence review stage
    "AssessHypothesisEvidence",
    # Iteration Orchestrator: pairwise calibration service
    "QueuePairwiseCalibration",
    "RunPairwiseCalibration",
    # Breeding Designer: successor route design
    "ReviseOrExpandRoute",
    # Iteration Orchestrator: synthesis
    "SynthesizeIterationFeedback",
    "GenerateFinalBreedingOverview",
]
TaskStatus = Literal["pending", "leased", "in_progress", "done", "failed", "dead", "cancelled"]


class Task(BaseModel):
    id: str
    session_id: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    agent: TaskAgent
    action: TaskAction
    target_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    status: TaskStatus = "pending"
    lease_owner: str | None = None
    lease_expires_at: int | None = None
    attempts: int = 0
    last_error: str | None = None
    idempotency_key: str | None = None


# --------------------------------------------------------------------------- #
# Task results — return values from agent.execute()


TaskResultKind = Literal[
    "evidence_curated",
    "iteration_decision",
    "validation_planned",
    "risk_reviewed",
    "hypothesis_created",
    "evidence_review_completed",
    "pairwise_calibration_queued",
    "pairwise_calibration_complete",
    "route_revision_completed",
    "system_feedback_generated",
    "final_overview_generated",
    "noop",
]


class TaskResult(BaseModel):
    kind: TaskResultKind
    hypothesis_ids: list[str] = Field(default_factory=list)
    review_ids: list[str] = Field(default_factory=list)
    match_ids: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
