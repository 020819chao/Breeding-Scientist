"""Shared Anthropic tool-use schemas for structured outputs.

Each agent gets one or more of these as required tool calls. Using tool-use
schemas (rather than "respond in JSON") is the most reliable structured-output
mechanism on the Anthropic API.
"""

from __future__ import annotations

from typing import Any

RECORD_HYPOTHESIS_TOOL: dict[str, Any] = {
    "name": "record_hypothesis",
    "description": (
        "Record a structured breeding hypothesis at the end of hypothesis design "
        "or route revision. Call this exactly once when your hypothesis is finalized. "
        "All citations must reference URLs that previously appeared in your "
        "tool_result outputs from search/fetch."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title":     {"type": "string", "description": "Short noun-phrase title."},
            "title_zh":  {"type": "string", "description": "Chinese short noun-phrase title."},
            "title_en":  {"type": "string", "description": "English short noun-phrase title."},
            "statement": {"type": "string", "description": "One sentence: the hypothesis."},
            "statement_zh": {"type": "string", "description": "Chinese one-sentence hypothesis."},
            "statement_en": {"type": "string", "description": "English one-sentence hypothesis."},
            "mechanism": {"type": "string", "description": "Detailed causal/mechanistic story."},
            "mechanism_zh": {"type": "string", "description": "Chinese detailed causal/mechanistic story."},
            "mechanism_en": {"type": "string", "description": "English detailed causal/mechanistic story."},
            "entities": {
                "type": "array", "items": {"type": "string"},
                "description": "Specific named actors (proteins, materials, datasets, agents, etc.).",
            },
            "anticipated_outcomes": {
                "type": "string",
                "description": "What would be observed if the hypothesis is true.",
            },
            "anticipated_outcomes_zh": {
                "type": "string",
                "description": "Chinese anticipated outcomes.",
            },
            "anticipated_outcomes_en": {
                "type": "string",
                "description": "English anticipated outcomes.",
            },
            "breeding_context": {
                "type": "object",
                "description": (
                    "Breeding-specific structured fields. Use concise but concrete values; "
                    "write 'unknown' only when the goal and literature genuinely do not specify it."
                ),
                "properties": {
                    "crop": {
                        "type": "string",
                        "description": "Crop/species or crop group, e.g. wheat, maize, rice, soybean.",
                    },
                    "target_trait": {
                        "type": "string",
                        "description": "Primary breeding trait(s) and direction of improvement.",
                    },
                    "germplasm": {
                        "type": "string",
                        "description": "Target germplasm, population, parents, donors, or breeding material.",
                    },
                    "donor_parent": {
                        "type": "string",
                        "description": "Donor parent/accession or source material for the target allele, trait, haplotype, or phenotype.",
                    },
                    "recurrent_parent": {
                        "type": "string",
                        "description": "Elite recurrent parent, recipient background, or target breeding population.",
                    },
                    "material_availability": {
                        "type": "string",
                        "description": "Whether named materials appear obtainable or locally recorded; include accession IDs, source clues, or 'unknown'.",
                    },
                    "target_population_of_environments": {
                        "type": "string",
                        "description": "Target environments, stress scenarios, regions, seasons, or management systems.",
                    },
                    "candidate_genes_qtl": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Candidate genes, QTL, haplotypes, markers, pathways, or genomic regions.",
                    },
                    "breeding_strategy": {
                        "type": "string",
                        "description": "Crossing, introgression, MAS, genomic selection, speed breeding, phenomic selection, editing, etc.",
                    },
                    "selection_scheme": {
                        "type": "string",
                        "description": "Concrete generation-by-generation selection route, e.g. F2 screen, BC1F1 foreground selection, BC2F2 fixation, GS cycle, DH line extraction.",
                    },
                    "phenotyping_plan": {
                        "type": "string",
                        "description": "Traits, assays, timing, environments, controls, and field/nursery measurements.",
                    },
                    "genotyping_plan": {
                        "type": "string",
                        "description": "Markers, sequencing/genotyping platform, genomic prediction, haplotyping, or validation plan.",
                    },
                    "validation_trial_design": {
                        "type": "string",
                        "description": "Concrete first validation population/trial design and decision criteria.",
                    },
                    "decision_thresholds": {
                        "type": "string",
                        "description": "Go/no-go thresholds for advancing, pausing, or discarding the breeding route.",
                    },
                    "cycle_time_estimate": {
                        "type": "string",
                        "description": "Expected time to first decisive evidence and to deployable lines, if known.",
                    },
                    "expected_breeding_value": {
                        "type": "string",
                        "description": "Expected genetic gain, stability, quality, resilience, cycle-time, or deployment benefit.",
                    },
                    "risks_tradeoffs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Likely risks: linkage drag, yield penalty, GxE instability, phenotyping bottleneck, cost, regulation, etc.",
                    },
                    "evidence_gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Missing literature, data, germplasm, or experiments needed before deployment.",
                    },
                    "fallback_route": {
                        "type": "string",
                        "description": "Backup breeding route if the main donor, marker, trait effect, or trial result fails.",
                    },
                },
                "required": [
                    "crop",
                    "target_trait",
                    "germplasm",
                    "donor_parent",
                    "recurrent_parent",
                    "material_availability",
                    "target_population_of_environments",
                    "candidate_genes_qtl",
                    "breeding_strategy",
                    "selection_scheme",
                    "phenotyping_plan",
                    "genotyping_plan",
                    "validation_trial_design",
                    "decision_thresholds",
                    "cycle_time_estimate",
                    "expected_breeding_value",
                    "risks_tradeoffs",
                    "evidence_gaps",
                    "fallback_route",
                ],
            },
            "breeding_context_zh": {
                "type": "object",
                "description": (
                    "Chinese version of breeding_context using the same keys and scientific IDs. "
                    "All explanatory values should be Chinese except stable names, markers, "
                    "accession IDs, URLs, and KG IDs."
                ),
            },
            "breeding_context_en": {
                "type": "object",
                "description": (
                    "English version of breeding_context using the same keys and scientific IDs."
                ),
            },
            "novelty_argument": {
                "type": "string",
                "description": "What is new relative to the cited literature.",
            },
            "novelty_argument_zh": {
                "type": "string",
                "description": "Chinese novelty argument.",
            },
            "novelty_argument_en": {
                "type": "string",
                "description": "English novelty argument.",
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url":     {"type": "string"},
                        "title":   {"type": "string"},
                        "excerpt": {"type": "string", "description": "Verbatim short quote from the source."},
                        "doi":     {"type": "string"},
                        "year":    {"type": "integer"},
                    },
                    "required": ["url", "title"],
                },
            },
            "strategy": {
                "type": "string",
                "enum": ["literature", "debate", "combine", "simplify",
                         "out_of_box", "feasibility", "assumption", "feedback_driven"],
                "description": "Strategy that produced this hypothesis (set by the agent).",
            },
            "parent_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Hypothesis IDs this one descends from (revision steps only).",
            },
        },
        "required": [
            "title", "title_zh", "title_en",
            "statement", "statement_zh", "statement_en",
            "mechanism", "mechanism_zh", "mechanism_en",
            "entities", "anticipated_outcomes", "breeding_context",
            "breeding_context_zh", "breeding_context_en",
            "anticipated_outcomes_zh", "anticipated_outcomes_en",
            "novelty_argument", "citations",
            "novelty_argument_zh", "novelty_argument_en",
        ],
    },
}


