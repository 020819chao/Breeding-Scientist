from __future__ import annotations

from pathlib import Path

import httpx

from co_scientist.models import Hypothesis, ResearchPlan, Review, ReviewScores, Session, Task
from co_scientist.storage.artifacts import write_json
from co_scientist.storage.repos import events as events_repo
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import reviews as rev_repo
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.storage.repos import tasks as task_repo
from co_scientist.web.app import (
    _composite_breeding_rank_score,
    _extract_germplasm_table,
    _iteration_audit_summary,
    _latest_iteration_decisions_for_session,
    _load_evidence_graph_view,
    _graph_node_type,
    _load_hypothesis_evidence_subgraph_view,
    _load_iteration_decisions,
    _load_route_revision_graph_view,
    _rank_hypotheses_for_prioritized_routes,
    _route_admission_summary,
    _select_graph_nodes,
    create_app,
    hypothesis_lifecycle_label,
)


def test_extract_germplasm_table_from_final_overview_markdown() -> None:
    markdown = """
# Executive summary
Supported claim [Source](https://example.org/a).

# Germplasm resource evidence table
| Material | Accession ID | Use / trait clue | Source | Risk / evidence gap |
| --- | --- | --- | --- | --- |
| 263A | ARCH-263A | parent selection | https://example.org/263a | availability needs confirmation |
| Xiaojinmiao | FPS2025-136 | stem thickness donor | https://example.org/fps | single-environment evidence |

---

# Final report audit
Passed deterministic checks.
"""
    rows = _extract_germplasm_table(markdown)

    assert rows == [
        {
            "Material": "263A",
            "Accession ID": "ARCH-263A",
            "Use / trait clue": "parent selection",
            "Source": "https://example.org/263a",
            "Risk / evidence gap": "availability needs confirmation",
        },
        {
            "Material": "Xiaojinmiao",
            "Accession ID": "FPS2025-136",
            "Use / trait clue": "stem thickness donor",
            "Source": "https://example.org/fps",
            "Risk / evidence gap": "single-environment evidence",
        },
    ]


def test_extract_germplasm_table_ignores_missing_table() -> None:
    assert _extract_germplasm_table("# Executive summary\n\nNo table.") == []


def test_hypothesis_lifecycle_label_maps_current_states() -> None:
    assert hypothesis_lifecycle_label("draft") == "draft"
    assert hypothesis_lifecycle_label("reviewed") == "candidate"
    assert hypothesis_lifecycle_label("calibration_pool") == "candidate"
    assert hypothesis_lifecycle_label("pinned") == "ready"
    assert hypothesis_lifecycle_label("quarantined") == "blocked"
    assert hypothesis_lifecycle_label("rejected") == "rejected"
    assert hypothesis_lifecycle_label("retired") == "archived"


def test_select_graph_nodes_preserves_evidence_type_coverage() -> None:
    nodes = [
        {"id": "environment:dryland", "type": "environment", "label": "dryland"},
        {"id": "material:donor", "type": "germplasm", "label": "donor"},
        {"id": "gene:DRO1", "type": "gene_qtl", "label": "DRO1"},
        {"id": "trait:drought", "type": "trait", "label": "drought tolerance"},
        {"id": "risk:gxE", "type": "risk", "label": "GxE risk"},
        {"id": "evidence:paper", "type": "evidence", "label": "paper"},
        {"id": "other:strategy", "type": "breeding_strategy", "label": "strategy"},
        {"id": "trait:yield", "type": "trait", "label": "yield"},
    ]
    edges = [
        {"source": "trait:drought", "target": "material:donor"},
        {"source": "trait:drought", "target": "gene:DRO1"},
        {"source": "trait:drought", "target": "environment:dryland"},
        {"source": "trait:drought", "target": "risk:gxE"},
        {"source": "trait:drought", "target": "evidence:paper"},
    ]

    selected = _select_graph_nodes(nodes, edges, limit=6)

    selected_types = {_graph_node_type(node) for node in selected}
    assert {
        "trait",
        "germplasm",
        "gene_qtl_marker",
        "environment_protocol",
        "risk",
        "rag_evidence",
    } <= selected_types


