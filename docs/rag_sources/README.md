# Local RAG Sources

Place local evidence materials here before running `scripts/build_rag_index.py`.

Supported in the first stable pass:

- Markdown files (`.md`)
- UTF-8 text files (`.txt`)

Use this directory for paper notes, abstracts, advisor-provided summaries, protocol notes, and curated literature excerpts. The RAG index treats these files as candidate evidence snippets. Keep source names clear enough to cite in reports.

## Source Templates

Do not put blank templates in this directory because they will be indexed as
evidence. Instead, copy one of the templates from `docs/templates/rag/`, fill it
with real source-bound content, then save the completed note here.

Template guide:

- `docs/RAG_SOURCE_TEMPLATE_GUIDE.md`

Available templates:

- `docs/templates/rag/paper_evidence_note_template.md`
- `docs/templates/rag/germplasm_material_note_template.md`
- `docs/templates/rag/marker_protocol_note_template.md`
- `docs/templates/rag/seita5g404900_caps_validation_template.md`
- `docs/templates/rag/seed_material_confirmation_template.md`
- `docs/templates/rag/field_observation_note_template.md`
- `docs/templates/rag/expert_judgment_note_template.md`

After adding completed notes, rebuild and test:

```bash
python scripts/build_rag_index.py
python scripts/search_evidence.py "Seita.5G404900 CAPS 263A lodging"
```
