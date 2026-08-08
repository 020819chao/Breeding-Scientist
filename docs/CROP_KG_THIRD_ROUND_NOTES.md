# Millet KG Third-Round Notes

This round adds the first lightweight foxtail millet knowledge graph layer on top of the germplasm resource table.

## Completed

New data and schema:

- `docs/templates/foxtail_millet_kg_seed.json`
- `docs/CROP_KG_SCHEMA.md`

New KG helper module:

- `co_scientist/knowledge/crop_kg_graph.py`

It validates:

- JSON root shape
- required node and edge fields
- unique node and edge IDs
- controlled node types
- controlled confidence values
- edge endpoints referencing known nodes

New local tool:

```text
crop_kg_search
```

The tool is available to current six-agent workflow steps:

- Evidence Curator evidence curation
- Breeding Designer hypothesis design
- Risk Reviewer risk review
- Iteration Orchestrator-triggered revision steps

It is intentionally not available to:

- pairwise ranking / composite prioritization helper
- semantic deduplication helper
- final overview assembly helper

New scripts:

```bash
python scripts/validate_crop_kg.py
python scripts/search_crop_kg.py "CAPS Seita.5G404900" --node-type marker --limit 1
```

New tests:

- `co_scientist/tests/unit/test_crop_kg_graph.py`
- registry coverage in `co_scientist/tests/unit/test_tools_registry.py`

## Current Seed Coverage

The seed graph contains:

- 19 nodes
- 17 edges

Initial entity coverage includes:

- crop: foxtail millet
- traits: dense-planting architecture, lodging resistance, yield components, early maturity
- germplasm: 263A, Chuang 29, Xiaojinmiaoguzi, Bocaigen, Yugu1, Longgu7
- gene/QTL and marker: Seita.5G404900 and its CAPS marker
- evidence/environment: Chifeng 2023-2024 panel and Chifeng Inner Mongolia
- strategy/protocol/risk nodes for MAS, dense-planting lodging trials, dwarfing yield penalty, and single-environment evidence

## Usage Boundary

`crop_kg_search` results are local graph clues. They may guide hypothesis construction, review, and feasibility refinement, but they are not final literature evidence. Agents must not infer unlisted causal effects, markers, availability, or validated breeding value from the KG.

For final scientific claims, agents still need literature tools and source URLs. For material-specific claims, `germplasm_search` remains the accession-level resource check.

## Verification

Passed:

```text
python scripts/validate_crop_kg.py
python scripts/search_crop_kg.py "CAPS Seita.5G404900" --node-type marker --limit 1
D:\Develped\AssistDevelped\Anaconda\envs\breeding-scientist\python.exe -m pytest co_scientist\tests\unit\test_crop_kg_graph.py co_scientist\tests\unit\test_tools_registry.py
```

