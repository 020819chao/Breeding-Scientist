from __future__ import annotations

from datetime import UTC, datetime

import httpx

from co_scientist.models import ResearchPlan, Session
from co_scientist.storage.artifacts import write_json
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.web.app import create_app


async def test_evidence_package_renders_reader_friendly_interpretation(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_readable_evidence",
        created_at=now,
        updated_at=now,
        status="done",
        research_goal="Improve rice salinity tolerance",
        research_plan=ResearchPlan(objective="Improve rice salinity tolerance"),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_readable",
        {
            "mode": "bfrs",
            "knowledge_snapshot_id": "kb_test_snapshot",
            "knowledge_batch_id": "rice_test_batch",
            "research_goal": session.research_goal,
            "local_germplasm": {
                "results": [
                    {
                        "name": "Pokkali",
                        "summary": "Salt-tolerant donor reference.",
                        "data_confidence": "medium",
                    }
                ]
            },
            "local_crop_kg": {
                "results": [
                    {
                        "name": "Saltol / qSKC1",
                        "summary": "A salinity-tolerance QTL route.",
                        "evidence_level": "local_kg_clue",
                    }
                ]
            },
            "local_rag": {
                "results": [
                    {
                        "title": "Rice salinity evidence pack",
                        "text": "Local genotype and multi-environment validation remain necessary.",
                        "evidence_level": "local_rag",
                    }
                ]
            },
            "evidence_gaps": [
                {
                    "type": "marker_assay_preflight",
                    "severity": "high",
                    "message": "Parental polymorphism needs confirmation.",
                }
            ],
        },
    )

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/sessions/{session.id}/artifacts/"
            "artifacts/ses_readable_evidence/evidence/package_readable.json"
        )

    assert response.status_code == 200
    assert "证据解读" in response.text
    assert "当前判断" in response.text
    assert "Pokkali" in response.text
    assert "Saltol / qSKC1" in response.text
    assert "目前还不能确定什么" in response.text
    assert "检测亲本多态性" in response.text
    assert "查看原始证据数据（JSON）" in response.text
