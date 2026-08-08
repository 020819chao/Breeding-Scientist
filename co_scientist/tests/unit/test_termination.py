"""Tests for the termination predicate + StabilityTracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from co_scientist.config import Config
from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.orchestrator.breeding_termination import should_stop_breeding
from co_scientist.orchestrator.termination import (
    PairwiseCalibrationSnapshot,
    StabilityTracker,
    StopReason,
    budget_exceeded,
    should_stop,
    wall_clock_exceeded,
)
from co_scientist.storage.artifacts import write_json
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo


def _session(
    *,
    used_usd: float = 0.0,
    budget_usd: float = 25.0,
    used_tokens: int = 0,
    budget_tokens: int = 1_000_000,
    deadline_in_s: float | None = None,
) -> Session:
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=deadline_in_s) if deadline_in_s is not None else None
    return Session(
        id="ses_t", created_at=now, updated_at=now, status="running",
        research_goal="g", research_plan=ResearchPlan(objective="o"),
        config_snapshot={}, budget_tokens=budget_tokens, budget_usd=budget_usd,
        budget_used_tokens=used_tokens, budget_used_usd=used_usd,
        wall_deadline=deadline,
    )


# ----------------------------- budget / wall ----------------------------- #

def test_budget_exceeded_by_usd() -> None:
    assert not budget_exceeded(_session(used_usd=10, budget_usd=25))
    assert budget_exceeded(_session(used_usd=25, budget_usd=25))
    assert budget_exceeded(_session(used_usd=30, budget_usd=25))


def test_budget_exceeded_by_tokens() -> None:
    assert budget_exceeded(_session(used_tokens=2_000_000, budget_tokens=1_000_000))
    assert not budget_exceeded(_session(used_tokens=500_000, budget_tokens=1_000_000))


def test_wall_clock_exceeded() -> None:
    assert not wall_clock_exceeded(_session(deadline_in_s=60))
    assert wall_clock_exceeded(_session(deadline_in_s=-60))


def test_external_stop_wins_over_progress() -> None:
    cfg = Config()
    tracker = StabilityTracker(k=3, n=3, eps=25)
    assert should_stop(cfg, _session(), tracker, external_stop=True) is StopReason.EXTERNAL


def test_termination_config_prefers_pairwise_calibration_names() -> None:
    cfg = Config()
    cfg.termination.pairwise_calibration_stability_k = 7
    cfg.termination.pairwise_calibration_stability_n = 4
    cfg.termination.pairwise_calibration_stability_eps = 12.5
    cfg.termination.pairwise_calibration_snapshot_every = 6
    cfg.termination.min_pairwise_calibrations_before_stable = 40
    cfg.termination.min_pairwise_calibrations_per_hypothesis = 4

    assert cfg.termination.effective_pairwise_calibration_stability_k == 7
    assert cfg.termination.effective_pairwise_calibration_stability_n == 4
    assert cfg.termination.effective_pairwise_calibration_stability_eps == 12.5
    assert cfg.termination.effective_pairwise_calibration_snapshot_every == 6
    assert cfg.termination.effective_min_pairwise_calibrations_before_stable == 40
    assert cfg.termination.effective_min_pairwise_calibrations_per_hypothesis == 4


# ----------------------------- stability tracker ----------------------------- #

def _snap(
    pairwise_calibration_count: int,
    ids: list[str],
    calibration_scores: list[float],
    pool_size: int = 0,
    top_pairwise_calibrations: list[int] | None = None,
) -> PairwiseCalibrationSnapshot:
    return PairwiseCalibrationSnapshot(
        pairwise_calibration_count=pairwise_calibration_count,
        top_ids=tuple(ids),
        top_calibration_scores=tuple(calibration_scores),
        top_pairwise_calibrations=tuple(top_pairwise_calibrations or ()),
        pool_size=pool_size,
    )


def test_stability_requires_n_snapshots() -> None:
    tr = StabilityTracker(k=3, n=3, eps=25)
    tr.push(_snap(10, ["a", "b", "c"], [1500, 1400, 1300]))
    tr.push(_snap(20, ["a", "b", "c"], [1500, 1400, 1300]))
    assert not tr.is_stable()
    tr.push(_snap(30, ["a", "b", "c"], [1500, 1400, 1300]))
    assert tr.is_stable()


def test_stability_fails_when_top_k_changes() -> None:
    tr = StabilityTracker(k=3, n=3, eps=50)
    for mc in (10, 20):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300]))
    tr.push(_snap(30, ["a", "b", "d"], [1500, 1400, 1310]))    # c 鈫?d
    assert not tr.is_stable()


def test_stability_fails_when_top_k_order_changes() -> None:
    tr = StabilityTracker(k=3, n=3, eps=50)
    tr.push(_snap(10, ["a", "b", "c"], [1500, 1400, 1300]))
    tr.push(_snap(20, ["b", "a", "c"], [1400, 1500, 1300]))
    tr.push(_snap(30, ["a", "b", "c"], [1500, 1400, 1300]))
    assert not tr.is_stable()


def test_stability_fails_when_pairwise_calibration_drifts_past_epsilon() -> None:
    tr = StabilityTracker(k=3, n=3, eps=25)
    tr.push(_snap(10, ["a", "b", "c"], [1500, 1400, 1300]))
    tr.push(_snap(20, ["a", "b", "c"], [1510, 1410, 1310]))
    tr.push(_snap(30, ["a", "b", "c"], [1540, 1390, 1305]))   # a moved by 40 > 25
    assert not tr.is_stable()


def test_stability_passes_when_within_epsilon() -> None:
    tr = StabilityTracker(k=3, n=3, eps=30)
    tr.push(_snap(10, ["a", "b", "c"], [1500, 1400, 1300]))
    tr.push(_snap(20, ["a", "b", "c"], [1510, 1410, 1310]))
    tr.push(_snap(30, ["a", "b", "c"], [1520, 1395, 1305]))   # all moves within 25
    assert tr.is_stable()


# ----------------------------- combined predicate ----------------------------- #

def test_should_stop_returns_budget_first() -> None:
    cfg = Config()
    tr = StabilityTracker(k=3, n=3, eps=25)
    s = _session(used_usd=100, budget_usd=10)
    assert should_stop(cfg, s, tr) is StopReason.BUDGET


def test_should_stop_returns_wall_clock_when_budget_ok() -> None:
    cfg = Config()
    tr = StabilityTracker(k=3, n=3, eps=25)
    s = _session(used_usd=1, budget_usd=10, deadline_in_s=-10)
    assert should_stop(cfg, s, tr) is StopReason.WALL_CLOCK


def test_should_stop_none_when_running() -> None:
    cfg = Config()
    tr = StabilityTracker(k=3, n=3, eps=25)
    s = _session(used_usd=1, budget_usd=10, deadline_in_s=60)
    assert should_stop(cfg, s, tr) is None


def test_should_stop_returns_pairwise_calibration_stable() -> None:
    cfg = Config()
    tr = StabilityTracker(k=3, n=3, eps=25)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=3))
    assert should_stop(cfg, _session(), tr) is StopReason.PAIRWISE_CALIBRATION_STABLE


# ----------------------------- min_ideas guard ----------------------------- #

def test_min_ideas_guard_blocks_stable_on_small_pool() -> None:
    """pairwise_calibration_stable must not fire when pool_size < min_ideas."""
    tr = StabilityTracker(k=3, n=3, eps=25, min_ideas=10)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=3))
    assert not tr.is_stable()


def test_min_ideas_guard_allows_stable_once_pool_is_large_enough() -> None:
    tr = StabilityTracker(k=3, n=3, eps=25, min_ideas=3)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=3))
    assert tr.is_stable()


def test_min_ideas_guard_zero_is_disabled() -> None:
    """Default min_ideas=0 must never block stability (backward compat)."""
    tr = StabilityTracker(k=3, n=3, eps=25, min_ideas=0)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=1))
    assert tr.is_stable()


# ----------------------------- pairwise calibration count guard ----------------------------- #

def test_min_pairwise_calibrations_guard_blocks_stable_below_threshold() -> None:
    """pairwise_calibration_stable must not fire below the calibration threshold."""
    tr = StabilityTracker(k=3, n=3, eps=25, min_pairwise_calibrations=100)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=20))
    assert not tr.is_stable()


def test_min_pairwise_calibrations_guard_allows_stable_once_enough_checks() -> None:
    tr = StabilityTracker(k=3, n=3, eps=25, min_pairwise_calibrations=30)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=20))
    assert tr.is_stable()


def test_min_pairwise_calibrations_guard_zero_is_disabled() -> None:
    tr = StabilityTracker(k=3, n=3, eps=25, min_pairwise_calibrations=0)
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=1))
    assert tr.is_stable()


def test_per_hypothesis_calibration_guard_requires_each_top_route() -> None:
    tr = StabilityTracker(
        k=3,
        n=3,
        eps=25,
        min_pairwise_calibrations_per_hypothesis=3,
    )
    for mc, played in ((10, [3, 3, 2]), (15, [4, 4, 2]), (20, [5, 5, 2])):
        tr.push(
            _snap(
                mc,
                ["a", "b", "c"],
                [1500, 1400, 1300],
                pool_size=3,
                top_pairwise_calibrations=played,
            )
        )
    assert not tr.is_stable()


def test_per_hypothesis_calibration_guard_allows_mature_top_routes() -> None:
    tr = StabilityTracker(
        k=3,
        n=3,
        eps=25,
        min_pairwise_calibrations_per_hypothesis=3,
    )
    for mc, played in ((10, [3, 3, 3]), (15, [4, 4, 4]), (20, [5, 5, 5])):
        tr.push(
            _snap(
                mc,
                ["a", "b", "c"],
                [1500, 1400, 1300],
                pool_size=3,
                top_pairwise_calibrations=played,
            )
        )
    assert tr.is_stable()


# ----------------------------- combined guards ----------------------------- #

def test_both_guards_must_pass_for_stability() -> None:
    """Stable only when both min_ideas and calibration-count guards pass."""
    tr = StabilityTracker(k=3, n=3, eps=25, min_ideas=10, min_pairwise_calibrations=100)
    # pool_size OK but matches too low 鈫?not stable
    for mc in (10, 20, 30):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=15))
    assert not tr.is_stable()
    # Now push with both satisfied
    for mc in (110, 120, 130):
        tr.push(_snap(mc, ["a", "b", "c"], [1500, 1400, 1300], pool_size=15))
    assert tr.is_stable()


# ----------------------------- breeding termination ----------------------------- #

async def test_breeding_termination_success_ready(tmp_cfg, conn) -> None:
    session = await _insert_breeding_session(conn)
    await _insert_breeding_hypothesis(conn, session.id, "hyp_keep_a", calibration_score=1300)
    await _insert_breeding_hypothesis(conn, session.id, "hyp_keep_b", calibration_score=1300)
    await _write_decision(tmp_cfg, session.id, "hyp_keep_a", action="keep", total_score=86)
    await _write_decision(tmp_cfg, session.id, "hyp_keep_b", action="keep", total_score=82)

    assert await should_stop_breeding(tmp_cfg, conn, session) is StopReason.BREEDING_SUCCESS_READY


async def test_breeding_termination_evidence_blocked(tmp_cfg, conn) -> None:
    session = await _insert_breeding_session(conn, session_id="ses_breeding_blocked")
    for idx, action in enumerate(("pause", "reject", "pause", "revise")):
        hid = f"hyp_blocked_{idx}"
        await _insert_breeding_hypothesis(conn, session.id, hid, calibration_score=1200 + idx)
        await _write_decision(tmp_cfg, session.id, hid, action=action, total_score=45)

    assert await should_stop_breeding(tmp_cfg, conn, session) is StopReason.BREEDING_EVIDENCE_BLOCKED


async def test_breeding_termination_no_composite_gain(tmp_cfg, conn) -> None:
    session = await _insert_breeding_session(conn, session_id="ses_breeding_no_gain")
    for idx, action in enumerate(("revise", "revise", "pause", "revise", "expand")):
        hid = f"hyp_no_gain_{idx}"
        await _insert_breeding_hypothesis(conn, session.id, hid, calibration_score=1180 + idx)
        await _write_decision(tmp_cfg, session.id, hid, action=action, total_score=50)

    assert await should_stop_breeding(tmp_cfg, conn, session) is StopReason.BREEDING_NO_COMPOSITE_GAIN


async def test_breeding_termination_none_when_signal_is_insufficient(tmp_cfg, conn) -> None:
    session = await _insert_breeding_session(conn, session_id="ses_breeding_continue")
    await _insert_breeding_hypothesis(conn, session.id, "hyp_continue_a", calibration_score=1200)
    await _write_decision(tmp_cfg, session.id, "hyp_continue_a", action="keep", total_score=70)

    assert await should_stop_breeding(tmp_cfg, conn, session) is None


async def test_breeding_termination_max_hypotheses_reached(tmp_cfg, conn) -> None:
    session = await _insert_breeding_session(
        conn,
        session_id="ses_breeding_max_reached",
        research_plan=ResearchPlan(objective="o", max_hypothesis_count=2),
    )
    for idx, action in enumerate(("revise", "expand")):
        hid = f"hyp_max_{idx}"
        await _insert_breeding_hypothesis(conn, session.id, hid, calibration_score=1210 + idx)
        await _write_decision(tmp_cfg, session.id, hid, action=action, total_score=66)

    assert (
        await should_stop_breeding(tmp_cfg, conn, session)
        is StopReason.BREEDING_MAX_HYPOTHESES_REACHED
    )


async def test_breeding_termination_max_hypotheses_allows_single_ready_keep(
    tmp_cfg,
    conn,
) -> None:
    session = await _insert_breeding_session(
        conn,
        session_id="ses_breeding_max_single_keep",
        research_plan=ResearchPlan(objective="o", max_hypothesis_count=1),
    )
    await _insert_breeding_hypothesis(conn, session.id, "hyp_single_keep", calibration_score=1300)
    await _write_decision(tmp_cfg, session.id, "hyp_single_keep", action="keep", total_score=86)

    assert await should_stop_breeding(tmp_cfg, conn, session) is None


async def _insert_breeding_session(
    conn,
    *,
    session_id: str = "ses_breeding_success",
    research_plan: ResearchPlan | None = None,
) -> Session:
    session = _session()
    update = {"id": session_id}
    if research_plan is not None:
        update["research_plan"] = research_plan
    session = session.model_copy(update=update)
    await sess_repo.insert(conn, session)
    return session


async def _insert_breeding_hypothesis(
    conn,
    session_id: str,
    hypothesis_id: str,
    *,
    calibration_score: float,
) -> None:
    await hyp_repo.insert(
        conn,
        Hypothesis(
            id=hypothesis_id,
            session_id=session_id,
            created_at=datetime.now(UTC),
            created_by="breeding_designer",
            strategy="literature",
            title=hypothesis_id,
            summary=hypothesis_id,
            full_text=f"# {hypothesis_id}",
            artifact_path=f"artifacts/{session_id}/hypotheses/{hypothesis_id}.json",
            calibration_score=calibration_score,
            state="calibration_pool",
        ),
    )


async def _write_decision(
    tmp_cfg,
    session_id: str,
    hypothesis_id: str,
    *,
    action: str,
    total_score: float,
) -> None:
    await write_json(
        tmp_cfg,
        session_id,
        "iteration",
        f"decision_{hypothesis_id}",
        {
            "created_at": "2026-07-27T12:00:00+00:00",
            "hypothesis_id": hypothesis_id,
            "action": action,
            "total_score": total_score,
            "scorecard": [
                {"dimension": "evidence_support", "score": total_score},
                {"dimension": "validation_actionability", "score": total_score},
                {"dimension": "review_strength", "score": total_score},
                {"dimension": "risk_control", "score": total_score},
            ],
        },
    )
