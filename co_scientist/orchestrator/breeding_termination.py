"""Breeding-specific termination checks for the iterative evidence loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite

from ..config import Config
from ..models import Session
from ..prioritization.composite import (
    latest_iteration_decisions_for_session,
    rank_hypotheses_for_prioritized_routes,
)
from ..storage.repos import hypotheses as hyp_repo
from .termination import StopReason

SUCCESS_KEEP_MIN = 2
SUCCESS_SCORE_THRESHOLD = 75.0
MIN_DECISIONS_BEFORE_BLOCKED = 3
BLOCKED_RATIO_THRESHOLD = 0.75
NO_GAIN_MIN_DECISIONS = 5
NO_GAIN_TOP_SCORE_THRESHOLD = 60.0
NO_GAIN_BAD_RATIO_THRESHOLD = 0.60


@dataclass(frozen=True)
class BreedingTerminationSnapshot:
    total_decisions: int
    keep_ready: int
    pause_reject: int
    bad_actions: int
    hypothesis_count: int
    max_hypothesis_count: int | None
    top_composite_score: float | None
    reason: StopReason | None


async def should_stop_breeding(
    cfg: Config,
    conn: aiosqlite.Connection,
    session: Session,
) -> StopReason | None:
    snapshot = await breeding_termination_snapshot(cfg, conn, session)
    return snapshot.reason


async def breeding_termination_snapshot(
    cfg: Config,
    conn: aiosqlite.Connection,
    session: Session,
) -> BreedingTerminationSnapshot:
    decisions = latest_iteration_decisions_for_session(cfg, session.id)
    hypotheses = await hyp_repo.list_for_session(conn, session.id)
    hypothesis_count = len(hypotheses)
    max_hypothesis_count = _positive_int_or_none(
        session.research_plan.max_hypothesis_count
    )
    active_hypotheses = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.state not in {"rejected", "retired"}
    ]
    ranked, rank_map = rank_hypotheses_for_prioritized_routes(active_hypotheses, decisions)
    top_score = rank_map.get(ranked[0].id, {}).get("score") if ranked else None
    top_composite_score = float(top_score) if isinstance(top_score, int | float) else None

    total_decisions = len(decisions)
    keep_ready = 0
    pause_reject = 0
    bad_actions = 0
    for hypothesis_id, decision in decisions.items():
        action = str(decision.get("action") or "pending")
        score = _score_for(hypothesis_id, rank_map, decision)
        if action == "keep" and score >= SUCCESS_SCORE_THRESHOLD:
            keep_ready += 1
        if action in {"pause", "reject"}:
            pause_reject += 1
        if action in {"revise", "pause", "reject"}:
            bad_actions += 1

    reason = _reason_from_snapshot(
        total_decisions=total_decisions,
        keep_ready=keep_ready,
        pause_reject=pause_reject,
        bad_actions=bad_actions,
        hypothesis_count=hypothesis_count,
        max_hypothesis_count=max_hypothesis_count,
        top_composite_score=top_composite_score,
    )
    return BreedingTerminationSnapshot(
        total_decisions=total_decisions,
        keep_ready=keep_ready,
        pause_reject=pause_reject,
        bad_actions=bad_actions,
        hypothesis_count=hypothesis_count,
        max_hypothesis_count=max_hypothesis_count,
        top_composite_score=top_composite_score,
        reason=reason,
    )


def _reason_from_snapshot(
    *,
    total_decisions: int,
    keep_ready: int,
    pause_reject: int,
    bad_actions: int,
    hypothesis_count: int,
    max_hypothesis_count: int | None,
    top_composite_score: float | None,
) -> StopReason | None:
    if keep_ready >= SUCCESS_KEEP_MIN:
        return StopReason.BREEDING_SUCCESS_READY
    if (
        max_hypothesis_count is not None
        and hypothesis_count >= max_hypothesis_count
        and total_decisions > 0
        and keep_ready < min(SUCCESS_KEEP_MIN, max_hypothesis_count)
    ):
        return StopReason.BREEDING_MAX_HYPOTHESES_REACHED
    if (
        total_decisions >= MIN_DECISIONS_BEFORE_BLOCKED
        and pause_reject / total_decisions >= BLOCKED_RATIO_THRESHOLD
    ):
        return StopReason.BREEDING_EVIDENCE_BLOCKED
    if total_decisions >= NO_GAIN_MIN_DECISIONS and top_composite_score is not None:
        bad_ratio = bad_actions / total_decisions
        if (
            top_composite_score < NO_GAIN_TOP_SCORE_THRESHOLD
            and bad_ratio >= NO_GAIN_BAD_RATIO_THRESHOLD
        ):
            return StopReason.BREEDING_NO_COMPOSITE_GAIN
    return None


def _score_for(
    hypothesis_id: str,
    rank_map: dict[str, dict[str, Any]],
    decision: dict[str, Any],
) -> float:
    rank_score = rank_map.get(hypothesis_id, {}).get("score")
    if isinstance(rank_score, int | float):
        return float(rank_score)
    total_score = decision.get("total_score")
    if isinstance(total_score, int | float):
        return float(total_score)
    return 0.0


def _positive_int_or_none(value: int | None) -> int | None:
    if value is None:
        return None
    if value <= 0:
        return None
    return value
