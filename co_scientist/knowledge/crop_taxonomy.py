"""Canonical crop names and multilingual aliases used across the system."""

from __future__ import annotations

import re
from typing import Any


# These IDs are persisted in evidence and acceptance artifacts.  Keep them
# stable, and add aliases here instead of creating crop-specific exceptions.
CROP_ALIASES: dict[str, tuple[str, ...]] = {
    "rice": (
        "rice", "paddy rice", "oryza sativa",
        "\u6c34\u7a3b", "\u7a3b", "\u7a3b\u4f5c",
    ),
    "foxtail millet": (
        "foxtail millet", "setaria italica",
        "\u8c37\u5b50", "\u5c0f\u7c73",
    ),
    "sorghum": (
        "sorghum", "sorghum bicolor", "\u9ad8\u7cb1",
    ),
    # Panicum miliaceum is commonly called both proso millet and broomcorn
    # millet.  It has one canonical ID to prevent a false scope mismatch.
    "proso millet": (
        "proso millet", "common millet", "broomcorn millet",
        "panicum miliaceum", "\u9ece\u5b50", "\u7ce0\u5b50", "\u9ecd",
    ),
    "pearl millet": (
        "pearl millet", "pennisetum glaucum", "cenchrus americanus",
        "\u73cd\u73e0\u7c9f",
    ),
    "finger millet": (
        "finger millet", "eleusine coracana",
        "\u7a37\u5b50", "\u9e21\u722a\u8c37",
    ),
    "barnyard millet": (
        "barnyard millet", "echinochloa esculenta", "echinochloa crus-galli",
        "\u7a17\u5b50", "\u7a17\u8c37",
    ),
    "buckwheat": (
        "buckwheat", "fagopyrum", "\u8349\u9ea6",
    ),
    "oat": (
        "oat", "oats", "avena", "\u71d5\u9ea6",
    ),
    "quinoa": (
        "quinoa", "chenopodium quinoa", "\u85dc\u9ea6",
    ),
    "wheat": (
        "wheat", "triticum", "\u5c0f\u9ea6",
    ),
    "barley": (
        "barley", "hordeum vulgare", "\u5927\u9ea6",
    ),
    "maize": (
        "maize", "corn", "zea mays", "\u7389\u7c73",
    ),
    "soybean": (
        "soybean", "soy bean", "glycine max",
        "\u5927\u8c46", "\u9ec4\u8c46",
    ),
    "mung bean": (
        "mung bean", "green gram", "vigna radiata", "\u7eff\u8c46",
    ),
    "adzuki bean": (
        "adzuki bean", "vigna angularis", "\u8d64\u5c0f\u8c46", "\u7ea2\u5c0f\u8c46",
    ),
    "chickpea": (
        "chickpea", "garbanzo", "cicer arietinum", "\u9e70\u5634\u8c46",
    ),
    "cowpea": (
        "cowpea", "vigna unguiculata", "\u8c47\u8c46",
    ),
    "peanut": (
        "peanut", "groundnut", "arachis hypogaea", "\u82b1\u751f",
    ),
    "potato": (
        "potato", "solanum tuberosum", "\u9a6c\u94c3\u85af", "\u571f\u8c46",
    ),
    "sweet potato": (
        "sweet potato", "ipomoea batatas", "\u7518\u85af", "\u7ea2\u85af",
    ),
}


def _normalize(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[_-]+", " ", text)
    return re.sub(r"\s+", " ", text)


def crop_candidates(value: Any) -> tuple[str, ...]:
    """Return all unambiguous crop IDs explicitly present in ``value``."""

    if value is None:
        return ()
    text = _normalize(value)
    if not text:
        return ()

    normalized_aliases = {
        canonical: tuple(_normalize(alias) for alias in aliases)
        for canonical, aliases in CROP_ALIASES.items()
    }
    matches: list[str] = []
    for canonical, aliases in normalized_aliases.items():
        if text in aliases:
            matches.append(canonical)
            continue
        for alias in aliases:
            if any("\u4e00" <= char <= "\u9fff" for char in alias):
                found = alias in text
            else:
                found = bool(re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text))
            if found:
                matches.append(canonical)
                break
    return tuple(matches)


def canonical_crop(value: Any) -> str | None:
    """Return a stable crop ID without unsafe or ambiguous matching.

    Exact aliases are preferred. English and Latin aliases use ASCII word
    boundaries; Chinese aliases use phrase matching. Unknown values remain
    normalized and are never guessed into a known crop.
    """

    if value is None:
        return None
    text = _normalize(value)
    if not text:
        return None
    matches = crop_candidates(text)
    if len(matches) == 1:
        return matches[0]
    return text


__all__ = ["CROP_ALIASES", "canonical_crop", "crop_candidates"]
