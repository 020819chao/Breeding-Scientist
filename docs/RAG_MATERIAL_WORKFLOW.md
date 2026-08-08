# RAG Material Workflow

This workflow keeps local breeding materials source-bound, searchable, and safe
for the breeding-scientist agents to use.

## Scope

Use this workflow when adding local notes, protocols, seed records, advisor
comments, field observations, or curated paper summaries to the project RAG
layer.

The current stable evidence channels are:

- `germplasm_search`: accession and material clues from the local germplasm CSV.
- `crop_kg_search`: structured crop-pack relationship clues from the
  lightweight KG.
- `evidence_search`: source-bound text snippets indexed from
  `docs/rag_sources/`.
- `marker_qtl_library_seed.csv`: local marker, gene, and QTL clues for
  Evidence Curator.
- `phenotype_protocol_library_seed.csv`: local phenotyping protocol clues.
- `field_trial_records_seed.csv`: local field-trial and validation-record
  clues.

The three breeding-library CSV schemas are documented in
`docs/BREEDING_LIBRARIES_SCHEMA.md`. Validate and search them with:

```bash
python scripts/validate_breeding_libraries.py
python scripts/search_breeding_libraries.py "drought tolerance stay-green" --crop "foxtail millet"
```

## 1. Choose The Right Template

Keep blank templates in `docs/templates/rag/`. Do not put unfilled templates in
`docs/rag_sources/`, because everything in `docs/rag_sources/` can be indexed as
evidence.

Use these defaults:

| Material type | Template |
| --- | --- |
| Paper, abstract, or curated literature note | `docs/templates/rag/paper_evidence_note_template.md` |
| Parent, accession, donor, recurrent parent, or check material | `docs/templates/rag/germplasm_material_note_template.md` |
| Generic marker or assay protocol | `docs/templates/rag/marker_protocol_note_template.md` |
| Seita.5G404900/CAPS validation in 263A, Jingu 21, and Zhangza 13 | `docs/templates/rag/seita5g404900_caps_validation_template.md` |
| Seed inventory, germination, identity, and crossing readiness | `docs/templates/rag/seed_material_confirmation_template.md` |
| Field, nursery, greenhouse, or phenotyping observation | `docs/templates/rag/field_observation_note_template.md` |
| Advisor or breeder judgment | `docs/templates/rag/expert_judgment_note_template.md` |

## 2. Fill A Source-Bound Note

Copy the selected template into `docs/rag_sources/` only after replacing every
placeholder with real content.

Recommended file names for the current project:

- `seita5g404900_caps_validation_2026-07.md`
- `263a_jingu21_zhangza13_seed_confirmation_2026-07.md`
- `jingu21_zhangza13_lodging_greenhouse_2026-07.md`
- `seita5g404900_author_protocol_reply_2026-07.md`

Rules for a safe note:

- Keep one note focused on one source or one tightly related evidence set.
- Add DOI, URL, accession ID, lab notebook ID, email date, or internal record ID
  whenever available.
- Mark missing items explicitly as `unknown`, `pending`, or `failed`; do not
  leave them ambiguous.
- Use `Evidence Boundary` to say what the note does not prove.
- Delete every `<fill>` placeholder before indexing.

## 3. Rebuild The RAG Index

After adding or editing completed files in `docs/rag_sources/`, rebuild:

```bash
python scripts/build_rag_index.py
```

In the current Windows environment used for testing, the explicit interpreter is:

```powershell
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe scripts\build_rag_index.py
```

Expected output should report the indexed chunk count and write:

```text
data/rag/evidence_index.json
```

## 4. Verify Retrieval Before Running A Session

Run targeted searches and check that the intended local notes appear near the
top.

```bash
python scripts/search_evidence.py "Seita.5G404900 CAPS primer enzyme 263A"
python scripts/search_evidence.py "263A Jingu 21 Zhangza 13 seed germination accession"
python scripts/search_evidence.py "SiNF-YC2 supplementary evidence lodging dense planting"
```

If a note does not appear:

- add clearer keywords to `Suggested Search Keywords`;
- make the title and first section more specific;
- keep the claim in plain searchable wording;
- rebuild the index and search again.

## 5. Run A Small Validation Session

Use one focused question first. Keep budget and concurrency small so failures are
easy to inspect.

```powershell
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe -m co_scientist.cli run "鍩轰簬鏈湴RAG璧勬枡銆佺璐ㄨ祫婧愬簱鍜岃交閲忕煡璇嗗浘璋憋紝璁捐263A鐨凷eita.5G404900/CAPS绛変綅鍩哄洜瀵煎叆鏅嬭胺21鍜屽紶鏉?3鐨?0澶╁惎鍔ㄩ獙璇佹柟妗堛€傝姹傛槑纭緵浣撲翰鏈€佽疆鍥炰翰鏈€佹潗鏂欏彲寰楁€с€丆APS鏍囪寰呯‘璁や簨椤广€侀鎵硅〃鍨嬫寚鏍囥€丟O/PAUSE/STOP闂ㄦ锛屽苟鎶奡iNF-YC2鍙綔涓鸿ˉ鍏呰瘉鎹垨澶囬€夋柟鍚戙€? --n 1 --wall-clock 360 --budget-usd 0.5 --concurrency 1
```

After completion, check:

```powershell
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe -m co_scientist.cli status <session_id>
rg -n "local-rag://|germplasm://|millet-kg://|GO|PAUSE|STOP|CAPS|SiNF-YC2" data\artifacts\<session_id>
Get-Content data\artifacts\<session_id>\final\overview_audit.json -Encoding UTF8
```

A good validation run should have:

- session status `done`;
- `overview_audit.json` status `pass`;
- `local-rag://` citations in the hypothesis, review, or final report;
- explicit donor parent, recurrent parents, material availability, genotyping
  plan, phenotyping plan, and GO/PAUSE/STOP thresholds;
- SiNF-YC2 treated only as supplementary evidence or fallback.

## 6. Interpret Evidence Conservatively

Local RAG notes are not broad literature consensus. Treat them as bounded local
evidence.

Use this rule:

- If the note says a marker exists, the agent may plan marker validation.
- If the note says primer/enzyme details are unknown, the agent must flag marker
  readiness as a risk.
- If the local germplasm table lists a material, the agent may treat it as a
  candidate resource clue.
- If seed inventory, germination, or genotype has not been confirmed, the agent
  must keep material availability conditional.
- If the KG links a gene, trait, material, or strategy, the agent may use it for
  hypothesis construction, but final claims still need source URLs or explicit
  evidence gaps.

## 7. Current Baseline Check

The current baseline has passed the focused regression suite:

```text
37 passed
```

Covered tests:

- local RAG indexing/search behavior;
- millet KG validation/search behavior;
- germplasm validation behavior;
- tool-loop and raw tool-argument recovery behavior;
- final report audit behavior.

The small Seita.5G404900/CAPS validation session also completed with final audit
status `pass`.

