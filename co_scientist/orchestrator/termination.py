"""Termination predicate for the Supervisor's main loop.

`should_stop(session)` returns one of:
- BUDGET: token or USD budget exhausted
- WALL_CLOCK: session time deadline crossed
- PAIRWISE_CALIBRATION_STABLE: prioritized routes are stable across snapshots
- None: keep running
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import aiosqlite

from ..config import Config
from ..models import RANKABLE_HYPOTHESIS_STATES, Session


class StopReason(Enum):
    BUDGET = "budget"
    WALL_CLOCK = "wall_clock"
    PAIRWISE_CALIBRATION_STABLE = "pairwise_calibration_stable"
    BREEDING_SUCCESS_READY = "breeding_success_ready"
    BREEDING_EVIDENCE_BLOCKED = "breeding_evidence_blocked"
    BREEDING_NO_COMPOSITE_GAIN = "breeding_no_composite_gain"
    BREEDING_MAX_HYPOTHESES_REACHED = "breeding_max_hypotheses_reached"
    TASK_FAILURE = "task_failure"
    EXTERNAL = "external"      # user pressed pause/abort or invoked /sessions/{id}/abort
    IDLE = "idle"              # queue drained and decide_next_steps returned 0


@dataclass
class PairwiseCalibrationSnapshot:
    """The top-K route calibration state at one point in time."""

    pairwise_calibration_count: int
    top_ids: tuple[str, ...]
    top_calibration_scores: tuple[float, ...]
    top_pairwise_calibrations: tuple[int, ...] = ()
    pool_size: int = 0  # total rankable hypotheses at snapshot time


class StabilityTracker:
    """Owns recent pairwise calibration snapshots for one session."""

    def __init__(
        self,
        k: int,
        n: int,
        eps: float,
        min_ideas: int = 0,
        min_pairwise_calibrations: int = 0,
        min_pairwise_calibrations_per_hypothesis: int = 0,
    ) -> None:
        self.k = k
        self.n = n
        self.eps = eps
        self.min_ideas = min_ideas
        self.min_pairwise_calibrations = min_pairwise_calibrations
        self.min_pairwise_calibrations_per_hypothesis = min_pairwise_calibrations_per_hypothesis
        self._history: list[PairwiseCalibrationSnapshot] = []

    def push(self, snap: PairwiseCalibrationSnapshot) -> None:
        self._history.append(snap)
        # Keep slightly more than needed so we can see drift.
        if len(self._history) > self.n * 2:
            self._history = self._history[-self.n * 2 :]

    @property
    def history(self) -> list[PairwiseCalibrationSnapshot]:
        return list(self._history)

    def is_stable(self) -> bool:
        if len(self._history) < self.n:
            return False
        recent = self._history[-self.n :]
        # Guard: do not declare stability until the pool is large enough
        # and enough pairwise calibration checks have been completed.
        if self.min_ideas > 0 and recent[-1].pool_size < self.min_ideas:
            return False
        if (
            self.min_pairwise_calibrations > 0
            and recent[-1].pairwise_calibration_count < self.min_pairwise_calibrations
        ):
            return False
        for snapshot in recent[1:]:
            # Ranking stability is order-sensitive: swapping first and second
            # place must not be treated as the same leaderboard.
            if snapshot.top_ids != recent[0].top_ids:
                return False

        if self.min_pairwise_calibrations_per_hypothesis > 0:
            played = recent[-1].top_pairwise_calibrations
            if (
                not played
                or min(played) < self.min_pairwise_calibrations_per_hypothesis
            ):
                return False

        per_id: dict[str, list[float]] = {}
        for snapshot in recent:
            for hid, score in zip(
                snapshot.top_ids,
                snapshot.top_calibration_scores,
                strict=True,
            ):
                per_id.setdefault(hid, []).append(score)
        return all(max(scores) - min(scores) < self.eps for scores in per_id.values())


async def snapshot_top_k_pairwise_calibration(
    conn: aiosqlite.Connection, session_id: str, k: int
) -> PairwiseCalibrationSnapshot:
    """Read current top-K calibration state, completed check count, and pool size."""
    placeholders = ",".join("?" for _ in RANKABLE_HYPOTHESIS_STATES)
    async with conn.execute(
        f"""SELECT id, calibration_score, pairwise_calibrations_played FROM hypotheses
              WHERE session_id=? AND state IN ({placeholders})
                AND calibration_score IS NOT NULL
              ORDER BY calibration_score DESC LIMIT ?""",
        (session_id, *RANKABLE_HYPOTHESIS_STATES, k),
    ) as cur:
        rows = await cur.fetchall()
    async with conn.execute(
        """SELECT COUNT(*) AS n FROM pairwise_calibration_matches
             WHERE session_id=? AND mode != 'invalid'""",
        (session_id,),
    ) as cur:
        mc_row = await cur.fetchone()
    async with conn.execute(
        f"""SELECT COUNT(*) AS n FROM hypotheses
              WHERE session_id=? AND state IN ({placeholders})""",
        (session_id, *RANKABLE_HYPOTHESIS_STATES),
    ) as cur:
        pool_row = await cur.fetchone()
    return PairwiseCalibrationSnapshot(
        pairwise_calibration_count=mc_row["n"] if mc_row else 0,
        top_ids=tuple(r["id"] for r in rows),
        top_calibration_scores=tuple(r["calibration_score"] for r in rows),
        top_pairwise_calibrations=tuple(r["pairwise_calibrations_played"] or 0 for r in rows),
        pool_size=pool_row["n"] if pool_row else 0,
    )


snapshot_top_k = snapshot_top_k_pairwise_calibration


def budget_exceeded(session: Session) -> bool:
    return (
        (session.budget_usd > 0 and session.budget_used_usd >= session.budget_usd)
        or (session.budget_tokens > 0 and session.budget_used_tokens >= session.budget_tokens)
    )


def wall_clock_exceeded(session: Session) -> bool:
    if session.wall_deadline is None:
        return False
    now = datetime.now(UTC)
    deadline = session.wall_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return now >= deadline


def should_stop(
    cfg: Config,
    session: Session,
    tracker: StabilityTracker,
    external_stop: bool = False,
) -> StopReason | None:
    if external_stop:
        return StopReason.EXTERNAL
    if budget_exceeded(session):
        return StopReason.BUDGET
    if wall_clock_exceeded(session):
        return StopReason.WALL_CLOCK
    del cfg  # reserved for future config-driven termination rules
    if tracker.is_stable():
        return StopReason.PAIRWISE_CALIBRATION_STABLE
    return None
