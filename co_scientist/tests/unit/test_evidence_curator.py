from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from co_scientist.agents.base import AgentDeps
from co_scientist.agents.breeding_designer import (
    _attach_evidence_provenance,
    _attach_iteration_parentage,
    _build_payload_route_revision_intent_context,
    _load_iteration_decision_context,
)
from co_scientist.agents.evidence_curator import (
    EvidenceCuratorAgent,
    _build_graph_delta,
    _chunk_matches_crop,
    _crop_hint,
    _curate_rag,
    _derive_queries,
    _record_matches_target_scope,
    _target_anchor_terms,
)
from co_scientist.agents.iteration_orchestrator import (
    IterationOrchestratorAgent,
    _decide_iteration,
)
from co_scientist.agents.risk_reviewer import RiskReviewerAgent
from co_scientist.agents.supervisor import (
    Supervisor,
    _apply_explicit_hypothesis_bounds,
    _hypothesis_count_limit,
    _hypothesis_design_gate,
    _resolve_initial_hypothesis_count,
)
from co_scientist.agents.validation_planner import (
    ValidationPlannerAgent,
    _build_validation_plan,
    _enrich_breeding_context,
)
from co_scientist.knowledge.breeding_libraries import (
    FIELD_TRIAL_COLUMNS,
    MARKER_QTL_COLUMNS,
    PHENOTYPE_PROTOCOL_COLUMNS,
)
from co_scientist.knowledge.germplasm import EXPECTED_COLUMNS
from co_scientist.knowledge.rag import (
    build_evidence_index,
    load_evidence_index,
    save_evidence_index,
)
from co_scientist.models import (
    Hypothesis,
    ResearchPlan,
    Review,
    ReviewScores,
    Session,
    Task,
    TaskResult,
)
from co_scientist.storage.artifacts import read_json, write_json
from co_scientist.storage.repos import events as events_repo
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import reviews as rev_repo
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.storage.repos import tasks as task_repo


