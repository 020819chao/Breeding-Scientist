"""Tests for pairwise-calibration math + idempotent persistence."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from co_scientist import ids
from co_scientist.models import Hypothesis, PairwiseCalibrationMatch
from co_scientist.models.pairwise_calibration import (
    PairwiseCalibrationMatch as DirectPairwiseCalibrationMatch,
)
from co_scientist.orchestrator.pairwise_calibration import (
    calibration_k_factor,
    expected_score,
    update_pairwise_calibration_score,
)
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import pairwise_calibration as pairwise_repo


def test_equal_ratings_expect_half() -> None:
    assert expected_score(1200, 1200) == pytest.approx(0.5)


def test_higher_rating_favored() -> None:
    assert expected_score(1500, 1200) > 0.8
    assert expected_score(1200, 1500) < 0.2


def test_k_factor_decays() -> None:
    assert calibration_k_factor(0) == 32
    assert calibration_k_factor(4) == 32
    assert calibration_k_factor(5) == 16
    assert calibration_k_factor(100) == 16


def test_update_zero_sum() -> None:
    u = update_pairwise_calibration_score(
        1200,
        1200,
        "a",
        pairwise_calibrations_min=0,
    )
    # zero-sum
    assert math.isclose(
        u.calibration_a_after + u.calibration_b_after,
        2400,
        abs_tol=1e-9,
    )
    # winner gains, loser drops
    assert u.calibration_a_after > 1200
    assert u.calibration_b_after < 1200


def test_underdog_win_is_high_payoff() -> None:
    u = update_pairwise_calibration_score(
        1100,
        1500,
        "a",
        pairwise_calibrations_min=10,
    )
    # K=16, expected_a ~0.09, delta = 16*(1 - 0.09) = ~14.5
    assert 13 < u.calibration_a_after - 1100 < 16


@pytest.mark.asyncio
async def test_apply_pairwise_calibration_update_is_idempotent(conn) -> None:
    """Re-applying the same match_id never double-counts."""
    now = datetime.now(UTC)

    # Set up a session row + two hypotheses in pairwise calibration.
    await conn.execute(
        """INSERT INTO sessions(id, created_at, updated_at, status, research_goal,
                                 research_plan, config_snapshot, budget_tokens, budget_usd)
           VALUES ('ses_t', ?, ?, 'running', 'test', '{}', '{}', 1000000, 10.0)""",
        (now.isoformat(), now.isoformat()),
    )
    await conn.commit()

    for hid in ("hyp_x", "hyp_y"):
        h = Hypothesis(
            id=hid, session_id="ses_t", created_at=now,
            created_by="breeding_designer", strategy="literature",
            title="t", summary="s", full_text="f",
            artifact_path=f"artifacts/ses_t/hypotheses/{hid}.json",
            calibration_score=1200, pairwise_calibrations_played=0, state="calibration_pool",
        )
        await hyp_repo.insert(conn, h)

    mid = ids.match_id("hyp_x", "hyp_y", "round1")
    m = PairwiseCalibrationMatch(
        id=mid, session_id="ses_t", created_at=now,
        hyp_a="hyp_x", hyp_b="hyp_y", mode="pairwise", winner="a",
        calibration_a_before=1200.0, calibration_b_before=1200.0,
        calibration_a_after=1216.0, calibration_b_after=1184.0, rationale="test",
    )
    assert m.calibration_a_before == 1200.0
    assert m.calibration_b_before == 1200.0
    assert m.calibration_a_after == 1216.0
    assert m.calibration_b_after == 1184.0
    await pairwise_repo.record_pairwise_calibration(conn, m)

    ok1 = await pairwise_repo.apply_pairwise_calibration_update(
        conn, match_id=mid, hyp_a="hyp_x", hyp_b="hyp_y", winner="a",
        calibration_a_before=1200.0, calibration_b_before=1200.0,
        calibration_a_after=1216.0, calibration_b_after=1184.0,
    )
    assert ok1 is True

    # Re-apply: should no-op.
    ok2 = await pairwise_repo.apply_pairwise_calibration_update(
        conn, match_id=mid, hyp_a="hyp_x", hyp_b="hyp_y", winner="a",
        calibration_a_before=1200.0, calibration_b_before=1200.0,
        calibration_a_after=1216.0, calibration_b_after=1184.0,
    )
    assert ok2 is False

    # State reflects exactly one update
    hx = await hyp_repo.fetch(conn, "hyp_x")
    hy = await hyp_repo.fetch(conn, "hyp_y")
    assert hx is not None and hy is not None
    assert hx.calibration_score == 1216.0
    assert hy.calibration_score == 1184.0
    assert hx.pairwise_calibrations_played == 1
    assert hy.pairwise_calibrations_played == 1
    assert DirectPairwiseCalibrationMatch is PairwiseCalibrationMatch
