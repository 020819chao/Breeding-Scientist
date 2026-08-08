from __future__ import annotations

from datetime import UTC, datetime

import httpx

from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.storage.artifacts import write_json
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.web.app import create_app


def _session(session_id: str, status: str) -> Session:
    now = datetime.now(UTC)
    return Session(
        id=session_id,
        created_at=now,
        updated_at=now,
        status=status,
        research_goal="Improve mixed-grain drought resilience",
        research_plan=ResearchPlan(
            objective="Improve mixed-grain drought resilience",
            initial_hypothesis_count=2,
            max_hypothesis_count=4,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )


async def test_delete_completed_session_removes_rows_and_owned_files(tmp_cfg, conn) -> None:
    session_id = "ses_delete_completed"
    await sess_repo.insert(conn, _session(session_id, "done"))
    await hyp_repo.insert(
        conn,
        Hypothesis(
            id="hyp_delete_completed",
            session_id=session_id,
            created_at=datetime.now(UTC),
            created_by="breeding_designer",
            strategy="literature",
            title="A drought-resilient mixed-grain route",
            summary="A locally testable route.",
            full_text="Detailed route.",
            artifact_path="artifacts/ses_delete_completed/hypotheses/hyp_delete_completed.json",
        ),
    )
    await write_json(tmp_cfg, session_id, "meta", "session", {"session_id": session_id})
    for directory in ("vectors", "logs"):
        path = tmp_cfg.data_dir / directory / session_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "marker.txt").write_text("owned by session", encoding="utf-8")

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/api/sessions/{session_id}")
        listing = await client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "session_id": session_id}
    assert await sess_repo.fetch(conn, session_id) is None
    assert await hyp_repo.fetch(conn, "hyp_delete_completed") is None
    assert all(item["id"] != session_id for item in listing.json())
    assert not (tmp_cfg.data_dir / "artifacts" / session_id).exists()
    assert not (tmp_cfg.data_dir / "vectors" / session_id).exists()
    assert not (tmp_cfg.data_dir / "logs" / session_id).exists()


async def test_delete_running_session_requires_termination(tmp_cfg, conn) -> None:
    session_id = "ses_delete_running"
    await sess_repo.insert(conn, _session(session_id, "running"))

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert "先终止" in response.json()["error"]
    assert await sess_repo.fetch(conn, session_id) is not None
