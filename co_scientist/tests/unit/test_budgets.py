"""Tests for the budget guard."""

from __future__ import annotations

import pytest

from co_scientist.config import Config
from co_scientist.llm.budgets import BudgetExceeded, TokenBudget


@pytest.mark.asyncio
async def test_admit_then_settle_updates_counters() -> None:
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=10.0)

    await b.admit("breeding_designer", est_tokens=1000, est_usd=0.5)
    snap1 = b.snapshot()
    assert snap1["_global"]["reserved_usd"] == pytest.approx(0.5)

    await b.settle(
        "breeding_designer",
        est_tokens=1000, est_usd=0.5,
        actual_input_tokens=500, actual_output_tokens=300, actual_usd=0.40,
    )
    snap2 = b.snapshot()
    assert snap2["_global"]["reserved_usd"] == pytest.approx(0.0)
    assert snap2["_global"]["used_usd"] == pytest.approx(0.40)
    assert snap2["_global"]["used_tokens"] == 800
    assert snap2["_global"]["used_input_tokens"] == 500
    assert snap2["_global"]["used_output_tokens"] == 300
    assert snap2["breeding_designer"]["used_usd"] == pytest.approx(0.40)
    assert snap2["breeding_designer"]["used_input_tokens"] == 500
    assert snap2["breeding_designer"]["used_output_tokens"] == 300


@pytest.mark.asyncio
async def test_global_cap_eventually_blocks_runaway_spend() -> None:
    """Repeated admits across all agents eventually hit either the per-agent share
    or the global cap; the system must refuse to keep admitting indefinitely."""
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=1.0)
    raised = False
    for _ in range(200):
        for agent in (
            "goal_interpreter", "evidence_curator", "breeding_designer",
            "validation_planner", "risk_reviewer", "iteration_orchestrator",
        ):
            try:
                await b.admit(agent, est_tokens=10, est_usd=0.01)
            except BudgetExceeded:
                raised = True
                break
        if raised:
            break
    assert raised, "BudgetExceeded should fire long before 1200 admits"


@pytest.mark.asyncio
async def test_per_agent_share_is_enforced() -> None:
    cfg = Config()
    # Breeding Designer uses its configured six-agent budget share 鈫?$0.20 of $1
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=1.0)
    # under share
    await b.admit("breeding_designer", est_tokens=100, est_usd=0.10)
    # over share (plus the half-reserve allowance), should raise eventually
    with pytest.raises(BudgetExceeded):
        # 3x more should clearly exceed share+reserve
        for _ in range(20):
            await b.admit("breeding_designer", est_tokens=100, est_usd=0.30)


@pytest.mark.asyncio
async def test_share_percent_for_unknown_agent_is_zero() -> None:
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=10.0)
    # 'unknown' has 0% share; only the half-reserve allowance buffers us
    assert b.share_usd("unknown") == 0.0


@pytest.mark.asyncio
async def test_six_agent_budget_shares_are_exposed() -> None:
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=10.0)

    assert b.share_usd("breeding_designer") == pytest.approx(
        10.0 * cfg.budget_shares.breeding_designer
    )
    assert b.share_usd("iteration_orchestrator") == pytest.approx(
        10.0 * cfg.budget_shares.iteration_orchestrator
    )
    await b.admit("breeding_designer", est_tokens=100, est_usd=0.5)


@pytest.mark.asyncio
async def test_settle_with_zero_actual_releases_reservation() -> None:
    """If a call fails after admission (e.g. retry exhaustion), the caller must
    be able to release the reservation with actual=0 so the reserve doesn't leak."""
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=1.0)

    await b.admit("breeding_designer", est_tokens=500, est_usd=0.20)
    snap_mid = b.snapshot()
    assert snap_mid["_global"]["reserved_usd"] == pytest.approx(0.20)

    # Simulate failed call: settle with actual=0
    await b.settle(
        "breeding_designer",
        est_tokens=500, est_usd=0.20,
        actual_input_tokens=0, actual_output_tokens=0, actual_usd=0.0,
    )
    snap_end = b.snapshot()
    assert snap_end["_global"]["reserved_usd"] == pytest.approx(0.0)
    assert snap_end["_global"]["used_usd"] == pytest.approx(0.0)
    # Subsequent admit should now succeed
    await b.admit("breeding_designer", est_tokens=500, est_usd=0.20)


@pytest.mark.asyncio
async def test_shared_reserve_can_be_borrowed_by_one_agent() -> None:
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=1.0)

    # Risk Reviewer has a $0.10 base share and can borrow the unused shared
    # reserve instead of receiving a duplicated static allowance.
    await b.admit("risk_reviewer", est_tokens=100, est_usd=0.15)
    snap = b.snapshot()
    assert snap["risk_reviewer"]["reserve_used_usd"] == pytest.approx(0.05)
    assert snap["_global"]["reserve_committed_usd"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_shared_reserve_is_not_oversubscribed() -> None:
    cfg = Config()
    b = TokenBudget(cfg=cfg, budget_tokens=10_000, budget_usd=1.0)

    await b.admit("risk_reviewer", est_tokens=100, est_usd=0.15)
    with pytest.raises(BudgetExceeded, match="reserve_cap"):
        await b.admit("evidence_curator", est_tokens=100, est_usd=0.21)
