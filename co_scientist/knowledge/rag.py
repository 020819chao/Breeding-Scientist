"""Local evidence RAG indexing and deterministic search helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .crop_taxonomy import CROP_ALIASES, canonical_crop

SUPPORTED_EXTENSIONS = {".md", ".txt"}
IGNORED_SOURCE_NAMES = {"readme.md"}
DEFAULT_CHUNK_CHARS = 1400
DEFAULT_CHUNK_OVERLAP = 180


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    source_path: str
    title: str
    text: str
    start_line: int
    end_line: int
    crop_scope: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class EvidenceIndex:
    version: int
    source_dir: str
    chunk_count: int
    chunks: list[EvidenceChunk]


@dataclass(frozen=True)
class EvidenceSearchResult:
    score: float
    chunk: EvidenceChunk
    matched_terms: list[str]


def build_evidence_index(
    source_dir: Path,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> EvidenceIndex:
    """Build a small local RAG index from UTF-8 Markdown/text sources."""

    chunks: list[EvidenceChunk] = []
    if not source_dir.exists():
        return EvidenceIndex(version=1, source_dir=str(source_dir), chunk_count=0, chunks=[])

    seen_documents: set[str] = set()
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if _should_ignore_source(path):
            continue
        text = path.read_text(encoding="utf-8")
        document_id = document_id_for_text(text)
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        chunks.extend(
            _chunk_file(
                path,
                source_dir,
                chunk_chars=chunk_chars,
                overlap=chunk_overlap,
                document_id=document_id,
                text=text,
            )
        )

    return EvidenceIndex(version=1, source_dir=str(source_dir), chunk_count=len(chunks), chunks=chunks)


def save_evidence_index(index: EvidenceIndex, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": index.version,
        "source_dir": index.source_dir,
        "chunk_count": index.chunk_count,
        "chunks": [asdict(chunk) for chunk in index.chunks],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_evidence_index(path: Path) -> EvidenceIndex:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    raw_chunks = payload.get("chunks", [])
    source_text: dict[str, list[str]] = {}
    source_document_text: dict[str, list[str]] = {}
    for chunk in raw_chunks:
        source_path = str(chunk.get("source_path") or "")
        if not chunk.get("crop_scope"):
            source_text.setdefault(source_path, []).append(str(chunk.get("text") or ""))
        if not chunk.get("document_id"):
            source_document_text.setdefault(source_path, []).append(str(chunk.get("text") or ""))
    inferred_scope = {
        source_path: _extract_crop_scope("\n".join(texts), Path(source_path))
        for source_path, texts in source_text.items()
    }
    inferred_document_ids = {
        source_path: document_id_for_text("\n".join(texts))
        for source_path, texts in source_document_text.items()
    }
    chunks = []
    for chunk in raw_chunks:
        normalized_chunk = dict(chunk)
        normalized_chunk["crop_scope"] = (
            normalized_chunk.get("crop_scope")
            or inferred_scope.get(str(normalized_chunk.get("source_path") or ""))
        )
        normalized_chunk["document_id"] = (
            normalized_chunk.get("document_id")
            or inferred_document_ids.get(str(normalized_chunk.get("source_path") or ""))
        )
        chunks.append(EvidenceChunk(**normalized_chunk))
    return EvidenceIndex(
        version=int(payload.get("version") or 1),
        source_dir=str(payload.get("source_dir") or ""),
        chunk_count=len(chunks),
        chunks=chunks,
    )


def search_evidence_index(
    index: EvidenceIndex,
    query: str,
    *,
    source_filter: str | None = None,
    limit: int = 5,
) -> list[EvidenceSearchResult]:
    """Search local evidence chunks with stable TF-IDF-like keyword scoring."""

    query_terms = _terms(query)
    if not query_terms:
        return []

    source_filter_text = (source_filter or "").strip().lower()
    chunks = [
        chunk
        for chunk in index.chunks
        if not source_filter_text or source_filter_text in chunk.source_path.lower()
    ]
    if not chunks:
        return []

    doc_freq: dict[str, int] = {}
    tokenized: dict[str, list[str]] = {}
    for chunk in chunks:
        tokens = _terms(f"{chunk.title} {chunk.text}")
        tokenized[chunk.chunk_id] = tokens
        token_set = set(tokens)
        for term in query_terms:
            if term in token_set:
                doc_freq[term] = doc_freq.get(term, 0) + 1

    results: list[EvidenceSearchResult] = []
    for chunk in chunks:
        tokens = tokenized[chunk.chunk_id]
        token_count = max(len(tokens), 1)
        matched_terms = sorted({term for term in query_terms if term in tokens})
        if not matched_terms:
            continue

        score = 0.0
        for term in matched_terms:
            tf = tokens.count(term) / token_count
            idf = math.log((1 + len(chunks)) / (1 + doc_freq.get(term, 0))) + 1
            title_boost = 1.5 if term in _terms(chunk.title) else 1.0
            score += tf * idf * title_boost
        score += len(matched_terms) * 0.25
        results.append(EvidenceSearchResult(score=round(score, 6), chunk=chunk, matched_terms=matched_terms))

    return sorted(
        results,
        key=lambda result: (-result.score, result.chunk.source_path, result.chunk.start_line),
    )[:limit]


def _chunk_file(
    path: Path,
    source_dir: Path,
    *,
    chunk_chars: int,
    overlap: int,
    document_id: str | None = None,
    text: str | None = None,
) -> list[EvidenceChunk]:
    text = text if text is not None else path.read_text(encoding="utf-8")
    document_id = document_id or document_id_for_text(text)
    title = _extract_title(text) or path.stem
    crop_scope = _extract_crop_scope(text, path)
    lines = text.splitlines()
    chunks: list[EvidenceChunk] = []
    cursor = 0
    chunk_index = 1
    while cursor < len(lines):
        selected: list[str] = []
        start_line = cursor + 1
        char_count = 0
        line_idx = cursor
        while line_idx < len(lines) and (not selected or char_count < chunk_chars):
            line = lines[line_idx]
            selected.append(line)
            char_count += len(line) + 1
            line_idx += 1
        chunk_text = "\n".join(selected).strip()
        if chunk_text:
            rel_path = path.relative_to(source_dir).as_posix()
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{rel_path}#chunk-{chunk_index}",
                    source_path=rel_path,
                    title=title,
                    text=chunk_text,
                    start_line=start_line,
                    end_line=line_idx,
                    crop_scope=crop_scope,
                    document_id=document_id,
                )
            )
            chunk_index += 1
        if line_idx >= len(lines):
            break
        overlap_chars = 0
        rewind = line_idx
        while rewind > cursor and overlap_chars < overlap:
            rewind -= 1
            overlap_chars += len(lines[rewind]) + 1
        cursor = max(rewind, cursor + 1)
    return chunks


def _should_ignore_source(path: Path) -> bool:
    name = path.name.lower()
    return name in IGNORED_SOURCE_NAMES or name.startswith("_")


def document_id_for_text(text: str) -> str:
    """Return a stable content identity for one local evidence document."""

    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"doc:sha256:{digest}"


def deduplicate_source_documents(source_dir: Path) -> int:
    """Remove later duplicate source files, keeping the first sorted path."""

    seen_documents: set[str] = set()
    removed = 0
    if not source_dir.exists():
        return removed
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if _should_ignore_source(path):
            continue
        document_id = document_id_for_text(path.read_text(encoding="utf-8"))
        if document_id in seen_documents:
            path.unlink()
            removed += 1
            continue
        seen_documents.add(document_id)
    return removed


def _extract_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        if stripped:
            return stripped[:120]
    return None


def _extract_crop_scope(text: str, path: Path | None = None) -> str | None:
    """Extract a stable crop label from a source card or its file path."""

    scope_lines = [
        line.split(":", 1)[1]
        for line in text.splitlines()
        if ":" in line
        and line.split(":", 1)[0].strip().lstrip("-* ").strip().lower()
        in {"crop", "crop/species", "crop scope", "作物", "作物/物种"}
    ]
    for value in [*scope_lines, str(path or "")]:
        crop = _canonical_crop(value)
        if crop:
            return crop
    return None


def _canonical_crop(value: str) -> str | None:
    crop = canonical_crop(value)
    return crop if crop in CROP_ALIASES else None


def _terms(text: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]+", text.lower())
        if len(term) > 1
    ]
