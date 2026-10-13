"""Tests for the parts of `paperctl` that write into the vault.

The rest of the script is recoverable: a card can be rebuilt from its search
result, a review can be re-synthesised. Three things cannot, and every test
below is about one of them:

* `## 我的笔记` — the user's own writing.
* `topic_terms` — a judgement made by reading a review, not derivable from any
  data source.
* `domains` — which search produced the card. Nothing else records it.

So the assertions here are mostly *negative*: after an operation, what is still
byte-identical? Run with `pytest scripts/test_paperctl.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import paperctl  # noqa: E402

CARD = """---
type: paper
title: "An Example Paper"
authors: [A Author, B Author]
year: 2026
source: arxiv
source_id: "2609.12345"
topics: [cs.IR]
url: "https://arxiv.org/abs/2609.12345"
added: 2026-09-27
updated: 2026-09-27
status: unread
---

## 摘要（原文）

An abstract.

## 一句话提要

一句话。

## 我的笔记

手写的东西，**不能动**。
- 一条待办
"""


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """A vault holding one card, with a note the tests must never disturb."""
    papers = tmp_path / paperctl._SUBDIR / paperctl._SECTIONS["papers"]
    papers.mkdir(parents=True)
    (papers / "2026-an-example-paper-arxiv-260912345.md").write_text(CARD, encoding="utf-8")
    return tmp_path


def card(vault: Path) -> Path:
    return next((vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"]).glob("*.md"))


def notes_of(text: str) -> str:
    return text[text.index("## 我的笔记") :]


def run_enrich(vault: Path, payload, capsys, *extra: str) -> dict:
    terms = vault / "terms.json"
    terms.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    args = paperctl.main(
        ["card-enrich", "--json", str(terms), "--vault", str(vault), *extra]
    )
    assert args == 0
    return json.loads(capsys.readouterr().out)


# --- apply_enrichment ------------------------------------------------------


def test_terms_merge_instead_of_overwriting():
    """A second review of one topic must not drop the first review's theme."""
    meta = {"topic_terms": ["安全与投毒"]}
    meta, added, _ = paperctl.apply_enrichment(meta, topic_terms=["图结构 RAG"])
    assert meta["topic_terms"] == ["安全与投毒", "图结构 RAG"]
    assert added == ["图结构 RAG"]


def test_terms_dedupe_and_keep_their_order():
    meta = {"topic_terms": ["A", "B"]}
    meta, added, _ = paperctl.apply_enrichment(meta, topic_terms=["B", "C"])
    assert meta["topic_terms"] == ["A", "B", "C"]
    assert added == ["C"]


def test_replace_is_the_way_back():
    meta = {"topic_terms": ["打错的词"]}
    meta, _, _ = paperctl.apply_enrichment(meta, topic_terms=["对的词"], replace=True)
    assert meta["topic_terms"] == ["对的词"]


def test_replace_with_nothing_clears_the_key():
    meta, _, _ = paperctl.apply_enrichment({"topic_terms": ["A"]}, topic_terms=[], replace=True)
    assert "topic_terms" not in meta


def test_a_hand_written_string_is_read_as_a_one_item_list():
    """The contract says list; a human editing the card may not have agreed."""
    assert paperctl._as_list("图结构 RAG") == ["图结构 RAG"]
    assert paperctl._as_list(["A", " ", "B"]) == ["A", "B"]
    assert paperctl._as_list(None) == []


def test_domains_merge_and_have_no_replace():
    """A second search does not un-find the paper, so domains only ever grow."""
    meta, _, added = paperctl.apply_enrichment({"domains": ["ai"]}, domains=["finance"])
    assert meta["domains"] == ["ai", "finance"]
    assert added == ["finance"]


# --- write_card ------------------------------------------------------------