async def test_load_iteration_decisions_filters_by_hypothesis(tmp_cfg) -> None:
    await write_json(
        tmp_cfg,
        "ses_web_iteration",
        "iteration",
        "decision_a",
        {
            "created_at": "2026-07-27T10:00:00+00:00",
            "hypothesis_id": "hyp_target",
            "action": "revise",
            "total_score": 62.5,
            "scorecard": [
                {
                    "dimension": "validation_actionability",
                    "score": 55.0,
                    "weight": 0.15,
                    "weighted_score": 8.25,
                    "rationale": "Marker validation gap remains.",
                }
            ],
        },
    )
    await write_json(
        tmp_cfg,
        "ses_web_iteration",
        "iteration",
        "decision_b",
        {
            "created_at": "2026-07-27T11:00:00+00:00",
            "hypothesis_id": "hyp_other",
            "action": "keep",
            "total_score": 80.0,
        },
    )

    decisions = _load_iteration_decisions(tmp_cfg, "ses_web_iteration", "hyp_target")

    assert len(decisions) == 1
    assert decisions[0]["action"] == "revise"
    assert decisions[0]["scorecard"][0]["dimension"] == "validation_actionability"
    assert decisions[0]["decision_path"].endswith("iteration/decision_a.json")


async def test_load_evidence_graph_view_and_page_render(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_graph",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            initial_hypothesis_count=1,
            max_hypothesis_count=1,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "breeding_evidence_graph",
        {
            "version": 1,
            "session_id": session.id,
            "updated_at": "2026-07-27T12:00:00+00:00",
            "node_count": 3,
            "edge_count": 2,
            "nodes": [
                {"id": "material:ARCH-263A", "type": "germplasm", "label": "263A"},
                {"id": "trait:lodging", "type": "trait", "label": "lodging resistance"},
                {"id": "marker:Si5G404900C", "type": "marker", "label": "Si5G404900C"},
            ],
            "edges": [
                {
                    "source": "material:ARCH-263A",
                    "predicate": "has_trait",
                    "target": "trait:lodging",
                },
                {
                    "source": "marker:Si5G404900C",
                    "predicate": "marker_for",
                    "target": "trait:lodging",
                },
            ],
        },
    )

    graph = _load_evidence_graph_view(tmp_cfg, session.id)

    assert graph["available"] is True
    assert graph["node_types"]["germplasm"] == 1
    assert graph["node_types"]["gene_qtl_marker"] == 1
    assert graph["visible_edge_count"] == 2

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}/evidence-graph")

    assert response.status_code == 200
    assert "Breeding Evidence Graph" in response.text
    assert "交互式证据图谱" in response.text
    assert "data-cytoscape-graph" in response.text
    assert "cytoscape.min.js" in response.text
    assert "data-cy-filter=\"gene_qtl_marker\"" in response.text
    assert "查看全部节点和关系明细" in response.text
    assert 'class="graph-data-details"' in response.text
    assert "Si5G404900C" in response.text
    assert "marker_for" in response.text


async def test_session_page_groups_internal_tasks_into_six_agents(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_six_agents",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            initial_hypothesis_count=1,
            max_hypothesis_count=3,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    for agent, action, status in [
        ("evidence_curator", "CurateEvidencePackage", "done"),
        ("breeding_designer", "DesignHypothesis", "done"),
        ("risk_reviewer", "AssessHypothesisEvidence", "done"),
        ("iteration_orchestrator", "RunPairwiseCalibration", "pending"),
        ("validation_planner", "PlanValidation", "pending"),
        ("risk_reviewer", "ReviewRisk", "pending"),
    ]:
        await task_repo.enqueue(
            conn,
            Task(
                id=f"task_{agent}_{action}",
                session_id=session.id,
                created_at=now,
                agent=agent,
                action=action,
                payload={},
                priority=100,
                status=status,
                idempotency_key=f"{session.id}::{agent}::{action}",
            ),
        )

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}")

    assert response.status_code == 200
    assert "推荐育种路线" in response.text
    assert "系统正在整理证据和候选路线" in response.text
    assert "暂停分析" in response.text
    assert "六智能体执行状态" in response.text
    assert "证据整理" in response.text
    assert "育种设计" in response.text
    assert "agent-card-summary" in response.text
    assert f'data-session-id="{session.id}"' in response.text
    assert "data-agent-stream" in response.text
    assert "EventSource" in response.text
    assert "agent_progress" in response.text
    assert f"/sessions/{session.id}/agent-outputs" in response.text
    assert "当前没有正在执行的智能体" in response.text
    assert "Token" not in response.text
    assert "模型调用" not in response.text


