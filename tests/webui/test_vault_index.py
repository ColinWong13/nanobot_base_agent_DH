"""Tests for the vault reader behind the knowledge pages.

Two kinds of assertion live here, and they are both about *not lying to the
user*:

* a card that cannot be parsed must be **counted**, never silently dropped --
  a page that shows 80 papers when the vault holds 81 is wrong in a way the
  reader cannot see;
* a theme must never be labelled with the wrong term. The short labels and the
  body's headings are paired positionally, so a length mismatch means the
  pairing is a guess, and a guess here puts a false claim about the user's own
  review on screen.

The rest is the ordinary machinery: the cache, the registry join, and the
refusal to count a chat log as a literature question.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.webui import vault_index

PAPER = """---
type: paper
title: "An Example Paper"
year: 2026
source: arxiv
source_id: "2609.12345"
topics: [cs.IR]
topic_terms: [图结构 RAG]
domains: [ai]
added: 2026-09-27
status: unread
---

## 摘要（原文）

An abstract.

## 一句话提要

一句话提要在这里。

## 我的笔记

手写的东西。
"""

REVIEW = """---
type: review
topic: "Retrieval-Augmented Generation (RAG)"
topic_slug: rag
papers: 2
window: 2026-08-28 ~ 2026-09-28
themes: [图结构 RAG, 安全与投毒]
---

## Executive Summary

Body.

### Theme 1: 图结构 RAG 的"性价比"之争

Prose.

### Theme 2: 安全——投毒攻击面扩大，防御走向工具化

Prose.
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    """The index cache is module-global; a stale hit would leak between tests."""
    vault_index.invalidate_cache()
    yield
    vault_index.invalidate_cache()


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A vault with one card and one review, plus a registry naming `ai`.

    The registry lookup is redirected at the module, not at the environment: it
    reads `get_workspace_path()`, and without this patch a test that deletes its
    own registry would silently read the *live* one and pass anyway.
    """
    monkeypatch.setenv(vault_index.VAULT_ENV, str(tmp_path))
    monkeypatch.setattr(vault_index, "get_workspace_path", lambda *a, **k: tmp_path)
    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    reviews = vault_index.workspace_dir() / vault_index._REVIEWS_DIR
    papers.mkdir(parents=True)
    reviews.mkdir(parents=True)
    (papers / "2026-an-example-paper-arxiv-260912345.md").write_text(PAPER, encoding="utf-8")
    (reviews / "slr-rag.md").write_text(REVIEW, encoding="utf-8")

    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "domains.json").write_text(
        json.dumps({"domains": {"ai": {"label": "人工智能 / AI", "venues": []}}}),
        encoding="utf-8",
    )
    return tmp_path


# --- the vault must be read whole -------------------------------------------


def test_a_missing_workspace_is_a_file_not_found(tmp_path: Path, monkeypatch) -> None:
    """The route turns this into a 404 naming the path, which is a setup step,
    not a server fault."""
    monkeypatch.setenv(vault_index.VAULT_ENV, str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        vault_index.read_knowledge_index()


def test_a_broken_card_is_counted_not_dropped(vault: Path) -> None:
    """The failure mode this guards: a corrupt card vanishing from the page
    makes the vault look smaller than it is, and nothing says so."""
    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    (papers / "broken.md").write_text("---\n: : not yaml : :\n---\n\nbody\n", encoding="utf-8")

    index = vault_index.read_knowledge_index()
    assert index["counts"]["papers"] == 1  # the good one still renders
    assert index["counts"]["skipped"] == 1
    assert index["skipped"][0]["path"] == "broken.md"


def test_a_non_paper_file_in_the_papers_dir_is_ignored(vault: Path) -> None:
    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    (papers / "notes.md").write_text("---\ntype: note\n---\n\nprose\n", encoding="utf-8")
    assert vault_index.read_knowledge_index()["counts"]["papers"] == 1


def test_a_card_without_frontmatter_is_discovered_not_lost(vault: Path) -> None:
    """`split_frontmatter` in the skill is lenient about a missing block for
    the same reason: a hand-written card is still a card."""
    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    (papers / "hand-written.md").write_text("# Just prose\n", encoding="utf-8")
    index = vault_index.read_knowledge_index()
    assert index["counts"]["papers"] == 2
    assert index["counts"]["skipped"] == 0


# --- the cache --------------------------------------------------------------


def test_the_index_rebuilds_when_the_vault_changes(vault: Path) -> None:
    """mtime+size is the invalidation key. A cache that only ever grew would
    make every newly written card invisible until the gateway restarted."""
    before = vault_index.read_knowledge_index()
    assert before["counts"]["papers"] == 1

    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    (papers / "2026-second-arxiv-260999999.md").write_text(PAPER, encoding="utf-8")

    assert vault_index.read_knowledge_index()["counts"]["papers"] == 2


def test_the_cache_serves_the_same_object_on_a_hit(vault: Path) -> None:
    assert vault_index.read_knowledge_index() is vault_index.read_knowledge_index()


# --- themes: never guess a label --------------------------------------------


def test_themes_pair_the_short_label_with_its_heading(vault: Path) -> None:
    review = vault_index.read_knowledge_index()["reviews"][0]
    assert review["themes"] == [
        {"term": "图结构 RAG", "title": '图结构 RAG 的"性价比"之争'},
        {"term": "安全与投毒", "title": "安全——投毒攻击面扩大，防御走向工具化"},
    ]


def test_a_theme_count_mismatch_refuses_to_pair(vault: Path) -> None:
    """The load-bearing test. One label short and a positional pairing would
    silently relabel every theme after the gap -- the page would attribute the
    user's own argument to the wrong heading."""
    review_path = vault_index.workspace_dir() / vault_index._REVIEWS_DIR / "slr-rag.md"
    review_path.write_text(
        REVIEW.replace(
            "themes: [图结构 RAG, 安全与投毒]",
            "themes: [图结构 RAG]",
        ),
        encoding="utf-8",
    )

    themes = vault_index.read_knowledge_index()["reviews"][0]["themes"]
    # Falls back to the headings: long labels are cosmetic, wrong ones are not.
    assert [t["term"] for t in themes] == [
        '图结构 RAG 的"性价比"之争',
        "安全——投毒攻击面扩大，防御走向工具化",
    ]


