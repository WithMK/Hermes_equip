"""Shared fail-closed evidence and completion checks."""
import re
from typing import Any, Mapping, Sequence


def citations(answer: str) -> tuple[str, ...]:
    # Square brackets are reserved for source IDs in grounded output.
    return tuple(dict.fromkeys(re.findall(r"\[([^\[\]\n]+)\]", answer)))


def validate_answer(answer: str, allowed: Sequence[str]) -> None:
    if not answer.strip():
        raise ValueError("answer is empty")
    cited = set(citations(answer))
    unknown = cited - set(allowed)
    if unknown:
        raise ValueError(f"unknown evidence citations: {sorted(unknown)}")
    if allowed and not cited:
        raise ValueError("answer does not cite any retrieved source")


def validate_finish(reason: str) -> None:
    # Empty is retained for legacy endpoints that omit finish_reason.
    if reason not in {"", "stop", "no_evidence"}:
        raise ValueError(f"incomplete completion: {reason}")


def bounded_sources(
    sources: Sequence[Mapping[str, Any]], budget: int
) -> list[dict[str, Any]]:
    """Keep complete evidence blocks only; never validate against omitted blocks."""
    selected = []
    for source in sources:
        item = dict(source)
        content = str(item.get("code") or item.get("text") or "").strip()
        if not content:
            continue
        # Same canonical block used by rendering; skip oversized blocks.
        if len(render_source(item)) > budget:
            continue
        selected.append(item)
        budget -= len(render_source(item)) + 2
    return selected


def render_source(source: Mapping[str, Any]) -> str:
    label = " | ".join(str(source.get(key)) for key in (
        "file_name", "relative_path", "class_name", "method_name", "section"
    ) if source.get(key))[:1000]
    return f"[{source['source_id']}] {label}\n{source.get('code') or source.get('text') or ''}".strip()


def render_sources(sources: Sequence[Mapping[str, Any]]) -> str:
    return "\n\n".join(render_source(item) for item in sources)
