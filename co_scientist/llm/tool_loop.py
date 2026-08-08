"""The assistant↔tool_use↔tool_result loop.

The agent gives us:
- An initial AgentCallSpec (system + user blocks, tools, tool_choice).
- A ToolRegistry (or just the subset relevant for this agent).
- A max_iters cap.

We drive turns until the model returns a non-tool-use stop_reason, or we hit
the cap (which surfaces as ToolLoopExhausted to the calling agent).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..ids import tool_run_id
from ..tools.base import ToolCtx
from ..tools.registry import ToolRegistry
from .anthropic_client import AgentCallSpec, AnthropicClient, AnthropicResponse, CallContext


class ToolLoopExhausted(RuntimeError):
    def __init__(self, agent: str, iters: int):
        super().__init__(f"tool loop for agent {agent!r} exhausted after {iters} iterations")
        self.agent = agent
        self.iters = iters


@dataclass
class ToolLoopResult:
    response: AnthropicResponse  # final assistant message
    iterations: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    seen_urls: set[str] = field(default_factory=set)
    observed_sources: list[dict[str, str]] = field(default_factory=list)
    """Union of URLs that appeared in any tool_result over the loop.

    Used by structured-output validation to reject hallucinated citations:
    record_hypothesis.citations[].url must be in this set.
    """


async def run_tool_loop(
    client: AnthropicClient,
    *,
    spec: AgentCallSpec,
    ctx: CallContext,
    registry: ToolRegistry,
    max_iters: int,
    parallel_cap: int = 4,
    tool_timeout_s: float = 30.0,
    force_terminal_tool: str | None = None,
    terminal_tool_names: tuple[str, ...] = (
        "record_hypothesis",
        "record_review",
        "record_system_feedback",
        "record_rubric_score",
        "record_research_plan",
    ),
    force_terminal_after_iters: int = 6,
    force_terminal_after_sources: int = 3,
) -> ToolLoopResult:
    """Drive the assistant ↔ tool_use ↔ tool_result loop.

    Loop termination:
    - stop_reason != "tool_use" — the model signalled end_turn.
    - The assistant response contains a `terminal_tool_names` call. These are
      virtual "structured output capture" tools (e.g. `record_hypothesis`):
      the assistant has already produced its final answer in tool_use.input,
      so dispatching the tool is unnecessary and we should not invite the
      model to call it again. Claude reliably ends its turn after calling
      these; Gemini / OpenAI-compat models do not, so we short-circuit
      explicitly. Without this short-circuit the loop will repeatedly
      re-invite the recording tool until max_iters and then raise
      ToolLoopExhausted — even though a perfectly good record was emitted
      on the first call.
    - max_iters reached — raise ToolLoopExhausted.

    `force_terminal_tool`: if set, the *final* allowed iteration forces
    `tool_choice` to that tool so the model must emit a record instead of
    spending its last turn on yet another search. This prevents the
    "looped until exhausted, produced nothing" failure mode where a model
    keeps verifying novelty and never commits.
    """
    seen_urls: set[str] = set()
    observed_sources: list[dict[str, str]] = []
    tool_calls_log: list[dict[str, Any]] = []
    iterations = 0
    current_spec = spec
    terminal_set = set(terminal_tool_names)

    last: AnthropicResponse | None = None

    while iterations < max_iters:
        iterations += 1
        # Optionally force the recording tool so the model commits instead of
        # burning the whole budget on open-ended literature search. We force on
        # the final iteration no matter what, and earlier once enough source
        # URLs have been observed to support a grounded record.
        call_spec = current_spec
        # if force_terminal_tool and iterations == max_iters:
        #     call_spec = AgentCallSpec(
        #         route=current_spec.route,
        #         system_blocks=current_spec.system_blocks,
        #         user_blocks=current_spec.user_blocks,
        #         tools=current_spec.tools,
        #         tool_choice={"type": "tool", "name": force_terminal_tool},
        #         max_output_tokens=current_spec.max_output_tokens,
        #         stop_sequences=current_spec.stop_sequences,
        #         extra_messages=current_spec.extra_messages,
        #     )
        should_force_terminal = False
        if force_terminal_tool:
            has_enough_sources = len(seen_urls) >= force_terminal_after_sources
            should_force_terminal = (
                iterations == max_iters
                or (iterations >= force_terminal_after_iters and has_enough_sources)
            )

        if force_terminal_tool and should_force_terminal:
            # DeepSeek may ignore a forced named tool when other tools remain
            # available. On finalization turns, expose only the terminal tool.
            forced_tools = [
                tool for tool in current_spec.tools if tool.get("name") == force_terminal_tool
            ]

            if not forced_tools:
                raise RuntimeError(
                    f"Terminal tool {force_terminal_tool!r} was not found in the available tools."
                )

            finalization_instruction = _finalization_instruction(force_terminal_tool, seen_urls)
            call_spec = AgentCallSpec(
                route=current_spec.route,
                system_blocks=current_spec.system_blocks,
                user_blocks=current_spec.user_blocks,
                tools=forced_tools,
                tool_choice={"type": "tool", "name": force_terminal_tool},
                max_output_tokens=current_spec.max_output_tokens,
                stop_sequences=current_spec.stop_sequences,
                extra_messages=[
                    *current_spec.extra_messages,
                    {
                        "role": "user",
                        "content": finalization_instruction,
                    }
                ],
            )
        resp = await client.call(call_spec, ctx)
        last = resp
        stop = getattr(resp.raw, "stop_reason", None)

        if stop != "tool_use":
            return ToolLoopResult(
                response=resp,
                iterations=iterations,
                tool_calls=tool_calls_log,
                seen_urls=seen_urls,
                observed_sources=observed_sources,
            )

        # Extract tool_use blocks from the assistant response
        tool_uses = [b for b in resp.raw.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return ToolLoopResult(
                response=resp,
                iterations=iterations,
                tool_calls=tool_calls_log,
                seen_urls=seen_urls,
                observed_sources=observed_sources,
            )

        # Early termination: if any tool_use is a terminal recording tool,
        # treat this response as the final assistant message. We still log
        # the call so observability sees it, but we do NOT dispatch (the
        # registry would return "unknown tool" anyway) and we do NOT loop.
        if any(getattr(b, "name", "") in terminal_set for b in tool_uses):
            for b in tool_uses:
                tool_calls_log.append(
                    {
                        "name": getattr(b, "name", ""),
                        "args": dict(getattr(b, "input", {}) or {}),
                        "is_error": False,
                        "duration_ms": 0,
                    }
                )
            return ToolLoopResult(
                response=resp,
                iterations=iterations,
                tool_calls=tool_calls_log,
                seen_urls=seen_urls,
                observed_sources=observed_sources,
            )

        tool_uses = tool_uses[:parallel_cap]
        kept_ids = {getattr(tu, "id", None) for tu in tool_uses}

        # Dispatch in parallel
        results = await asyncio.gather(
            *(_dispatch(registry, tu, ctx, tool_timeout_s) for tu in tool_uses),
            return_exceptions=False,
        )

        # Update url tracking + log
        for tu, r in zip(tool_uses, results, strict=True):
            tool_calls_log.append(
                {
                    "name": tu.name,
                    "args": tu.input,
                    "is_error": r["is_error"],
                    "duration_ms": r.get("duration_ms", 0),
                }
            )
            for u in _extract_urls(r.get("content")):
                seen_urls.add(u)
            existing_source_urls = {s["url"] for s in observed_sources}
            for source in _extract_sources(r.get("content")):
                if source["url"] not in existing_source_urls:
                    observed_sources.append(source)
                    existing_source_urls.add(source["url"])

        # Build next-turn spec: append the assistant message + a single user message
        # carrying all tool_result blocks. The assistant message must only carry
        # the tool_use blocks we actually dispatched — Anthropic requires every
        # tool_use to be paired with exactly one tool_result on the next turn.
        assistant_blocks = _content_to_dicts(resp.raw.content)
        assistant_blocks = [
            b for b in assistant_blocks if b.get("type") != "tool_use" or b.get("id") in kept_ids
        ]
        next_messages: list[dict[str, Any]] = list(current_spec.extra_messages)
        next_messages.append({"role": "assistant", "content": assistant_blocks})
        next_messages.append(
            {
                "role": "user",
                "content": [
                    _tool_result_block(tu, r) for tu, r in zip(tool_uses, results, strict=True)
                ],
            }
        )
        current_spec = AgentCallSpec(
            route=current_spec.route,
            system_blocks=current_spec.system_blocks,
            user_blocks=current_spec.user_blocks,
            tools=current_spec.tools,
            tool_choice=current_spec.tool_choice,
            max_output_tokens=current_spec.max_output_tokens,
            stop_sequences=current_spec.stop_sequences,
            extra_messages=next_messages,
        )

    assert last is not None
    raise ToolLoopExhausted(ctx.agent, iterations)


def _finalization_instruction(force_terminal_tool: str, seen_urls: set[str]) -> str:
    url_hint = ""
    if seen_urls:
        sample_urls = "\n".join(f"- {u}" for u in sorted(seen_urls)[:8])
        url_hint = (
            "\n\nObserved source URLs from prior tool results; use these rather "
            "than inventing new URLs:\n"
            f"{sample_urls}"
        )
    if force_terminal_tool == "record_review":
        return (
            "Finalization turn. Do not perform any further literature search. "
            "Call record_review exactly once now. Use the literature/tool-result "
            "context already provided in this conversation. If any source URLs "
            "were observed, include at least one of those URLs in evidence[] with "
            "a short excerpt or summary from the tool result. Do not invent URLs. "
            "Keep the tool arguments compact: at most six assumptions, at most six "
            "evidence entries, concise notes, and no long report-style sections."
            f"{url_hint}"
        )
    if force_terminal_tool == "record_hypothesis":
        return (
            "Finalization turn. Do not perform any further literature search. "
            "Call record_hypothesis exactly once now. Use the literature/tool-result "
            "context already provided in this conversation. If any source URLs "
            "were observed, include at least one of those URLs in citations[] with "
            "a short excerpt or summary from the tool result. Do not invent URLs. "
            "Keep the tool arguments compact: one or two concise sentences per "
            "string field, at most five entities, at most five risks/evidence gaps, "
            "and no long report-style paragraphs."
            f"{url_hint}"
        )
    return (
        "Finalization turn. Do not perform any further tool calls. "
        f"Call {force_terminal_tool} exactly once now."
        f"{url_hint}"
    )


# --------------------------------------------------------------------------- #
# helpers


async def _dispatch(
    registry: ToolRegistry, tool_use, ctx: CallContext, timeout_s: float
) -> dict[str, Any]:
    """Run one tool call. Returns a dict with content + is_error + duration."""
    t0 = time.monotonic()
    run_id = tool_run_id()
    tctx = ToolCtx(
        cfg=registry._cfg,
        db=None,  # tools use their own write paths; DB writes go via repos
        session_id=ctx.session_id,
        task_id=ctx.task_id,
        run_id=run_id,
    )
    args = dict(tool_use.input) if isinstance(tool_use.input, dict) else {"args": tool_use.input}
    try:
        result = await asyncio.wait_for(registry.call(tool_use.name, args, tctx), timeout=timeout_s)
    except TimeoutError:
        return {
            "is_error": True,
            "content": {"error": f"tool {tool_use.name!r} timed out"},
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    return {
        "is_error": bool(result.is_error),
        "content": _tool_result_content(result),
        "duration_ms": result.duration_ms,
    }


def _tool_result_content(result) -> Any:
    if result.is_error:
        return {"error": result.error_message or "unknown error"}
    return result.content if result.content is not None else {"ok": True}


def _tool_result_block(tool_use, r: dict[str, Any]) -> dict[str, Any]:
    body = r["content"]
    return {
        "type": "tool_result",
        "tool_use_id": tool_use.id,
        "content": _content_to_text(body),
        "is_error": r["is_error"],
    }


def _content_to_text(body: Any) -> str:
    if isinstance(body, str):
        return body
    return json.dumps(body, default=str, ensure_ascii=False)[:20_000]


def _content_to_dicts(content) -> list[dict[str, Any]]:
    """Convert SDK content blocks to plain dicts for re-sending.

    Thinking blocks must preserve their `signature` verbatim — Anthropic rejects
    a continuation turn that omits it.
    """
    out: list[dict[str, Any]] = []
    for b in content:
        t = getattr(b, "type", None)
        if t == "text":
            out.append({"type": "text", "text": getattr(b, "text", "")})
        elif t == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": getattr(b, "id", ""),
                    "name": getattr(b, "name", ""),
                    "input": getattr(b, "input", {}),
                }
            )
        elif t == "thinking":
            d: dict[str, Any] = {"type": "thinking", "thinking": getattr(b, "thinking", "")}
            sig = getattr(b, "signature", None)
            if sig:
                d["signature"] = sig
            out.append(d)
        elif t == "redacted_thinking":
            data = getattr(b, "data", None)
            if data:
                out.append({"type": "redacted_thinking", "data": data})
    return out


_URL_RE_KEYS = ("url", "abs_url", "pdf_url", "pubmed_url")
_SUPPORTED_SOURCE_URL_PREFIXES = ("http://", "https://", "local-rag://")


def _extract_urls(body: Any) -> list[str]:
    """Pull URLs out of nested tool_result content (best effort)."""
    out: list[str] = []
    _walk_urls(body, out)
    return out


def _walk_urls(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if (
                k in _URL_RE_KEYS
                and isinstance(v, str)
                and v.startswith(_SUPPORTED_SOURCE_URL_PREFIXES)
            ):
                out.append(v)
            else:
                _walk_urls(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_urls(item, out)


def _extract_sources(body: Any) -> list[dict[str, str]]:
    """Pull source URL + title + excerpt from nested tool_result content."""
    out: list[dict[str, str]] = []
    _walk_sources(body, out)
    return out


def _walk_sources(node: Any, out: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        url = _first_url(node)
        if url:
            title = str(node.get("title") or node.get("name") or "Tool-observed source")
            excerpt = _first_excerpt(node)
            out.append({"url": url, "title": title[:300], "excerpt": excerpt[:1200]})
        for value in node.values():
            _walk_sources(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_sources(item, out)


def _first_url(node: dict[str, Any]) -> str | None:
    for key in _URL_RE_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value.startswith(_SUPPORTED_SOURCE_URL_PREFIXES):
            return value
    return None


def _first_excerpt(node: dict[str, Any]) -> str:
    for key in ("excerpt", "abstract", "summary", "text", "content"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return "Source URL observed in a literature/search/fetch tool result."
