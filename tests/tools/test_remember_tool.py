"""Tests for the `remember` tool — the agent's mid-conversation memory write."""

import json
from pathlib import Path

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.remember import RememberTool
from nanobot.config.schema import ToolsConfig


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


def _entries(store: MemoryStore) -> list[dict]:
    # A rejected note leaves the journal untouched, so a missing file is an
    # empty journal rather than an error.
    if not store.history_file.exists():
        return []
    raw = store.history_file.read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in raw.splitlines()] if raw else []


def _ctx(tmp_path: Path, memory: MemoryStore | None) -> ToolContext:
    return ToolContext(config=ToolsConfig(), workspace=str(tmp_path), memory=memory)


def _conversation(session_key: str | None = "feishu:ou_test"):
    return request_context(
        RequestContext(channel="feishu", chat_id="ou_test", session_key=session_key)
    )


class TestWiring:
    def test_disabled_without_a_memory_store(self, tmp_path: Path) -> None:
        assert RememberTool.enabled(_ctx(tmp_path, None)) is False

    def test_enabled_with_a_memory_store(self, tmp_path: Path, store: MemoryStore) -> None:
        assert RememberTool.enabled(_ctx(tmp_path, store)) is True

    def test_create_without_a_memory_store_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="memory store"):
            RememberTool.create(_ctx(tmp_path, None))

    def test_loader_registers_it(self, tmp_path: Path, store: MemoryStore) -> None:
        from nanobot.agent.tools.loader import ToolLoader

        registry = ToolRegistry()
        registered = ToolLoader().load(_ctx(tmp_path, store), registry)
        assert "remember" in registered
        assert registry.has("remember")

    def test_subagent_scope_does_not_get_it(self, tmp_path: Path, store: MemoryStore) -> None:
        """`_scopes` stays {"core"}: batch subagents must not write long-term memory."""
        from nanobot.agent.tools.loader import ToolLoader

        registry = ToolRegistry()
        ToolLoader().load(_ctx(tmp_path, store), registry, scope="subagent")
        assert not registry.has("remember")

    def test_it_is_not_marked_read_only(self, store: MemoryStore) -> None:
        """It mutates history.jsonl, so it must not be parallelized as side-effect free."""
        assert RememberTool(store).read_only is False


class TestExecute:
    @pytest.mark.asyncio
    async def test_saves_the_note_with_session_key(
        self, store: MemoryStore, tmp_path: Path
    ) -> None:
        tool = RememberTool(store)
        with _conversation():
            result = json.loads(await tool.execute(note="Colin's vault root is ~/Desktop/MD files for ob"))

        assert result["saved"] is True
        entries = _entries(store)
        assert len(entries) == 1
        assert entries[0]["content"] == "Colin's vault root is ~/Desktop/MD files for ob"
        assert entries[0]["session_key"] == "feishu:ou_test"
        assert result["cursor"] == entries[0]["cursor"]

    @pytest.mark.asyncio
    async def test_tag_is_prefixed_into_the_content(self, store: MemoryStore) -> None:
        """Dream routes on these bracketed tags, so they must live in the text."""
        tool = RememberTool(store)
        with _conversation():
            result = json.loads(await tool.execute(note="prefers terse replies", tag="permanent"))

        assert result["tag"] == "permanent"
        assert _entries(store)[0]["content"] == "[permanent] prefers terse replies"

    @pytest.mark.asyncio
    async def test_omitted_tag_writes_the_bare_note(self, store: MemoryStore) -> None:
        tool = RememberTool(store)
        with _conversation():
            result = json.loads(await tool.execute(note="plain fact"))

        assert result["tag"] == "durable"
        assert _entries(store)[0]["content"] == "plain fact"

    @pytest.mark.asyncio
    async def test_cursor_advances_across_calls(self, store: MemoryStore) -> None:
        tool = RememberTool(store)
        with _conversation():
            first = json.loads(await tool.execute(note="one"))
            second = json.loads(await tool.execute(note="two"))

        assert second["cursor"] == first["cursor"] + 1

    @pytest.mark.asyncio
    async def test_whitespace_only_note_is_rejected_and_not_written(
        self, store: MemoryStore
    ) -> None:
        """`min_length=1` passes on spaces; an empty entry would still cost Dream a slot."""
        tool = RememberTool(store)
        with _conversation():
            result = await tool.execute(note="   \n  ")

        assert result.is_error is True
        assert _entries(store) == []

    @pytest.mark.asyncio
    async def test_works_without_a_bound_request_context(self, store: MemoryStore) -> None:
        """A background turn may have no session; the note is still worth keeping."""
        tool = RememberTool(store)
        await tool.execute(note="fact from a contextless run")

        assert "session_key" not in _entries(store)[0]


class TestSchema:
    def test_note_is_required_and_bounded(self, store: MemoryStore) -> None:
        schema = RememberTool(store).parameters
        assert schema["required"] == ["note"]
        assert schema["properties"]["note"]["maxLength"] == 2000
        assert schema["properties"]["note"]["minLength"] == 1

    def test_tag_enum_covers_every_dream_retention_tag(self, store: MemoryStore) -> None:
        schema = RememberTool(store).parameters
        assert schema["properties"]["tag"]["enum"] == [
            "skip",
            "correction",
            "permanent",
            "durable",
            "ephemeral",
        ]

    def test_tag_is_optional(self, store: MemoryStore) -> None:
        assert RememberTool(store).parameters["required"] == ["note"]

    @pytest.mark.asyncio
    async def test_over_long_note_is_truncated_at_the_tools_own_bound(
        self, store: MemoryStore
    ) -> None:
        """Schema validation normally rejects >2000 first; this pins the backstop for
        providers that skip validation, so a runaway note cannot bloat Dream's input.

        The stored text overshoots the bound slightly because the store appends its
        own truncation marker — that is the store's business, not this tool's.
        """
        tool = RememberTool(store)
        with _conversation():
            await tool.execute(note="x" * 5_000)

        content = _entries(store)[0]["content"]
        assert 2_000 <= len(content) <= 2_100
        assert content.startswith("x" * 100)


class TestHintLeak:
    def test_progress_hint_does_not_echo_the_note(self) -> None:
        """`_extract_arg` falls back to the first string arg, so a keyed template
        would print the note body whenever the optional `tag` is omitted."""
        from nanobot.providers.base import ToolCallRequest
        from nanobot.utils.tool_hints import format_tool_hints

        hint = format_tool_hints(
            [
                ToolCallRequest(
                    id="1",
                    name="remember",
                    arguments={"note": "SECRET-CONTENT-SHOULD-NOT-APPEAR"},
                )
            ]
        )
        assert hint == "remember"
        assert "SECRET" not in hint
