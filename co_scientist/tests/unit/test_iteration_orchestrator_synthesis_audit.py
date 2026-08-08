from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from co_scientist.agents.iteration_orchestrator_synthesis import (
    _append_audit_section,
    _append_germplasm_resource_table,
    _audit_final_overview,
    _ensure_breeding_elements_section,
    _ensure_next_breeding_cycle_section,
    _ensure_source_map_section,
    _ensure_validation_plan_section,
    _finalize_overview_variant,
    _format_workflow_facts,
    _mark_remaining_unsupported_lines,
    _mark_remaining_unsupported_lines_until_clean,
    _normalize_markdown_links,
    _top_hypotheses_for_final_overview,
)
from co_scientist.models import Hypothesis
from co_scientist.orchestrator.termination_report import termination_report_markdown


def _six_agent_report(source: str = "https://example.org/source") -> str:
    return f"""
# Executive summary
Wheat drought tolerance should advance only through a source-backed validation route [Source]({source}).

# Six-agent loop conclusion
Goal Interpreter fixed the crop, trait, environment, and stop criteria [H-1].
Evidence Curator supplied a Breeding Evidence Graph with material, marker, field, and risk evidence [Source]({source}).
Breeding Designer produced a compact design card, Validation Planner defined trials, Risk Reviewer flagged GxE risk, and Iteration Orchestrator closed the loop [H-1].

# Recommended breeding directions
## Direction A
The route tests elite wheat germplasm for yield stability under rainfed environments [Source]({source}).

# Breeding decision table
| crop / germplasm | target trait | genes/QTL/markers | phenotyping | genotyping | trial | risk | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| wheat elite population | drought tolerance and yield | QTL-1 marker SNP | field phenotyping assay | SNP genotyping | multi-environment trial replicate design | GxE risk | {source} |

# Parent and material list
- Donor parent D1 and recurrent parent R1 require seed confirmation before crossing [Source]({source}).

# Evidence graph summary
- material:D1 -> trait:drought tolerance -> marker:SNP-1 -> trial:rainfed nursery is the main evidence path [Source]({source}).

# Risks and evidence requests
- Evidence gap: confirm marker polymorphism, local material availability, and GxE stability before advancement [H-1].

# Suggested next breeding cycle
Run a multi-environment trial in the target population of environments [H-1].

# 90-day validation plan
Within 90 days, confirm seed, run marker assay preflight, plant a nursery, phenotype yield and stay-green, and stop if yield drops by more than 10% [Source]({source}).

# Source map and evidence gaps
- {source} supports the QTL, marker, trial, and risk rationale.
"""


def test_final_overview_audit_passes_supported_six_agent_report() -> None:
    audit = _audit_final_overview(_six_agent_report())
    assert audit["status"] == "pass"


def test_final_overview_audit_accepts_chinese_section_headings() -> None:
    report = "\n".join(
        [
            "# 执行摘要",
            "The crop germplasm parent donor material and target trait have source support https://example.org/source.",
            "# 六智能体闭环结论",
            "# 推荐育种方向",
            "# 育种决策表",
            "# 亲本和材料清单",
            "# 证据图谱摘要",
            "# 风险与补证清单",
            "# 建议的下一轮育种周期",
            "# 90天验证计划",
            "# 来源图谱与证据缺口",
            "The gene QTL marker phenotyping genotyping validation trial environment risk and GxE evidence are recorded https://example.org/source.",
        ]
    )
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"


def test_final_overview_audit_accepts_chinese_breeding_terms() -> None:
    report = "\n".join(
        [
            "# 执行摘要",
            "水稻种质材料用于改良抗旱恢复和产量稳定性。",
            "# 六智能体闭环结论",
            "# 推荐育种方向",
            "# 育种决策表",
            "| 作物 | 目标性状 | 基因标记 | 表型测定 | 基因型测定 | 试验设计 | 风险 | 引用来源 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 水稻种质 | 抗旱恢复与产量稳定性 | DRO1 QTL 标记 | 表型鉴定 | 基因分型 | 多环境重复试验 | GxE 风险 | https://example.org/source |",
            "# 亲本和材料清单",
            "# 证据图谱摘要",
            "# 风险与补证清单",
            "# 建议的下一轮育种周期",
            "# 90天验证计划",
            "# 来源图谱与证据缺口",
        ]
    )
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"
    assert audit["missing_breeding_elements"] == []


def test_final_overview_audit_accepts_local_rag_source_urls() -> None:
    report = _six_agent_report("local-rag://sinfyc2_lodging_note.md#L1-L4")
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"
    assert audit["missing_breeding_elements"] == []


def test_final_overview_audit_ignores_stale_appended_audit() -> None:
    report = _six_agent_report() + """

# Final report audit
Needs attention before treating this as a polished report.
## Missing sections
- Recommended breeding directions
"""
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"


