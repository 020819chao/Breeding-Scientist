# Crop KG Pack Template

This guide defines the standard template for adding a new minor-grain crop
knowledge-graph pack to the breeding scientist system.

Use this when preparing data for sorghum, broomcorn millet, proso millet,
buckwheat, oat, quinoa, or any future minor-grain crop.

## Files

Blank machine-readable template:

```text
docs/templates/crop_kg_pack_template.json
```

Current seed pack example:

```text
docs/templates/foxtail_millet_kg_seed.json
```

Recommended file name for a new pack:

```text
docs/templates/<crop_key>_kg_seed.json
```

Examples:

```text
docs/templates/sorghum_kg_seed.json
docs/templates/rice_kg_seed.json
docs/templates/buckwheat_kg_seed.json
docs/templates/broomcorn_millet_kg_seed.json
```

## JSON Shape

```json
{
  "metadata": {
    "name": "crop_kg_pack_template",
    "version": "0.1.0",
    "crop_key": "sorghum",
    "crop_name": "sorghum",
    "scientific_name": "Sorghum bicolor",
    "last_updated": "YYYY-MM-DD",
    "scope": "Local crop-pack KG for minor-grain breeding hypotheses.",
    "source_boundary": "Use traceable sources only.",
    "maintainer_notes": "Free text."
  },
  "nodes": [],
  "edges": []
}
```

The validator requires `nodes` and `edges` to be lists. Metadata is not used for
hard validation yet, but it should be filled for traceability.

## Required Node Fields

Every node must contain:

```text
id, name, type, summary, source_refs, data_confidence
```

Recommended optional fields:

```text
crop, aliases, notes, last_updated, availability, validation_status
```

Allowed node types:

```text
crop
germplasm
trait
gene_qtl
marker
environment
evidence
breeding_strategy
risk
phenotype_protocol
```

## Required Edge Fields

Every edge must contain:

```text
id, subject, predicate, object, evidence, source_refs, data_confidence
```

`subject` and `object` must be existing node IDs.

Recommended predicates:

```text
has_trait
has_trait_clue
carries_gene_or_qtl
carries_gene_or_qtl_clue
has_marker
can_support
adapted_to
supported_by
contradicted_by
requires_validation
has_risk
alternative_to
used_in_scheme
validates_trait
observes_trait
uses_material
```

## Confidence Values

Use only:

```text
high, medium, low
```

Suggested interpretation:

```text
high    local experiment record, advisor-confirmed record, or strong local KG/RAG relation
medium  same-crop publication, limited local record, or partially validated relation
low     related-crop analogy, model inference, seed clue, or unvalidated route idea
```

## ID Conventions

Use stable, lowercase prefixes:

```text
crop:<crop_key>
germplasm:<crop_key>-<accession_or_name>
trait:<trait_key>
gene_qtl:<gene_or_qtl_key>
marker:<marker_key>
environment:<environment_key>
evidence:<source_or_record_key>
breeding_strategy:<strategy_key>
risk:<risk_key>
phenotype_protocol:<protocol_key>
edge:<short_relation_key>
```

Examples:

```text
crop:sorghum
trait:drought_tolerance
germplasm:sorghum-btx623
gene_qtl:qstaygreen_1
marker:snp_qstaygreen_1
environment:managed_drought_nursery
edge:sorghum_has_drought_tolerance_target
```

## Minimal Filled Example

```json
{
  "metadata": {
    "name": "sorghum_kg_seed",
    "version": "0.1.0",
    "crop_key": "sorghum",
    "crop_name": "sorghum",
    "scientific_name": "Sorghum bicolor",
    "last_updated": "YYYY-MM-DD",
    "scope": "Local seed KG for sorghum breeding hypotheses.",
    "source_boundary": "Traceable sources only.",
    "maintainer_notes": "Seed data for system testing."
  },
  "nodes": [
    {
      "id": "crop:sorghum",
      "name": "sorghum",
      "type": "crop",
      "aliases": ["Sorghum bicolor"],
      "summary": "Target crop for this crop-pack KG.",
      "source_refs": "local project scope",
      "data_confidence": "medium"
    },
    {
      "id": "trait:drought_tolerance",
      "name": "drought tolerance",
      "type": "trait",
      "aliases": ["stay-green", "water-stress tolerance"],
      "summary": "Ability to maintain yield and canopy function under managed drought.",
      "source_refs": "replace with DOI, URL, local-rag URI, or local record ID",
      "data_confidence": "medium"
    }
  ],
  "edges": [
    {
      "id": "edge:sorghum_has_drought_tolerance_target",
      "subject": "crop:sorghum",
      "predicate": "has_trait",
      "object": "trait:drought_tolerance",
      "evidence": "Drought tolerance is a target trait in this crop-pack scope.",
      "source_refs": "local project scope",
      "data_confidence": "medium"
    }
  ]
}
```

## Registration

After creating a filled pack, add it to config:

```toml
[knowledge.crop_kg_packs]
sorghum = "./docs/templates/sorghum_kg_seed.json"
buckwheat = "./docs/templates/buckwheat_kg_seed.json"
```

The default foxtail millet seed pack is registered through
`knowledge.crop_kg_json`.

## Validation

Validate one pack:

```bash
python scripts/validate_crop_kg.py docs/templates/sorghum_kg_seed.json
```

Search one pack:

```bash
python scripts/search_crop_kg.py "drought tolerance" --json docs/templates/sorghum_kg_seed.json
```

Search through the system tool after registration:

```text
crop_kg_search(query="drought tolerance", crop="sorghum")
```

## Data Entry Checklist

Before handing a pack to the system, check:

```text
1. Every node has id, name, type, summary, source_refs, data_confidence.
2. Every edge points to existing subject and object node IDs.
3. Every source_refs value is traceable.
4. Local experiment/advisor records are labeled clearly.
5. Same-crop evidence and related-crop analogy are not mixed without notes.
6. Marker and QTL claims include validation status or an explicit validation gap.
7. Single-environment evidence is marked as a risk or limitation.
8. The file passes scripts/validate_crop_kg.py.
```

## Evidence Boundary

Crop KG packs are structured evidence clues. They help the Evidence Curator build
the Breeding Evidence Graph, but they are not final proof. Downstream agents must
preserve uncertainty and request validation when material availability, marker
polymorphism, causal effect, or multi-environment performance is not confirmed.