async def test_hypothesis_evidence_subgraph_view_and_page_render(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_subgraph",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            initial_hypothesis_count=1,
            max_hypothesis_count=1,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    hypothesis = Hypothesis(
        id="hyp_subgraph",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="CAPS-assisted lodging route",
        summary="Validate marker-assisted lodging resistance.",
        full_text="# CAPS-assisted lodging route",
        artifact_path="artifacts/ses_web_subgraph/hypotheses/hyp_subgraph.json",
    )
    await hyp_repo.insert(conn, hypothesis)
    child = hypothesis.model_copy(
        update={
            "id": "hyp_subgraph_child",
            "title": "CAPS-assisted lodging successor",
            "artifact_path": "artifacts/ses_web_subgraph/hypotheses/hyp_subgraph_child.json",
            "parent_ids": [hypothesis.id],
        }
    )
    await hyp_repo.insert(conn, child)
    package_path = await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_subgraph",
        {
            "target_hypothesis_id": hypothesis.id,
            "mode": "dfrs",
            "search_strategy": "depth_first_route_search",
            "queries": ["Si5G404900C lodging validation"],
            "local_germplasm": {
                "results": [
                    {
                        "accession_id": "ARCH-263A",
                        "name": "263A",
                        "primary_traits": "lodging resistance",
                        "availability": "unknown",
                        "risk_notes": "availability requires confirmation",
                    }
                ]
            },
            "local_crop_kg": {
                "results": [
                    {
                        "id": "marker:Si5G404900C",
                        "type": "marker",
                        "name": "Si5G404900C",
                        "data_confidence": "high",
                        "edges": [
                            {
                                "predicate": "requires_validation",
                                "object": "risk:marker_transferability",
                            }
                        ],
                    }
                ]
            },
            "local_rag": {
                "results": [
                    {
                        "title": "CAPS preflight",
                        "url": "local-rag://caps_preflight.md#L1-L2",
                        "text": "Si5G404900C CAPS marker requires local validation.",
                    }
                ]
            },
            "local_marker_qtl": {
                "results": [
                    {
                        "marker_id": "MQTL-LODGE-001",
                        "marker_name": "Si5G404900C CAPS",
                        "trait": "lodging resistance",
                        "gene_or_qtl": "Seita.5G404900",
                        "validation_status": "needs_local_parent_preflight",
                        "data_confidence": "high",
                        "risk_notes": "Marker transferability requires local validation.",
                        "source_refs": "local-rag://caps_preflight.md",
                    }
                ]
            },
            "local_phenotype_protocols": {
                "results": [
                    {
                        "protocol_id": "PHENO-LODGE-001",
                        "trait": "lodging resistance",
                        "target_environment": "dense planting nursery",
                        "measurement_method": "Record lodging score and stem strength.",
                        "decision_thresholds": "Advance if lodging improves without yield penalty.",
                        "validation_status": "local_protocol_ready",
                        "data_confidence": "high",
                    }
                ]
            },
            "local_field_trials": {
                "results": [
                    {
                        "trial_id": "TRIAL-LODGE-001",
                        "trait": "lodging resistance",
                        "environment": "dense planting nursery",
                        "materials": "ARCH-263A; Jingu21",
                        "decision_outcome": "pending_local_validation",
                        "phenotype_summary": "Lodging score and stem strength are pending.",
                        "data_confidence": "medium",
                        "risk_notes": "Seed availability is unresolved.",
                    }
                ]
            },
            "evidence_gaps": [
                {
                    "severity": "high",
                    "type": "genotype_or_marker_validation",
                    "target": "ARCH-263A",
                    "message": "Marker claim needs genotype evidence.",
                }
            ],
            "breeding_evidence_graph_delta": {
                "nodes": [
                    {"id": "material:ARCH-263A", "type": "germplasm", "label": "263A"},
                    {"id": "marker:Si5G404900C", "type": "marker", "label": "Si5G404900C"},
                ],
                "edges": [
                    {
                        "source": "marker:Si5G404900C",
                        "predicate": "requires_validation",
                        "target": "risk:marker_transferability",
                    }
                ],
            },
        },
    )
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_subgraph",
        {
            "created_at": "2026-07-27T12:00:00+00:00",
            "hypothesis_id": hypothesis.id,
            "evidence_package_path": package_path,
            "action": "revise",
            "new_hypothesis_direction": "Resolve the CAPS marker validation gap.",
        },
    )

    subgraph = _load_hypothesis_evidence_subgraph_view(tmp_cfg, session.id, hypothesis.id)

    assert subgraph["available"] is True
    assert subgraph["scope"] == "hypothesis"
    assert subgraph["hypothesis_id"] == hypothesis.id
    assert subgraph["node_types"]["risk"] == 1
    assert subgraph["source_package_paths"] == [Path(package_path).as_posix()]
    assert subgraph["evidence_package_summaries"][0]["germplasm"][0]["accession_id"] == "ARCH-263A"
    assert subgraph["evidence_package_summaries"][0]["gaps"][0]["type"] == "genotype_or_marker_validation"

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}/hypotheses/{hypothesis.id}/evidence-subgraph")

    assert response.status_code == 200
    assert "Hypothesis Evidence Subgraph" in response.text
    assert "查看路线背景与迭代信息" in response.text
    assert "Resolve the CAPS marker validation gap." in response.text
    assert "后续路线" in response.text
    assert child.id in response.text
    assert "查看证据资料" in response.text
    assert "交互式证据图谱" in response.text
    assert "ARCH-263A" in response.text
    assert "CAPS preflight" in response.text
    assert "标记与基因证据" in response.text
    assert "Si5G404900C CAPS" in response.text
    assert "表型验证方案" in response.text
    assert "Record lodging score and stem strength." in response.text
    assert "田间试验记录" in response.text
    assert "Jingu21" in response.text
    assert "验证" in response.text
    assert "risk:marker_transferability" in response.text