def test_validation_plan_paragraph_is_promoted_to_a_section() -> None:
    report = "# 执行摘要\n\n**首个验证试验。** 90天内完成材料确认和标记预检。"
    revised = _ensure_validation_plan_section(report, language="zh")
    assert "# 90天验证计划" in revised
    assert _audit_final_overview(revised)["missing_sections"]


def test_termination_report_markdown_explains_hypothesis_cap() -> None:
    session = SimpleNamespace(
        research_plan=SimpleNamespace(max_hypothesis_count=2),
    )
    section = termination_report_markdown(
        session=session,
        hypotheses=[object(), object()],
        decisions={
            "hyp_a": {"action": "revise", "total_score": 66.0},
            "hyp_b": {"action": "expand", "total_score": 68.0},
        },
        stop_reason="breeding_max_hypotheses_reached",
        language="en",
    )

    assert "# System termination rationale" in section
    assert "Stop reason: `breeding_max_hypotheses_reached`" in section
    assert "Hypotheses generated: 2 / 2" in section
    assert "Directly advanceable routes: 0" in section
    assert "Revision-needed candidate routes: 1" in section
    assert "Expansion-needed candidate routes: 1" in section
    assert "failed to produce useful candidate hypotheses" in section
    assert "Keep-ready routes" not in section
    assert "user-defined hypothesis cap" in section


def test_finalize_overview_variant_appends_termination_rationale() -> None:
    section = termination_report_markdown(
        session=SimpleNamespace(research_plan=SimpleNamespace(max_hypothesis_count=1)),
        hypotheses=[object()],
        decisions={"hyp_a": {"action": "revise", "total_score": 66.0}},
        stop_reason="breeding_max_hypotheses_reached",
        language="en",
    )

    finalized, audit = _finalize_overview_variant(
        _six_agent_report(),
        [],
        evidence_text=_six_agent_report(),
        hypothesis_ids=["hyp_a"],
        language="en",
        termination_section=section,
    )

    assert audit["status"] == "pass"
    assert "# System termination rationale" in finalized
    assert "breeding_max_hypotheses_reached" in finalized
    assert finalized.index("# System termination rationale") < finalized.index("# Final report audit")


def test_ensure_source_map_section_appends_missing_source_map() -> None:
    report = _six_agent_report().split("# Source map and evidence gaps")[0].rstrip()

    amended = _ensure_source_map_section(
        report,
        evidence_text="local-rag://foxtail_millet/preflight.md#L1-L4\nhttps://example.org/qtl",
        language="zh",
    )
    audit = _audit_final_overview(amended)

    assert amended
    assert "local-rag://foxtail_millet/preflight.md#L1-L4" in amended
    assert "https://example.org/qtl" in amended
    assert audit["status"] == "pass"


def test_finalize_overview_variant_repairs_missing_cycle_sections() -> None:
    report = """
# Executive summary
The route is source-backed [H-1].

# Six-agent loop conclusion
The six agents closed the loop [H-1].

# Recommended breeding directions
The route uses wheat germplasm, a marker, phenotyping, and a field trial [H-1].

# Breeding decision table
| crop | trait | marker | phenotyping | genotyping | trial | risk | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| wheat | drought tolerance | QTL-1 | field phenotyping | SNP genotyping | replicated trial | GxE risk | https://example.org/source |

# Parent and material list
- Donor D1 and recurrent parent R1 need confirmation [H-1].

# Evidence graph summary
- material D1 -> trait -> marker -> trial [H-1].

# Risks and evidence requests
- Evidence gap: confirm polymorphism and availability [H-1].
"""
    amended = _ensure_next_breeding_cycle_section(report, hypothesis_ids=["hyp_a"], language="en")
    amended = _ensure_validation_plan_section(amended, language="en")
    amended = _ensure_source_map_section(amended, evidence_text="https://example.org/source")
    assert _audit_final_overview(amended)["status"] == "pass"


def test_breeding_elements_repair_makes_missing_dimensions_explicit() -> None:
    report = """
# Executive summary
The route is source-backed [H-1].

# Breeding decision table
| crop | source |
| --- | --- |
| wheat | https://example.org/source |
"""
    repaired = _ensure_breeding_elements_section(
        report,
        missing=["target_trait", "phenotyping"],
        language="en",
    )
    audit = _audit_final_overview(repaired)

    assert "target trait" in repaired
    assert "phenotyping" in repaired
    assert "target_trait" not in audit["missing_breeding_elements"]
    assert "phenotyping" not in audit["missing_breeding_elements"]