RECORD_REVIEW_TOOL: dict[str, Any] = {
    "name": "record_review",
    "description": (
        "Record a structured review of a hypothesis. Every claim in `evidence[]` "
        "must include a URL and a verbatim excerpt; the URL must have appeared in "
        "your tool_result outputs. Pick exactly one verdict."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": [
                    "already_explained",
                    "other_more_likely",
                    "missing_piece",
                    "neutral",
                    "disproved",
                ],
            },
            "kind": {
                "type": "string",
                "enum": ["full", "verification", "observation", "simulation"],
                "description": "Which review mode you ran.",
            },
            "novelty":     {"type": "number", "minimum": 0, "maximum": 1},
            "correctness": {"type": "number", "minimum": 0, "maximum": 1},
            "testability": {"type": "number", "minimum": 0, "maximum": 1},
            "feasibility": {"type": "number", "minimum": 0, "maximum": 1},
            "genetic_gain_potential": {"type": "number", "minimum": 0, "maximum": 1},
            "selection_actionability": {"type": "number", "minimum": 0, "maximum": 1},
            "field_trial_feasibility": {"type": "number", "minimum": 0, "maximum": 1},
            "material_availability": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Whether named donors, recurrent parents, populations, or resource panels are obtainable and well described.",
            },
            "marker_readiness": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Whether marker assays, haplotypes, genotyping platforms, or selection models are ready for breeder use.",
            },
            "gxe_risk": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Risk score where 1 means high genotype-by-environment instability risk.",
            },
            "phenotyping_cost": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Cost/burden score where 1 means high phenotyping burden.",
            },
            "breeding_cycle_time": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Cycle-time burden where 1 means slow to implement.",
            },
            "deployment_risk": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Deployment risk where 1 means high regulatory, agronomic, market, or operational risk.",
            },
            "assumptions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "assumption":   {"type": "string"},
                        "plausibility": {"type": "string", "enum": ["plausible", "uncertain", "implausible"]},
                        "rationale":    {"type": "string"},
                    },
                    "required": ["assumption", "plausibility", "rationale"],
                },
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim":   {"type": "string"},
                        "url":     {"type": "string"},
                        "excerpt": {"type": "string"},
                    },
                    "required": ["claim", "url", "excerpt"],
                },
            },
            "notes": {"type": "string", "description": "Anything that didn't fit the structured fields."},
        },
        "required": ["verdict", "kind", "evidence"],
    },
}