async def test_route_revision_graph_view_and_page_render(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_route_revision",
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
    parent = Hypothesis(
        id="hyp_parent_route",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Parent marker route",
        summary="Parent route needs local marker validation.",
        full_text="# Parent marker route",
        artifact_path="artifacts/ses_web_route_revision/hypotheses/hyp_parent_route.json",
        calibration_score=1240,
        state="calibration_pool",
    )
    child = parent.model_copy(
        update={
            "id": "hyp_child_route",
            "title": "Child validation route",
            "summary": "Child route resolves marker validation.",
            "full_text": "# Child validation route",
            "artifact_path": "artifacts/ses_web_route_revision/hypotheses/hyp_child_route.json",
            "parent_ids": [parent.id],
            "calibration_score": 1220,
        }
    )
    await hyp_repo.insert(conn, parent)
    await hyp_repo.insert(conn, child)
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_parent_route",
        {
            "created_at": "2026-07-27T11:00:00+00:00",
            "hypothesis_id": parent.id,
            "action": "revise",
            "total_score": 64.0,
            "evidence_package_path": "artifacts/ses_web_route_revision/evidence/package_parent.json",
            "validation_plan_path": "artifacts/ses_web_route_revision/validation/plan_parent.json",
            "risk_review_path": "artifacts/ses_web_route_revision/risk/review_parent.json",
            "new_hypothesis_direction": "Resolve local marker validation before prioritization.",
            "evidence_gap_to_resolve": ["marker needs local validation"],
            "do_not_repeat": ["Do not restate marker claims without validation."],
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
                "new_hypothesis_direction": "Resolve local marker validation before prioritization.",
                "evidence_gap_to_resolve": ["marker needs local validation"],
                "do_not_repeat": ["Do not restate marker claims without validation."],
            },
        },
    )
    decisions = _latest_iteration_decisions_for_session(tmp_cfg, session.id)

    graph = _load_route_revision_graph_view([parent, child], decisions)

    assert graph["available"] is True
    assert graph["node_count"] == 2
    assert graph["edge_count"] == 1
    assert graph["edges"][0]["source"] == parent.id
    assert graph["edges"][0]["target"] == child.id
    assert graph["edges"][0]["action"] == "revise"
    assert "marker validation" in graph["edges"][0]["direction"]
    assert graph["edges"][0]["evidence_package_path"].endswith("package_parent.json")

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}/route-revision-graph")
        focus_response = await client.get(
            f"/sessions/{session.id}/hypotheses/{child.id}/route-revision-graph"
        )
        detail_response = await client.get(f"/sessions/{session.id}/hypotheses/{parent.id}")

    assert response.status_code == 200
    assert "路线修订图" in response.text
    assert "Parent marker route" in response.text
    assert "Child validation route" in response.text
    assert "Resolve local marker validation before prioritization." in response.text
    assert "父假设证据子图" in response.text
    assert "package_parent.json" in response.text
    assert "plan_parent.json" in response.text
    assert "review_parent.json" in response.text
    assert focus_response.status_code == 200
    assert "路线修订子图" in focus_response.text
    assert parent.id in focus_response.text
    assert child.id in focus_response.text
    assert detail_response.status_code == 200
    assert "路线迭代" in detail_response.text
    assert "后续路线" in detail_response.text
    assert child.id in detail_response.text