def test_a_review_with_no_declared_themes_still_lists_its_headings(vault: Path) -> None:
    review_path = vault_index.workspace_dir() / vault_index._REVIEWS_DIR / "slr-rag.md"
    review_path.write_text(
        REVIEW.replace("themes: [图结构 RAG, 安全与投毒]\n", ""), encoding="utf-8"
    )
    assert len(vault_index.read_knowledge_index()["reviews"][0]["themes"]) == 2


def test_an_archive_is_not_listed_as_a_review(vault: Path) -> None:
    reviews = vault_index.workspace_dir() / vault_index._REVIEWS_DIR
    (reviews / "slr-rag-archive.md").write_text(
        REVIEW.replace("type: review", "type: review-archive"), encoding="utf-8"
    )
    assert vault_index.read_knowledge_index()["counts"]["reviews"] == 1


# --- derived tables ---------------------------------------------------------


def test_a_topic_a_card_carries_but_no_review_declares_still_gets_a_row(vault: Path) -> None:
    """It is on a card, so the page has to be able to show it -- an orphan term
    is a real inconsistency in the vault, not a reason to hide the card."""
    papers = vault_index.workspace_dir() / vault_index._PAPERS_DIR
    (papers / "orphan.md").write_text(
        PAPER.replace("topic_terms: [图结构 RAG]", "topic_terms: [没人声明过的词]"),
        encoding="utf-8",
    )
    topics = {t["term"]: t for t in vault_index.read_knowledge_index()["topics"]}
    assert topics["没人声明过的词"]["count"] == 1
    assert topics["没人声明过的词"]["review"] is None
    assert topics["没人声明过的词"]["title"] == "没人声明过的词"


def test_the_topic_title_comes_from_the_review(vault: Path) -> None:
    topics = {t["term"]: t for t in vault_index.read_knowledge_index()["topics"]}
    assert topics["图结构 RAG"]["title"] == '图结构 RAG 的"性价比"之争'
    assert topics["图结构 RAG"]["review"] == "rag"


def test_the_domain_label_is_read_from_the_registry(vault: Path) -> None:
    """Read, not stored on the card, so renaming a domain renames it here."""
    assert vault_index.read_knowledge_index()["domains"] == [
        {"id": "ai", "label": "人工智能 / AI", "count": 1}
    ]