def test_finalize_overview_variant_adds_missing_source_map_before_audit() -> None:
    report = _six_agent_report().split("# Source map and evidence gaps")[0].rstrip()

    finalized, audit = _finalize_overview_variant(
        report,
        [],
        evidence_text="local-rag://foxtail_millet/preflight.md#L1-L4",
        hypothesis_ids=["hyp_a"],
        language="en",
    )

    assert "# Source map and evidence gaps" in finalized
    assert "local-rag://foxtail_millet/preflight.md#L1-L4" in finalized
    assert audit["status"] == "pass"


def test_final_overview_top_hypotheses_use_composite_rank_not_pairwise_only() -> None:
    now = datetime.now(UTC)
    keep_hyp = Hypothesis(
        id="hyp_keep_final",
        session_id="ses_final_rank",
        created_at=now,
        created_by="breeding_designer",
        strategy="literature",
        title="Keep route",
        summary="",
        full_text="",
        artifact_path="artifacts/ses_final_rank/hypotheses/hyp_keep_final.json",
        calibration_score=1210,
        state="calibration_pool",
    )
    pause_hyp = keep_hyp.model_copy(update={"id": "hyp_pause_final", "title": "Pause route", "calibration_score": 1500})
    rejected_hyp = keep_hyp.model_copy(
        update={"id": "hyp_rejected_final", "title": "Rejected route", "calibration_score": 1600, "state": "rejected"}
    )
    decisions = {
        keep_hyp.id: {
            "action": "keep",
            "total_score": 84.0,
            "scorecard": [
                {"dimension": "evidence_support", "score": 86.0},
                {"dimension": "validation_actionability", "score": 82.0},
                {"dimension": "review_strength", "score": 84.0},
                {"dimension": "risk_control", "score": 85.0},
            ],
        },
        pause_hyp.id: {
            "action": "pause",
            "total_score": 45.0,
            "scorecard": [
                {"dimension": "evidence_support", "score": 45.0},
                {"dimension": "validation_actionability", "score": 35.0},
                {"dimension": "review_strength", "score": 42.0},
                {"dimension": "risk_control", "score": 30.0},
            ],
        },
    }

    top, rank_map = _top_hypotheses_for_final_overview([rejected_hyp, pause_hyp, keep_hyp], decisions, k=10)

    assert [hyp.id for hyp in top] == ["hyp_keep_final", "hyp_pause_final"]
    assert rank_map[keep_hyp.id]["score"] > rank_map[pause_hyp.id]["score"]


def test_workflow_facts_prevent_initial_count_confusion() -> None:
    session = SimpleNamespace(
        research_plan=SimpleNamespace(initial_hypothesis_count=2, max_hypothesis_count=4)
    )
    text = _format_workflow_facts(
        session=session,
        hypotheses=[object(), object(), object(), object()],
        stop_reason="breeding_max_hypotheses_reached",
    )

    assert "Parsed initial_hypothesis_count: 2" in text
    assert "Hypotheses actually produced by the closed loop: 4" in text
    assert "never call the final hypothesis count the initial count" in text


def test_final_overview_audit_flags_missing_support_and_six_agent_sections() -> None:
    report = """
# Executive summary
This direction is likely to improve yield stability and should be advanced immediately.
"""
    audit = _audit_final_overview(report)
    assert audit["status"] == "needs_attention"
    assert "Six-agent loop conclusion" in audit["missing_sections"]
    assert "Breeding decision table" in audit["missing_sections"]
    assert audit["unsupported_important_lines"]

    amended = _append_audit_section(report, audit)
    assert "# Final report audit" in amended
    assert "Needs attention" in amended


def test_final_overview_audit_accepts_reasonable_new_heading_variants() -> None:
    report = _six_agent_report().replace(
        "# Six-agent loop conclusion",
        "# Six Agent Workflow Conclusion",
    ).replace(
        "# Recommended breeding directions",
        "# Breeding Directions",
    )
    audit = _audit_final_overview(report)
    assert "Six-agent loop conclusion" not in audit["missing_sections"]
    assert "Recommended breeding directions" not in audit["missing_sections"]
    assert audit["status"] == "pass"


def test_final_overview_audit_accepts_six_agent_sections() -> None:
    report = _six_agent_report("https://example.org/a")
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"
    assert audit["missing_sections"] == []
    assert audit["missing_breeding_elements"] == []


def test_final_overview_audit_ignores_appended_pass_audit_section() -> None:
    report = _six_agent_report() + """

---

# Final report audit
Passed deterministic checks: required sections are present, important claim lines include source URLs or hypothesis references, and core breeding decision elements are represented.
"""
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"
    assert audit["unsupported_important_lines"] == []


def test_final_overview_audit_accepts_chinese_system_inference_markers() -> None:
    report = _six_agent_report().replace(
        "The route tests elite wheat germplasm for yield stability under rainfed environments [Source](https://example.org/source).",
        "3. **Mechanism note**: system inference indicates this route may improve drought persistence; evidence gap: validate parent-background effect in the next round.",
    )
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"
    assert audit["unsupported_important_lines"] == []


