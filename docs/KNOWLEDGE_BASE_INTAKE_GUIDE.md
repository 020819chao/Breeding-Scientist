# Knowledge Base Intake Guide

This guide defines the local knowledge-base intake surface for the minor-grain
breeding scientist system.

The system has three core knowledge sources:

```text
1. Germplasm resource table
2. Crop-pack knowledge graph
3. Local RAG source library
```

It also has three structured support libraries used by Evidence Curator:

```text
4. Marker/QTL library
5. Phenotype protocol library
6. Field-trial record library
```

Together, these inputs form the local evidence boundary for the Breeding
Evidence Graph.

## 0. Automated Batch Intake

New data should be prepared as one portable batch directory containing
`manifest.json` and any subset of the six supported source inputs. A batch
must contain at least one valid data record; omitted source types are treated
as empty incremental updates. After the batch is filled, run:

```bash
python scripts/import_knowledge_batch.py path/to/batch
```

The importer validates the batch first. If validation passes, it
automatically:

```text
1. merges structured CSV records by stable ID
2. merges crop KG nodes and edges by stable ID
3. archives RAG sources under the batch ID
4. rebuilds the local RAG evidence index
5. writes data/knowledge/active/catalog.json
```

The runtime reads the active catalog automatically. Existing records are
preserved even when a later batch omits their source category. An incoming
record with the same stable ID replaces the older record and is counted in the
import report. Use `--dry-run` to inspect the merge without activating it.

The downloadable full template is only a schema reference. When preparing an
incremental batch, keep only the files and manifest entries that contain new
records. A ZIP containing only headers, empty KG arrays, ignored RAG files, or
no source entries is rejected as an empty batch.

## 1. Germplasm Resource Table

Purpose:

```text
Records available or candidate breeding materials, their traits, availability,
known genes/QTL/markers, evidence, and risk notes.
```

Default file:

```text
docs/templates/germplasm_resources_public_seed.csv
```

Blank template:

```text
docs/templates/germplasm_resources_template.csv
```

Schema:

```text
docs/GERMPLASM_RESOURCE_SCHEMA.md
```

Validation:

```bash
python scripts/validate_germplasm.py
```

Used by:

```text
germplasm_search
Evidence Curator -> local_germplasm
Breeding Evidence Graph -> germplasm/material nodes
```

## 2. Crop-Pack Knowledge Graph

Purpose:

```text
Stores relationship evidence among crop, germplasm, traits, genes/QTL, markers,
environments, protocols, strategies, risks, and sources.
```

Blank template:

```text
docs/templates/crop_kg_pack_template.json
```

Current seed pack:

```text
docs/templates/foxtail_millet_kg_seed.json
```

Schema and filling guide:

```text
docs/CROP_KG_PACK_TEMPLATE.md
```

Validation:

```bash
python scripts/validate_crop_kg.py docs/templates/crop_kg_pack_template.json
python scripts/validate_crop_kg.py docs/templates/foxtail_millet_kg_seed.json
```

Registration:

```toml
[knowledge.crop_kg_packs]
sorghum = "./docs/templates/sorghum_kg_seed.json"
buckwheat = "./docs/templates/buckwheat_kg_seed.json"
```

Used by:

```text
crop_kg_search
Evidence Curator -> local_crop_kg
Breeding Evidence Graph -> KG-derived nodes and edges
```

## 3. Local RAG Source Library

Purpose:

```text
Stores local papers, notes, advisor confirmations, marker protocols, material
confirmation records, field observations, and expert judgments as searchable
text evidence.
```

Template directory:

```text
docs/templates/rag/
```

Filled source directory:

```text
docs/rag_sources/
```

Guide:

```text
docs/RAG_SOURCE_TEMPLATE_GUIDE.md
docs/RAG_MATERIAL_WORKFLOW.md
```

Build index:

```bash
python scripts/build_rag_index.py
```

Used by:

```text
evidence_search
Evidence Curator -> local_rag
Breeding Evidence Graph -> RAG evidence nodes
```

Important rule:

```text
Keep blank templates in docs/templates/rag/.
Only filled evidence files should go into docs/rag_sources/.
```

## 4. Marker/QTL Library

Purpose:

```text
Records marker, gene, QTL, haplotype, assay, validation status, and risk clues.
```

Test seed file:

```text
docs/templates/marker_qtl_library_seed.csv
```

Blank template for new data:

```text
docs/templates/marker_qtl_library_template.csv
```

Schema:

```text
docs/BREEDING_LIBRARIES_SCHEMA.md
```

Used by:

```text
Evidence Curator -> local_marker_qtl
Breeding Evidence Graph -> gene/QTL/marker nodes
```

## 5. Phenotype Protocol Library

Purpose:

```text
Records how a trait should be measured, under which target environment, at what
stage, with what replication and decision thresholds.
```

Test seed file:

```text
docs/templates/phenotype_protocol_library_seed.csv
```

Blank template for new data:

```text
docs/templates/phenotype_protocol_library_template.csv
```

Used by:

```text
Evidence Curator -> local_phenotype_protocols
Validation Planner -> phenotyping route design
```

## 6. Field-Trial Record Library

Purpose:

```text
Records field, nursery, greenhouse, preflight, or planned validation records.
It captures materials, environments, observed traits, genotype summaries,
decision outcomes, and risks.
```

Test seed file:

```text
docs/templates/field_trial_records_seed.csv
```

Blank template for new data:

```text
docs/templates/field_trial_records_template.csv
```

Used by:

```text
Evidence Curator -> local_field_trials
Validation Planner -> local validation feasibility
Risk Reviewer -> local evidence gaps
```

## Unified Validation

Run all local knowledge-base checks:

```bash
python scripts/validate_knowledge_base.py
```

Run all checks and write the RAG index:

```bash
python scripts/validate_knowledge_base.py --build-rag-index
```

Fail if the configured RAG index does not already exist:

```bash
python scripts/validate_knowledge_base.py --require-rag-index
```

The unified validator checks:

```text
germplasm CSV schema and row validity
all configured crop KG packs
RAG source directory and optional saved index
marker/QTL CSV
phenotype protocol CSV
field-trial CSV
```

## Recommended Intake Order

Use this order when a new crop or project batch arrives:

```text
1. Fill germplasm table first.
2. Fill crop KG pack with the most important relationships.
3. Add local RAG source files for papers, advisor notes, and experimental records.
4. Fill marker/QTL, phenotype protocol, and field-trial libraries.
5. Run scripts/validate_knowledge_base.py.
6. Register new crop KG packs in config.
7. Run a small session and inspect Evidence Curator outputs.
```

## Evidence Boundary

These knowledge sources are structured evidence clues, not automatic proof.
Agents must preserve:

```text
source_refs
data_confidence
validation_status
material availability
marker/assay readiness
single-environment limitations
conflicting or missing evidence
```

High-quality hypotheses should be generated only after the system can trace a
route from material and trait evidence to KG/RAG support, validation plan, and
risk review.