async def test_evidence_curator_builds_local_first_package(tmp_path: Path, tmp_cfg, conn) -> None:
    germplasm_csv = tmp_path / "germplasm.csv"
    _write_germplasm_csv(germplasm_csv)
    tmp_cfg.knowledge.germplasm_csv = str(germplasm_csv)

    kg_json = tmp_path / "crop_kg.json"
    kg_json.write_text(
        json.dumps(
            {
                "metadata": {},
                "nodes": [
                    {
                        "id": "trait:lodging",
                        "name": "lodging resistance",
                        "type": "trait",
                        "summary": "Dense planting lodging resistance in foxtail millet.",
                        "source_refs": "local note",
                        "data_confidence": "medium",
                    },
                    {
                        "id": "marker:Si5G404900C",
                        "name": "Si5G404900C CAPS",
                        "type": "marker",
                        "summary": "CAPS marker for Seita.5G404900 validation.",
                        "source_refs": "https://doi.org/10.1016/j.cj.2022.09.003",
                        "data_confidence": "high",
                    },
                ],
                "edges": [
                    {
                        "id": "edge:marker_for",
                        "subject": "marker:Si5G404900C",
                        "predicate": "marker_for",
                        "object": "trait:lodging",
                        "evidence": "CAPS marker should be locally validated.",
                        "source_refs": "https://doi.org/10.1016/j.cj.2022.09.003",
                        "data_confidence": "high",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp_cfg.knowledge.crop_kg_json = str(kg_json)

    rag_sources = tmp_path / "rag_sources"
    rag_sources.mkdir()
    (rag_sources / "caps_preflight.md").write_text(
        "# CAPS preflight\n\nSi5G404900C CAPS marker requires local validation in recurrent parents.\n",
        encoding="utf-8",
    )
    rag_index = tmp_path / "evidence_index.json"
    save_evidence_index(build_evidence_index(rag_sources), rag_index)
    tmp_cfg.knowledge.rag_sources_dir = str(rag_sources)
    tmp_cfg.knowledge.rag_index_json = str(rag_index)

    marker_qtl_csv = tmp_path / "marker_qtl.csv"
    _write_marker_qtl_csv(marker_qtl_csv)
    tmp_cfg.knowledge.marker_qtl_csv = str(marker_qtl_csv)

    protocol_csv = tmp_path / "phenotype_protocol.csv"
    _write_phenotype_protocol_csv(protocol_csv)
    tmp_cfg.knowledge.phenotype_protocol_csv = str(protocol_csv)

    field_trial_csv = tmp_path / "field_trial.csv"
    _write_field_trial_csv(field_trial_csv)
    tmp_cfg.knowledge.field_trial_csv = str(field_trial_csv)

    now = datetime.now(UTC)
    session = Session(
        id="ses_test_evidence",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance under dense planting, prioritize CAPS marker validation",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance under dense planting",
            constraints=["local germplasm only"],
            idea_attributes=["CAPS marker", "lodging resistance"],
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)

    agent = EvidenceCuratorAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    task = Task(
        id="tsk_test_evidence",
        session_id=session.id,
        created_at=now,
        agent="evidence_curator",
        action="CurateEvidencePackage",
        payload={"mode": "bfrs", "n_initial": 2},
        status="pending",
    )

    result = await agent.execute(task)

    assert result.kind == "evidence_curated"
    assert result.extra["n_initial"] == 2
    package = await read_json(tmp_cfg, result.extra["evidence_package_path"])
    graph = await read_json(tmp_cfg, result.extra["breeding_evidence_graph_path"])
    assert package["local_germplasm"]["results"][0]["accession_id"] == "ARCH-263A"
    assert package["local_crop_kg"]["results"]
    assert package["local_crop_kg"]["results"]
    assert package["local_rag"]["results"]
    assert package["local_marker_qtl"]["results"][0]["marker_id"] == "MQTL-LODGE-001"
    assert package["local_phenotype_protocols"]["results"][0]["protocol_id"] == "PHENO-LODGE-001"
    assert package["local_field_trials"]["results"][0]["trial_id"] == "TRIAL-LODGE-001"
    assert package["evidence_gaps"]
    gap_types = {gap["type"] for gap in package["evidence_gaps"]}
    assert "marker_assay_preflight" in gap_types
    assert "pending_local_field_validation" in gap_types
    assert package["breeding_evidence_graph_delta"]["nodes"]
    assert package["breeding_evidence_graph_delta"]["edges"]
    assert package["breeding_evidence_graph_path"] == result.extra["breeding_evidence_graph_path"]
    assert graph["node_count"] >= len(package["breeding_evidence_graph_delta"]["nodes"])
    assert graph["edge_count"] >= len(package["breeding_evidence_graph_delta"]["edges"])
    assert any("tsk_test_evidence" in node["source_task_ids"] for node in graph["nodes"])
    graph_node_types = {node["type"] for node in graph["nodes"]}
    assert {"marker_qtl", "phenotype_protocol", "field_trial"} <= graph_node_types

    second_task = task.model_copy(
        update={
            "id": "tsk_test_evidence_second",
            "payload": {"mode": "dfrs", "focus": "Si5G404900C", "n_initial": 1},
        }
    )
    second_result = await agent.execute(second_task)
    second_graph = await read_json(tmp_cfg, second_result.extra["breeding_evidence_graph_path"])
    assert second_result.extra["breeding_evidence_graph_path"] == result.extra["breeding_evidence_graph_path"]
    assert second_graph["node_count"] >= graph["node_count"]
    assert any(
        "tsk_test_evidence_second" in node["source_task_ids"]
        for node in second_graph["nodes"]
    )

    record: dict[str, object] = {}
    await _attach_evidence_provenance(tmp_cfg, record, result.extra["evidence_package_path"])
    assert record["evidence_package_path"] == result.extra["evidence_package_path"]
    assert record["breeding_evidence_graph_path"] == result.extra["breeding_evidence_graph_path"]
    assert record["evidence_package_counts"]["gaps"] >= 1  # type: ignore[index]
    assert "material_availability" in record["evidence_gap_types"]


def test_evidence_curator_queries_use_goal_interpreter_boundaries() -> None:
    plan = ResearchPlan(
        objective="Improve lodging resistance",
        crop="foxtail millet",
        target_traits=["lodging resistance", "stem strength"],
        target_environments=["dense planting"],
        material_constraints=["local germplasm only"],
        preferred_breeding_strategies=["MAS"],
        validation_constraints=["CAPS marker preflight"],
        success_criteria=["lower lodging without yield penalty"],
    )

    queries = _derive_queries("goal text", plan, focus="Si5G404900C")

    assert _crop_hint(plan) == "foxtail millet"
    joined = " ".join(queries)
    assert "foxtail millet" in joined
    assert "lodging resistance" in joined
    assert "dense planting" in joined
    assert "local germplasm only" in joined
    assert "CAPS marker preflight" in joined

    zh_plan = ResearchPlan(
        objective="Improve foxtail millet lodging resistance under dense planting",
        crop="foxtail millet",
        target_traits=["lodging resistance", "stem strength"],
        target_environments=["dense planting"],
    )
    zh_queries = _derive_queries("foxtail millet lodging resistance breeding", zh_plan)
    zh_joined = " ".join(zh_queries)

    assert _crop_hint(zh_plan) == "foxtail millet"
    assert "foxtail millet lodging resistance dense planting" in zh_joined
    assert "phenotype protocol field trial" in zh_joined


def test_rag_crop_scope_isolated_across_source_chunks(tmp_path: Path) -> None:
    sources = tmp_path / "rag"
    sources.mkdir()
    (sources / "foxtail_note.md").write_text(
        "# Mixed reference\n\n- Crop/species: foxtail millet (Setaria italica)\n"
        "- Comparison note mentions rice, but this card is for foxtail millet.\n",
        encoding="utf-8",
    )
    (sources / "rice_note.md").write_text(
        "# Mixed reference\n\n- Crop/species: rice (Oryza sativa)\n"
        "- Comparison note mentions foxtail millet, but this card is for rice.\n",
        encoding="utf-8",
    )

    index_path = tmp_path / "evidence_index.json"
    save_evidence_index(build_evidence_index(sources, chunk_chars=80), index_path)
    index = load_evidence_index(index_path)

    scopes_by_source = {
        source: {chunk.crop_scope for chunk in index.chunks if chunk.source_path == source}
        for source in {chunk.source_path for chunk in index.chunks}
    }
    assert scopes_by_source["foxtail_note.md"] == {"foxtail millet"}
    assert scopes_by_source["rice_note.md"] == {"rice"}
    assert all(
        _chunk_matches_crop(chunk, "foxtail millet") == (chunk.source_path == "foxtail_note.md")
        for chunk in index.chunks
    )
    assert all(
        _chunk_matches_crop(chunk, "rice") == (chunk.source_path == "rice_note.md")
        for chunk in index.chunks
    )


def test_rag_crop_filter_runs_before_mixed_index_top_k(tmp_path: Path, tmp_cfg) -> None:
    sources = tmp_path / "rag"
    sources.mkdir()
    for index in range(9):
        (sources / f"foxtail_{index}.md").write_text(
            "# Foxtail reference\n\n- Crop/species: foxtail millet\n"
            "- rice submergence comparison keyword\n",
            encoding="utf-8",
        )
    (sources / "z_rice.md").write_text(
        "# Rice reference\n\n- Crop/species: rice (Oryza sativa)\n"
        "- rice submergence recovery evidence\n",
        encoding="utf-8",
    )

    index_path = tmp_path / "evidence_index.json"
    save_evidence_index(build_evidence_index(sources), index_path)
    tmp_cfg.knowledge.rag_sources_dir = str(sources)
    tmp_cfg.knowledge.rag_index_json = str(index_path)

    result = _curate_rag(
        tmp_cfg,
        ["rice submergence"],
        crop_hint="rice",
        target_scope="rice submergence",
    )

    assert result["results"]
    assert {item["crop_scope"] for item in result["results"]} == {"rice"}
    assert {item["source_path"] for item in result["results"]} == {"z_rice.md"}


def test_evidence_curator_target_scope_excludes_unrelated_material_route() -> None:
    target_scope = (
        "Improve foxtail millet stay-green and grain yield stability under drought stress."
    )
    assert "drought" in _target_anchor_terms(target_scope)
    assert "stay-green" in _target_anchor_terms(target_scope)

    flood_scope = "Improve rice submergence tolerance and post-flood recovery."
    assert "submergence" in _target_anchor_terms(flood_scope)
    assert "recovery" in _target_anchor_terms(flood_scope)

    drought_parent = {
        "accession_id": "FPS2025-148",
        "primary_traits": "yield components; grain traits",
        "breeding_use": "parent selection; phenotypic validation candidate",
        "known_genes_qtls": "",
        "markers": "",
    }
    lodging_benchmark = {
        "accession_id": "ARCH-Jingu21",
        "primary_traits": "lodging resistance; stem strength",
        "breeding_use": "cultivar management benchmark; lodging check material",
        "known_genes_qtls": "",
        "markers": "",
    }

    assert _record_matches_target_scope(drought_parent, target_scope)
    assert not _record_matches_target_scope(lodging_benchmark, target_scope)


def test_evidence_graph_only_links_materials_from_filtered_germplasm() -> None:
    graph = _build_graph_delta(
        {
            "results": [
                {
                    "accession_id": "ARCH-263A",
                    "name": "263A",
                    "data_confidence": "medium",
                }
            ]
        },
        {"results": []},
        {"results": []},
        {
            "results": [
                {
                    "marker_id": "MQTL-LODGE-001",
                    "marker_name": "Si5G404900C CAPS",
                    "linked_materials": "263A; Jingu21; Zhangza13",
                    "data_confidence": "medium",
                }
            ]
        },
        {"results": []},
        {
            "results": [
                {
                    "trial_id": "TRIAL-LODGE-001",
                    "materials": "263A; Jingu21; candidate local recurrent parents",
                    "data_confidence": "medium",
                }
            ]
        },
    )

    node_ids = {node["id"] for node in graph["nodes"]}
    edge_materials = {
        endpoint
        for edge in graph["edges"]
        for endpoint in (edge.get("source"), edge.get("target"))
        if isinstance(endpoint, str) and endpoint.startswith("material:")
    }
    assert "material:ARCH-263A" in node_ids
    assert "material:Jingu21" not in node_ids
    assert "material:Zhangza13" not in node_ids
    assert edge_materials == {"material:ARCH-263A"}


def test_supervisor_resolves_initial_count_from_goal_interpreter_boundaries() -> None:
    assert (
        _resolve_initial_hypothesis_count(
            ResearchPlan(
                objective="o",
                initial_hypothesis_count=2,
                max_hypothesis_count=5,
            ),
            requested=3,
            run_max=60,
        )
        == 2
    )
    assert (
        _hypothesis_count_limit(
            ResearchPlan(objective="o", max_hypothesis_count=4),
            run_max=60,
        )
        == 4
    )
    assert (
        _hypothesis_count_limit(
            ResearchPlan(objective="o", max_hypothesis_count=40),
            run_max=6,
        )
        == 6
    )
    assert (
        _resolve_initial_hypothesis_count(
            ResearchPlan(
                objective="o",
                initial_hypothesis_count=8,
                max_hypothesis_count=4,
            ),
            requested=3,
            run_max=60,
        )
        == 4
    )
    assert (
        _resolve_initial_hypothesis_count(
            ResearchPlan(objective="o"),
            requested=3,
            run_max=2,
        )
        == 2
    )


def test_explicit_initial_count_overrides_goal_interpreter_cap() -> None:
    plan = ResearchPlan(
        objective="o",
        initial_hypothesis_count=1,
        max_hypothesis_count=1,
    )

    overridden = _apply_explicit_hypothesis_bounds(plan, requested_initial=2)

    assert overridden.initial_hypothesis_count == 2
    assert overridden.max_hypothesis_count == 2


def test_explicit_max_hypotheses_clamps_parsed_initial_count() -> None:
    plan = ResearchPlan(
        objective="o",
        initial_hypothesis_count=4,
        max_hypothesis_count=8,
    )

    overridden = _apply_explicit_hypothesis_bounds(plan, requested_max=2)

    assert overridden.initial_hypothesis_count == 2
    assert overridden.max_hypothesis_count == 2


def test_missing_explicit_hypothesis_bounds_preserve_parsed_plan() -> None:
    plan = ResearchPlan(
        objective="o",
        initial_hypothesis_count=1,
        max_hypothesis_count=1,
    )

    assert _apply_explicit_hypothesis_bounds(plan) == plan


async def test_supervisor_routes_bfrs_and_dfrs_evidence_followups(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_evidence_followups",
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

    supervisor = Supervisor(tmp_cfg)
    bfrs_task = Task(
        id="tsk_bfrs_followup",
        session_id=session.id,
        created_at=now,
        agent="evidence_curator",
        action="CurateEvidencePackage",
        payload={"mode": "bfrs", "n_initial": 2},
        status="pending",
    )
    await supervisor._apply_follow_ups(
        conn,
        session,
        bfrs_task,
        TaskResult(
            kind="evidence_curated",
            extra={
                "evidence_package_path": "artifacts/ses_test_evidence_followups/evidence/package.json",
                "n_initial": 2,
                "enqueue_design": True,
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    design_rows = [row for row in rows if row["agent"] == "breeding_designer"]
    assert len(design_rows) == 2
    assert all(
        row["payload"]["evidence_package_path"]
        == "artifacts/ses_test_evidence_followups/evidence/package.json"
        for row in design_rows
    )

    dfrs_task = bfrs_task.model_copy(
        update={
            "id": "tsk_dfrs_followup",
            "payload": {"mode": "dfrs", "enqueue_design": False},
            "target_id": "hyp_reviewed",
        }
    )
    await supervisor._apply_follow_ups(
        conn,
        session,
        dfrs_task,
        TaskResult(
            kind="evidence_curated",
            hypothesis_ids=["hyp_reviewed"],
            extra={
                "enqueue_design": False,
                "mode": "dfrs",
                "target_hypothesis_id": "hyp_reviewed",
                "evidence_package_path": "artifacts/ses_test_evidence_followups/evidence/package.json",
            },
        ),
    )
    rows = await _task_rows(conn, session.id)
    assert len([row for row in rows if row["agent"] == "breeding_designer"]) == 2
    assert any(
        row["agent"] == "validation_planner"
        and row["payload"].get("source") == "dfrs_evidence_completed"
        for row in rows
    )

    hypothesis = Hypothesis(
        id="hyp_reviewed",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="CAPS-assisted lodging hypothesis",
        summary="Use a CAPS marker clue to prioritize local lodging-resistance validation.",
        full_text="Si5G404900C CAPS marker should be validated in recurrent parents.",
        artifact_path="artifacts/ses_test_evidence_followups/hypotheses/hyp_reviewed.json",
    )
    await hyp_repo.insert(conn, hypothesis)
    review_task = Task(
        id="tsk_review_followup",
        session_id=session.id,
        created_at=now,
        agent="iteration_orchestrator",
        action="AssessHypothesisEvidence",
        target_id=hypothesis.id,
        payload={"kind": "full"},
        status="pending",
    )
    await supervisor._apply_follow_ups(
        conn,
        session,
        review_task,
        TaskResult(
            kind="evidence_review_completed",
            hypothesis_ids=[hypothesis.id],
            extra={
                "evidence_package_path": (
                    "artifacts/ses_test_evidence_followups/evidence/package_review.json"
                ),
                "breeding_evidence_graph_path": (
                    "artifacts/ses_test_evidence_followups/evidence/graph.json"
                ),
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    validation_rows = [
        row
        for row in rows
        if row["agent"] == "validation_planner" and row["target_id"] == hypothesis.id
        and row["payload"].get("source") == "evidence_review_completed"
    ]
    pairwise_rows = [
        row
        for row in rows
        if row["agent"] == "iteration_orchestrator"
        and row["action"] == "QueuePairwiseCalibration"
        and row["target_id"] == hypothesis.id
    ]
    assert len(validation_rows) == 1
    assert validation_rows[0]["action"] == "PlanValidation"


    assert validation_rows[0]["payload"]["evidence_package_path"].endswith(
        "package_review.json"
    )
    assert validation_rows[0]["payload"]["breeding_evidence_graph_path"].endswith(
        "graph.json"
    )
    assert not pairwise_rows

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_validation_followup",
            session_id=session.id,
            created_at=now,
            agent="validation_planner",
            action="PlanValidation",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="validation_planned",
            hypothesis_ids=[hypothesis.id],
            extra={
                "validation_plan_path": (
                    "artifacts/ses_test_evidence_followups/validation/plan.json"
                )
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    dfrs_rows = [
        row
        for row in rows
        if row["agent"] == "evidence_curator" and row["target_id"] == hypothesis.id
    ]
    assert len(dfrs_rows) == 1
    assert dfrs_rows[0]["payload"]["mode"] == "dfrs"
    assert dfrs_rows[0]["payload"]["enqueue_design"] is False
    assert dfrs_rows[0]["payload"]["validation_plan_path"].endswith("plan.json")

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_dfrs_after_validation",
            session_id=session.id,
            created_at=now,
            agent="evidence_curator",
            action="CurateEvidencePackage",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="evidence_curated",
            hypothesis_ids=[hypothesis.id],
            extra={
                "enqueue_design": False,
                "mode": "dfrs",
                "target_hypothesis_id": hypothesis.id,
                "evidence_package_path": (
                    "artifacts/ses_test_evidence_followups/evidence/package.json"
                ),
                "breeding_evidence_graph_path": (
                    "artifacts/ses_test_evidence_followups/evidence/breeding_evidence_graph.json"
                ),
                "validation_plan_path": (
                    "artifacts/ses_test_evidence_followups/validation/plan.json"
                ),
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    dfrs_validation_rows = [
            row
            for row in rows
            if row["agent"] == "validation_planner"
            and row["target_id"] == hypothesis.id
            and row["payload"].get("source") == "dfrs_evidence_completed"
            and str(row["payload"].get("validation_plan_path", "")).endswith("plan.json")
        ]
    assert len(dfrs_validation_rows) == 1
    assert dfrs_validation_rows[0]["action"] == "PlanValidation"
    assert dfrs_validation_rows[0]["payload"]["evidence_package_path"].endswith(
        "package.json"
    )

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_dfrs_validation_followup",
            session_id=session.id,
            created_at=now,
            agent="validation_planner",
            action="PlanValidation",
            target_id=hypothesis.id,
            payload={"source": "dfrs_evidence_completed"},
            status="pending",
        ),
        TaskResult(
            kind="validation_planned",
            hypothesis_ids=[hypothesis.id],
            extra={
                "source": "dfrs_evidence_completed",
                "validation_plan_path": (
                    "artifacts/ses_test_evidence_followups/validation/plan_dfrs.json"
                ),
                "evidence_package_path": (
                    "artifacts/ses_test_evidence_followups/evidence/package.json"
                ),
                "breeding_evidence_graph_path": (
                    "artifacts/ses_test_evidence_followups/evidence/breeding_evidence_graph.json"
                ),
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    risk_rows = [
        row
        for row in rows
        if row["agent"] == "risk_reviewer"
        and row["target_id"] == hypothesis.id
        and str(row["payload"].get("validation_plan_path", "")).endswith("plan_dfrs.json")
    ]
    assert len(risk_rows) == 1
    assert risk_rows[0]["action"] == "ReviewRisk"

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_risk_followup",
            session_id=session.id,
            created_at=now,
            agent="risk_reviewer",
            action="ReviewRisk",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="risk_reviewed",
            hypothesis_ids=[hypothesis.id],
            extra={
                "evidence_package_path": (
                    "artifacts/ses_test_evidence_followups/evidence/package.json"
                ),
                "breeding_evidence_graph_path": (
                    "artifacts/ses_test_evidence_followups/evidence/breeding_evidence_graph.json"
                ),
                "validation_plan_path": (
                    "artifacts/ses_test_evidence_followups/validation/plan.json"
                ),
                "risk_review_path": "artifacts/ses_test_evidence_followups/risk/review.json",
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    iteration_rows = [
        row
        for row in rows
        if row["agent"] == "iteration_orchestrator"
        and row["target_id"] == hypothesis.id
        and str(row["payload"].get("risk_review_path", "")).endswith("review.json")
    ]
    assert len(iteration_rows) == 1
    assert iteration_rows[0]["payload"]["validation_plan_path"].endswith("plan.json")

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_iteration_keep",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="iteration_decision",
            hypothesis_ids=[hypothesis.id],
            extra={"action": "keep"},
        ),
    )
    rows = await _task_rows(conn, session.id)
    pairwise_rows = [
        row
        for row in rows
        if row["agent"] == "iteration_orchestrator"
        and row["action"] == "QueuePairwiseCalibration"
        and row["target_id"] == hypothesis.id
    ]
    assert len(pairwise_rows) == 1
    assert pairwise_rows[0]["action"] == "QueuePairwiseCalibration"

    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_iteration_revise",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="iteration_decision",
            hypothesis_ids=[hypothesis.id],
            extra={
                "action": "revise",
                "evidence_package_path": "artifacts/ses_test_evidence_followups/evidence/package.json",
                "decision_path": "artifacts/ses_test_evidence_followups/iteration/decision.json",
                "validation_plan_path": "artifacts/ses_test_evidence_followups/validation/plan.json",
                "risk_review_path": "artifacts/ses_test_evidence_followups/risk/review.json",
                "route_revision_intent": {
                    "route_revision_intent": "repair_parent_route",
                    "new_hypothesis_direction": "Resolve local marker validation gap.",
                    "evidence_gap_to_resolve": ["marker needs local validation"],
                    "do_not_repeat": ["Do not restate marker claims without validation."],
                },
                "evidence_gap_to_resolve": ["marker needs local validation"],
                "new_hypothesis_direction": "Resolve local marker validation gap.",
                "parent_hypothesis_id": hypothesis.id,
                "do_not_repeat": ["Do not restate marker claims without validation."],
            },
        ),
    )
    rows = await _task_rows(conn, session.id)
    iteration_design = [
        row
        for row in rows
        if row["agent"] == "breeding_designer"
        and row["target_id"] == hypothesis.id
        and row["payload"].get("iteration_action") == "revise"
    ]
    assert len(iteration_design) == 1
    assert iteration_design[0]["payload"]["iteration_decision_path"].endswith("decision.json")
    assert iteration_design[0]["payload"]["validation_plan_path"].endswith("plan.json")
    assert iteration_design[0]["payload"]["risk_review_path"].endswith("review.json")
    assert (
        iteration_design[0]["payload"]["route_revision_intent"][
            "route_revision_intent"
        ]
        == "repair_parent_route"
    )
    assert "route_revision_intent" in iteration_design[0]["payload"]
    assert iteration_design[0]["payload"]["new_hypothesis_direction"].startswith("Resolve")
    assert iteration_design[0]["payload"]["do_not_repeat"]


async def test_supervisor_requeues_route_admission_states_idempotently(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_route_admission_queue",
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

    def make_hypothesis(hid: str, *, score: float | None, plays: int) -> Hypothesis:
        return Hypothesis(
            id=hid,
            session_id=session.id,
            created_at=now,
            created_by="breeding_designer",
            strategy="literature",
            title=hid,
            summary="",
            full_text="",
            artifact_path=f"artifacts/{session.id}/hypotheses/{hid}.json",
            calibration_score=score,
            pairwise_calibrations_played=plays,
            state="calibration_pool" if score is not None else "reviewed",
        )

    await hyp_repo.insert(conn, make_hypothesis("hyp_needs_review", score=None, plays=0))
    await hyp_repo.insert(conn, make_hypothesis("hyp_needs_pairwise", score=1200, plays=0))
    await hyp_repo.insert(conn, make_hypothesis("hyp_needs_evidence", score=1240, plays=3))
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_pairwise",
        {
            "created_at": "2026-08-05T10:00:00+00:00",
            "hypothesis_id": "hyp_needs_pairwise",
            "action": "keep",
            "review_gate": "pass",
        },
    )
    await write_json(
        tmp_cfg,
        session.id,
        "iteration",
        "decision_evidence",
        {
            "created_at": "2026-08-05T11:00:00+00:00",
            "hypothesis_id": "hyp_needs_evidence",
            "action": "revise",
            "review_gate": "mixed",
            "reason": "marker validation gap",
            "reasons": ["Marker validation gap remains."],
            "evidence_gap_to_resolve": ["local marker validation"],
        },
    )

    supervisor = Supervisor(tmp_cfg)
    assert await supervisor._schedule_route_admission_followups(conn, session) == 3

    rows = await _task_rows(conn, session.id)
    assert {row["action"] for row in rows} == {
        "AssessHypothesisEvidence",
        "QueuePairwiseCalibration",
        "CurateEvidencePackage",
    }
    assert await supervisor._schedule_route_admission_followups(conn, session) == 0


async def test_supervisor_does_not_expand_past_max_hypothesis_count(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_max_hypotheses",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            max_hypothesis_count=1,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    hypothesis = Hypothesis(
        id="hyp_at_limit",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="At limit",
        summary="Already reaches max hypothesis count.",
        full_text="# At limit",
        artifact_path="artifacts/ses_test_max_hypotheses/hypotheses/hyp_at_limit.json",
    )
    await hyp_repo.insert(conn, hypothesis)

    supervisor = Supervisor(tmp_cfg)
    await supervisor._apply_follow_ups(
        conn,
        session,
        Task(
            id="tsk_iteration_revise_at_limit",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        ),
        TaskResult(
            kind="iteration_decision",
            hypothesis_ids=[hypothesis.id],
            extra={
                "action": "revise",
                "evidence_package_path": "artifacts/ses_test_max_hypotheses/evidence/package.json",
                "decision_path": "artifacts/ses_test_max_hypotheses/iteration/decision.json",
            },
        ),
    )

    rows = await _task_rows(conn, session.id)
    design_rows = [row for row in rows if row["agent"] == "breeding_designer"]
    assert design_rows == []
    events = await events_repo.recent(conn, session.id, limit=10)
    skipped = [
        event
        for event in events
        if event["event"] == "hypothesis_design_skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0]["payload"]["reason"] == "max_hypothesis_count_reached"
    assert skipped[0]["payload"]["current_count"] == 1
    assert skipped[0]["payload"]["limit"] == 1
    assert skipped[0]["payload"]["action"] == "revise"
    assert skipped[0]["payload"]["hypothesis_id"] == hypothesis.id


async def test_supervisor_counts_pending_design_slots_toward_max_hypothesis_count(
    tmp_cfg, conn
) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_reserved_hypothesis_slot",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance",
        research_plan=ResearchPlan(
            objective="Improve foxtail millet lodging resistance",
            max_hypothesis_count=3,
        ),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    for hid in ("hyp_existing_a", "hyp_existing_b"):
        await hyp_repo.insert(
            conn,
            Hypothesis(
                id=hid,
                session_id=session.id,
                created_at=now,
                created_by="breeding_designer",
                strategy="literature",
                title=hid,
                summary="Existing route.",
                full_text="# Existing route",
                artifact_path=f"artifacts/{session.id}/hypotheses/{hid}.json",
            ),
        )
    await task_repo.enqueue(
        conn,
        Task(
            id="tsk_reserved_design_slot",
            session_id=session.id,
            created_at=now,
            agent="breeding_designer",
            action="DesignHypothesis",
            payload={"strategy": "literature", "n": 1},
            priority=100,
            status="pending",
            idempotency_key="reserved-design-slot",
        ),
    )

    gate = await _hypothesis_design_gate(conn, session, run_max=60)

    assert gate == {"can_enqueue": False, "current_count": 3, "limit": 3}


async def test_iteration_orchestrator_decides_from_review_and_dfrs_package(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_iteration",
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
    hypothesis = Hypothesis(
        id="hyp_iteration",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Marker-assisted lodging route",
        summary="Validate a CAPS marker route for lodging resistance.",
        full_text="Marker route needs local validation.",
        artifact_path="artifacts/ses_test_iteration/hypotheses/hyp_iteration.json",
    )
    await hyp_repo.insert(conn, hypothesis)
    await rev_repo.insert(
        conn,
        Review(
            id="rev_iteration",
            hypothesis_id=hypothesis.id,
            session_id=session.id,
            created_at=now,
            kind="full",
            verdict="missing_piece",
            scores=ReviewScores(novelty=0.7, correctness=0.55, testability=0.8, feasibility=0.45),
            body="Needs marker validation.",
            artifact_path="artifacts/ses_test_iteration/reviews/rev_iteration.json",
        ),
    )
    package_path = await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_iteration",
        {
            "mode": "dfrs",
            "local_germplasm": {"results": [{"accession_id": "ARCH-263A"}]},
            "local_crop_kg": {"results": [{"id": "marker:Si5G404900C"}]},
            "local_rag": {"results": []},
            "evidence_gaps": [
                {
                    "type": "genotype_or_marker_validation",
                    "severity": "high",
                    "target": "ARCH-263A",
                    "message": "Marker claims need local genotype evidence.",
                }
            ],
        },
    )
    validation_plan_path = await write_json(
        tmp_cfg,
        session.id,
        "validation",
        "plan_iteration",
        {
            "validation_readiness_score": 88.0,
            "readiness_level": "ready",
            "critical_evidence_gaps": [],
        },
    )
    risk_review_path = await write_json(
        tmp_cfg,
        session.id,
        "risk",
        "review_iteration",
        {
            "risk_control_score": 82.0,
            "risk_level": "controlled",
            "risk_items": [
                {
                    "category": "genetic",
                    "severity": "medium",
                    "message": "Marker transferability requires preflight.",
                }
            ],
        },
    )

    agent = IterationOrchestratorAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    result = await agent.execute(
        Task(
            id="tsk_iteration_decide",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={"evidence_package_path": package_path},
            status="pending",
        )
    )

    assert result.kind == "iteration_decision"
    assert result.extra["action"] == "revise"
    decision = await read_json(tmp_cfg, result.extra["decision_path"])
    assert decision["review_verdict"] == "missing_piece"
    assert decision["gap_counts"]["by_type"]["genotype_or_marker_validation"] == 1
    assert decision["scorecard"]
    assert decision["total_score"] == result.extra["total_score"]
    assert "keep" in decision["decision_thresholds"]
    assert decision["next_step_recommendation"] == "generate_revised_hypothesis_from_decision"
    assert decision["route_revision_intent"]["route_revision_intent"] == "repair_parent_route"
    assert "route_revision_intent" in decision
    assert decision["new_hypothesis_direction"].startswith("Revise the parent route")
    assert decision["evidence_gap_to_resolve"]
    assert decision["parent_hypothesis_id"] == hypothesis.id
    assert decision["do_not_repeat"]
    context = await _load_iteration_decision_context(tmp_cfg, result.extra["decision_path"])
    assert "## Scorecard" in context
    assert "validation_actionability" in context
    assert "## Successor route intent" in context
    assert "Evidence gaps to resolve" in context

    keep_result = await agent.execute(
        Task(
            id="tsk_iteration_decide_with_validation",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={
                "evidence_package_path": package_path,
                "validation_plan_path": validation_plan_path,
                "risk_review_path": risk_review_path,
            },
            status="pending",
        )
    )
    keep_decision = await read_json(tmp_cfg, keep_result.extra["decision_path"])
    assert keep_decision["validation_plan_path"] == validation_plan_path
    assert keep_decision["risk_review_path"] == risk_review_path
    scorecard = {
        row["dimension"]: row
        for row in keep_decision["scorecard"]
    }
    assert "Validation Planner readiness score" in scorecard["validation_actionability"]["rationale"]
    assert "Risk Reviewer" in scorecard["risk_control"]["rationale"]


def test_iteration_orchestrator_retains_strong_route_with_actionable_preflight_gap() -> None:
    review = Review(
        id="rev_preflight_route",
        hypothesis_id="hyp_preflight_route",
        session_id="ses_preflight_route",
        created_at=datetime.now(UTC),
        kind="verification",
        verdict="missing_piece",
        scores=ReviewScores(novelty=0.7, correctness=0.8, testability=0.8, feasibility=0.7),
        body="The route is plausible; validate the marker and material locally.",
        artifact_path="artifacts/ses_preflight_route/reviews/rev_preflight_route.json",
    )

    decision = _decide_iteration(
        hypothesis_id="hyp_preflight_route",
        review=review,
        package={
            "evidence_gaps": [
                {
                    "type": "marker_assay_preflight",
                    "severity": "high",
                    "message": "Validate marker polymorphism in the target parents.",
                }
            ]
        },
        validation_plan={
            "validation_readiness_score": 62.0,
            "critical_evidence_gaps": [],
        },
        risk_review={
            "risk_control_score": 65.0,
            "risk_items": [
                {"severity": "medium", "category": "genetic", "message": "Preflight needed."}
            ],
        },
    )

    assert decision["action"] == "keep"
    assert "preflight gap" in decision["reasons"][0]


def test_design_payload_route_revision_intent_context() -> None:
    context = _build_payload_route_revision_intent_context(
        {
            "parent_hypothesis_id": "hyp_parent",
            "iteration_action": "revise",
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
                "new_hypothesis_direction": "Resolve local marker validation gap.",
                "evidence_gap_to_resolve": ["marker needs local validation"],
                "do_not_repeat": ["Do not restate marker claims without validation."],
            },
        }
    )

    assert "# Required successor route intent" in context
    assert "hyp_parent" in context
    assert "repair_parent_route" in context
    assert "marker needs local validation" in context
    assert "Do not restate marker claims without validation." in context


def test_design_payload_route_revision_context_accepts_current_intent() -> None:
    context = _build_payload_route_revision_intent_context(
        {
            "parent_hypothesis_id": "hyp_parent",
            "iteration_action": "revise",
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
                "new_hypothesis_direction": "Resolve local marker validation gap.",
            },
        }
    )

    assert "repair_parent_route" in context
    assert "Resolve local marker validation gap." in context


def test_design_iteration_parentage_attaches_parent_ids() -> None:
    record = {"statement": "Validate a revised marker route."}

    _attach_iteration_parentage(
        record,
        {
            "parent_hypothesis_id": "hyp_parent",
            "iteration_action": "revise",
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
            },
            "new_hypothesis_direction": "Resolve local marker validation gap.",
            "evidence_gap_to_resolve": ["marker needs local validation"],
            "do_not_repeat": ["Do not repeat unsupported marker claims."],
        },
    )

    assert record["parent_ids"] == ["hyp_parent"]
    assert record["parent_hypothesis_id"] == "hyp_parent"
    assert record["new_hypothesis_direction"].startswith("Resolve")
    assert record["evidence_gap_to_resolve"]


async def test_iteration_orchestrator_penalizes_incomplete_design_card(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_design_audit_iteration",
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
    artifact_path = await write_json(
        tmp_cfg,
        session.id,
        "hypotheses",
        "hyp_design_audit",
        {
            "record": {
                "statement": "Use a marker-assisted lodging route.",
                "breeding_design_card_audit": {
                    "status": "needs_attention",
                    "completeness_score": 42.0,
                    "missing_fields": [
                        "donor_parent",
                        "recurrent_parent",
                        "candidate_genes_qtl",
                        "validation_trial_design",
                        "fallback_route",
                    ],
                    "missing_critical_fields": [
                        "donor_parent",
                        "recurrent_parent",
                        "candidate_genes_qtl",
                        "validation_trial_design",
                    ],
                },
            }
        },
    )
    hypothesis = Hypothesis(
        id="hyp_design_audit",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Incomplete marker-assisted route",
        summary="A route with incomplete breeding design card fields.",
        full_text="Needs design card completion.",
        artifact_path=artifact_path,
    )
    await hyp_repo.insert(conn, hypothesis)
    await rev_repo.insert(
        conn,
        Review(
            id="rev_design_audit",
            hypothesis_id=hypothesis.id,
            session_id=session.id,
            created_at=now,
            kind="full",
            verdict="neutral",
            scores=ReviewScores(novelty=0.8, correctness=0.8, testability=0.85, feasibility=0.8),
            body="Otherwise plausible.",
            artifact_path="artifacts/ses_test_design_audit_iteration/reviews/rev_design_audit.json",
        ),
    )
    package_path = await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_design_audit",
        {
            "local_germplasm": {"results": [{"accession_id": "ARCH-263A"}, {"accession_id": "R1"}]},
            "local_crop_kg": {"results": [{"id": "marker:Si5G404900C"}, {"id": "trait:lodging"}]},
            "local_rag": {"results": [{"url": "local-rag://note#L1-L3"}, {"url": "local-rag://note#L4-L6"}]},
            "evidence_gaps": [],
        },
    )
    validation_plan_path = await write_json(
        tmp_cfg,
        session.id,
        "validation",
        "plan_design_audit",
        {
            "validation_readiness_score": 90.0,
            "readiness_level": "ready",
            "critical_evidence_gaps": [],
        },
    )
    risk_review_path = await write_json(
        tmp_cfg,
        session.id,
        "risk",
        "review_design_audit",
        {
            "risk_control_score": 95.0,
            "risk_level": "controlled",
            "risk_items": [],
        },
    )

    agent = IterationOrchestratorAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    result = await agent.execute(
        Task(
            id="tsk_design_audit_iteration",
            session_id=session.id,
            created_at=now,
            agent="iteration_orchestrator",
            action="DecideIteration",
            target_id=hypothesis.id,
            payload={
                "evidence_package_path": package_path,
                "validation_plan_path": validation_plan_path,
                "risk_review_path": risk_review_path,
            },
            status="pending",
        )
    )

    decision = await read_json(tmp_cfg, result.extra["decision_path"])
    assert result.extra["action"] == "revise"
    assert decision["breeding_design_card_audit"]["penalty"] > 0
    assert "candidate_genes_qtl" in decision["breeding_design_card_audit"]["missing_critical_fields"]
    scorecard = {
        row["dimension"]: row
        for row in decision["scorecard"]
    }
    assert "Breeding design card incompleteness penalty" in scorecard["local_resource_readiness"]["rationale"]
    assert "Breeding design card incompleteness penalty" in scorecard["validation_actionability"]["rationale"]
    assert "Breeding design card incompleteness penalty" in scorecard["risk_control"]["rationale"]
    assert any("Breeding design card" in reason for reason in decision["reasons"])


async def test_validation_planner_writes_structured_plan(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_validation_planner",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance under dense planting",
        research_plan=ResearchPlan(objective="Improve foxtail millet lodging resistance"),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    artifact_path = await write_json(
        tmp_cfg,
        session.id,
        "hypotheses",
        "hyp_validation",
        {
            "record": {
                "breeding_context": {
                    "crop": "foxtail millet",
                    "target_trait": "lodging resistance",
                    "germplasm": "donor x elite line progeny",
                    "donor_parent": "ARCH-263A",
                    "recurrent_parent": "elite local parent",
                    "material_availability": "local seed inventory pending",
                    "target_population_of_environments": "dense planting nursery",
                    "candidate_genes_qtl": ["Seita.5G404900", "Si5G404900C CAPS"],
                    "phenotyping_plan": "stem strength and lodging score under dense planting",
                    "genotyping_plan": "CAPS marker preflight in parents and progeny",
                    "validation_trial_design": "small dense-planting RCBD trial",
                    "decision_thresholds": "advance if lodging score improves without yield penalty",
                    "cycle_time_estimate": "one marker preflight plus one field season",
                    "risks_tradeoffs": ["marker transferability", "yield penalty"],
                    "evidence_gaps": ["CAPS marker needs local validation"],
                }
            }
        },
    )
    hypothesis = Hypothesis(
        id="hyp_validation",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="CAPS-assisted lodging route",
        summary="Validate marker-assisted lodging resistance.",
        full_text="Si5G404900C CAPS marker route requires local validation.",
        artifact_path=artifact_path,
    )
    await hyp_repo.insert(conn, hypothesis)
    await rev_repo.insert(
        conn,
        Review(
            id="rev_validation",
            hypothesis_id=hypothesis.id,
            session_id=session.id,
            created_at=now,
            kind="full",
            verdict="neutral",
            scores=ReviewScores(novelty=0.7, correctness=0.65, testability=0.85, feasibility=0.7),
            body="Testable with marker preflight and field validation.",
            artifact_path="artifacts/ses_test_validation_planner/reviews/rev_validation.json",
        ),
    )

    agent = ValidationPlannerAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    result = await agent.execute(
        Task(
            id="tsk_validation_plan",
            session_id=session.id,
            created_at=now,
            agent="validation_planner",
            action="PlanValidation",
            target_id=hypothesis.id,
            payload={},
            status="pending",
        )
    )

    assert result.kind == "validation_planned"
    plan = await read_json(tmp_cfg, result.extra["validation_plan_path"])
    assert plan["hypothesis_id"] == hypothesis.id
    assert plan["breeding_goal"]["crop"] == "foxtail millet"
    assert plan["materials_plan"]["required_materials"][0] == "ARCH-263A"
    assert plan["genotyping_plan"]["targets"]
    assert plan["field_trial_design"]["decision_thresholds"]
    assert plan["validation_readiness_score"] == result.extra["validation_readiness_score"]
    assert plan["critical_evidence_gaps"]


def test_validation_planner_enriches_missing_context_from_evidence_package() -> None:
    package = {
        "local_germplasm": {
            "results": [
                {
                    "accession_id": "RICE-FR13A",
                    "name": "FR13A",
                    "availability": "unknown",
                }
            ]
        },
        "local_marker_qtl": {
            "results": [
                {
                    "gene_or_qtl": "Sub1A-1",
                    "marker_name": "Sub1A functional assay",
                    "marker_type": "functional assay",
                    "assay_protocol": "confirm the functional allele in both parents",
                    "validation_status": "needs_local_parent_preflight",
                }
            ]
        },
        "local_phenotype_protocols": {
            "results": [
                {
                    "validation_status": "local_protocol_ready",
                    "measurement_method": "survival and recovery score",
                    "scale_or_unit": "percentage",
                    "stage": "after controlled submergence",
                    "replication": "three replicates",
                    "decision_thresholds": "advance if recovery improves without yield penalty",
                }
            ]
        },
        "local_field_trials": {
            "results": [
                {
                    "environment": "flood-prone lowland nursery",
                    "test_design": "RCBD with flooded and non-flooded checks",
                    "materials": "FR13A and local recurrent parent",
                    "phenotype_summary": "record survival, recovery, fertility, and yield",
                    "decision_outcome": "pending_local_validation",
                }
            ]
        },
        "local_crop_kg": {"results": []},
        "local_rag": {"results": []},
    }
    context = _enrich_breeding_context(
        {
            "crop": "rice",
            "target_trait": "submergence tolerance",
            "material_availability": "unknown",
            "candidate_genes_qtl": [],
            "phenotyping_plan": "unknown",
            "genotyping_plan": "unknown",
            "validation_trial_design": "unknown",
        },
        package,
    )
    plan = _build_validation_plan(
        session_id="ses_test_package_context",
        task_id="tsk_test_package_context",
        hypothesis_id="hyp_test_package_context",
        hypothesis_title="Sub1A preflight route",
        research_goal="Improve rice flood recovery",
        breeding_context=context,
        hypothesis_text="Validate the route locally.",
        review=None,
        evidence_package_path="artifacts/evidence/package.json",
        evidence_package=package,
    )

    assert context["candidate_genes_qtl"] == ["Sub1A-1", "Sub1A functional assay"]
    assert "survival and recovery score" in plan["phenotyping_plan"]["protocol"]
    assert "FR13A" in plan["field_trial_design"]["population"]
    assert "RCBD" in plan["field_trial_design"]["design"]
    assert plan["evidence_basis"]["marker_qtl_hits"] == 1
    assert plan["validation_readiness_score"] > 45


async def test_risk_reviewer_writes_structured_risk_package(tmp_cfg, conn) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_test_risk_reviewer",
        created_at=now,
        updated_at=now,
        status="running",
        research_goal="Improve foxtail millet lodging resistance under dense planting",
        research_plan=ResearchPlan(objective="Improve foxtail millet lodging resistance"),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    await sess_repo.insert(conn, session)
    artifact_path = await write_json(
        tmp_cfg,
        session.id,
        "hypotheses",
        "hyp_risk",
        {
            "record": {
                "breeding_context": {
                    "crop": "foxtail millet",
                    "target_trait": "lodging resistance",
                    "donor_parent": "ARCH-263A",
                    "recurrent_parent": "elite local parent",
                    "material_availability": "local seed inventory pending",
                    "candidate_genes_qtl": ["Si5G404900C CAPS"],
                    "risks_tradeoffs": ["marker transferability", "yield penalty"],
                    "evidence_gaps": ["CAPS marker needs local validation"],
                }
            }
        },
    )
    hypothesis = Hypothesis(
        id="hyp_risk",
        session_id=session.id,
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="CAPS-assisted lodging route",
        summary="Validate marker-assisted lodging resistance.",
        full_text="Marker transferability and yield penalty need review.",
        artifact_path=artifact_path,
    )
    await hyp_repo.insert(conn, hypothesis)
    await rev_repo.insert(
        conn,
        Review(
            id="rev_risk",
            hypothesis_id=hypothesis.id,
            session_id=session.id,
            created_at=now,
            kind="full",
            verdict="missing_piece",
            scores=ReviewScores(novelty=0.7, correctness=0.6, testability=0.8, feasibility=0.4),
            body="Feasibility needs stronger material and marker confirmation.",
            artifact_path="artifacts/ses_test_risk_reviewer/reviews/rev_risk.json",
        ),
    )
    validation_plan_path = await write_json(
        tmp_cfg,
        session.id,
        "validation",
        "plan_risk",
        {
            "risk_controls": [
                {
                    "risk": "marker transferability",
                    "control": "run CAPS polymorphism in parents and progeny",
                }
            ],
            "critical_evidence_gaps": [
                {
                    "type": "genotype_or_marker_validation",
                    "severity": "high",
                    "message": "Marker claims need local genotype evidence.",
                }
            ],
        },
    )
    evidence_package_path = await write_json(
        tmp_cfg,
        session.id,
        "evidence",
        "package_risk",
        {
            "evidence_gaps": [
                {
                    "type": "material_availability",
                    "severity": "high",
                    "message": "Seed lot availability is pending.",
                }
            ],
            "conflict_evidence": [
                {"message": "A local note reports possible yield penalty."}
            ],
        },
    )

    agent = RiskReviewerAgent(
        AgentDeps(cfg=tmp_cfg, db=conn, llm=None, tools=None)  # type: ignore[arg-type]
    )
    result = await agent.execute(
        Task(
            id="tsk_risk_review",
            session_id=session.id,
            created_at=now,
            agent="risk_reviewer",
            action="ReviewRisk",
            target_id=hypothesis.id,
            payload={
                "evidence_package_path": evidence_package_path,
                "validation_plan_path": validation_plan_path,
            },
            status="pending",
        )
    )

    assert result.kind == "risk_reviewed"
    risk_review = await read_json(tmp_cfg, result.extra["risk_review_path"])
    assert risk_review["hypothesis_id"] == hypothesis.id
    assert risk_review["risk_items"]
    assert risk_review["risk_counts"]["by_category"]["material"] >= 1
    assert risk_review["risk_counts"]["by_severity"]["high"] >= 1
    assert risk_review["risk_control_score"] == result.extra["risk_control_score"]
    assert risk_review["must_resolve_before_prioritization"]


def _write_germplasm_csv(path: Path) -> None:
    row = {col: "" for col in EXPECTED_COLUMNS}
    row.update(
        {
            "accession_id": "ARCH-263A",
            "name": "263A",
            "crop": "foxtail millet",
            "germplasm_type": "line",
            "source": "local",
            "availability": "unknown",
            "primary_traits": "lodging resistance; semi-dwarf architecture",
            "summary": "Candidate semi-dwarf donor for lodging resistance validation.",
            "known_genes_qtls": "Seita.5G404900",
            "markers": "Si5G404900C CAPS",
            "phenotype_evidence": "lodging-related architecture clue",
            "genotype_evidence": "no genotype evidence in recurrent parents",
            "breeding_use": "donor parent",
            "risk_notes": "availability and marker transferability require confirmation",
            "source_refs": "https://doi.org/10.1016/j.cj.2022.09.003",
            "data_confidence": "medium",
        }
    )
    path.write_text(
        ",".join(EXPECTED_COLUMNS)
        + "\n"
        + ",".join(_csv_cell(row[col]) for col in EXPECTED_COLUMNS)
        + "\n",
        encoding="utf-8",
    )


def _write_marker_qtl_csv(path: Path) -> None:
    row = {col: "" for col in MARKER_QTL_COLUMNS}
    row.update(
        {
            "marker_id": "MQTL-LODGE-001",
            "crop": "foxtail millet",
            "trait": "lodging resistance",
            "gene_or_qtl": "Seita.5G404900",
            "marker_name": "Si5G404900C CAPS",
            "marker_type": "CAPS",
            "linked_materials": "ARCH-263A; Jingu21",
            "validation_status": "needs_local_parent_preflight",
            "assay_protocol": "Run CAPS assay in donor and recurrent parents.",
            "source_refs": "https://doi.org/10.1016/j.cj.2022.09.003",
            "evidence_summary": "CAPS marker clue for lodging-related architecture.",
            "risk_notes": "Marker transferability requires local validation.",
            "data_confidence": "high",
            "last_updated": "2026-07-28",
        }
    )
    _write_csv_row(path, MARKER_QTL_COLUMNS, row)


def _write_phenotype_protocol_csv(path: Path) -> None:
    row = {col: "" for col in PHENOTYPE_PROTOCOL_COLUMNS}
    row.update(
        {
            "protocol_id": "PHENO-LODGE-001",
            "crop": "foxtail millet",
            "trait": "lodging resistance",
            "target_environment": "dense planting",
            "measurement_method": "Record lodging score, stem strength, and yield.",
            "scale_or_unit": "1-9 score; N; kg/plot",
            "stage": "heading to maturity",
            "replication": "RCBD with 3 replicates",
            "decision_thresholds": "Improve lodging without material yield penalty.",
            "source_refs": "local-rag://dense_lodging_90day_validation_note.md",
            "validation_status": "local_protocol_ready",
            "risk_notes": "Single season is preliminary.",
            "data_confidence": "high",
        }
    )
    _write_csv_row(path, PHENOTYPE_PROTOCOL_COLUMNS, row)


def _write_field_trial_csv(path: Path) -> None:
    row = {col: "" for col in FIELD_TRIAL_COLUMNS}
    row.update(
        {
            "trial_id": "TRIAL-LODGE-001",
            "crop": "foxtail millet",
            "trait": "lodging resistance",
            "environment": "dense planting nursery",
            "season": "2026 pre-season",
            "materials": "ARCH-263A; Jingu21",
            "test_design": "Parent-only preflight plus small RCBD plot.",
            "phenotype_summary": "Lodging score and stem strength are pending.",
            "genotype_summary": "CAPS marker preflight required.",
            "decision_outcome": "pending_local_validation",
            "source_refs": "local-rag://bc1f1_first_cycle_phenotyping_preflight.md",
            "data_confidence": "medium",
            "risk_notes": "Seed and marker polymorphism are unresolved.",
        }
    )
    _write_csv_row(path, FIELD_TRIAL_COLUMNS, row)


def _write_csv_row(path: Path, columns: list[str], row: dict[str, str]) -> None:
    path.write_text(
        ",".join(columns)
        + "\n"
        + ",".join(_csv_cell(row[col]) for col in columns)
        + "\n",
        encoding="utf-8",
    )


def _csv_cell(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


async def _task_rows(conn, session_id: str) -> list[dict[str, object]]:
    async with conn.execute(
        "SELECT agent, action, target_id, payload, priority FROM tasks WHERE session_id=? ORDER BY priority, created_at",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "agent": row["agent"],
            "action": row["action"],
            "target_id": row["target_id"],
            "payload": json.loads(row["payload"]),
            "priority": row["priority"],
        }
        for row in rows
    ]
