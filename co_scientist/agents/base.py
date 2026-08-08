"""BaseAgent — shared run-loop plumbing for all six specialized agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import aiosqlite

from ..config import Config
from ..llm.provider import LLMProvider
from ..models import Task, TaskResult
from ..safety.quoting import SAFETY_PREAMBLE
from ..tools.registry import ToolRegistry


@dataclass
class AgentDeps:
    """Bundle of resources every agent needs."""

    cfg: Config
    db: aiosqlite.Connection
    llm: LLMProvider
    tools: ToolRegistry


class BaseAgent:
    name: str = "base"

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    # Subclasses override
    async def execute(self, task: Task) -> TaskResult:  # pragma: no cover
        raise NotImplementedError

    # ----------------------------- helpers ----------------------------- #

    def _system_prompt_header(self) -> str:
        """Common safety preamble prepended to every agent's system prompt."""
        return (
            f"You are the {self.name} agent in a multi-agent breeding-scientist system "
            f"for crop improvement and grain breeding. Think like a plant breeder, "
            f"quantitative geneticist, field-trial designer, and translational crop "
            f"scientist: prioritize genetic gain, trait architecture, genotype-by-"
            f"environment effects, feasible crossing or selection strategies, and "
            f"field-validated outcomes. Operate carefully and cite your sources. "
            f"{SAFETY_PREAMBLE}"
        )

    @staticmethod
    def _final_tool_use(response, tool_name: str) -> dict[str, Any] | None:
        """Find the most recent tool_use block with the given name in a response.

        Returns the .input dict, or None if not present.
        """
        for block in reversed(response.raw.content or []):
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool_name:
                inp = getattr(block, "input", None)
                if not isinstance(inp, dict):
                    return None
                record = dict(inp)
                if set(record) == {"_raw_arguments"}:
                    recovered = _recover_raw_tool_arguments(str(record["_raw_arguments"]))
                    if recovered:
                        recovered["_recovered_from_raw_arguments"] = True
                        return recovered
                return record
        return None

    @staticmethod
    def _final_text(response) -> str:
        parts = []
        for block in response.raw.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "\n".join(parts).strip()


def _recover_raw_tool_arguments(raw: str) -> dict[str, Any]:
    """Recover key fields from truncated OpenAI-compatible tool JSON.

    Some OpenAI-compatible providers return a long function-call argument string
    that is cut off at max tokens. Full JSON parsing is then impossible, but the
    leading fields often contain enough structured content to preserve the task
    instead of marking it dead. This helper is intentionally conservative: it
    first tries normal JSON parsing, then extracts only complete JSON string
    values and leaves citations/evidence to each agent's observed-source
    fallback.
    """

    raw = raw.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    keys = (
        "title",
        "title_zh",
        "title_en",
        "statement",
        "statement_zh",
        "statement_en",
        "mechanism",
        "mechanism_zh",
        "mechanism_en",
        "anticipated_outcomes",
        "anticipated_outcomes_zh",
        "anticipated_outcomes_en",
        "novelty_argument",
        "novelty_argument_zh",
        "novelty_argument_en",
        "verdict",
        "kind",
        "notes",
    )
    out: dict[str, Any] = {}
    for key in keys:
        value = _extract_json_string_field(raw, key)
        if value is not None:
            out[key] = value

    for key in (
        "novelty",
        "correctness",
        "testability",
        "feasibility",
        "genetic_gain_potential",
        "selection_actionability",
        "field_trial_feasibility",
        "material_availability",
        "marker_readiness",
        "gxe_risk",
        "phenotyping_cost",
        "breeding_cycle_time",
        "deployment_risk",
    ):
        value = _extract_json_number_field(raw, key)
        if value is not None:
            out[key] = value

    entities = _extract_json_string_array(raw, "entities")
    if entities:
        out["entities"] = entities[:8]

    # Keep required fields present enough for downstream rendering. Source
    # evidence is still repaired from observed tool results by each agent.
    out.setdefault("entities", [])
    out.setdefault("citations", [])
    out.setdefault("evidence", [])
    return out


def _extract_json_string_field(raw: str, key: str) -> str | None:
    marker = f'"{key}"'
    pos = raw.find(marker)
    if pos < 0:
        return None
    colon = raw.find(":", pos + len(marker))
    if colon < 0:
        return None
    quote = raw.find('"', colon + 1)
    if quote < 0:
        return None

    chars: list[str] = []
    escaped = False
    for char in raw[quote + 1:]:
        if escaped:
            chars.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            try:
                return json.loads('"' + "".join(chars) + '"')
            except JSONDecodeError:
                return "".join(chars)
        chars.append(char)
    return None


def _extract_json_number_field(raw: str, key: str) -> float | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+(?:\.\d+)?)', raw)
    if not match:
        return None
    return float(match.group(1))


def _extract_json_string_array(raw: str, key: str) -> list[str]:
    marker = f'"{key}"'
    pos = raw.find(marker)
    if pos < 0:
        return []
    start = raw.find("[", pos + len(marker))
    end = raw.find("]", start + 1)
    if start < 0 or end < 0:
        return []
    try:
        parsed = json.loads(raw[start:end + 1])
    except JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]
