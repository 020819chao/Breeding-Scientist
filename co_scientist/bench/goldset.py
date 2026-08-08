"""Gold-set scoring for breeding bench runs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldEntity:
    """One target entity in a gold set."""

    name: str
    aliases: tuple[str, ...] = ()


@dataclass
class GoldSet:
    """Ordered list of target entities for one bench."""

    label: str
    description: str
    entities: list[GoldEntity] = field(default_factory=list)


@dataclass
class HitRecord:
    """Which gold entity hit, and which hypothesis surfaced it."""

    entity: str
    matched_alias: str
    hypothesis_id: str
    field: str


_ALPHANUM_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Normalize and split into alphanumeric runs.

    This handles breeding identifiers with punctuation such as Seita.5G404900,
    qPH5.1, CAPS-marker, and accession aliases without relying on fragile
    word-boundary regexes.
    """
    if not text:
        return []
    normed = unicodedata.normalize("NFKD", text)
    return [m.group(0).lower() for m in _ALPHANUM_RE.finditer(normed)]


def _contains_subseq(haystack: list[str], needle: list[str]) -> bool:
    """True if `needle` appears as a contiguous run in `haystack`."""
    if not needle:
        return False
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def _entity_matches(entity: GoldEntity, fields: dict[str, str]) -> list[HitRecord] | None:
    """Return the first matching HitRecord across `fields`, or None."""
    alias_token_pairs = [
        (n, toks) for n in (entity.name, *entity.aliases) if (toks := _tokens(n))
    ]
    for field_label, text in fields.items():
        if not text:
            continue
        text_toks = _tokens(text)
        for alias, alias_toks in alias_token_pairs:
            if _contains_subseq(text_toks, alias_toks):
                return [HitRecord(
                    entity=entity.name, matched_alias=alias,
                    hypothesis_id="", field=field_label,
                )]
    return None


def score_hypothesis_against_goldset(
    hypothesis: dict,
    goldset: GoldSet,
) -> list[HitRecord]:
    """Return every gold entity that appears in one hypothesis record."""
    hyp_id = hypothesis.get("id", "") or ""
    fields: dict[str, str] = {
        "title": str(hypothesis.get("title") or ""),
        "summary": str(hypothesis.get("summary") or ""),
        "full_text": str(hypothesis.get("full_text") or ""),
        "entities": " ".join(
            str(e) for e in (hypothesis.get("entities") or []) if isinstance(e, str)
        ),
    }
    citations = hypothesis.get("citations") or []
    if isinstance(citations, list):
        cit_text_parts: list[str] = []
        for c in citations:
            if isinstance(c, dict):
                cit_text_parts.append(str(c.get("title") or ""))
                cit_text_parts.append(str(c.get("excerpt") or ""))
        fields["citation"] = " ".join(cit_text_parts)

    out: list[HitRecord] = []
    for entity in goldset.entities:
        rec = _entity_matches(entity, fields)
        if rec is not None:
            rec[0].hypothesis_id = hyp_id
            out.extend(rec)
    return out


def score_candidate_against_goldset(
    hypotheses: list[dict],
    goldset: GoldSet,
) -> dict[str, list[HitRecord]]:
    """Run the matcher across every hypothesis for one bench candidate."""
    aggregate: dict[str, list[HitRecord]] = {}
    for h in hypotheses:
        for hit in score_hypothesis_against_goldset(h, goldset):
            aggregate.setdefault(hit.entity, []).append(hit)
    return aggregate


MINOR_GRAIN_DROUGHT_DEMO = GoldSet(
    label="minor-grain-drought-demo",
    description=(
        "Minor-grain drought-tolerance demo clues. The current seed crop pack "
        "uses foxtail millet examples: a named marker/QTL clue, a stress-response "
        "mechanism, and a local validation route."
    ),
    entities=[
        GoldEntity(
            name="Seita.5G404900",
            aliases=("5G404900", "qPH5.1", "qPH5_1", "STARP"),
        ),
        GoldEntity(
            name="SiDREB2-like",
            aliases=("DREB2-like", "SiDREB2", "DREB2"),
        ),
        GoldEntity(
            name="CAPS marker validation",
            aliases=("CAPS", "marker validation", "genotyping validation"),
        ),
    ],
)


MINOR_GRAIN_RESOURCE_DEMO = GoldSet(
    label="minor-grain-resource-demo",
    description=(
        "Minor-grain resource-route demo clues. The current seed crop pack uses "
        "foxtail millet parents and validation gates to test material-aware "
        "breeding routes."
    ),
    entities=[
        GoldEntity(
            name="Jingu 21",
            aliases=("Jingu21", "Jingu-21", "Jingu 21 recurrent parent"),
        ),
        GoldEntity(
            name="Zhangza 13",
            aliases=("Zhangza13", "Zhangza-13", "Zhangza 13 recurrent parent"),
        ),
        GoldEntity(
            name="263A",
            aliases=("263 A", "semi-dwarf 263A", "263A donor"),
        ),
        GoldEntity(
            name="BC1F1 validation",
            aliases=("BC1F1", "backcross validation", "first-cycle phenotyping"),
        ),
        GoldEntity(
            name="managed drought phenotyping",
            aliases=("managed stress", "water-stress phenotype", "SPAD"),
        ),
    ],
)


GOLDSETS: dict[str, GoldSet] = {
    MINOR_GRAIN_DROUGHT_DEMO.label: MINOR_GRAIN_DROUGHT_DEMO,
    MINOR_GRAIN_RESOURCE_DEMO.label: MINOR_GRAIN_RESOURCE_DEMO,
}