RECORD_SYSTEM_FEEDBACK_TOOL: dict[str, Any] = {
    "name": "record_system_feedback",
    "description": "Record a structured meta-review of the session's reviews + debates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "common_weaknesses":     {"type": "array", "items": {"type": "string"}},
            "common_strengths":      {"type": "array", "items": {"type": "string"}},
            "suggested_focus_areas": {"type": "array", "items": {"type": "string"}},
            "narrative":             {"type": "string"},
        },
        "required": ["narrative"],
    },
}


RECORD_RESEARCH_PLAN_TOOL: dict[str, Any] = {
    "name": "record_research_plan",
    "description": "Record the parsed research plan derived from the scientist's goal.",
    "input_schema": {
        "type": "object",
        "properties": {
            "objective":       {"type": "string"},
            "preferences":     {"type": "array", "items": {"type": "string"}},
            "constraints":     {"type": "array", "items": {"type": "string"}},
            "idea_attributes": {"type": "array", "items": {"type": "string"}},
            "crop": {
                "type": "string",
                "description": "Crop/species if explicit or strongly implied, e.g. foxtail millet, wheat, rice.",
            },
            "target_traits": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Target breeding traits and improvement directions, ordered by priority when possible.",
            },
            "target_environments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Target production environments, stresses, ecologies, management systems, or regions.",
            },
            "material_constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Constraints on parents, donors, local germplasm, seed inventory, or material boundaries.",
            },
            "preferred_breeding_strategies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Preferred or allowed strategies such as MAS, GS, backcrossing, crossing, phenotypic selection, editing.",
            },
            "validation_constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Phenotyping, genotyping, field trial, cost, time, or local validation constraints.",
            },
            "success_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete go/no-go criteria for a successful breeding hypothesis or validation plan.",
            },
            "initial_hypothesis_count": {
                "type": "integer",
                "minimum": 1,
                "description": "Initial hypothesis count requested by the scientist, if stated.",
            },
            "max_hypothesis_count": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of hypotheses requested or implied, if stated.",
            },
            "local_first": {
                "type": "boolean",
                "description": "True when local knowledge base, KG, RAG, local germplasm, or advisor records should be prioritized.",
            },
            "domain_hint":     {"type": "string"},
            "notes":           {"type": "string"},
        },
        "required": ["objective", "preferences", "idea_attributes"],
    },
}
