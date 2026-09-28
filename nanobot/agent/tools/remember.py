"""Tool for writing a fact to long-term memory during a conversation."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_session_key
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

# Retention tags from templates/agent/dream.md. Dream routes a history entry by
# reading these bracketed prefixes out of the content, so the tag has to travel
# inside the text of the entry rather than in a field of its own.
_RETENTION_TAGS = ("skip", "correction", "permanent", "durable", "ephemeral")

# Well under MemoryStore's 64k defensive hard cap. That default exists only to
# catch an LLM echoing its input back; memory.py asks callers to bound their own
# content more tightly, and a fact worth remembering is a sentence, not a page.
_NOTE_MAX_CHARS = 2_000


@tool_parameters(
    tool_parameters_schema(
        note=StringSchema(
            "One atomic fact to keep, stated plainly (e.g. \"Colin's vault root is "
            "~/Desktop/MD files for ob\"). Write the fact, not the story of learning it.",
            min_length=1,
            max_length=_NOTE_MAX_CHARS,
        ),
        tag=StringSchema(
            "Retention hint for Dream. Defaults to durable when omitted. "
            "correction: replaces an older conflicting fact. "
            "permanent: preferences, identity, standing rules. "
            "durable: project context that holds while the work is active. "
            "ephemeral: useful now, expendable soon. "
            "skip: audit-only, never consolidate into saved memory.",
            enum=list(_RETENTION_TAGS),
        ),
        required=["note"],
    )
)
class RememberTool(Tool):
    """Append a fact to the memory journal for later consolidation."""

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return (
            "Save one fact to long-term memory so it outlives this conversation. "
            "Writes to memory/history.jsonl, which Dream later consolidates into "
            "MEMORY.md, USER.md, SOUL.md or a skill.\n"
            "Call this as soon as you learn something worth keeping: a correction "
            "from the user, a stable preference, a project decision, an "
            "infrastructure detail that cost real effort to establish.\n"
            "One fact per call — this is a memory journal, not a log. Skip anything "
            "already recorded, anything trivially re-derivable from the files, and "
            "transient status.\n"
            "Distinct from the `my` tool's scratchpad, which is session-local and "
            "lost on restart; this survives restarts and is read back by Dream."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.memory is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.memory is None:
            raise RuntimeError("RememberTool requires an initialized memory store")
        return cls(ctx.memory)

    async def execute(self, note: str, tag: str | None = None, **kwargs: Any) -> Any:
        text = note.strip()
        if not text:
            return self.error("note is empty after trimming whitespace; nothing was saved.")

        content = f"[{tag}] {text}" if tag else text
        cursor = self._memory.append_history(
            content,
            max_chars=_NOTE_MAX_CHARS,
            session_key=current_request_session_key(),
        )
        return json.dumps(
            {"saved": True, "cursor": cursor, "tag": tag or "durable"},
            ensure_ascii=False,
        )