def test_a_missing_registry_falls_back_to_the_id(vault: Path) -> None:
    """The page is about the vault and must render with no registry at all."""
    (vault / "registry" / "domains.json").unlink()
    assert vault_index.read_knowledge_index()["domains"][0]["label"] == "ai"


# --- past questions ---------------------------------------------------------


def _session_row(tmp_path: Path, key: str, records: list[dict]) -> dict:
    """Write a session file and return the row shape `read_inquiries` consumes.

    Spelled out rather than built by `_public_row`, which derives the path from
    a session-directory layout this reader does not care about: all it needs is
    `key` and a readable `path`.
    """
    path = tmp_path / f"{key.replace(':', '_')}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
    )
    return {
        "key": key,
        "created_at": "2026-09-28T10:00:00",
        "updated_at": "2026-09-28T10:05:00",
        "title": "",
        "preview": "",
        "path": str(path),
    }


def _ran_pipeline(question: str) -> list[dict]:
    return [
        {"role": "user", "content": "你好"},
        {"role": "user", "content": question},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "exec",
                        "arguments": '{"command": "python3 scripts/paperctl.py list"}',
                    }
                }
            ],
        },
    ]


def test_a_session_that_ran_the_pipeline_is_an_inquiry(tmp_path: Path) -> None:
    row = _session_row(tmp_path, "feishu:ou_1", _ran_pipeline("RAG 最近有什么新进展吗？"))
    inquiries = vault_index.read_inquiries([row])
    assert [i["channel"] for i in inquiries] == ["feishu"]
    assert inquiries[0]["questions"] == ["RAG 最近有什么新进展吗？"]


def test_a_session_that_only_mentions_the_pipeline_is_not(tmp_path: Path) -> None:
    """The dream-consolidation case, and the reason the test looks at tool
    *calls* rather than the raw text: those sessions read whole transcripts, so
    every pipeline word appears in their results without their having run
    anything. A raw-text grep puts them on the page."""
    row = _session_row(
        tmp_path,
        "dream:20260928-115708",
        [
            {"role": "user", "content": "You are running Dream. Consolidate the context."},
            {
                "role": "tool",
                "content": "... skills/literature-search/scripts/paperctl.py ... 资讯检索 ...",
            },
        ],
    )
    assert vault_index.read_inquiries([row]) == []


def test_chatter_is_not_shown_as_a_question(tmp_path: Path) -> None:
    """The feishu round really did collect the vault's cards, so its session
    qualifies -- but its first messages are "可以了", "不要", "？". A page that
    presents those as the user's explored interests is worse than a short one."""
    records = _ran_pipeline("我想看 RAG 最新进展")
    records[1:1] = [{"role": "user", "content": t} for t in ("可以了", "不要", "？", "怎么用")]
    row = _session_row(tmp_path, "feishu:ou_1", records)
    assert vault_index.read_inquiries([row])[0]["questions"] == ["我想看 RAG 最新进展"]


def test_a_resumed_work_framing_is_not_a_question(tmp_path: Path) -> None:
    row = _session_row(
        tmp_path,
        "feishu:ou_1",
        _ran_pipeline("Continue the active task from the working-memory checkpoint above."),
    )
    assert vault_index.read_inquiries([row]) == []


def test_the_day_context_is_a_library_fact_not_an_attribution(tmp_path: Path) -> None:
    """It is named `library_that_day` on purpose. The transcripts truncate tool
    output, so "what this question collected" is not recoverable -- claiming it
    would report 71 of 80 cards with no way for the reader to tell."""
    row = _session_row(tmp_path, "feishu:ou_1", _ran_pipeline("找我需要的论文，谢谢"))
    papers = [
        {"id": "2609.11111", "added": "2026-09-28"},
        {"id": "2609.22222", "added": "2026-09-28"},
        {"id": "2609.33333", "added": "2026-09-27"},
    ]
    inquiries = vault_index.read_inquiries([row], papers=papers)
    assert inquiries[0]["library_that_day"] == {
        "date": "2026-09-28",
        "papers": ["2609.11111", "2609.22222"],
    }


def test_a_date_typed_by_yaml_survives_json() -> None:
    """PyYAML resolves `added: 2026-09-27` to a `date`, which is not
    JSON-serialisable -- the card is fine and the response would be a 500."""
    assert vault_index._as_text(vault_index.date(2026, 9, 27)) == "2026-09-27"
    json.dumps({"added": vault_index._as_text(vault_index.date(2026, 9, 27))})