def test_append_germplasm_resource_table_uses_accession_ids() -> None:
    report = """
# 鎵ц鎽樿
璋峰瓙鑰愬瘑妞嶆牚鍨嬪彲浼樺厛鑰冭檻 ARCH-263A 鍜?FPS2025-148 [Source](https://example.org/a)銆?"""
    records = [
        {
            "accession_id": "ARCH-263A",
            "name": "263A",
            "breeding_use": "semi-dwarf donor",
            "primary_traits": "semi-dwarf",
            "source_refs": "https://example.org/263a",
            "risk_notes": "availability needs confirmation",
        },
        {
            "accession_id": "FPS2025-148",
            "name": "Xiaojinmiaoguzi",
            "breeding_use": "stem strength donor candidate",
            "primary_traits": "stem thickness",
            "source_refs": "https://example.org/fps",
            "risk_notes": "single-environment evidence only",
        },
    ]

    amended = _append_germplasm_resource_table(report, records)
    assert "Accession ID" in amended
    assert "| 263A | ARCH-263A | semi-dwarf donor | https://example.org/263a | availability needs confirmation |" in amended
    assert "| Xiaojinmiaoguzi | FPS2025-148 | stem strength donor candidate | https://example.org/fps | single-environment evidence only |" in amended


def test_append_germplasm_resource_table_does_not_duplicate_existing_table() -> None:
    report = """
# 鎵ц鎽樿
ARCH-263A [Source](https://example.org/a)

# Germplasm resource evidence table
| Material | Accession ID | Use / trait clue | Source | Risk / evidence gap |
| --- | --- | --- | --- | --- |
"""
    amended = _append_germplasm_resource_table(report, [{"accession_id": "ARCH-263A", "name": "263A"}])
    assert amended == report


def test_append_germplasm_resource_table_filters_out_of_scope_parent_rows() -> None:
    report = """
# Parent and material list
| Material | Role | Evidence |
| --- | --- | --- |
| FPS2025-148 | recurrent parent | local panel |
| Jingu 21 / Zhangza 13 | fallback parent | lodging route |
"""

    amended = _append_germplasm_resource_table(
        report,
        [{"accession_id": "FPS2025-148", "name": "Xiaojinmiaoguzi"}],
    )

    assert "FPS2025-148" in amended
    assert "Jingu 21 / Zhangza 13" not in amended


def test_final_overview_audit_does_not_require_sources_for_questions() -> None:
    report = _six_agent_report().replace(
        "The route tests elite wheat germplasm for yield stability under rainfed environments [Source](https://example.org/source).",
        "Do the three loci show additive or synergistic effects when combined?\n"
        "The route tests elite wheat germplasm for yield stability under rainfed environments [Source](https://example.org/source).",
    )
    audit = _audit_final_overview(report)
    assert audit["status"] == "pass"


def test_mark_remaining_unsupported_lines_adds_hypothesis_support() -> None:
    report = _six_agent_report().replace(
        "Run a multi-environment trial in the target population of environments [H-1].",
        "- Assemble a diversity panel of 100 spring wheat lines and run a managed terminal-drought trial with 3 replicates.",
    )
    audit = _audit_final_overview(report)
    assert audit["unsupported_important_lines"]

    marked = _mark_remaining_unsupported_lines(report, audit, hypothesis_ids=["hyp_abc123"])
    marked_audit = _audit_final_overview(marked)
    assert marked_audit["status"] == "pass"
    assert "`hyp_abc123`" in marked


def test_mark_remaining_unsupported_lines_until_clean_handles_capped_audit() -> None:
    report = _six_agent_report().replace(
        "Run a multi-environment trial in the target population of environments [H-1].",
        "\n".join(
            f"- Run selection recommendation {i} across drought environments with marker-assisted phenotyping and field validation."
            for i in range(20)
        ),
    )
    audit = _audit_final_overview(report)
    assert len(audit["unsupported_important_lines"]) == 12

    marked, marked_audit = _mark_remaining_unsupported_lines_until_clean(
        report,
        audit,
        hypothesis_ids=["hyp_abc123"],
    )
    assert marked_audit["status"] == "pass"
    assert marked.count("`hyp_abc123`") == 20


def test_normalize_markdown_links_repairs_closing_bracket_typo() -> None:
    text = "TaNTL1 evidence [Source](https://pubmed.ncbi.nlm.nih.gov/35512580/]."
    assert _normalize_markdown_links(text) == (
        "TaNTL1 evidence [Source](https://pubmed.ncbi.nlm.nih.gov/35512580/)."
    )
