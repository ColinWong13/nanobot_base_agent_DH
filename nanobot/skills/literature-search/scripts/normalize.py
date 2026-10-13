#!/usr/bin/env python3
"""Normalise external search-skill output into paperctl's paper shape.

The pipeline never issues an HTTP request of its own — retrieval belongs to the
`literature-search-arxiv` / `literature-search-openalex` skills. This script is
the seam between them and `paperctl.py`: it reads whatever shape those skills
emit and produces the normalised paper records that `paperctl card-write` takes.

It also performs **venue auto-tiering** (planning/info-retrieval-agent.md §4.2):
the venue name is recovered from arXiv's `comment` / `journal_ref` or from
OpenAlex's `primary_location.source`, then matched against the domain registry
to assign a tier. When nothing matches, the tier is left empty rather than
guessed.

Usage:
    uv run arxiv_search.py --query '...' --max_results 20 | python3 normalize.py --source arxiv --domain ai
    python3 normalize.py --source openalex --domain finance < openalex.json
    python3 normalize.py --source arxiv --domain ai --in arxiv.json --out papers.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent


def _resolve_workspace() -> Path:
    """Locate the agent workspace.

    Not derived from this file's path: the skill ships both inside a workspace
    (``<workspace>/skills/<name>/``) and inside the installed package
    (``nanobot/skills/<name>/``), and only the first makes that derivation
    correct. The workspace is a configured value, so it is read from the config
    -- the same helper as in ``paperctl.py``.
    """
    env = os.environ.get("NANOBOT_WORKSPACE")
    if env:
        return Path(env).expanduser()
    try:
        config = json.loads((Path.home() / ".nanobot" / "config.json").read_text("utf-8"))
        configured = config.get("agents", {}).get("defaults", {}).get("workspace")
        if configured:
            return Path(configured).expanduser()
    except (OSError, ValueError):
        pass
    return Path.home() / ".nanobot" / "workspace"


_WORKSPACE = _resolve_workspace()
_REGISTRY = _WORKSPACE / "registry" / "domains.json"

# arXiv ids arrive as '2005.11401v3'; the canonical id drops the version.
_VERSION_SUFFIX = re.compile(r"v\d+$")

# An arXiv `comment` is free text. It says as much about where a paper was
# *not* accepted as where it was, and `journal_ref` is empty on essentially
# every preprint -- measured 2026-09-27 on 60 recent cs.CL papers: 0 of 60 had
# a journal_ref. Of the 14 whose comment named a venue, 7 said
# "submitted"/"preprint" and 3 named a workshop co-located with the venue.
# Recording `venue: ICASSP, venue_tier: B` for a paper that was only submitted
# is a factual error, so a comment match needs positive evidence of acceptance.
_ACCEPTED = re.compile(r"\b(accept\w*|to appear|forthcoming|camera[- ]ready)\b", re.I)
_DECLINED = re.compile(
    r"\b(submit\w*|under review|preprint|in preparation|co-located)\b", re.I
)
_WORKSHOP = re.compile(r"\bworkshops?\b", re.I)


def load_registry(domain: str) -> dict:
    if not _REGISTRY.exists():
        return {"venues": []}
    domains = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("domains", {})
    return domains.get(domain) or {"venues": []}


def build_venue_index(domain: dict) -> list[tuple[str, dict, bool]]:
    """Return (match_string, venue, case_sensitive) triples, longest first.

    Two tiers of confidence, because the registry contains venue abbreviations
    that are also ordinary English words:

    * **Full names** ("Conference on Neural Information Processing Systems")
      are unambiguous, so they match case-insensitively.
    * **Abbreviations of 3+ chars** ("NeurIPS", "ACL", "CVPR") match
      case-sensitively. Prose writes "is", "ai", "vr" in lower case; a venue
      is written in its own casing.
    * **Abbreviations of 1-2 chars** ("AI" = Artificial Intelligence journal,
      "IS" = Information Systems, "VR") are **not matchable at all**. Measured
      2026-09-27: case-insensitive matching labelled three unrelated RAG papers
      with `venue=AI tier=A` / `venue=IS tier=B` off the words "AI" and "is" in
      their abstracts. A missing tier is recoverable; a wrong one silently
      promotes junk. Leave it empty — that is what "填不上时留空，不猜" means.
    """
    pairs: list[tuple[str, dict, bool]] = []
    for venue in domain.get("venues", []):
        name = venue.get("name") or ""
        if len(name) >= 3:
            pairs.append((name, venue, True))
        if full := venue.get("full_name"):
            pairs.append((full, venue, False))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def match_venue(text: str | None, index: list[tuple[str, dict, bool]]) -> dict | None:
    """Find the first registry venue named in *text*.

    Longest name first, so 'ACM MM' is not shadowed by 'ACM'.
    """
    if not text:
        return None
    for name, venue, case_sensitive in index:
        if case_sensitive:
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text):
                return venue
        else:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])"
            if re.search(pattern, text.lower()):
                return venue
    return None


def venue_from_arxiv(paper: dict, index: list[tuple[str, dict, bool]]) -> tuple[dict | None, str]:
    """Recover (venue, evidence_text) from an arXiv record.

    `journal_ref` is authoritative — arXiv sets it only for a published paper —
    so a match there is taken as-is. `comment` is free text and must clear two
    gates first: it has to claim acceptance, and it must not be describing a
    workshop that merely sits alongside the venue.

    A rejected comment is still returned as the second element, so a card with
    no tier can be explained rather than looking like a matcher failure.
    """
    journal_ref = str(paper.get("journal_ref") or "").strip()
    if venue := match_venue(journal_ref, index):
        return venue, journal_ref

    comment = str(paper.get("comment") or "").strip()
    if not comment:
        return None, ""
    if _DECLINED.search(comment) or not _ACCEPTED.search(comment):
        return None, comment

    venue = match_venue(comment, index)
    if venue and _WORKSHOP.search(comment) and "workshop" not in venue["name"].lower():
        # 'Accepted at the REALM Workshop ... at EMNLP 2026' is a workshop
        # paper. CCF ranks main conferences, so the parent tier would be a
        # promotion the paper did not earn.
        return None, comment
    return venue, comment


def restore_abstract(inverted: dict | None) -> str:
    """Reassemble OpenAlex's `abstract_inverted_index` into plain text.

    The field is a {word: [positions]} map, not text. Rebuild it by inverting
    the mapping; positions can repeat across words in malformed records, so the
    last write wins rather than crashing on a duplicate key.
    """
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for i in indexes or []:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _first(paper: dict, *keys: str):
    """Return the first non-empty value among *keys*.

    The two arXiv skills in this workspace disagree on field names, and either
    may be the one a given run used:

    | concept   | `literature-search-arxiv` | `systematic-literature-review` |
    |-----------|---------------------------|--------------------------------|
    | abstract  | `summary`                 | `abstract`                     |
    | category  | `primary_category` (str)  | `categories` (list)            |
    | abs url   | derived from id           | `abs_url`                      |

    Reading both costs nothing and removes a crash whose traceback points at
    this line rather than at the shape mismatch that caused it.
    """
    for key in keys:
        value = paper.get(key)
        if value:
            return value
    return None


def extract_papers(payload) -> list[dict]:
    """Pull the paper list out of whatever envelope the caller emitted.

    `literature-search-arxiv` prints `{"status", "results_count", "papers"}`;
    `systematic-literature-review` prints a bare JSON array. Both are valid
    input here.
    """
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("papers", "results", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
    return []


def normalise_arxiv(payload, index: list[tuple[str, dict, bool]]) -> list[dict]:
    out: list[dict] = []
    for paper in extract_papers(payload):
        raw_id = paper.get("id") or ""
        source_id = _VERSION_SUFFIX.sub("", raw_id)
        if not source_id:
            continue

        published = paper.get("published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None

        venue, hint = venue_from_arxiv(paper, index)

        categories = _first(paper, "categories", "primary_category") or []
        if isinstance(categories, str):
            categories = [categories]

        # Pin the PDF to the canonical id, not the version arXiv's feed named.
        # `source_id` already drops 'v1', and the card contract shows the
        # unversioned form; a version-pinned link goes stale on the next
        # revision, which is the opposite of what a reference list wants.
        pdf_url = paper.get("pdf_url")
        if pdf_url:
            pdf_url = re.sub(r"v\d+(\.pdf)?$", r"\1", pdf_url)

        record = {
            "source": "arxiv",
            "source_id": source_id,
            "title": (paper.get("title") or "").strip(),
            "abstract": (_first(paper, "summary", "abstract") or "").strip(),
            "authors": paper.get("authors") or [],
            "year": year,
            "url": _first(paper, "abs_url") or f"https://arxiv.org/abs/{source_id}",
            "pdf_url": pdf_url,
            "categories": categories,
            "doi": paper.get("doi"),
            "venue_match_text": hint or None,
        }
        if venue:
            record["venue"] = venue["name"]
            record["venue_tier"] = venue.get("tier")
        out.append(record)
    return out


def normalise_openalex(payload, index: list[tuple[str, dict, bool]]) -> list[dict]:
    out: list[dict] = []
    for work in extract_papers(payload):
        # Prefer the DOI as the stable id (survives OpenAlex re-merges); fall
        # back to the W-id, which is what OpenAlex promises to keep stable.
        doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
        openalex_id = (work.get("id") or "").rsplit("/", 1)[-1]
        source_id = doi or openalex_id
        if not source_id:
            continue

        authors = [
            (a.get("author") or {}).get("display_name")
            for a in (work.get("authorships") or [])
        ]
        source = ((work.get("primary_location") or {}).get("source")) or {}
        venue_name = source.get("display_name")

        # OpenAlex names the journal directly, so match on that; fall back to
        # the ISSN when the name is absent.
        venue = match_venue(venue_name, index) or match_venue(source.get("issn_l"), index)

        record = {
            "source": "openalex",
            "source_id": source_id,
            "title": (work.get("display_name") or "").strip(),
            "abstract": restore_abstract(work.get("abstract_inverted_index")),
            "authors": [a for a in authors if a],
            "year": work.get("publication_year"),
            "url": work.get("doi") or work.get("id"),
            "categories": [
                t for t in [
                    ((work.get("primary_topic") or {}).get("display_name")),
                ] if t
            ],
            "doi": doi,
            "venue_match_text": venue_name,
        }
        if venue_name:
            record["venue"] = venue_name
        if venue:
            record["venue_tier"] = venue.get("tier")
        if issn := source.get("issn_l"):
            record["issn"] = issn
        out.append(record)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalise external search output")
    parser.add_argument("--source", required=True, choices=["arxiv", "openalex"])
    parser.add_argument("--domain", required=True, help="Registry domain, e.g. ai / finance")
    parser.add_argument("--in", dest="infile", type=Path, help="Input JSON; omit for stdin")
    parser.add_argument("--out", dest="outfile", type=Path, help="Output JSON; omit for stdout")
    parser.add_argument(
        "--drop-empty-abstract",
        action="store_true",
        help="Skip records with no abstract (front-matter, announcements)",
    )
    args = parser.parse_args(argv)

    raw = args.infile.read_text(encoding="utf-8") if args.infile else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"输入不是合法 JSON：{exc}", file=sys.stderr)
        return 2

    domain = load_registry(args.domain)
    index = build_venue_index(domain)

    records = (
        normalise_arxiv(payload, index)
        if args.source == "arxiv"
        else normalise_openalex(payload, index)
    )
    before = len(records)
    if args.drop_empty_abstract:
        records = [r for r in records if r.get("abstract")]

    text = json.dumps(records, ensure_ascii=False, indent=2)
    if args.outfile:
        args.outfile.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    tiered = sum(1 for r in records if r.get("venue_tier"))
    print(
        f"规范化 {len(records)}/{before} 条（领域 {args.domain}）；"
        f"定级成功 {tiered} 条，未定级 {len(records) - tiered} 条（留空，未猜）",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
