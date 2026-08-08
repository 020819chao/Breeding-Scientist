from __future__ import annotations

from datetime import UTC, datetime

from co_scientist.agents.base import AgentDeps
from co_scientist.agents.route_revision import RouteRevisionAgent
from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.storage.artifacts import write_json
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo


async def test_route_revision_selects_top_parents_by_composite_rank(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_route_revision_composite",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(objective="Improve foxtail millet lodging resistance"),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    keep = _hypothesis(
        session.id, "hyp_keep_parent", "Keep parent", calibration_score=1210
    )
    revise = _hypothesis(
        session.id, "hyp_revise_parent", "Revise parent", calibration_score=1390
    )
    pause = _hypothesis(
        session.id, "hyp_pause_parent", "Pause parent", calibration_score=1520
    )
    for hypothesis in (keep, revise, pause):
        await hyp_repo.insert(conn, hypothesis)

    await _decision(tmp_cfg, session.id, keep.id, action="keep", total_score=84.0)
    await _decision(tmp_cfg, session.id, revise.id, action="revise", total_score=74.0)
    await _decision(tmp_cfg, session.id, pause.id, action="pause", total_score=92.0)

    agent = RouteRevisionAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    top = await agent._top_by_composite_rank(session.id, k=2)

    assert [hypothesis.id for hypothesis in top] == [keep.id, revise.id]


def _hypothesis(
    session_id: str,
    hypothesis_id: str,
    title: str,
    *,
    calibration_score: float,
) -> Hypothesis:
    return Hypothesis(
        id=hypothesis_id,
        session_id=session_id,
        created_at=datetime.now(UTC),
        created_by="breeding_designer",
        strategy="literature",
        title=title,
        summary=title,
        full_text=f"# {title}",
        artifact_path=f"artifacts/{session_id}/hypotheses/{hypothesis_id}.json",
        calibration_score=calibration_score,
        state="calibration_pool",
    )


async def _decision(
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
