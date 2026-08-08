"""Evidence Curator agent - local-first evidence package builder.

V1 is deliberately deterministic and local-first: it gathers structured clues
from the germplasm CSV, crop-pack KG, and local RAG index, then writes
an evidence package artifact for downstream breeding hypothesis design.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..knowledge.breeding_libraries import (
    load_field_trial_records,
    load_marker_qtl_records,
    load_phenotype_protocol_records,
    search_field_trial_records,
    search_marker_qtl_records,
    search_phenotype_protocol_records,
)
from ..knowledge.crop_kg import resolve_crop_kg_packs, search_crop_kg_packs
from ..knowledge.crop_taxonomy import CROP_ALIASES, canonical_crop
from ..knowledge.germplasm import load_germplasm_records, search_germplasm_records
from ..knowledge.rag import (
    build_evidence_index,
    load_evidence_index,
    search_evidence_index,
)
from ..logging import get_logger
from ..models import Task, TaskResult
from ..storage.artifacts import read_json, write_json
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent

log = get_logger("evidence_curator")


class EvidenceCuratorAgent(BaseAgent):
    """Build a structured, auditable evidence package before hypothesis design."""

    name = "Evidence Curator"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "CurateEvidencePackage":
            raise ValueError(f"EvidenceCuratorAgent does not handle action {task.action!r}")

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")

        mode = str(task.payload.get("mode") or "bfrs").lower()
        if mode not in {"bfrs", "dfrs"}:
            mode = "bfrs"
        focus = await _resolve_focus_text(self.deps.cfg, self.deps.db, task)
        enqueue_design = bool(task.payload.get("enqueue_design", mode == "bfrs"))
        queries = _derive_queries(session.research_goal, session.research_plan, focus=focus)
        crop_hint = _crop_hint(session.research_plan)

        # Keep the target boundary anchored to the parsed goal/plan. A revised
        # hypothesis may mention discarded parent routes; those mentions must
        # not widen local retrieval back to an unrelated material family.
        target_scope = _target_scope_text(session.research_goal, session.research_plan)
        germplasm = _curate_germplasm(
            self.deps.cfg,
            queries,
            crop_hint=crop_hint,
            target_scope=target_scope,
        )
        kg = _curate_crop_kg(self.deps.cfg, queries, crop_hint=crop_hint)
        rag = _curate_rag(
            self.deps.cfg,
            queries,
            crop_hint=crop_hint,
            target_scope=target_scope,
        )
        marker_qtl = _curate_marker_qtl(self.deps.cfg, queries, crop_hint=crop_hint)
        phenotype_protocols = _curate_phenotype_protocols(
            self.deps.cfg,
            queries,
            crop_hint=crop_hint,
        )
        field_trials = _curate_field_trials(self.deps.cfg, queries, crop_hint=crop_hint)
        graph_delta = _build_graph_delta(
            germplasm,
            kg,
            rag,
            marker_qtl,
            phenotype_protocols,
            field_trials,
        )
        graph_path = await _merge_and_write_evidence_graph(
            self.deps.cfg,
            session.id,
            graph_delta,
            source_task_id=task.id,
        )
        gaps = _detect_gaps(
            germplasm,
            kg,
            rag,
            marker_qtl,
            phenotype_protocols,
            field_trials,
        )

        package = {
            "version": 2,
            "agent": self.name,
            "mode": mode,
            "search_strategy": "breadth_first_route_search" if mode == "bfrs" else "depth_first_route_search",
            "session_id": session.id,
            "knowledge_snapshot_id": (
                session.config_snapshot.get("knowledge_snapshot", {}).get("snapshot_id")
                if isinstance(session.config_snapshot.get("knowledge_snapshot"), dict)
                else None
            ),
            "knowledge_batch_id": (
                session.config_snapshot.get("knowledge_snapshot", {}).get("active_batch_id")
                if isinstance(session.config_snapshot.get("knowledge_snapshot"), dict)
                else None
            ),
            "target_hypothesis_id": task.target_id,
            "research_goal": session.research_goal,
            "queries": queries,
            "focus": focus,
            "validation_plan_path": task.payload.get("validation_plan_path"),
            "enqueue_design": enqueue_design,
            "source_priority": [
                "local_germplasm_resource",
                "local_crop_kg",
                "local_rag",
                "local_marker_qtl_library",
                "local_phenotype_protocol_library",
                "local_field_trial_records",
                "external_literature_placeholder",
            ],
            "local_germplasm": germplasm,
            "local_crop_kg": kg,
            "local_rag": rag,
            "local_marker_qtl": marker_qtl,
            "local_phenotype_protocols": phenotype_protocols,
            "local_field_trials": field_trials,
            "external_literature": {
                "status": "not_run_in_v1",
                "note": (
                    "Evidence Curator V1 is local-first. External literature remains "
                    "available to downstream tool-using agents and can be added as a "
                    "future curator source."
                ),
            },
            "evidence_gaps": gaps,
            "breeding_evidence_graph_delta": graph_delta,
            "breeding_evidence_graph_path": graph_path,
            "downstream_guidance": _downstream_guidance(gaps),
        }
        artifact_path = await write_json(
            self.deps.cfg,
            session.id,
            "evidence",
            f"package_{task.id}",
            package,
        )

        log.info(
            "evidence_package_curated",
            session_id=session.id,
            artifact_path=artifact_path,
            n_germplasm=len(germplasm["results"]),
            n_kg=len(kg["results"]),
            n_rag=len(rag["results"]),
            n_marker_qtl=len(marker_qtl["results"]),
            n_phenotype_protocols=len(phenotype_protocols["results"]),
            n_field_trials=len(field_trials["results"]),
            n_gaps=len(gaps),
        )
        return TaskResult(
            kind="evidence_curated",
            extra={
                "evidence_package_path": artifact_path,
                "breeding_evidence_graph_path": graph_path,
                "validation_plan_path": task.payload.get("validation_plan_path"),
                "n_initial": int(task.payload.get("n_initial") or 3),
                "mode": mode,
                "target_hypothesis_id": task.target_id,
                "enqueue_design": enqueue_design,
                "counts": {
                    "germplasm": len(germplasm["results"]),
                    "kg": len(kg["results"]),
                    "rag": len(rag["results"]),
                    "marker_qtl": len(marker_qtl["results"]),
                    "phenotype_protocols": len(phenotype_protocols["results"]),
                    "field_trials": len(field_trials["results"]),
                    "gaps": len(gaps),
                },
            },
        )


async def _resolve_focus_text(cfg, db, task: Task) -> str:
    parts: list[str] = []
    raw_focus = str(task.payload.get("focus") or "").strip()
    if raw_focus:
        parts.append(raw_focus)

    validation_plan_path = task.payload.get("validation_plan_path")
    if validation_plan_path:
        try:
            validation_plan = await read_json(cfg, str(validation_plan_path))
        except Exception:
            validation_plan = {}
        if isinstance(validation_plan, dict):
            parts.append(_validation_plan_focus(validation_plan))

    if task.target_id:
        hypothesis = await hyp_repo.fetch(db, task.target_id)
        if hypothesis is not None:
            parts.extend(
                [
                    hypothesis.title or "",
                    hypothesis.summary or "",
                    _compact_text(hypothesis.full_text, max_chars=1200),
                ]
            )
        else:
            parts.append(task.target_id)

    return "\n".join(part for part in parts if part)


def _validation_plan_focus(plan: dict[str, Any]) -> str:
    parts: list[str] = []
    goal = plan.get("breeding_goal")
    if isinstance(goal, dict):
        for key in (
            "target_trait",
            "target_environment",
            "donor_parent",
            "recurrent_parent",
        ):
            parts.append(str(goal.get(key) or ""))
        markers = goal.get("candidate_genes_qtl_markers")
        if isinstance(markers, list):
            parts.append(" ".join(str(marker) for marker in markers))
    for gap in plan.get("critical_evidence_gaps") or []:
        if isinstance(gap, dict):
            parts.append(str(gap.get("message") or ""))
    requests = plan.get("next_agent_requests")
    if isinstance(requests, dict):
        parts.append(str(requests.get("evidence_curator_focus") or ""))
    return "\n".join(part for part in parts if part.strip())


def _derive_queries(goal: str, plan, *, focus: str = "") -> list[str]:
    raw: list[str] = [
        goal,
        getattr(plan, "objective", "") or "",
        focus,
        getattr(plan, "crop", "") or "",
        " ".join(getattr(plan, "target_traits", []) or []),
        " ".join(getattr(plan, "target_environments", []) or []),
        " ".join(getattr(plan, "material_constraints", []) or []),
        " ".join(getattr(plan, "preferred_breeding_strategies", []) or []),
        " ".join(getattr(plan, "validation_constraints", []) or []),
        " ".join(getattr(plan, "success_criteria", []) or []),
        " ".join(getattr(plan, "idea_attributes", []) or []),
        " ".join(getattr(plan, "constraints", []) or []),
    ]
    for preference in getattr(plan, "preferences", []) or []:
        raw.append(str(preference))
    raw.extend(_breeding_query_aliases(" ".join(str(item) for item in raw if item)))

    queries: list[str] = []
    seen: set[str] = set()
    for item in raw:
        q = " ".join(str(item).split()).strip()
        if len(q) < 2:
            continue
        key = q.lower()
        if key in seen:
            continue
        queries.append(q)
        seen.add(key)
        if len(queries) >= 16:
            break
    return queries or [goal.strip() or "breeding evidence"]


def _target_scope_text(goal: str, plan, focus: str = "") -> str:
    """Build the narrow relevance boundary used by local evidence retrieval."""

    parts = [
        goal,
        getattr(plan, "objective", "") or "",
        " ".join(getattr(plan, "target_traits", []) or []),
        " ".join(getattr(plan, "target_environments", []) or []),
        focus,
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _target_anchor_terms(text: str) -> tuple[str, ...]:
    """Return specific trait anchors; generic words must not define relevance."""

    lower = text.lower()
    anchors: list[str] = []

    if any(
        token in lower
        for token in (
            "drought",
            "water stress",
            "water-stress",
            "water-limited",
            "dryland",
            "干旱",
            "抗旱",
            "耐旱",
        )
    ):
        anchors.extend(("drought", "water stress", "water-stress", "water-limited", "dryland"))
    if any(
        token in lower
        for token in ("stay-green", "stay green", "senescence", "chlorophyll", "持绿", "衰老")
    ):
        anchors.extend(("stay-green", "stay green", "senescence", "chlorophyll"))
    if any(
        token in lower
        for token in ("yield stability", "yield variability", "yield-cv", "产量稳定", "产量变异")
    ):
        anchors.extend(("yield stability", "yield variability", "yield-cv"))
    if any(
        token in lower
        for token in ("lodging", "stem strength", "dense planting", "倒伏", "茎秆强度", "密植")
    ):
        anchors.extend(("lodging", "stem strength", "dense planting"))
    if any(token in lower for token in ("grain quality", "quality trait", "品质", "籽粒品质")):
        anchors.extend(("grain quality", "quality trait"))
    if any(
        token in lower
        for token in (
            "submergence",
            "waterlogging",
            "flood recovery",
            "post-flood",
            "post-submergence",
            "recovery vigor",
            "淹水",
            "耐淹",
            "洪涝",
        )
    ):
        anchors.extend(
            (
                "submergence",
                "waterlogging",
                "flood recovery",
                "post-flood",
                "post-submergence",
                "recovery",
            )
        )
    if any(
        token in lower
        for token in ("marker validation", "marker preflight", "caps", "starp", "qtl validation")
    ):
        anchors.extend(("marker", "qtl", "caps", "starp"))
    return tuple(dict.fromkeys(anchors))


def _record_evidence_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(field) or "")
        for field in (
            "primary_traits",
            "strengths",
            "known_genes_qtls",
            "markers",
            "breeding_use",
            "stress_tolerance",
            "quality_traits",
            "disease_resistance",
        )
    ).lower()


def _record_matches_target_scope(record: dict[str, Any], target_scope: str) -> bool:
    """Reject records matched only by generic words such as local or material."""

    anchors = _target_anchor_terms(target_scope)
    if not anchors:
        return True

    accession_id = str(record.get("accession_id") or "").lower()
    name = str(record.get("name") or "").lower()
    scope_lower = target_scope.lower()
    if (accession_id and accession_id in scope_lower) or (name and name in scope_lower):
        return True

    evidence_text = _record_evidence_text(record)
    if any(anchor in evidence_text for anchor in anchors):
        return True

    # Yield-component accessions are valid candidates for a yield-stability
    # goal even when the public row does not claim drought tolerance itself.
    if "yield stability" in scope_lower and "yield" in evidence_text:
        return True

    # A documented marker/QTL resource remains useful as a guardrail even when
    # its primary trait differs from the current target. It must have an
    # explicit gene/QTL or marker field, not merely a generic marker query hit.
    return bool(record.get("known_genes_qtls") or record.get("markers"))


def _rag_chunk_matches_target_scope(chunk: Any, target_scope: str) -> bool:
    anchors = _target_anchor_terms(target_scope)
    if not anchors:
        return True
    text = f"{getattr(chunk, 'source_path', '')} {getattr(chunk, 'title', '')} {getattr(chunk, 'text', '')}".lower()
    return any(anchor in text for anchor in anchors)


def _chunk_matches_crop(chunk: Any, crop_hint: str | None) -> bool:
    if not crop_hint:
        return True
    source_scope = str(getattr(chunk, "crop_scope", "") or "").strip()
    if source_scope:
        normalized_scope = _normalize_crop_hint(source_scope)
        normalized_target = _normalize_crop_hint(crop_hint)
        if not normalized_scope or not normalized_target:
            return False
        return normalized_scope == normalized_target
    # Unscoped documents remain eligible as general evidence. Explicitly
    # scoped documents above must pass the canonical crop check.
    return True


def _breeding_query_aliases(text: str) -> list[str]:
    aliases: list[str] = []
    lower = text.lower()
    if _normalize_crop_hint(text) == "foxtail millet":
        aliases.append("foxtail millet Setaria italica")
    if _normalize_crop_hint(text) == "rice":
        aliases.append("rice Oryza sativa breeding")
        if any(token in text for token in ("\u6d2a\u6d9d", "\u6df9\u6c34", "\u6c34\u6df9")) or any(
            term in lower for term in ("submergence", "flood")
        ):
            aliases.append("rice Sub1A submergence tolerance")
        if "\u5e72\u65f1" in text or "\u6297\u65f1" in text or "drought" in lower:
            aliases.append("rice DRO1 drought root angle")
        if "\u76d0" in text or "\u76d0\u78b1" in text or "salinity" in lower or "salt" in lower:
            aliases.append("rice Saltol OsHKT1;5 salinity tolerance")
        if "\u7a3b\u762e" in text or "blast" in lower:
            aliases.append("rice Pi-ta blast resistance")
        if "\u767d\u53f6\u67af" in text or "bacterial blight" in lower:
            aliases.append("rice Xa21 bacterial blight resistance")
    if any(token in text for token in ("抗倒伏", "倒伏")) or "lodging" in lower:
        aliases.extend(
            [
                "foxtail millet lodging resistance dense planting",
                "lodging resistance stem strength plant height CAPS marker Si5G404900C",
            ]
        )
    if "密植" in text or "dense planting" in lower:
        aliases.append("dense planting lodging resistance phenotype protocol field trial")
    if any(token in text for token in ("抗旱", "耐旱", "干旱")) or "drought" in lower:
        aliases.append("foxtail millet drought tolerance stay-green managed water-stress")
    if any(token in text for token in ("抗病", "病害", "白发病")) or "blast" in lower:
        aliases.append("foxtail millet blast resistance disease screening nursery")
    if any(token in text for token in ("品质", "蛋白", "淀粉")) or "quality" in lower:
        aliases.append("foxtail millet grain quality protein starch quality")
    if any(token in text for token in ("早熟", "熟期", "开花")) or "maturity" in lower:
        aliases.append("foxtail millet early maturity flowering time short-season adaptation")
    return aliases


def _normalize_crop_hint(text: str) -> str | None:
    crop = canonical_crop(text)
    return crop if crop in CROP_ALIASES else None


def _crop_hint(plan_or_text) -> str | None:
    if not isinstance(plan_or_text, str):
        crop = str(getattr(plan_or_text, "crop", "") or "").strip()
        normalized_crop = _normalize_crop_hint(crop)
        if normalized_crop:
            return normalized_crop
        text = " ".join(
            [
                str(getattr(plan_or_text, "objective", "") or ""),
                " ".join(getattr(plan_or_text, "target_traits", []) or []),
                " ".join(getattr(plan_or_text, "target_environments", []) or []),
            ]
        )
    else:
        text = plan_or_text
    normalized_text = _normalize_crop_hint(text)
    if normalized_text:
        return normalized_text
    return None


def _curate_germplasm(
    cfg,
    queries: list[str],
    *,
    crop_hint: str | None,
    target_scope: str = "",
) -> dict[str, Any]:
    path = cfg.germplasm_csv_path
    out = {"source": str(path), "status": "missing", "results": []}
    if not path.exists():
        return out
    try:
        records = load_germplasm_records(path)
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            matches = search_germplasm_records(
                records,
                query,
                crop=crop_hint,
                limit=6,
            )
            for match in matches:
                record = match.record
                if not _record_matches_target_scope(record, target_scope):
                    continue
                accession_id = record.get("accession_id") or record.get("name") or ""
                if not accession_id:
                    continue
                item = collected.setdefault(
                    accession_id,
                    {
                        "accession_id": accession_id,
                        "name": record.get("name"),
                        "crop": record.get("crop"),
                        "primary_traits": record.get("primary_traits"),
                        "availability": record.get("availability"),
                        "summary": record.get("summary"),
                        "known_genes_qtls": record.get("known_genes_qtls"),
                        "markers": record.get("markers"),
                        "phenotype_evidence": record.get("phenotype_evidence"),
                        "genotype_evidence": record.get("genotype_evidence"),
                        "breeding_use": record.get("breeding_use"),
                        "risk_notes": record.get("risk_notes"),
                        "source_refs": record.get("source_refs"),
                        "data_confidence": record.get("data_confidence"),
                        "matched_queries": [],
                        "matched_fields": [],
                        "score": 0,
                        "evidence_level": _evidence_level(
                            "local_germplasm_resource",
                            record.get("data_confidence"),
                        ),
                    },
                )
                item["matched_queries"].append(query)
                item["matched_fields"] = sorted({*item["matched_fields"], *match.matched_fields})
                item["score"] = max(int(item["score"]), match.score)
        out.update({"status": "ok", "results": list(collected.values())})
    except Exception as e:  # pragma: no cover - exercised through integration logs
        out.update({"status": "error", "error": str(e)})
    return out


def _curate_crop_kg(cfg, queries: list[str], *, crop_hint: str | None) -> dict[str, Any]:
    try:
        packs = resolve_crop_kg_packs(cfg, crop_hint)
    except ValueError as e:
        return {"source": None, "status": "unsupported_crop", "error": str(e), "results": []}
    out = {
        "source": str(packs[0].path) if len(packs) == 1 else None,
        "source_packs": [
            {
                "key": pack.key,
                "crop_name": pack.crop_name,
                "source": str(pack.path),
                "available": pack.path.exists(),
            }
            for pack in packs
        ],
        "status": "missing",
        "results": [],
    }
    if not any(pack.path.exists() for pack in packs):
        return out
    try:
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            matches = search_crop_kg_packs(
                cfg,
                query,
                crop=crop_hint,
                include_edges=True,
                limit=8,
            )
            for pack_match in matches:
                pack = pack_match.pack
                match = pack_match.match
                node = match.node
                node_id = node.get("id") or node.get("name")
                if not node_id:
                    continue
                item_key = f"{pack.key}:{node_id}"
                item = collected.setdefault(
                    item_key,
                    {
                        "id": node_id,
                        "name": node.get("name"),
                        "type": node.get("type"),
                        "crop_pack": pack.key,
                        "crop_scope": pack.crop_name,
                        "source_kg": str(pack.path),
                        "aliases": node.get("aliases", []),
                        "summary": node.get("summary"),
                        "source_refs": node.get("source_refs"),
                        "data_confidence": node.get("data_confidence"),
                        "matched_queries": [],
                        "matched_fields": [],
                        "score": 0,
                        "edges": [],
                        "evidence_level": _evidence_level("local_kg", node.get("data_confidence")),
                    },
                )
                item["matched_queries"].append(query)
                item["matched_fields"] = sorted({*item["matched_fields"], *match.matched_fields})
                item["score"] = max(int(item["score"]), match.score)
                edge_ids = {edge.get("id") for edge in item["edges"]}
                for edge in match.edges:
                    if edge.get("id") in edge_ids:
                        continue
                    item["edges"].append(_format_kg_edge(edge, pack_match.nodes_by_id))
        out.update({"status": "ok", "results": list(collected.values())})
    except Exception as e:  # pragma: no cover
        out.update({"status": "error", "error": str(e)})
    return out


def _curate_rag(
    cfg,
    queries: list[str],
    *,
    crop_hint: str | None = None,
    target_scope: str = "",
) -> dict[str, Any]:
    index_path = cfg.rag_index_path
    source_dir = cfg.rag_sources_dir
    out = {
        "source_index": str(index_path),
        "source_dir": str(source_dir),
        "status": "missing",
        "results": [],
    }
    try:
        if index_path.exists():
            index = load_evidence_index(index_path)
            status = "ok"
        elif source_dir.exists():
            index = build_evidence_index(source_dir)
            status = "built_in_memory"
        else:
            return out

        collected: dict[str, dict[str, Any]] = {}
        scoped_index = index
        if crop_hint:
            scoped_chunks = [
                chunk for chunk in index.chunks if _chunk_matches_crop(chunk, crop_hint)
            ]
            scoped_index = replace(
                index,
                chunks=scoped_chunks,
                chunk_count=len(scoped_chunks),
            )
        for query in queries:
            matches = search_evidence_index(scoped_index, query, limit=8)
            for match in matches:
                chunk = match.chunk
                if not _chunk_matches_crop(chunk, crop_hint):
                    continue
                if not _rag_chunk_matches_target_scope(chunk, target_scope):
                    continue
                item = collected.setdefault(
                    chunk.chunk_id,
                    {
                        "chunk_id": chunk.chunk_id,
                        "source_path": chunk.source_path,
                        "crop_scope": getattr(chunk, "crop_scope", None),
                        "title": chunk.title,
                        "text": chunk.text,
                        "line_range": [chunk.start_line, chunk.end_line],
                        "url": (
                            f"local-rag://{chunk.source_path}"
                            f"#L{chunk.start_line}-L{chunk.end_line}"
                        ),
                        "matched_queries": [],
                        "matched_terms": [],
                        "score": 0.0,
                        "evidence_level": "local_rag",
                    },
                )
                item["matched_queries"].append(query)
                item["matched_terms"] = sorted({*item["matched_terms"], *match.matched_terms})
                item["score"] = max(float(item["score"]), match.score)
        out.update({"status": status, "results": list(collected.values())})
    except Exception as e:  # pragma: no cover
        out.update({"status": "error", "error": str(e)})
    return out


def _curate_marker_qtl(cfg, queries: list[str], *, crop_hint: str | None) -> dict[str, Any]:
    path = cfg.marker_qtl_csv_path
    out = {"source": str(path), "status": "missing", "results": []}
    if not path.exists():
        return out
    try:
        records = load_marker_qtl_records(path)
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            for match in search_marker_qtl_records(records, query, crop=crop_hint, limit=8):
                record = match.record
                marker_id = record.get("marker_id") or record.get("marker_name") or ""
                if not marker_id:
                    continue
                item = collected.setdefault(
                    marker_id,
                    {
                        **record,
                        "matched_queries": [],
                        "matched_fields": [],
                        "score": 0,
                        "evidence_level": _evidence_level(
                            "local_marker_qtl_library",
                            record.get("data_confidence"),
                        ),
                    },
                )
                item["matched_queries"].append(query)
                item["matched_fields"] = sorted({*item["matched_fields"], *match.matched_fields})
                item["score"] = max(int(item["score"]), match.score)
        out.update({"status": "ok", "results": list(collected.values())})
    except Exception as e:  # pragma: no cover
        out.update({"status": "error", "error": str(e)})
    return out


def _curate_phenotype_protocols(
    cfg,
    queries: list[str],
    *,
    crop_hint: str | None,
) -> dict[str, Any]:
    path = cfg.phenotype_protocol_csv_path
    out = {"source": str(path), "status": "missing", "results": []}
    if not path.exists():
        return out
    try:
        records = load_phenotype_protocol_records(path)
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            for match in search_phenotype_protocol_records(records, query, crop=crop_hint, limit=8):
                record = match.record
                protocol_id = record.get("protocol_id") or ""
                if not protocol_id:
                    continue
                item = collected.setdefault(
                    protocol_id,
                    {
                        **record,
                        "matched_queries": [],
                        "matched_fields": [],
                        "score": 0,
                        "evidence_level": _evidence_level(
                            "local_phenotype_protocol_library",
                            record.get("data_confidence"),
                        ),
                    },
                )
                item["matched_queries"].append(query)
                item["matched_fields"] = sorted({*item["matched_fields"], *match.matched_fields})
                item["score"] = max(int(item["score"]), match.score)
        out.update({"status": "ok", "results": list(collected.values())})
    except Exception as e:  # pragma: no cover
        out.update({"status": "error", "error": str(e)})
    return out


def _curate_field_trials(cfg, queries: list[str], *, crop_hint: str | None) -> dict[str, Any]:
    path = cfg.field_trial_csv_path
    out = {"source": str(path), "status": "missing", "results": []}
    if not path.exists():
        return out
    try:
        records = load_field_trial_records(path)
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            for match in search_field_trial_records(records, query, crop=crop_hint, limit=8):
                record = match.record
                trial_id = record.get("trial_id") or ""
                if not trial_id:
                    continue
                item = collected.setdefault(
                    trial_id,
                    {
                        **record,
                        "matched_queries": [],
                        "matched_fields": [],
                        "score": 0,
                        "evidence_level": _evidence_level(
                            "local_field_trial_records",
                            record.get("data_confidence"),
                        ),
                    },
                )
                item["matched_queries"].append(query)
                item["matched_fields"] = sorted({*item["matched_fields"], *match.matched_fields})
                item["score"] = max(int(item["score"]), match.score)
        out.update({"status": "ok", "results": list(collected.values())})
    except Exception as e:  # pragma: no cover
        out.update({"status": "error", "error": str(e)})
    return out


def _format_kg_edge(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    subject = nodes_by_id.get(edge.get("subject"), {})
    obj = nodes_by_id.get(edge.get("object"), {})
    return {
        "id": edge.get("id"),
        "subject": edge.get("subject"),
        "subject_name": subject.get("name"),
        "predicate": edge.get("predicate"),
        "object": edge.get("object"),
        "object_name": obj.get("name"),
        "evidence": edge.get("evidence"),
        "source_refs": edge.get("source_refs"),
        "data_confidence": edge.get("data_confidence"),
        "evidence_level": _evidence_level("local_kg", edge.get("data_confidence")),
    }


def _build_graph_delta(
    germplasm: dict[str, Any],
    kg: dict[str, Any],
    rag: dict[str, Any],
    marker_qtl: dict[str, Any],
    phenotype_protocols: dict[str, Any],
    field_trials: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    material_aliases: dict[str, str] = {}

    def register_material_alias(value: Any, node_id: str) -> None:
        key = _slug(str(value or "")).casefold()
        if not key or key == "unknown":
            return
        material_aliases[key] = node_id
        # Local tables often use ARCH-263A while marker/trial records use 263A.
        tail = key.rsplit("-", 1)[-1]
        if len(tail) >= 3:
            material_aliases.setdefault(tail, node_id)

    def material_node_id(value: Any) -> str | None:
        candidate = _slug(str(value or ""))
        if not candidate or candidate == "unknown":
            return None
        candidate_key = candidate.casefold()
        if not material_aliases:
            return f"material:{candidate}"
        exact = material_aliases.get(candidate_key)
        if exact:
            return exact
        for alias, node_id in material_aliases.items():
            if len(candidate_key) >= 3 and (alias.endswith(candidate_key) or candidate_key.endswith(alias)):
                return node_id
        return None

    for record in germplasm.get("results", []):
        node_id = f"material:{record.get('accession_id')}"
        register_material_alias(record.get("accession_id"), node_id)
        register_material_alias(record.get("name"), node_id)
        nodes[node_id] = {
            "id": node_id,
            "type": "germplasm",
            "label": record.get("name") or record.get("accession_id"),
            "evidence_level": record.get("evidence_level"),
            "status": _status_from_confidence(record.get("data_confidence")),
        }
        if record.get("primary_traits"):
            trait_id = f"trait:{_slug(record['primary_traits'])}"
            nodes.setdefault(trait_id, {"id": trait_id, "type": "trait", "label": record["primary_traits"]})
            edges[f"{node_id}->has_trait->{trait_id}"] = {
                "source": node_id,
                "predicate": "has_trait",
                "target": trait_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("risk_notes"):
            risk_id = f"risk:{_slug(record['risk_notes'])}"
            nodes.setdefault(risk_id, {"id": risk_id, "type": "risk", "label": record["risk_notes"]})
            edges[f"{node_id}->has_risk->{risk_id}"] = {
                "source": node_id,
                "predicate": "has_risk",
                "target": risk_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }

    for item in kg.get("results", []):
        node_id = str(item.get("id"))
        nodes[node_id] = {
            "id": node_id,
            "type": item.get("type") or "kg_node",
            "label": item.get("name") or node_id,
            "evidence_level": item.get("evidence_level"),
            "status": _status_from_confidence(item.get("data_confidence")),
        }
        for edge in item.get("edges", []):
            if not edge.get("subject") or not edge.get("object"):
                continue
            edge_id = edge.get("id") or f"{edge['subject']}->{edge.get('predicate')}->{edge['object']}"
            edges[str(edge_id)] = {
                "source": edge.get("subject"),
                "predicate": edge.get("predicate"),
                "target": edge.get("object"),
                "provenance": edge.get("source_refs"),
                "evidence": edge.get("evidence"),
                "evidence_level": edge.get("evidence_level"),
                "status": _status_from_confidence(edge.get("data_confidence")),
            }

    for item in rag.get("results", []):
        node_id = f"evidence:{item.get('chunk_id')}"
        nodes[node_id] = {
            "id": node_id,
            "type": "rag_evidence",
            "label": item.get("title") or item.get("source_path"),
            "crop_scope": item.get("crop_scope"),
            "provenance": item.get("url"),
            "evidence_level": item.get("evidence_level"),
            "status": "local_evidence",
        }

    for record in marker_qtl.get("results", []):
        node_id = f"marker_qtl:{record.get('marker_id')}"
        nodes[node_id] = {
            "id": node_id,
            "type": "marker_qtl",
            "label": record.get("marker_name") or record.get("marker_id"),
            "evidence_level": record.get("evidence_level"),
            "status": _status_from_confidence(record.get("data_confidence")),
            "validation_status": record.get("validation_status"),
        }
        if record.get("trait"):
            trait_id = f"trait:{_slug(record['trait'])}"
            nodes.setdefault(trait_id, {"id": trait_id, "type": "trait", "label": record["trait"]})
            edges[f"{node_id}->has_trait->{trait_id}"] = {
                "source": node_id,
                "predicate": "has_trait",
                "target": trait_id,
                "provenance": record.get("source_refs"),
                "evidence": record.get("evidence_summary"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("gene_or_qtl"):
            gene_id = f"gene_qtl:{_slug(record['gene_or_qtl'])}"
            nodes.setdefault(
                gene_id,
                {"id": gene_id, "type": "gene_qtl", "label": record["gene_or_qtl"]},
            )
            edges[f"{node_id}->tags_gene_or_qtl->{gene_id}"] = {
                "source": node_id,
                "predicate": "tags_gene_or_qtl",
                "target": gene_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }
        for material in _split_multi_values(record.get("linked_materials")):
            material_id = material_node_id(material)
            if material_id is None:
                continue
            edges[f"{material_id}->has_marker->{node_id}"] = {
                "source": material_id,
                "predicate": "has_marker",
                "target": node_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("risk_notes"):
            risk_id = f"risk:{_slug(record['risk_notes'])}"
            nodes.setdefault(risk_id, {"id": risk_id, "type": "risk", "label": record["risk_notes"]})
            edges[f"{node_id}->has_risk->{risk_id}"] = {
                "source": node_id,
                "predicate": "has_risk",
                "target": risk_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }

    for record in phenotype_protocols.get("results", []):
        node_id = f"protocol:{record.get('protocol_id')}"
        nodes[node_id] = {
            "id": node_id,
            "type": "phenotype_protocol",
            "label": record.get("measurement_method") or record.get("protocol_id"),
            "evidence_level": record.get("evidence_level"),
            "status": _status_from_confidence(record.get("data_confidence")),
            "validation_status": record.get("validation_status"),
        }
        if record.get("trait"):
            trait_id = f"trait:{_slug(record['trait'])}"
            nodes.setdefault(trait_id, {"id": trait_id, "type": "trait", "label": record["trait"]})
            edges[f"{node_id}->validates_trait->{trait_id}"] = {
                "source": node_id,
                "predicate": "validates_trait",
                "target": trait_id,
                "provenance": record.get("source_refs"),
                "evidence": record.get("decision_thresholds"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("target_environment"):
            env_id = f"environment:{_slug(record['target_environment'])}"
            nodes.setdefault(
                env_id,
                {
                    "id": env_id,
                    "type": "environment",
                    "label": record["target_environment"],
                },
            )
            edges[f"{node_id}->adapted_to->{env_id}"] = {
                "source": node_id,
                "predicate": "adapted_to",
                "target": env_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }

    for record in field_trials.get("results", []):
        node_id = f"field_trial:{record.get('trial_id')}"
        nodes[node_id] = {
            "id": node_id,
            "type": "field_trial",
            "label": record.get("trial_id"),
            "evidence_level": record.get("evidence_level"),
            "status": _status_from_confidence(record.get("data_confidence")),
            "decision_outcome": record.get("decision_outcome"),
        }
        if record.get("trait"):
            trait_id = f"trait:{_slug(record['trait'])}"
            nodes.setdefault(trait_id, {"id": trait_id, "type": "trait", "label": record["trait"]})
            edges[f"{node_id}->observes_trait->{trait_id}"] = {
                "source": node_id,
                "predicate": "observes_trait",
                "target": trait_id,
                "provenance": record.get("source_refs"),
                "evidence": record.get("phenotype_summary"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("environment"):
            env_id = f"environment:{_slug(record['environment'])}"
            nodes.setdefault(env_id, {"id": env_id, "type": "environment", "label": record["environment"]})
            edges[f"{node_id}->adapted_to->{env_id}"] = {
                "source": node_id,
                "predicate": "adapted_to",
                "target": env_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }
        for material in _split_multi_values(record.get("materials")):
            material_id = material_node_id(material)
            if material_id is None:
                continue
            edges[f"{node_id}->uses_material->{material_id}"] = {
                "source": node_id,
                "predicate": "uses_material",
                "target": material_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }
        if record.get("risk_notes"):
            risk_id = f"risk:{_slug(record['risk_notes'])}"
            nodes.setdefault(risk_id, {"id": risk_id, "type": "risk", "label": record["risk_notes"]})
            edges[f"{node_id}->has_risk->{risk_id}"] = {
                "source": node_id,
                "predicate": "has_risk",
                "target": risk_id,
                "provenance": record.get("source_refs"),
                "evidence_level": record.get("evidence_level"),
            }

    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


async def _merge_and_write_evidence_graph(
    cfg,
    session_id: str,
    graph_delta: dict[str, list[dict[str, Any]]],
    *,
    source_task_id: str,
) -> str:
    rel_path = f"artifacts/{session_id}/evidence/breeding_evidence_graph.json"
    try:
        existing = await read_json(cfg, rel_path)
    except Exception:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    node_map: dict[str, dict[str, Any]] = {}
    edge_map: dict[str, dict[str, Any]] = {}
    existing_nodes = existing.get("nodes") if isinstance(existing.get("nodes"), list) else []
    existing_edges = existing.get("edges") if isinstance(existing.get("edges"), list) else []
    for node in existing_nodes:
        if isinstance(node, dict) and node.get("id"):
            node_map[str(node["id"])] = dict(node)
    for edge in existing_edges:
        if isinstance(edge, dict):
            edge_map[_edge_key(edge)] = dict(edge)

    for node in graph_delta.get("nodes", []):
        if not isinstance(node, dict) or not node.get("id"):
            continue
        key = str(node["id"])
        node_map[key] = _merge_graph_item(node_map.get(key, {}), node, source_task_id=source_task_id)

    for edge in graph_delta.get("edges", []):
        if not isinstance(edge, dict):
            continue
        key = _edge_key(edge)
        edge_map[key] = _merge_graph_item(edge_map.get(key, {}), edge, source_task_id=source_task_id)

    now = datetime.now(UTC).isoformat()
    graph = {
        "version": 1,
        "session_id": session_id,
        "updated_at": now,
        "node_count": len(node_map),
        "edge_count": len(edge_map),
        "nodes": sorted(node_map.values(), key=lambda item: str(item.get("id") or "")),
        "edges": sorted(
            edge_map.values(),
            key=lambda item: (
                str(item.get("source") or ""),
                str(item.get("predicate") or ""),
                str(item.get("target") or ""),
                str(item.get("provenance") or ""),
            ),
        ),
    }
    return await write_json(cfg, session_id, "evidence", "breeding_evidence_graph", graph)


def _merge_graph_item(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    source_task_id: str,
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    task_ids = set(str(item) for item in merged.get("source_task_ids", []) if item)
    task_ids.add(source_task_id)
    merged["source_task_ids"] = sorted(task_ids)
    return merged


def _edge_key(edge: dict[str, Any]) -> str:
    if edge.get("id"):
        return str(edge["id"])
    return "|".join(
        str(edge.get(key) or "")
        for key in ("source", "predicate", "target", "provenance")
    )


def _detect_gaps(
    germplasm: dict[str, Any],
    kg: dict[str, Any],
    rag: dict[str, Any],
    marker_qtl: dict[str, Any],
    phenotype_protocols: dict[str, Any],
    field_trials: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []

    for record in germplasm.get("results", []):
        availability = (record.get("availability") or "").lower()
        if availability in {"unknown", "limited", "unavailable"}:
            gaps.append(
                {
                    "type": "material_availability",
                    "severity": "blocking" if availability == "unavailable" else "high",
                    "target": record.get("accession_id"),
                    "message": "Material availability requires local confirmation.",
                }
            )
        genotype = (record.get("genotype_evidence") or "").lower()
        if (record.get("known_genes_qtls") or record.get("markers")) and (
            not genotype or "no genotype evidence" in genotype
        ):
            gaps.append(
                {
                    "type": "genotype_or_marker_validation",
                    "severity": "high",
                    "target": record.get("accession_id"),
                    "message": "Gene/QTL or marker claims need genotype evidence in the target background.",
                }
            )

    for item in kg.get("results", []):
        if item.get("data_confidence") == "low":
            gaps.append(
                {
                    "type": "low_confidence_kg_node",
                    "severity": "medium",
                    "target": item.get("id"),
                    "message": "KG clue has low confidence and should not be treated as proof.",
                }
            )
        for edge in item.get("edges", []):
            if edge.get("data_confidence") == "low":
                gaps.append(
                    {
                        "type": "low_confidence_kg_edge",
                        "severity": "medium",
                        "target": edge.get("id"),
                        "message": "KG relation has low confidence and needs supporting evidence.",
                    }
                )

    for record in marker_qtl.get("results", []):
        status = (record.get("validation_status") or "").lower()
        if any(token in status for token in ("pending", "needs", "unvalidated")):
            gaps.append(
                {
                    "type": "marker_assay_preflight",
                    "severity": "high",
                    "target": record.get("marker_id"),
                    "message": (
                        "Marker/QTL evidence needs local assay or parental polymorphism "
                        "confirmation before selection."
                    ),
                }
            )
        if record.get("data_confidence") == "low":
            gaps.append(
                {
                    "type": "low_confidence_marker_qtl",
                    "severity": "medium",
                    "target": record.get("marker_id"),
                    "message": "Marker/QTL library clue has low confidence.",
                }
            )

    for record in phenotype_protocols.get("results", []):
        if not record.get("decision_thresholds"):
            gaps.append(
                {
                    "type": "phenotype_protocol_threshold_missing",
                    "severity": "medium",
                    "target": record.get("protocol_id"),
                    "message": "Phenotyping protocol needs explicit advancement thresholds.",
                }
            )
        if record.get("data_confidence") == "low":
            gaps.append(
                {
                    "type": "low_confidence_phenotype_protocol",
                    "severity": "medium",
                    "target": record.get("protocol_id"),
                    "message": "Phenotyping protocol evidence has low confidence.",
                }
            )

    for record in field_trials.get("results", []):
        outcome = (record.get("decision_outcome") or "").lower()
        if any(token in outcome for token in ("pending", "requires", "template")):
            gaps.append(
                {
                    "type": "pending_local_field_validation",
                    "severity": "high",
                    "target": record.get("trial_id"),
                    "message": "Field-trial record is pending or not yet decision-grade.",
                }
            )
        if record.get("data_confidence") == "low":
            gaps.append(
                {
                    "type": "low_confidence_field_trial",
                    "severity": "medium",
                    "target": record.get("trial_id"),
                    "message": "Field-trial clue has low confidence and needs replication.",
                }
            )

    if not germplasm.get("results"):
        gaps.append(
            {
                "type": "missing_local_germplasm_hits",
                "severity": "high",
                "message": "No local germplasm records matched the current evidence queries.",
            }
        )
    if not rag.get("results"):
        gaps.append(
            {
                "type": "missing_local_rag_hits",
                "severity": "medium",
                "message": "No local RAG chunks matched the current evidence queries.",
            }
        )
    if marker_qtl.get("status") == "ok" and not marker_qtl.get("results"):
        gaps.append(
            {
                "type": "missing_local_marker_qtl_hits",
                "severity": "medium",
                "message": "No local marker/QTL records matched the current evidence queries.",
            }
        )
    if phenotype_protocols.get("status") == "ok" and not phenotype_protocols.get("results"):
        gaps.append(
            {
                "type": "missing_local_phenotype_protocol_hits",
                "severity": "medium",
                "message": "No local phenotyping protocols matched the current evidence queries.",
            }
        )
    if field_trials.get("status") == "ok" and not field_trials.get("results"):
        gaps.append(
            {
                "type": "missing_local_field_trial_hits",
                "severity": "medium",
                "message": "No local field-trial records matched the current evidence queries.",
            }
        )
    return gaps


def _downstream_guidance(gaps: list[dict[str, Any]]) -> list[str]:
    guidance = [
        (
            "Use local germplasm, KG, RAG, marker/QTL, phenotype protocol, "
            "and field-trial evidence before relying on model prior knowledge."
        ),
        (
            "Treat structured local hits as clues unless backed by local "
            "validation records or strong literature."
        ),
        "Explicitly carry evidence gaps into breeding_context.evidence_gaps and fallback_route.",
    ]
    if any(gap.get("severity") in {"blocking", "high"} for gap in gaps):
        guidance.append(
            "At least one high-severity gap was found; generated hypotheses "
            "should include a PAUSE/MODIFY-ready validation route."
        )
    return guidance


def _evidence_level(source_kind: str, confidence: Any) -> str:
    confidence_text = str(confidence or "").lower()
    if source_kind == "local_germplasm_resource":
        return "local_germplasm_high" if confidence_text == "high" else "local_germplasm_clue"
    if source_kind == "local_kg":
        return "local_kg_high_confidence" if confidence_text == "high" else "local_kg_clue"
    if source_kind == "local_marker_qtl_library":
        return "local_marker_qtl_high" if confidence_text == "high" else "local_marker_qtl_clue"
    if source_kind == "local_phenotype_protocol_library":
        return (
            "local_phenotype_protocol_high"
            if confidence_text == "high"
            else "local_phenotype_protocol_clue"
        )
    if source_kind == "local_field_trial_records":
        return "local_field_trial_high" if confidence_text == "high" else "local_field_trial_clue"
    return source_kind


def _status_from_confidence(confidence: Any) -> str:
    confidence_text = str(confidence or "").lower()
    if confidence_text == "high":
        return "supported"
    if confidence_text == "medium":
        return "needs_context"
    if confidence_text == "low":
        return "needs_validation"
    return "unknown"


def _slug(text: str, *, max_len: int = 80) -> str:
    safe = "_".join(str(text).strip().split())
    safe = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in safe)
    return (safe[:max_len] or "unknown").strip("_") or "unknown"


def _split_multi_values(value: Any) -> list[str]:
    text = str(value or "").replace(",", ";")
    return [part.strip() for part in text.split(";") if part.strip()]


def _compact_text(text: str, *, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."
