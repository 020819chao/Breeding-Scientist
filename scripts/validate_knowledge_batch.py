"""Validate one portable knowledge-base intake batch.

This command deliberately delegates to the same validator used by the web
upload and folder-monitor flows. A batch may contain any subset of the six
supported source types, but it must contain at least one valid data record.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.knowledge.intake import IntakeCheck, validate_knowledge_batch  # noqa: E402
from co_scientist.knowledge.rag import build_evidence_index, save_evidence_index  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path, help="Directory containing manifest.json.")
    parser.add_argument(
        "--build-rag-index",
        action="store_true",
        help="Write outputs/evidence_index.json when a RAG source directory is supplied.",
    )
    args = parser.parse_args(argv)

    report = validate_knowledge_batch(args.batch_dir)
    if report.ok and args.build_rag_index and report.sources is not None:
        rag_dir = report.sources.rag_sources_dir
        if rag_dir is not None:
            output = report.sources.rag_index_json or report.batch_dir / "outputs" / "evidence_index.json"
            try:
                save_evidence_index(build_evidence_index(rag_dir), output)
            except OSError as exc:
                report.checks.append(IntakeCheck("rag_index", False, str(exc)))
            else:
                report.checks.append(IntakeCheck("rag_index", True, f"wrote {output}"))

    for check in report.checks:
        print(f"{'OK' if check.ok else 'ERROR'} {check.name}: {check.message}")

    if report.ok:
        print(f"Knowledge batch validation passed: {report.batch_dir}")
        return 0
    print(f"Knowledge batch validation failed: {report.batch_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