async def test_session_priority_routes_show_latest_iteration_decision(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_priority",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            initial_hypothesis_count=1,
            max_hypothesis_count=1,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    hypothesis = Hypothesis(
        id="hyp_priority",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Priority-visible route",
        summary="Validate a route.",
        full_text="# Priority-visible route",
        artifact_path="artifacts/ses_web_priority/hypotheses/hyp_priority.json",
        calibration_score=1280,
        state="reviewed",
    )
    await hyp_repo.insert(conn, hypothesis)
    await rev_repo.insert(
        conn,
        Review(
            id="rev_priority",
            hypothesis_id=hypothesis.id,
            session_id=session.id,
            created_at=now,
            kind="full",
            verdict="missing_piece",
            scores=ReviewScores(
                novelty=0.55,
                correctness=0.45,
                testability=0.70,
                feasibility=0.50,
            ),
            body=(
                "# Review note\n\n"
                "**Conclusion.** missing_piece\n\n"
                "- Evidence gap: local marker validation is still required."
            ),
            artifact_path="artifacts/ses_web_priority/reviews/rev_priority.json",
        ),
    )
    package_path = await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_priority",
        {
            "target_hypothesis_id": hypothesis.id,
            "breeding_evidence_graph_delta": {
                "nodes": [{"id": "marker:Si5G404900C", "type": "marker", "label": "Si5G404900C"}],
                "edges": [],
            },
        },
    )
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_old",
        {
            "created_at": "2026-07-27T10:00:00+00:00",
            "hypothesis_id": hypothesis.id,
            "action": "keep",
            "total_score": 78.0,
        },
    )
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_new",
        {
            "created_at": "2026-07-27T11:00:00+00:00",
            "hypothesis_id": hypothesis.id,
            "action": "revise",
            "total_score": 62.5,
            "review_gate": "mixed",
            "next_step_recommendation": "generate_revised_hypothesis_from_decision",
            "reasons": ["Marker validation gap remains."],
            "evidence_package_path": package_path,
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
                "new_hypothesis_direction": "Resolve the local marker validation gap.",
                "evidence_gap_to_resolve": ["marker needs local validation"],
                "do_not_repeat": ["Do not restate marker claims without validation."],
            },
            "breeding_design_card_audit": {
                "status": "needs_attention",
                "completeness_score": 58.0,
                "missing_fields": ["donor_parent", "fallback_route"],
                "missing_critical_fields": ["donor_parent"],
                "penalty": 7.0,
            },
        },
    )

    latest = _latest_iteration_decisions_for_session(tmp_cfg, session.id)

    assert latest[hypothesis.id]["action"] == "revise"
    assert latest[hypothesis.id]["reason_summary"] == "Marker validation gap remains."
    assert latest[hypothesis.id]["has_evidence_package"] is True

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}")

    assert response.status_code == 200
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        artifact_response = await client.get(
            f"/sessions/{session.id}/artifacts/{package_path}"
        )
        outputs_response = await client.get(f"/sessions/{session.id}/agent-outputs")
    assert artifact_response.status_code == 200
    assert "package_priority" in artifact_response.text
    assert "六智能体成果文件" in artifact_response.text
    assert outputs_response.status_code == 200
    assert "六智能体成果审阅" in outputs_response.text
    assert "选择智能体" in outputs_response.text
    assert "结构化育种目标" in outputs_response.text
    assert "查看高级信息" in outputs_response.text
    assert outputs_response.text.count('class="agent-review-panel"') == 6
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as selected_client:
        selected_output_response = await selected_client.get(
            f"/sessions/{session.id}/agent-outputs?agent=Goal%20Interpreter"
        )
    assert selected_output_response.status_code == 200
    assert "查看全部六个智能体成果" in selected_output_response.text
    assert selected_output_response.text.count('class="agent-review-panel"') == 1
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as review_client:
        review_response = await review_client.post(
            f"/sessions/{session.id}/agent-outputs/review",
            data={
                "agent": "Evidence Curator",
                "output_key": package_path,
                "output_path": package_path,
                "target_id": hypothesis.id,
                "status": "needs_revision",
            "reviewer": "专家甲",
                "note": "补充本地标记验证证据。",
            },
            follow_redirects=False,
        )
        assert review_response.status_code == 303
        assert review_response.headers["location"].endswith("?saved=1")
        reviewed_outputs_response = await review_client.get(
            f"/sessions/{session.id}/agent-outputs"
        )
    assert "需修改" in reviewed_outputs_response.text
    assert "专家甲" in reviewed_outputs_response.text
    assert "补充本地标记验证证据。" in reviewed_outputs_response.text
    normalized_package_path = package_path.replace("\\", "/")
    async with conn.execute(
        "SELECT status FROM agent_output_reviews WHERE session_id=? AND output_key=?",
        (session.id, normalized_package_path),
    ) as cur:
        review_row = await cur.fetchone()
    assert review_row["status"] == "needs_revision"
    async with conn.execute(
        "SELECT action, agent, target_id FROM tasks WHERE session_id=? AND idempotency_key LIKE ?",
        (
            session.id,
            f"{session.id}::mentor_review::{normalized_package_path}::needs_revision",
        ),
    ) as cur:
        followup_row = await cur.fetchone()
    assert followup_row["action"] == "CurateEvidencePackage"
    assert followup_row["agent"] == "evidence_curator"
    assert followup_row["target_id"] == hypothesis.id
    assert "推荐育种路线" in response.text
    assert "需要进一步处理的路线" in response.text
    assert "查看路线证据图谱" in response.text
    assert "Priority-visible route" in response.text
    assert "补齐本地标记验证缺口" in response.text
    assert "六智能体执行状态" in response.text
    for agent_label in (
        "目标解析",
        "证据整理",
        "育种设计",
        "验证规划",
        "风险评审",
        "迭代编排",
    ):
        assert agent_label in response.text
    assert "迭代审计" not in response.text
    assert "假设数量边界" not in response.text
    assert f"/sessions/{session.id}/hypotheses/{hypothesis.id}" in response.text
    assert f"/sessions/{session.id}/hypotheses/{hypothesis.id}/evidence-subgraph" in response.text

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        detail_response = await client.get(f"/sessions/{session.id}/hypotheses/{hypothesis.id}")

    assert detail_response.status_code == 200
    assert "育种路线工作台" in detail_response.text
    assert "路线迭代" in detail_response.text
    assert "1280" not in detail_response.text
    assert "配对校准分" not in detail_response.text
    assert "配对检查" not in detail_response.text
    assert "育种评审笔记 (1)" not in detail_response.text
    assert "专家评审结论" in detail_response.text
    assert "Evidence review" in detail_response.text
    assert "needs evidence" in detail_response.text
    assert "<pre style=\"white-space:pre-wrap\">" not in detail_response.text
    assert "<strong>Conclusion.</strong> missing_piece" in detail_response.text
    assert "原始假设与推理依据" not in detail_response.text
    assert "Iteration Decisions" not in detail_response.text
    assert "迭代决策" not in detail_response.text
    assert "路线修订意图" not in detail_response.text
    assert "关键缺失字段" not in detail_response.text
    assert "donor_parent" not in detail_response.text


