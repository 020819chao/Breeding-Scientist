# RAG Baseline Stability Notes

This note records the current stable baseline for the breeding-scientist RAG
workflow after the Seita.5G404900/CAPS preflight validation pass.

## Baseline Status

The project now has a working local evidence layer for cautious breeding-project
planning:

- `evidence_search` retrieves source-bound snippets from `docs/rag_sources/`.
- `germplasm_search` provides accession and material clues from the local
  germplasm table.
- `crop_kg_search` provides lightweight crop-pack relationship clues.
- Final reports can cite exact `local-rag://<source_path>#L<start>-L<end>` URLs.
- Final reports now receive route-relevant local preflight cards directly from
  the RAG index, even if earlier agents omit those URLs.

The stable validation session is:

```text
ses_01KY3Q4MJMB3B1WS50PTABGC2Z
```

Artifacts:

- `data/artifacts/ses_01KY3Q4MJMB3B1WS50PTABGC2Z/final/overview_zh.md`
- `data/artifacts/ses_01KY3Q4MJMB3B1WS50PTABGC2Z/final/overview_en.md`
- `data/artifacts/ses_01KY3Q4MJMB3B1WS50PTABGC2Z/final/overview_audit.json`

The final audit passed in both Chinese and English.

## Current Preflight RAG Cards

These cards are indexed and should appear in final source maps for the
263A/Seita.5G404900 introgression route:

| Preflight area | Source file | Purpose |
| --- | --- | --- |
| CAPS validation | `docs/rag_sources/seita5g404900_caps_validation_preflight_2026-07.md` | Treat CAPS assay readiness as the first GO/PAUSE/STOP gate. |
| Seed/material confirmation | `docs/rag_sources/263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md` | Keep 263A, Jingu 21, and Zhangza 13 inventory, identity, germination, purity, and genotype as pending until verified. |
| Flowering synchrony and crossing risk | `docs/rag_sources/flowering_synchrony_crossing_risk_preflight_2026-07.md` | Make flowering overlap, fertility, crossing success, and seed set explicit 90-day gates. |
| BC1F1 first-cycle phenotyping | `docs/rag_sources/bc1f1_first_cycle_phenotyping_preflight_2026-07.md` | Require genotype-linked plant-level phenotyping before advancing. |

The current RAG index contains:

```text
26 chunks
```

## Stability Fixes Included

### Final Preflight URL Protection

Final synthesis now injects route-relevant local RAG preflight cards
from `data/rag/evidence_index.json`. This prevents reports from inventing
placeholder URLs such as `local-rag://preflight/...` and makes exact source
paths available during citation repair.

### Raw Tool Argument Recovery

The agent base layer can recover key fields from truncated OpenAI-compatible
tool arguments when providers return `_raw_arguments` instead of a parsed JSON
object. This keeps long breeding hypotheses from failing solely because the
provider truncated the tail of the JSON payload.

### String Breeding Context Tolerance

Hypothesis rendering now tolerates `breeding_context` as either a structured
object or a plain string. If the model returns a string, it is rendered as a
breeding-project context section rather than crashing hypothesis design.

## Regression Check

Focused regression suite passed:

```text
47 passed
```

Covered areas:

- RAG index/search behavior.
- Millet KG validation/search.
- Germplasm validation.
- Agent helper rendering and raw argument recovery.
- Tool-loop behavior.
- Final report audit behavior.
- Tool registry exposure.

## Remaining Real-World Evidence Gaps

The system is now stable enough to use, but the breeding project is still gated
by real data:

1. CAPS primer sequence, amplicon size, restriction enzyme, PCR program, and
   expected band patterns for 263A, Jingu 21, Zhangza 13, and F1 heterozygotes.
2. Actual seed inventory, lot IDs, seed source, seed age, storage condition,
   permission status, germination rate, purity, and abnormal seedling rate for
   263A, Jingu 21, and Zhangza 13.
3. Local Seita.5G404900 genotype confirmation for all three parents by CAPS,
   Sanger sequencing, or amplicon sequencing.
4. Flowering-time data under the planned greenhouse or nursery environment:
   days to emergence, booting, heading, pollen shed, stigma receptivity, and
   seed set.
5. BC1F1 plant-level data structure linking plant ID, cross ID, recurrent
   background, CAPS/sequencing call, plant height, basal internode traits,
   tiller number, heading date, lodging score, vigor, and fertility.

## Recommended Next Use

For the next real update, fill completed notes from the templates below and put
them into `docs/rag_sources/` only after placeholders are removed:

- `docs/templates/rag/seita5g404900_caps_validation_template.md`
- `docs/templates/rag/seed_material_confirmation_template.md`
- `docs/templates/rag/field_observation_note_template.md`

Then rebuild and verify:

```powershell
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe scripts\build_rag_index.py
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe scripts\search_evidence.py "Seita.5G404900 CAPS primer enzyme 263A"
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe scripts\search_evidence.py "263A Jingu 21 Zhangza 13 seed inventory germination purity"
```

Run a small validation session only after retrieval shows the intended notes.

