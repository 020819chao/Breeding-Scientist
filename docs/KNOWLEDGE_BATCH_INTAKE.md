# Knowledge Batch Intake

Use a batch when new minor-grain data arrives from a researcher, a local
experiment, a paper extraction pass, or an advisor confirmation.

## Batch layout

```text
batch-2026-08-04-sorghum/
  manifest.json
  sources/
    germplasm_resources.csv
    marker_qtl_library.csv
    phenotype_protocol_library.csv
    field_trial_records.csv
    kg/
      sorghum.json
    rag/
      paper_note.md
      field_observation.md
  outputs/
```

Start from:

```text
docs/templates/knowledge_intake_batch/manifest.json
```

The manifest is the single entry point. It records the batch identity, crop
scope, and paths for all six knowledge inputs:

```text
1. Germplasm resource table
2. Crop-pack knowledge graph pack(s)
3. Local RAG source directory
4. Marker/QTL library
5. Phenotype protocol library
6. Field-trial record library
```

## Validate a batch

Run from the project root:

```bash
python scripts/validate_knowledge_batch.py path/to/batch-2026-08-04-sorghum
```

The command is read-only by default. It validates the manifest, rejects paths
that escape the batch directory, checks every CSV and KG schema, and builds an
in-memory RAG index.

To write a batch-local RAG index:

```bash
python scripts/validate_knowledge_batch.py path/to/batch-2026-08-04-sorghum --build-rag-index
```

This writes only the path declared by `sources.rag_index_json`, normally
`outputs/evidence_index.json`. It does not change the live configuration or
the current seed knowledge base.

## Intake boundary

Passing validation means the batch is structurally usable. It does not mean a
claim is biologically proven. Evidence Curator still assigns source strength,
tracks conflicts and gaps, and sends unresolved marker, phenotype, material,
or field-trial claims to Validation Planner and Risk Reviewer.

Keep original source files and provenance inside the batch. Do not replace a
seed file in `docs/templates/` with project data. Promotion into the active
knowledge base should be a separate, reviewed operation.