async def test_session_detail_explains_max_hypothesis_stop_reason(tmp_cfg, conn) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session = Session(
        id="ses_web_max_stop",
        created_at=now,
        updated_at=now,
        status="done",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            initial_hypothesis_count=1,
            max_hypothesis_count=1,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    hypothesis = Hypothesis(
        id="hyp_max_stop",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Capped route",
        summary="Needs revision but the pool is capped.",
        full_text="# Capped route",
        artifact_path="artifacts/ses_web_max_stop/hypotheses/hyp_max_stop.json",
    )
    await hyp_repo.insert(conn, hypothesis)
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_max_stop",
        {
            "created_at": "2026-07-27T11:00:00+00:00",
            "hypothesis_id": hypothesis.id,
            "action": "revise",
            "total_score": 66.0,
        },
    )
    await events_repo.emit(
        conn,
        session_id=session.id,
        task_id=None,
        agent="supervisor",
        event="session_done",
        payload={"stop_reason": "breeding_max_hypotheses_reached"},
    )

    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{session.id}")

    assert response.status_code == 200
    assert "已达到探索上限" in response.text
    assert "breeding_max_hypotheses_reached" not in response.text
    assert "Hypotheses generated" not in response.text
    assert "max_hypothesis_count" not in response.text


def test_composite_breeding_rank_prioritizes_keep_over_revise_pause() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    keep_hyp = Hypothesis(
        id="hyp_keep_rank",
        session_id="ses_rank",
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Keep route",
        summary="",
        full_text="",
        artifact_path="artifacts/ses_rank/hypotheses/hyp_keep_rank.json",
        calibration_score=1210,
    )
    revise_hyp = keep_hyp.model_copy(update={"id": "hyp_revise_rank", "title": "Revise route", "calibration_score": 1380})
    pause_hyp = keep_hyp.model_copy(update={"id": "hyp_pause_rank", "title": "Pause route", "calibration_score": 1500})
    decisions = {
        keep_hyp.id: {
            "action": "keep",
            "total_score": 82.0,
            "scorecard": [
                {"dimension": "evidence_support", "score": 82.0},
                {"dimension": "validation_actionability", "score": 78.0},
                {"dimension": "review_strength", "score": 80.0},
                {"dimension": "risk_control", "score": 85.0},
            ],
        },
        revise_hyp.id: {
            "action": "revise",
            "total_score": 72.0,
            "scorecard": [
                {"dimension": "evidence_support", "score": 75.0},
                {"dimension": "validation_actionability", "score": 68.0},
                {"dimension": "review_strength", "score": 70.0},
                {"dimension": "risk_control", "score": 76.0},
            ],
        },
        pause_hyp.id: {
            "action": "pause",
            "total_score": 90.0,
            "scorecard": [
                {"dimension": "evidence_support", "score": 90.0},
                {"dimension": "validation_actionability", "score": 90.0},
                {"dimension": "review_strength", "score": 90.0},
                {"dimension": "risk_control", "score": 90.0},
            ],
        },
    }

    ranked, rank_map = _rank_hypotheses_for_prioritized_routes(
        [pause_hyp, revise_hyp, keep_hyp],
        decisions,
    )

    assert ranked[0].id == keep_hyp.id
    assert ranked[-1].id == pause_hyp.id
    assert rank_map[keep_hyp.id]["score"] > rank_map[revise_hyp.id]["score"]
    assert rank_map[pause_hyp.id]["score"] < 20
    low_pairwise = keep_hyp.model_copy(update={"id": "hyp_low_pairwise", "calibration_score": 1000})
    high_pairwise = keep_hyp.model_copy(update={"id": "hyp_high_pairwise", "calibration_score": 1600})
    same_decision = decisions[keep_hyp.id]
    low_score = _composite_breeding_rank_score(low_pairwise, same_decision)
    high_score = _composite_breeding_rank_score(high_pairwise, same_decision)
    assert low_score["score"] == high_score["score"]
    assert (
        low_score["components"]["pairwise_calibration"]
        < high_score["components"]["pairwise_calibration"]
    )
    assert _composite_breeding_rank_score(
        keep_hyp.model_copy(update={"calibration_score": None}),
        None,
    )["score"] > 0


