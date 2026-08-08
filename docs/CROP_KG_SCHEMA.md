# Lightweight Foxtail Millet Knowledge Graph Schema

This file defines the first local JSON format for the lightweight foxtail millet knowledge graph. It is intentionally small: the goal is to make crop, germplasm, trait, gene/QTL, marker, environment, evidence, strategy, and risk clues searchable by agents without claiming that the graph is complete proof.

## JSON Shape

```json
{
  "metadata": {},
  "nodes": [],
  "edges": []
}
```

Each node needs:

```text
id, name, type, summary, source_refs, data_confidence
```

Each edge needs:

```text
id, subject, predicate, object, evidence, source_refs, data_confidence
```

Allowed node types are:

```text
crop, germplasm, trait, gene_qtl, marker, environment, evidence,
breeding_strategy, risk, phenotype_protocol
```

Allowed confidence values are:

```text
high, medium, low
```

## Usage Boundary

The graph is a structured clue layer. Agents may use it to find relevant relationships and source URLs, but must not infer unlisted genes, markers, availability, causal effects, or validated breeding value. Literature tools and field validation remain required for final scientific claims.
