# RAG Source Template Guide

This guide defines stable templates for local RAG materials. Keep templates in
`docs/templates/rag/`; copy completed files into `docs/rag_sources/` only after
replacing all placeholders with real evidence.

## Why This Format

Local RAG sources should behave like curated breeding evidence cards. Each file
should make clear:

- what claim the source can support;
- what claim it cannot support;
- which germplasm, marker, trait, environment, or protocol it concerns;
- whether it is literature evidence, local observation, protocol evidence, or
  expert judgment;
- what the safest next breeding action is.

This prevents the agents from treating weak local notes as broad literature
consensus.

## Template Types

- `paper_evidence_note_template.md`: curated paper or abstract notes.
- `germplasm_material_note_template.md`: material/accession/parent evidence.
- `marker_protocol_note_template.md`: marker, primer, assay, and genotyping notes.
- `seita5g404900_caps_validation_template.md`: project-specific CAPS
  validation record for 263A, Jingu 21, and Zhangza 13.
- `seed_material_confirmation_template.md`: project-specific seed inventory,
  germination, identity, and crossing-readiness record for 263A, Jingu 21, and
  Zhangza 13.
- `field_observation_note_template.md`: field, nursery, or greenhouse records.
- `expert_judgment_note_template.md`: advisor or breeder judgment with clear
  confidence and limits.

## Recommended File Names

Use names that search well and cite clearly:

- `seita5g404900_caps_marker_note.md`
- `263a_material_availability_note.md`
- `seita5g404900_caps_validation_2026-07.md`
- `263a_jingu21_zhangza13_seed_confirmation_2026-07.md`
- `jingu21_zhangza13_lodging_field_note.md`
- `sinfyc2_supplementary_evidence_note.md`
- `dense_planting_lodging_2026_field_observation.md`

## Completion Rules

Before copying a filled template into `docs/rag_sources/`:

1. Delete every placeholder such as `<fill>`.
2. Keep claims short and source-bound.
3. Add URLs, DOIs, accession IDs, or internal record IDs when available.
4. Explicitly mark unsupported inferences as `Evidence boundary`.
5. Keep one note focused on one source or one tightly related evidence set.

## Indexing Workflow

After adding or editing files in `docs/rag_sources/`, rebuild and test:

```bash
python scripts/build_rag_index.py
python scripts/search_evidence.py "Seita.5G404900 CAPS 263A lodging"
```

The expected result should include the specific local note you intended to add.