def test_route_admission_requires_evidence_gate_and_pairwise_maturity() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    mature = Hypothesis(
        id="hyp_admission_mature",
        session_id="ses_admission",
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Mature route",
        summary="",
        full_text="",
        artifact_path="artifacts/ses_admission/hypotheses/hyp_admission_mature.json",
        calibration_score=1240,
        pairwise_calibrations_played=3,
        state="calibration_pool",
    )
    mature_decision = {"action": "keep", "review_gate": "pass"}
    assert _route_admission_summary(mature, mature_decision)["eligible"] is True
    assert _route_admission_summary(mature, mature_decision)["status"] == "ranked"

    uncalibrated = mature.model_copy(
        update={
            "id": "hyp_admission_uncalibrated",
            "calibration_score": None,
            "pairwise_calibrations_played": 0,
        }
    )
    pending = _route_admission_summary(uncalibrated, mature_decision)
    assert pending["eligible"] is False
    assert pending["status"] == "pairwise_pending"
    assert pending["pairwise_required"] == 3

    revise = _route_admission_summary(
        mature,
        {"action": "revise", "review_gate": "mixed", "reason_summary": "needs marker"},
    )
    assert revise["eligible"] is False
    assert revise["status"] == "evidence_gap"

    no_review = _route_admission_summary(mature, None)
    assert no_review["eligible"] is False
    assert no_review["status"] == "evidence_review_pending"