def test_write_card_records_the_domain(vault: Path):
    paper = {"source": "arxiv", "source_id": "2609.99999", "title": "New", "categories": ["cs.AI"]}
    paperctl.write_card(
        vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"], paper, domain="ai"
    )
    meta, _ = paperctl.split_frontmatter(
        next((vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"]).glob("*99999.md"))
        .read_text(encoding="utf-8")
    )
    assert meta["domains"] == ["ai"]


def test_a_rewrite_keeps_the_backfilled_terms(vault: Path, capsys):
    """The claim the whole design rests on: the search path cannot eat a theme."""
    papers = vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"]
    run_enrich(vault, [{"source": "arxiv", "source_id": "2609.12345",
                        "topic_terms": ["图结构 RAG"], "domains": ["ai"]}], capsys)

    # Now the search finds the paper again and rewrites every agent-owned field.
    paperctl.write_card(
        papers,
        {"source": "arxiv", "source_id": "2609.12345", "title": "Retitled",
         "authors": ["C"], "categories": ["cs.CL"]},
        domain="ai",
    )

    meta, _ = paperctl.split_frontmatter(card(vault).read_text(encoding="utf-8"))
    assert meta["topic_terms"] == ["图结构 RAG"]
    assert meta["domains"] == ["ai"]
    assert meta["title"] == "Retitled"  # agent-owned, overwritten as designed


def test_a_rewrite_leaves_the_notes_byte_identical(vault: Path):
    before = notes_of(card(vault).read_text(encoding="utf-8"))
    paperctl.write_card(
        vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"],
        {"source": "arxiv", "source_id": "2609.12345", "title": "Retitled",
         "abstract": "A different abstract."},
    )
    assert notes_of(card(vault).read_text(encoding="utf-8")) == before


# --- card-enrich -----------------------------------------------------------


def test_enrich_touches_the_frontmatter_only(vault: Path, capsys):
    before = card(vault).read_text(encoding="utf-8")
    result = run_enrich(
        vault,
        [{"source": "arxiv", "source_id": "2609.12345", "topic_terms": ["图结构 RAG"],
          "domains": ["ai"]}],
        capsys,
    )

    assert result["count"] == 1
    assert result["enriched"][0]["added_terms"] == ["图结构 RAG"]
    assert result["missing"] == []

    after = card(vault).read_text(encoding="utf-8")
    assert notes_of(after) == notes_of(before)
    # Everything below the frontmatter is byte-identical, notes included.
    assert before.split("---", 2)[2] == after.split("---", 2)[2]

    # Compare by key, not by line: `_dump_scalar` re-decides quoting on every
    # write, so a hand-quoted `title: "Plain"` comes back as `title: Plain`.
    # That is YAML-equivalent and must not read as "this test found a change".
    old_meta, _ = paperctl.split_frontmatter(before)
    new_meta, _ = paperctl.split_frontmatter(after)
    assert set(new_meta) - set(old_meta) == {"topic_terms", "domains"}
    assert {k: v for k, v in new_meta.items() if k in old_meta} == old_meta


def test_enrich_does_not_bump_updated(vault: Path, capsys):
    """`updated` means the card's content was refreshed. A theme is not content,
    and a bulk backfill must not make 81 old cards look new."""
    run_enrich(vault, [{"source": "arxiv", "source_id": "2609.12345",
                        "topic_terms": ["图结构 RAG"]}], capsys)
    meta, _ = paperctl.split_frontmatter(card(vault).read_text(encoding="utf-8"))
    # PyYAML resolves a bare date to datetime.date; the fallback parser leaves a
    # string. Either is fine here -- the point is that it did not become today.
    assert str(meta["updated"])[:10] == "2026-09-27"


def test_enrich_reports_a_card_it_cannot_find_and_creates_nothing(vault: Path, capsys):
    result = run_enrich(
        vault, [{"source": "arxiv", "source_id": "2609.00000", "topic_terms": ["X"]}], capsys
    )
    assert result["count"] == 0
    assert result["missing"] == [{"source": "arxiv", "source_id": "2609.00000"}]
    assert len(list((vault / paperctl._SUBDIR / paperctl._SECTIONS["papers"]).glob("*.md"))) == 1


def test_enrich_dry_run_writes_nothing(vault: Path, capsys):
    before = card(vault).read_text(encoding="utf-8")
    run_enrich(vault, [{"source": "arxiv", "source_id": "2609.12345",
                        "topic_terms": ["图结构 RAG"]}], capsys, "--dry-run")
    assert card(vault).read_text(encoding="utf-8") == before


def test_enrich_is_idempotent(vault: Path, capsys):
    payload = [{"source": "arxiv", "source_id": "2609.12345",
                "topic_terms": ["图结构 RAG"], "domains": ["ai"]}]
    run_enrich(vault, payload, capsys)
    once = card(vault).read_text(encoding="utf-8")
    second = run_enrich(vault, payload, capsys)

    assert card(vault).read_text(encoding="utf-8") == once
    assert second["enriched"][0]["changed"] is False
    assert second["enriched"][0]["added_terms"] == []