def test_composite_rank_applies_design_card_penalty() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    complete_hyp = Hypothesis(
        id="hyp_complete_design",
        session_id="ses_rank",
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Complete design",
        summary="",
        full_text="",
        artifact_path="artifacts/ses_rank/hypotheses/hyp_complete_design.json",
        calibration_score=1220,
    )
    incomplete_hyp = complete_hyp.model_copy(
        update={"id": "hyp_incomplete_design", "title": "Incomplete design"}
    )
    base_decision = {
        "action": "keep",
        "total_score": 84.0,
        "scorecard": [
            {"dimension": "evidence_support", "score": 84.0},
            {"dimension": "validation_actionability", "score": 84.0},
            {"dimension": "review_strength", "score": 84.0},
            {"dimension": "risk_control", "score": 84.0},
        ],
    }
    decisions = {
        complete_hyp.id: {
            **base_decision,
            "breeding_design_card_audit": {
                "status": "complete",
                "completeness_score": 95.0,
                "missing_fields": [],
                "missing_critical_fields": [],
            },
        },
        incomplete_hyp.id: {
            **base_decision,
            "breeding_design_card_audit": {
                "status": "needs_attention",
                "completeness_score": 45.0,
                "missing_fields": [
                    "donor_parent",
                    "validation_trial_design",
                    "fallback_route",
                ],
                "missing_critical_fields": ["donor_parent", "validation_trial_design"],
                "penalty": 22.0,
            },
        },
    }

    ranked, rank_map = _rank_hypotheses_for_prioritized_routes(
        [incomplete_hyp, complete_hyp],
        decisions,
    )

    assert ranked[0].id == complete_hyp.id
    assert rank_map[incomplete_hyp.id]["components"]["design_card_penalty"] > 0
    assert rank_map[complete_hyp.id]["components"]["design_card_penalty"] == 0
    assert rank_map[incomplete_hyp.id]["score"] < rank_map[complete_hyp.id]["score"]
    assert decisions[incomplete_hyp.id]["composite_components"]["design_card_penalty"] > 0
    assert decisions[incomplete_hyp.id]["breeding_design_card_audit"]["status"] == "needs_attention"


def test_iteration_audit_summary_prioritizes_review_items() -> None:
    audit = _iteration_audit_summary(
        {
            "hyp_keep": {"action": "keep", "total_score": 83.0},
            "hyp_revise": {
                "action": "revise",
                "total_score": 62.5,
                "reason_summary": "Marker validation gap remains.",
            },
            "hyp_pause": {
                "action": "pause",
                "total_score": 40.0,
                "reason_summary": "Material unavailable.",
            },
        }
    )

    assert audit["total_decisions"] == 3
    assert audit["action_counts"]["keep"] == 1
    assert audit["action_counts"]["revise"] == 1
    assert audit["action_counts"]["pause"] == 1
    assert audit["avg_score"] == 61.83
    assert audit["priority_items"][0]["hypothesis_id"] == "hyp_pause"
    assert audit["priority_items"][1]["hypothesis_id"] == "hyp_revise"
