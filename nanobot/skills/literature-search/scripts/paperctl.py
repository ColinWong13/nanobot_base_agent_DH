#!/usr/bin/env python3
"""Paper card store for the 资讯检索 pipeline.

This is the only script the pipeline owns outright. Retrieval is delegated to
the external `literature-search-arxiv` / `literature-search-openalex` skills;
this script takes their normalised output and does the parts nobody else can:
dedupe against the vault, write Obsidian paper cards, and read the domain
registry.

Design rules that matter (see planning/info-retrieval-agent.md §4.1):

* **Dedupe key is `source` + `source_id`.** Never title or DOI — titles get
  re-typeset and DOIs are absent on preprints.
* **Existing cards are merged, never clobbered.** Metadata keys are updated in
  place; the body from `## 我的笔记` onward is preserved byte-for-byte, because
  that section is the user's own writing.
* **Unknown frontmatter keys survive a rewrite.** A card may carry keys this
  script does not know about (added by hand or by a future version); they are
  round-tripped untouched.
* **A review is one living document per topic.** `20-Reviews/slr-<slug>.md` is
  updated in place for years, so reviews need the same identity discipline cards
  have. The identity is the slug, claimed by *either* the frontmatter's
  `topic_slug` *or* the filename -- a review with no frontmatter at all stays
  findable, which is the whole point (see references/review-card.md).
* **A review's `papers` count is derived from its body, never stored twice.**
  `review-write` recomputes it from the annotation identifier lines on every
  write. A count a model typed is a count that will eventually be wrong, and a
  wrong count makes the next run's dedupe look like it worked.

No third-party dependencies. PyYAML is used when importable and a small
fallback parser covers the subset of YAML this script itself emits.

Usage:
    python3 paperctl.py vault-init
    python3 paperctl.py domain ai
    python3 paperctl.py card-check --source arxiv --id 2005.11401
    python3 paperctl.py card-write --json paper.json
    python3 paperctl.py list --domain ai
    python3 paperctl.py review-list --ids papers.json
    python3 paperctl.py review-find --slug rag
    python3 paperctl.py review-write --slug rag --window '2025-09-28 ~ 2026-09-28'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# --- Locations -------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent.parent


def _resolve_workspace() -> Path:
    """Locate the agent workspace.

    Deliberately not derived from this file's path. The skill ships in two
    places -- inside a workspace (``<workspace>/skills/<name>/``) and inside the
    installed package (``nanobot/skills/<name>/``) -- and walking up from
    ``__file__`` is only correct for the first. For the second it lands on the
    package directory, where the registry lookup then quietly finds nothing.

    The workspace is a configured value, so it is read from where the agent
    reads it: ``agents.defaults.workspace`` in the config.
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

# The vault is the user's, not this project's, so there is no default that could
# be right for anyone but its author. Supplied by --vault or $OBSIDIAN_VAULT;
# main() refuses to run without one, rather than reading a directory that is not
# there and reporting an empty vault.
VAULT_ENV = "OBSIDIAN_VAULT"
_SUBDIR = "AI Workspace/资讯检索"
_SECTIONS = {
    "papers": "10-Papers",
    "reviews": "20-Reviews",
    "weekly": "30-Weekly",
}

_NOTES_HEADING = "## 我的笔记"
_SUMMARY_HEADING = "## 摘要（原文）"
_ONELINER_HEADING = "## 一句话提要"

try:  # PyYAML is present in nanobot's venv but not guaranteed system-wide.
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised only outside the venv
    _yaml = None


# --- Frontmatter -----------------------------------------------------------


def _parse_scalar(raw: str):
    """Parse one YAML scalar well enough for the values this script writes."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw in {"null", "~", ""}:
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body). Missing or malformed frontmatter yields ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")

    if _yaml is not None:
        try:
            parsed = _yaml.safe_load(block)
            if isinstance(parsed, dict):
                return parsed, body
        except Exception:
            pass  # fall through to the minimal parser

    data: dict = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = _parse_scalar(value)
    return data, body


def _dump_scalar(value) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_dump_scalar(v) for v in value) + "]"
    if isinstance(value, date):
        # PyYAML resolves a bare `updated: 2026-09-27` to a datetime.date, and a
        # date that reaches json.dumps raises TypeError -- so without this the
        # same command crashes or not depending on whether PyYAML imported.
        return value.isoformat()
    text = str(value)
    # Quote anything that would otherwise be read as a number, a bool, or
    # would break on a colon/comma/leading bracket.
    if re.fullmatch(r"-?\d+(\.\d+)?", text) or text.lower() in {"true", "false", "null", "~", ""}:
        return json.dumps(text, ensure_ascii=False)
    if any(ch in text for ch in ":#[]{}&*!|>'\"%@`") or text != text.strip():
        return json.dumps(text, ensure_ascii=False)
    return text


def _json_scalar(value):
    """Make a frontmatter value safe to hand to `json.dumps`.

    The mirror of `_dump_scalar`'s date guard, on the read path. PyYAML resolves
    a bare `added: 2026-09-28` to a datetime.date, and `json.dumps` raises
    TypeError on a date -- so without this every command echoing a card's dates
    back out would crash on all 81 cards at once, and the failure would read as
    a broken command rather than a type mismatch.

    Normalising every field, not just the ones known to be dates today, keeps
    the next date-bearing key from re-introducing the same crash.
    """
    if isinstance(value, date):
        return value.isoformat()
    return value


_CARD_ORDER = ["type", "title", "authors", "year", "venue", "venue_tier"]
# A review's identity keys belong at the top of its own block. Extending
# _CARD_ORDER instead would push every card's hand-added unknown keys around
# and bury `topic_slug` under `venue_tier`.
_REVIEW_ORDER = [
    "type",
    "topic",
    "topic_slug",
    "papers",
    "window",
    "source",
    "citation_format",
    "language",
    "created",
    "updated",
]


def dump_frontmatter(data: dict, order: list[str] | None = None) -> str:
    # 'type' first, 'title' early — cards are read by humans in Obsidian too.
    preferred = _CARD_ORDER if order is None else order
    keys = [k for k in preferred if k in data] + [k for k in data if k not in preferred]
    lines = ["---"]
    for key in keys:
        lines.append(f"{key}: {_dump_scalar(data[key])}")
    lines.append("---")
    return "\n".join(lines)


# --- Body ------------------------------------------------------------------


def merge_body(existing_body: str, abstract: str, one_liner: str | None) -> str:
    """Rebuild the generated body while preserving the user's own section.

    Everything from `## 我的笔记` onward is the user's writing and is copied
    through untouched; only the two generated sections are rewritten.
    """
    preserved = ""
    if _NOTES_HEADING in existing_body:
        preserved = existing_body[existing_body.index(_NOTES_HEADING) :].rstrip() + "\n"
    elif existing_body.strip():
        # A hand-written card with no notes heading: keep whatever is there.
        preserved = existing_body.rstrip() + "\n"

    if not preserved:
        preserved = f"{_NOTES_HEADING}\n\n<!-- 用户手写区，agent 不得覆写 -->\n"

    parts = [_SUMMARY_HEADING, "", abstract.strip() or "_（无摘要）_", ""]
    if one_liner:
        parts += [_ONELINER_HEADING, "", one_liner.strip(), ""]
    parts.append(preserved.rstrip() + "\n")
    return "\n".join(parts)


# --- Cards -----------------------------------------------------------------


def slugify(text: str, limit: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:limit].rstrip("-") or "untitled"


def card_path(papers_dir: Path, paper: dict) -> Path:
    year = paper.get("year") or "n.d."
    return papers_dir / f"{year}-{slugify(paper.get('title', ''))}-{paper['source']}-{slugify(paper['source_id'], 40)}.md"


def find_existing(papers_dir: Path, source: str, source_id: str) -> Path | None:
    """Locate an existing card for (source, source_id) by scanning frontmatter."""
    if not papers_dir.exists():
        return None
    for path in papers_dir.glob("*.md"):
        try:
            meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if meta.get("source") == source and str(meta.get("source_id") or meta.get("arxiv_id") or "") == source_id:
            return path
    return None


def _as_list(value) -> list[str]:
    """Coerce a frontmatter value to a list of non-empty strings.

    A hand-edited card can hold a bare string where the contract says list.
    Reading that as a one-item list beats dropping the user's edit on the floor.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_terms(raw: str | None) -> list[str] | None:
    """Split a comma-separated theme list.

    ``None`` and ``[]`` mean different things downstream: an absent flag leaves
    the stored themes alone, and there is no way to blank them from the CLI --
    the same "有值才覆盖" rule the other review fields follow.
    """
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def apply_enrichment(
    meta: dict,
    *,
    topic_terms: list | None = None,
    domains: list | None = None,
    replace: bool = False,
) -> tuple[dict, list[str], list[str]]:
    """Merge the curated keys into a card's frontmatter.

    Returns ``(meta, added_terms, added_domains)``.

    Both keys merge rather than overwrite, for different reasons:

    * ``topic_terms`` is written by a review, and a review is a living document
      -- the next pass over the same topic must add a theme without dropping the
      themes the first pass found. ``replace`` is the way back if a term was
      added by mistake, including clearing the key with an empty list.
    * ``domains`` records which searches found the paper. A second search does
      not un-find it, so there is nothing for ``replace`` to do.

    Neither key is in `write_card`'s overwrite list, so a card keeps them until
    something deliberately changes them.
    """
    meta = dict(meta)
    previous = _as_list(meta.get("topic_terms"))

    if topic_terms or replace:
        merged = list(dict.fromkeys([*([] if replace else previous), *_as_list(topic_terms)]))
        added_terms = [term for term in merged if term not in previous]
        if merged:
            meta["topic_terms"] = merged
        else:
            meta.pop("topic_terms", None)
    else:
        added_terms = []

    if domains:
        current = _as_list(meta.get("domains"))
        merged = list(dict.fromkeys([*current, *_as_list(domains)]))
        added_domains = [domain for domain in merged if domain not in current]
        meta["domains"] = merged
    else:
        added_domains = []

    return meta, added_terms, added_domains


def write_card(
    papers_dir: Path,
    paper: dict,
    *,
    one_liner: str | None = None,
    venue_tier: str | None = None,
    domain: str | None = None,
    dry_run: bool = False,
) -> tuple[str, Path]:
    """Create or merge one paper card. Returns (action, path).

    `domain` is the registry domain the search ran under (``ai``, ``finance``);
    it is recorded on the card as one more entry in ``domains``, so the card can
    later be browsed by the discipline it was collected for.
    """
    papers_dir.mkdir(parents=True, exist_ok=True)
    source = paper["source"]
    source_id = str(paper["source_id"])

    existing = find_existing(papers_dir, source, source_id)
    is_update = existing is not None
    path = existing or card_path(papers_dir, paper)

    if is_update:
        old_meta, old_body = split_frontmatter(path.read_text(encoding="utf-8"))
    else:
        old_meta, old_body = {}, ""

    meta = dict(old_meta)  # preserve unknown keys
    meta.update(
        {
            "type": "paper",
            "title": paper.get("title") or "",
            "authors": paper.get("authors") or [],
            "year": paper.get("year"),
            "source": source,
            "source_id": source_id,
            "topics": paper.get("categories") or [],
            "url": paper.get("url") or "",
        }
    )
    if venue := paper.get("venue"):
        meta["venue"] = venue
    if venue_tier:
        meta["venue_tier"] = venue_tier
    if pdf_url := paper.get("pdf_url"):
        meta["pdf_url"] = pdf_url
    if doi := paper.get("doi"):
        meta["doi"] = doi
    if source == "arxiv":
        meta.setdefault("arxiv_id", source_id)
    meta.setdefault("added", date.today().isoformat())
    meta["updated"] = date.today().isoformat()
    meta.setdefault("status", "unread")
    # The curated keys land after `status` rather than beside `topics`. The rest
    # of the frontmatter is emitted in data order on purpose, and slotting these
    # into `_CARD_ORDER` would reflow every card already in the vault -- a whole
    # frontmatter diff for a two-line change.
    meta, _, _ = apply_enrichment(
        meta,
        topic_terms=paper.get("topic_terms"),
        domains=[domain] if domain else None,
    )

    body = merge_body(old_body, paper.get("abstract") or "", one_liner)
    content = dump_frontmatter(meta) + "\n\n" + body

    if not dry_run:
        path.write_text(content, encoding="utf-8")
    return ("updated" if is_update else "created"), path


# --- Reviews ---------------------------------------------------------------

_REVIEW_PREFIX = "slr-"
_REVIEW_ARCHIVE_SUFFIX = "-archive"
_REVIEW_HEADING = "## Per-Paper Annotations"
_LEGACY_DATE = re.compile(r"-\d{8}$")  # slr-rag-20260928.md
_DEFAULT_LANGUAGE = "en"  # Colin, 2026-09-28: new reviews are written in English

# Reviews are scoped to one section on purpose. Measured 2026-09-28 on the live
# 80-paper review: `^### ` over the whole file gives 86, of which 6 are
# `### Theme N`; scoped to `## Per-Paper Annotations` it gives exactly 80.
# The heading match tolerates case and `Per Paper`, because that is the drift a
# human retyping the skeleton produces -- but not a different wording, which
# would be a silent miss.
_SECTION_HEADING = re.compile(r"^##[ \t]+Per[- ]Paper[ \t]+Annotations[ \t]*$", re.M | re.I)
_ANNOT_HEADING = re.compile(r"^### ", re.M)
# `^## ` cannot match `### ` -- index 2 is `#`, not a space -- so this is a
# clean level-2 cut for `## References` / `## 我的笔记`.
_SECTION_END = re.compile(r"^## ", re.M)

# The contract form, e.g. `**arXiv**: [2609.14572](https://arxiv.org/abs/2609.14572)`.
# The label is deliberately loose so a future `**DOI**: [...]` source works; the
# required `](url)` target is what makes it safe. Measured against every
# structural label the templates emit (`**Key findings**: [see appendix B]`,
# `**Research question**: <1 sentence>`, `### [1] Vaswani et al. ...`) nothing
# matches.
_ANNOT_LINK = re.compile(
    r"^[ \t]*\*\*(?P<label>[^*\n:]{1,24})\*\*:[ \t]*"
    r"\[(?P<id>[^\]\n]+)\]\((?P<url>[^)\s]+)\)[ \t]*$",
    re.M,
)
# The form the first review in the vault actually used, and the reason a
# link-only rule is not enough: `` `2609.23056` · cs.CL · 未定级 ``. Restricted
# to the arXiv id shape -- an unrestricted bare-backtick rule would match inline
# code in the prose.
_ANNOT_BARE = re.compile(r"^`(?P<id>\d{4}\.\d{4,5})`", re.M)

_ARXIV_URL = re.compile(r"arxiv\.org/abs/(?P<id>[^\s?#]+)")
_ARXIV_VERSION = re.compile(r"v\d+$")
# The id families a paper card's `source_id` can hold. Anything else is a parse
# problem, not an id: better a refusal than a made-up identifier.
_ID_SHAPES = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}|10\.\d{4,9}/\S+|W\d+)$")
# arXiv ids carry their submission month in the first four digits. New style
# (2007-04 onward) is `YYMM.NNNNN`; old style is `archive/YYMMNNN` and spans
# 1991-2007, so a two-digit year there is 19xx once it reaches 91.
_ARXIV_MONTH = re.compile(
    r"^(?:(?P<ny>\d{2})(?P<nm>\d{2})\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/(?P<oy>\d{2})(?P<om>\d{2})\d{3})$"
)
_HEADING_YEAR = re.compile(r"[（(](\d{4})[）)]")
_DATE_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}")

# A sibling review covering this share of the candidate set is the same topic.
# The floor stops a 3-paper run being blocked by a coincidental overlap.
_DUPLICATE_MIN_RATIO = 0.6
# A `## Per-Paper Annotations` section with no `### ` blocks may hold a real
# placeholder ("（尚未收录）") -- or annotations written without identifier lines.
# Past a couple of lines it is the latter.
_EMPTY_SECTION_MAX_LINES = 4
_DUPLICATE_MIN_OVERLAP = 10

# Colin, 2026-09-28: the window rolls, two years wide. Papers older than this
# are condensed into the review's archive file and dropped from its body.
_RETENTION_YEARS = 2


def canonical_slug(raw: str) -> str:
    """Normalise any slug spelling to the identity form.

    `RAG`, `slr-rag`, `slr-rag.md`, `slr-rag-20260928` and
    `Retrieval-Augmented Generation` all land on the same string. Being liberal
    here is the point: the slug *is* the dedupe key, so a near-miss -- the agent
    typing `retrieval-augmented-generation` for a review stored as `rag` -- is
    the exact failure this section exists to prevent.
    """
    text = (raw or "").strip()
    if text.lower().startswith(_REVIEW_PREFIX):
        text = text[len(_REVIEW_PREFIX) :]
    if text.lower().endswith(".md"):
        text = text[:-3]
    slug = slugify(_LEGACY_DATE.sub("", text))
    # `slugify`'s "untitled" is a null-object for a missing title, not a slug --
    # and it is truthy, so returning it here defeats every `or fallback` at the
    # call sites and turns an absent slug into a real-looking identity.
    return "" if slug == "untitled" else slug


def slug_from_filename(path: Path) -> str:
    """Derive the identity slug from a filename.

    This is the fallback that keeps a review with no frontmatter at all
    findable -- the direct antidote to the trap this section was written for.
    Note `slugify` strips `/` and `.`, so an agent-supplied slug can never
    escape `20-Reviews/`.
    """
    return canonical_slug(path.stem)


def review_archive_path(reviews_dir: Path, slug: str) -> Path:
    return reviews_dir / f"{_REVIEW_PREFIX}{slug}{_REVIEW_ARCHIVE_SUFFIX}.md"


def _normalise_id(token: str | None) -> str | None:
    """Canonicalise a captured identifier, or None if it is not one.

    Drops the version suffix and the `arXiv:` / URL wrapper so that
    `2005.11401v3`, `https://arxiv.org/abs/2005.11401` and `2005.11401` are one
    identifier rather than three -- otherwise a paper counted twice would
    inflate `papers` and break every overlap number computed from it.
    """
    if token is None:
        return None
    text = token.strip().strip("`").strip()
    if not text:
        return None
    if match := _ARXIV_URL.search(text):
        text = match.group("id")
    text = re.sub(r"^arxiv:\s*", "", text, flags=re.I)
    text = _ARXIV_VERSION.sub("", text)
    return text if _ID_SHAPES.match(text) else None


def _published_month(ident: str, heading: str) -> str | None:
    """Best-effort "YYYY-MM" for a covered paper, or None.

    A heading's `(2026)` is read as December on purpose: a year-only date could
    be any month, and assuming January would retire a paper that is still inside
    the window. Keeping something a year too long is recoverable; retiring it is
    not.
    """
    if match := _ARXIV_MONTH.match(ident):
        if match.group("ny"):
            return f"20{match.group('ny')}-{match.group('nm')}"
        old_year = int(match.group("oy"))
        return f"{1900 + old_year if old_year >= 91 else 2000 + old_year}-{match.group('om')}"
    if year := _HEADING_YEAR.search(heading):
        return f"{year.group(1)}-12"
    return None


def annotation_entries(body: str) -> tuple[list[dict], list[str]]:
    """Return (entries, problems) for the review's `## Per-Paper Annotations`.

    Each entry is `{"id", "heading", "date"}`. IDs are derived from the body
    rather than stored in frontmatter: a second copy in the header can drift
    from the annotations the reader actually sees, and the body is what the next
    run merges against -- so the body is the single source of truth and `papers`
    is a cache of it.

    An empty `problems` means the parse is trustworthy. Anything in it means the
    recomputed count is *known* to be wrong, and `review-write` refuses to write
    it: a silently wrong `papers` is worse than the parallel-review bug this
    work exists to fix, because nothing about the file looks broken.
    """
    heading = _SECTION_HEADING.search(body)
    if heading is None:
        return [], [f"正文缺少 `{_REVIEW_HEADING}` 标题"]

    rest = body[heading.end() :]
    if end := _SECTION_END.search(rest):  # `## References`, or `## 我的笔记`
        rest = rest[: end.start()]

    starts = [m.start() for m in _ANNOT_HEADING.finditer(rest)]
    spans = (
        [
            (start, starts[i + 1] if i + 1 < len(starts) else len(rest))
            for i, start in enumerate(starts)
        ]
        if starts
        # No `### ` at all: flat annotations, or a section the agent just
        # created. An empty section legitimately means zero.
        else [(0, len(rest))]
    )

    entries: list[dict] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, (start, stop) in enumerate(spans, 1):
        block = rest[start:stop]
        found = _ANNOT_LINK.search(block) or _ANNOT_BARE.search(block)
        if found is None:
            if starts:
                lines = block.splitlines()
                problems.append(f"第 {index} 个注释块没有标识行：{lines[0][:70] if lines else ''}")
            continue
        groups = found.groupdict()
        ident = _normalise_id(groups.get("id"))
        from_url = _normalise_id(groups.get("url"))
        if ident and from_url and ident != from_url:
            # A label/URL mismatch silently attributes the prose to a card that
            # exists but is not the one being described.
            problems.append(f"第 {index} 个注释块的文字与 URL 不一致：{ident} vs {from_url}")
            continue
        ident = ident or from_url
        if ident is None:
            problems.append(f"第 {index} 个注释块的标识无法识别：{groups.get('id')!r}")
            continue
        if ident in seen:
            problems.append(f"标识 {ident} 重复（第 {seen[ident]} 与第 {index} 个注释块）")
            continue
        seen[ident] = index
        lines = block.splitlines()
        heading_text = lines[0].lstrip("# ").strip() if lines else ""
        entries.append(
            {"id": ident, "heading": heading_text, "date": _published_month(ident, heading_text)}
        )
    if not starts and not entries and not problems:
        # No `### ` blocks at all and nothing parsed. An empty or placeholder
        # section legitimately means zero -- but so would a section full of
        # annotations written without identifier lines, and reporting 0 papers
        # for a review the reader sees as full is the silent-wrong-count failure
        # this whole parser exists to prevent. A placeholder is a line or two.
        if sum(1 for line in rest.splitlines() if line.strip()) > _EMPTY_SECTION_MAX_LINES:
            problems.append(
                f"`{_REVIEW_HEADING}` 一节有内容，却解析出 0 个标识：每个注释块的"
                f"第一行必须是标识行，或用 `### ` 分块。"
            )
    return entries, problems


def annotation_ids(body: str) -> tuple[list[str], list[str]]:
    """The covered ids, and any reason to distrust them."""
    entries, problems = annotation_entries(body)
    return [entry["id"] for entry in entries], problems


def iter_reviews(reviews_dir: Path) -> list[Path]:
    """Every file that is a review, by filename *or* by frontmatter.

    The union is deliberately over-inclusive. A `slr-*.md` file with no
    frontmatter at all is still a review -- that is the live
    `slr-rag-20260928.md` -- and a file with `type: review` is one even if it
    was named by hand. Missing a review is the failure being fixed, so detection
    errs toward seeing too many. Over-inclusion is harmless: only `review-write`
    mutates, and only the file it resolved by slug. Archive files are excluded
    by name *and* by type, so either signal alone is enough.
    """
    if not reviews_dir.exists():
        return []
    found = []
    for path in sorted(reviews_dir.glob("*.md")):
        try:
            meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        declared = str(meta.get("type", "")).lower()
        if declared == "review-archive" or path.stem.lower().endswith(_REVIEW_ARCHIVE_SUFFIX):
            continue
        if path.name.lower().startswith(_REVIEW_PREFIX) or declared == "review":
            found.append(path)
    return found


def find_reviews(reviews_dir: Path, slug: str) -> tuple[Path | None, list[Path]]:
    """All reviews claiming `slug`, best candidate first, plus the conflicts.

    Two independent claims are honoured and either is sufficient: the stored
    `topic_slug`, and the filename -- the only signal a frontmatter-less review
    has. They disagree exactly when a review was renamed by hand or predates the
    contract, and in that case it is still the same review.
    """
    matches: list[Path] = []
    for path in iter_reviews(reviews_dir):
        try:
            meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        stored = canonical_slug(str(meta.get("topic_slug") or ""))
        if (stored and stored == slug) or slug_from_filename(path) == slug:
            matches.append(path)
    if not matches:
        return None, []
    # Prefer the file whose name already *is* the contract name: that is the one
    # the next run's `review-find` will land on, so stamping anywhere else
    # guarantees the following lookup misses it.
    exact = [p for p in matches if p.stem.lower() == f"{_REVIEW_PREFIX}{slug}"]
    best = (exact or matches)[0]
    return best, [p for p in matches if p != best]


def window_bounds(window: str | None) -> tuple[str | None, str | None]:
    """(start, end) of a review's coverage span, tolerant of the separator.

    The contract spells it `2026-08-28 ~ 2026-09-28`, but a hand-edit could
    write an en dash or a hyphen, so this reads the dates rather than the
    punctuation. The *last* date is the end -- it is the watermark the next
    run's search starts from, so getting it backwards would silently re-search
    an old window.
    """
    tokens = _DATE_TOKEN.findall(window or "")
    if not tokens:
        return None, None
    return tokens[0], tokens[-1]


def retention_cutoff(window: str | None, years: int = _RETENTION_YEARS) -> str | None:
    """"YYYY-MM" before which a covered paper has fallen out of the window."""
    _, end = window_bounds(window)
    if end is None:
        return None
    try:
        end_date = date.fromisoformat(end)
    except ValueError:
        return None
    target = end_date.year - years
    try:
        cutoff = end_date.replace(year=target)
    except ValueError:  # 29 February in a non-leap year
        cutoff = end_date.replace(year=target, day=28)
    return cutoff.strftime("%Y-%m")


def _as_text(value) -> str | None:
    """A frontmatter value as JSON-safe text.

    Not cosmetic: PyYAML resolves `created: 2026-09-27` to a `datetime.date` and
    `json.dumps` raises TypeError on one, while the fallback parser returns a
    str -- so without this the same command crashes or not depending on whether
    PyYAML imported.
    """
    return None if value is None else str(value)


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def review_summary(path: Path) -> dict:
    """A review's identity, with `papers` derived from its body."""
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    ids, problems = annotation_ids(body)
    filename_slug = slug_from_filename(path)
    archive = review_archive_path(path.parent, filename_slug)
    return {
        "topic": _as_text(meta.get("topic")),
        "topic_slug": _as_text(meta.get("topic_slug")) or filename_slug,
        "papers": len(ids),
        # The header's own claim, kept beside the derived number so drift is
        # visible instead of silently corrected. They differ exactly when the
        # body was edited without a re-stamp, or a write went through --force.
        "papers_declared": _as_int(meta.get("papers")),
        "window": _as_text(meta.get("window")),
        "source": _as_text(meta.get("source")),
        "citation_format": _as_text(meta.get("citation_format")),
        "language": _as_text(meta.get("language")),
        "created": _as_text(meta.get("created") or meta.get("generated")),
        "updated": _as_text(meta.get("updated")),
        "filename_slug": filename_slug,
        "archive": str(archive) if archive.exists() else None,
        "problems": problems[:3],
        "problem_count": len(problems),
        "path": str(path),
    }


def load_ids(path: Path) -> list[str]:
    """Read candidate identifiers from a JSON or text file, or `-` for stdin.

    Four shapes are accepted so the caller never has to reshape a file to ask
    this question: the normalised paper list `normalize.py` emits
    (`[{"source_id": ...}, ...]`), that same list under a `papers` key (the raw
    arXiv skill returns a dict), a bare JSON array of ids, and plain text with
    one id per line.
    """
    raw = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw.splitlines()

    if isinstance(payload, dict):
        payload = payload.get("papers") or payload.get("results") or []
    if not isinstance(payload, list):
        payload = [payload]

    ids: list[str] = []
    for item in payload:
        candidate = (
            item.get("source_id") or item.get("arxiv_id") or item.get("id")
            if isinstance(item, dict)
            else item
        )
        ident = _normalise_id(_as_text(candidate))
        if ident and ident not in ids:
            ids.append(ident)
    return ids


def _write_atomic(path: Path, content: str) -> None:
    """Replace `path` in one step.

    A review is a years-lived file that may be open in Obsidian on a synced
    device, and `write_text` truncates before it writes -- anything reading in
    that window sees an empty or half-written file and syncs it. A card can
    always be regenerated from the search result; a review cannot.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def stamp_review(
    path: Path,
    *,
    expected_type: str = "review",
    topic: str | None = None,
    window: str | None = None,
    source: str | None = None,
    citation_format: str | None = None,
    language: str | None = None,
    themes: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Rewrite a review's frontmatter and report what changed. Body untouched.

    Field ownership mirrors `write_card` and splits the same three ways: keys
    this tool owns outright, keys overwritten only when a value is supplied, and
    keys the user owns. `papers` is the one that matters -- recomputed from the
    body on every write, so it cannot drift from the annotations the reader sees
    and cannot be typed by hand.
    """
    old_meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    if not old_meta and body.lstrip().startswith("---"):
        # No frontmatter parsed *and* the body still opens with a delimiter: a
        # UTF-8 BOM, or a block with no closing `---`. Writing here would stack
        # a second frontmatter block on top of the first.
        raise SystemExit(
            f"{path.name}：frontmatter 解析失败（可能是 BOM 或缺少收尾的 `---`），"
            f"拒绝写入以免叠加两层 frontmatter。修好后重跑，或用 --force。"
        )
    if not force:
        declared = str(old_meta.get("type", expected_type)).lower()
        if declared != expected_type:
            raise SystemExit(
                f"{path.name}：type 是 '{declared}'，不是 '{expected_type}'。用 --force 强行改写。"
            )

    entries, problems = annotation_entries(body)
    if problems:
        for line in problems[:10]:
            print(f"  !! {line}", file=sys.stderr)
        raise SystemExit(
            f"{path.name}：解析出 {len(entries)} 个论文标识，但有 {len(problems)} 处问题，"
            f"重算的 papers 一定不对，拒绝写入。\n"
            f"修好 `{_REVIEW_HEADING}` 一节；明知故犯时加 --force。"
        )

    # An archive is named `slr-<slug>-archive.md` on purpose, so comparing its
    # filename against `topic_slug` would fire on every correct archive -- and a
    # warning that is always true is a warning nobody reads. Strip the suffix so
    # the check still catches a genuine mismatch (stamping the wrong file).
    is_archive = expected_type == "review-archive"
    filename_slug = slug_from_filename(path)
    if is_archive and filename_slug.endswith(_REVIEW_ARCHIVE_SUFFIX):
        filename_slug = filename_slug[: -len(_REVIEW_ARCHIVE_SUFFIX)]
    stored_slug = canonical_slug(str(old_meta.get("topic_slug") or "")) or filename_slug
    warnings: list[str] = []
    if stored_slug != filename_slug:
        warnings.append(f"frontmatter 的 topic_slug 是 '{stored_slug}'，文件名是 '{filename_slug}'")

    meta = dict(old_meta)  # unknown keys survive, as with cards
    meta.update({"type": expected_type, "papers": len(entries), "updated": date.today().isoformat()})
    # setdefault, not assignment: rewriting the stored slug from the filename
    # would move the review out from under the slug the caller just found it by,
    # which is an identity change disguised as a rename.
    meta.setdefault("topic_slug", filename_slug)
    for key, value in (
        ("topic", topic),
        ("window", window),
        ("source", source),
        ("citation_format", citation_format),
        ("language", language),
    ):
        if value:
            meta[key] = value
    if themes:
        # The short labels the cards carry in `topic_terms`, positionally
        # matching the `### Theme N` headings in the body. It lives in the
        # frontmatter rather than being derived from the headings because three
        # of the six are not derivable: `安全——投毒攻击面扩大，防御走向工具化`
        # shortens to `安全与投毒`, which no rule would produce, and a graph node
        # labelled with the full heading is unreadable.
        meta["themes"] = [str(term).strip() for term in themes if str(term).strip()]
    # The first review in the vault spelled creation `generated`. Adopt it rather
    # than leaving the true creation date stranded under a key the contract does
    # not define.
    if "created" not in meta and (legacy := meta.pop("generated", None)):
        meta["created"] = legacy
    meta.setdefault("created", date.today().isoformat())
    meta.setdefault("language", _DEFAULT_LANGUAGE)

    cutoff = retention_cutoff(_as_text(meta.get("window")))
    # Retention is not something an archive can do: its annotations *are* the
    # already-retired ones, so every one of them is out of window by
    # construction and the warning would fire on every stamp. Say it does not
    # apply instead of reporting a count nobody can act on.
    retire = (
        []
        if is_archive
        else [e for e in entries if cutoff and e["date"] and e["date"] < cutoff]
    )
    header = dump_frontmatter(meta, _REVIEW_ORDER)
    if not dry_run:
        _write_atomic(path, header + "\n\n" + body)

    return {
        "action": "stamped",
        "path": str(path),
        "slug": stored_slug,
        "topic": _as_text(meta.get("topic")),
        "papers": {"before": _as_int(old_meta.get("papers")), "after": len(entries)},
        "window": _as_text(meta.get("window")),
        "source": _as_text(meta.get("source")),
        "citation_format": _as_text(meta.get("citation_format")),
        "language": _as_text(meta.get("language")),
        "themes": _as_list(meta.get("themes")),
        "created": _as_text(meta.get("created")),
        "updated": _as_text(meta.get("updated")),
        "retention": {
            "applies": not is_archive,
            "cutoff": cutoff,
            "years": _RETENTION_YEARS,
            "retire_count": len(retire),
            "retire": [{"id": e["id"], "heading": e["heading"], "date": e["date"]} for e in retire[:50]],
            "undated_count": sum(1 for e in entries if not e["date"]),
            "archive": None if is_archive else str(review_archive_path(path.parent, stored_slug)),
        },
        "warnings": warnings,
        "header": header if dry_run else None,
        "dry_run": dry_run,
    }


# --- Registry --------------------------------------------------------------


def load_domain(name: str) -> dict:
    if not _REGISTRY.exists():
        raise SystemExit(f"注册表不存在：{_REGISTRY}\n先跑 venue-registry/scripts/build_registry.py")
    domains = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("domains", {})
    if name not in domains:
        raise SystemExit(f"未知领域 '{name}'。可用：{', '.join(domains) or '（空）'}")
    return domains[name]


# --- Commands --------------------------------------------------------------


def cmd_vault_init(args: argparse.Namespace) -> int:
    root = args.vault / _SUBDIR
    for label in _SECTIONS.values():
        target = root / label
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=True)
        print(f"  {'·' if args.dry_run else '✓'} {target}")

    index = root / "README.md"
    if args.dry_run:
        print(f"  · {index}")
    elif not index.exists():
        index.write_text(
            "# 资讯检索\n\n"
            "本目录由 nanobot 的 `literature-search` 技能维护。\n\n"
            "| 目录 | 内容 | 谁写 |\n|---|---|---|\n"
            "| `10-Papers/` | 论文卡，一篇一文件 | agent 写，`## 我的笔记` 归你 |\n"
            "| `20-Reviews/` | 文献综述，**一主题一文件** `slr-<topic-slug>.md`，"
            "就地更新 | agent 写，`## 我的笔记` 归你 |\n"
            "| `30-Weekly/` | 每周问询产出的周报 | agent 写 |\n\n"
            "`20-Reviews/` 里是**活文档**，不是每次提问产生一份新报告。同一个主题再问"
            "一次，agent 会把新文献并进同一份文件，而不是另起一份。文件名不带日期"
            "——带日期的话，第一次更新时那个日期就成了假信息。创建日期在 frontmatter "
            "的 `created` 里。\n\n"
            "窗口期外的论文（发表时间早于覆盖区间末端两年）会从综述正文移出，浓缩进 "
            "`slr-<topic>-archive.md`。写综述时 agent 仍会读它，所以窗口外的脉络不会丢。\n\n"
            "领域注册表（哪些 venue 是权威的）不在 vault 里，"
            "在 `~/.nanobot/workspace/registry/domains.json`。\n",
            encoding="utf-8",
        )
        print(f"  ✓ {index}")
    return 0


def cmd_domain(args: argparse.Namespace) -> int:
    domain = load_domain(args.name)
    enabled = [v for v in domain["venues"] if v.get("enabled")]
    print(
        json.dumps(
            {
                "domain": args.name,
                "label": domain["label"],
                "aliases": domain.get("aliases", []),
                "arxiv_cats": domain.get("arxiv_cats", []),
                "confirmed": domain.get("confirmed", False),
                "enabled_venues": [
                    {
                        "name": v["name"],
                        "type": v.get("type"),
                        "tier": v.get("tier"),
                        "issn": v.get("issn"),
                        "full_name": v.get("full_name"),
                    }
                    for v in enabled
                ],
                "enabled_count": len(enabled),
                "total_count": len(domain["venues"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _warn_if_section_missing(vault: Path, section: str) -> None:
    """A missing section directory is a wrong `--vault`, not an empty vault.

    Every command that answers "is this already here?" answers it by globbing a
    section directory, and globbing a directory that does not exist yields
    nothing -- the identical answer to a directory that is genuinely empty.
    That makes a mistyped `--vault` indistinguishable from "nothing collected
    yet", which is a green light to re-download every card or to create a
    second review of a topic that already has one. `vault-init` creates all
    three sections, so an absent one is diagnostic rather than normal: this
    fires only on a wrong path, never on a correct but still-empty vault.

    The likely mistake is passing the pipeline directory instead of the vault
    root, since the pipeline tree lives *under* `AI Workspace/资讯检索/`.
    Exit codes are deliberately untouched -- this is information for whoever
    reads stderr, not a decision the tool should make on their behalf.
    """
    section_dir = vault / _SUBDIR / _SECTIONS[section]
    if section_dir.exists():
        return
    print(
        f"  !! {section_dir} 不存在——`--vault` 给的是 Obsidian 仓库根吗？"
        f"（流水线目录树在其下的 {_SUBDIR}/，不是 {_SUBDIR} 本身；"
        f"当前 --vault={vault}）路径确认无误的话，先跑 vault-init。",
        file=sys.stderr,
    )


def cmd_card_check(args: argparse.Namespace) -> int:
    _warn_if_section_missing(args.vault, "papers")
    papers_dir = args.vault / _SUBDIR / _SECTIONS["papers"]
    existing = find_existing(papers_dir, args.source, args.id)
    if existing:
        print(json.dumps({"exists": True, "path": str(existing)}, ensure_ascii=False))
        return 1
    print(json.dumps({"exists": False}, ensure_ascii=False))
    return 0


def cmd_card_write(args: argparse.Namespace) -> int:
    raw = args.json.read_text(encoding="utf-8") if args.json else sys.stdin.read()
    payload = json.loads(raw)
    papers = payload if isinstance(payload, list) else [payload]

    papers_dir = args.vault / _SUBDIR / _SECTIONS["papers"]
    results = []
    for i, paper in enumerate(papers, 1):
        if "source" not in paper or "source_id" not in paper:
            print(f"  [{i}/{len(papers)}] 跳过：缺 source 或 source_id", file=sys.stderr)
            continue
        action, path = write_card(
            papers_dir,
            paper,
            one_liner=paper.get("one_liner"),
            venue_tier=paper.get("venue_tier"),
            domain=paper.get("domain") or args.domain,
            dry_run=args.dry_run,
        )
        print(f"  [{i}/{len(papers)}] {action}: {path.name}", file=sys.stderr)
        results.append({"action": action, "path": str(path)})

    print(json.dumps({"written": results, "count": len(results)}, ensure_ascii=False, indent=2))
    return 0


def cmd_card_enrich(args: argparse.Namespace) -> int:
    """Merge curated frontmatter into cards that already exist.

    The commands that write cards are all driven by a search result, and a
    search result knows nothing about themes -- those come from the review
    written *about* the cards, which lands afterwards. So this is the separate
    pass that puts them on, and it is deliberately frontmatter-only: a card's
    body holds the abstract and, below `## 我的笔记`, the user's own writing.

    A card that is not there is reported, never created. A miss means the review
    cited something the vault does not hold, and inventing a card from a citation
    would paper over that.
    """
    raw = args.json.read_text(encoding="utf-8") if args.json else sys.stdin.read()
    payload = json.loads(raw)
    entries = payload if isinstance(payload, list) else [payload]

    _warn_if_section_missing(args.vault, "papers")
    papers_dir = args.vault / _SUBDIR / _SECTIONS["papers"]

    enriched: list[dict] = []
    missing: list[dict] = []
    for i, entry in enumerate(entries, 1):
        source, source_id = entry.get("source"), str(entry.get("source_id") or "")
        if not source or not source_id:
            print(f"  [{i}/{len(entries)}] 跳过：缺 source 或 source_id", file=sys.stderr)
            continue

        path = find_existing(papers_dir, source, source_id)
        if path is None:
            missing.append({"source": source, "source_id": source_id})
            print(f"  [{i}/{len(entries)}] 无卡：{source} {source_id}", file=sys.stderr)
            continue

        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        before = dict(meta)
        meta, added_terms, added_domains = apply_enrichment(
            meta,
            topic_terms=entry.get("topic_terms"),
            domains=entry.get("domains"),
            replace=args.replace,
        )

        changed = meta != before
        if changed and not args.dry_run:
            # Atomic, unlike `write_card`'s plain write: a card can be rebuilt
            # from its search result, but a backfilled theme and the user's
            # notes cannot. A truncated file here is unrecoverable.
            _write_atomic(path, dump_frontmatter(meta) + "\n\n" + body)

        mark = "·" if args.dry_run else ("✓" if changed else "=")
        print(
            f"  [{i}/{len(entries)}] {mark} {path.name}"
            f"  +{len(added_terms)}词 +{len(added_domains)}科",
            file=sys.stderr,
        )
        enriched.append(
            {
                "path": str(path),
                "changed": changed,
                "added_terms": added_terms,
                "added_domains": added_domains,
                "topic_terms": _as_list(meta.get("topic_terms")),
                "domains": _as_list(meta.get("domains")),
            }
        )

    if missing:
        print(f"  {len(missing)} 篇综述点名但 vault 里没有卡", file=sys.stderr)
    print(
        json.dumps(
            {"enriched": enriched, "missing": missing, "count": len(enriched)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    _warn_if_section_missing(args.vault, "papers")
    papers_dir = args.vault / _SUBDIR / _SECTIONS["papers"]
    if not papers_dir.exists():
        print(json.dumps({"papers": [], "count": 0}, ensure_ascii=False))
        return 0

    cards = []
    for path in sorted(papers_dir.glob("*.md")):
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        card = {
            "title": meta.get("title"),
            "source": meta.get("source"),
            "source_id": meta.get("source_id") or meta.get("arxiv_id"),
            "year": meta.get("year"),
            "venue": meta.get("venue"),
            "venue_tier": meta.get("venue_tier"),
            "status": meta.get("status"),
            # `added`/`updated` let a caller slice the collection by week from
            # this one call, instead of grepping frontmatter and re-reading each
            # card just to recover the titles behind the dates it found.
            "added": meta.get("added"),
            "updated": meta.get("updated"),
            "path": str(path),
        }
        cards.append({key: _json_scalar(value) for key, value in card.items()})
    print(json.dumps({"papers": cards, "count": len(cards)}, ensure_ascii=False, indent=2))
    return 0


def cmd_review_find(args: argparse.Namespace) -> int:
    _warn_if_section_missing(args.vault, "reviews")
    reviews_dir = args.vault / _SUBDIR / _SECTIONS["reviews"]
    slug = canonical_slug(args.slug)
    if not slug:
        raise SystemExit("--slug 不能为空，且必须含字母或数字（例：--slug rag）。")
    path, conflicts = find_reviews(reviews_dir, slug)
    if path is None:
        print(json.dumps({"exists": False, "slug": slug}, ensure_ascii=False))
        return 0
    payload: dict = {
        "exists": True,
        "path": str(path),
        "slug": slug,
        "review": review_summary(path),
    }
    if conflicts:
        # exit 2 is neither found nor missing: found, but with no winner chosen.
        # In shell truthiness 2 is a failure like 1, so `if ! cmd` still reads
        # as "exists" -- the safe direction.
        payload["ambiguous"] = True
        payload["conflicts"] = [str(p) for p in conflicts]
        payload["warnings"] = [
            f"有 {len(conflicts) + 1} 个文件都声称 slug '{slug}'，先合并它们再更新"
        ]
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def cmd_review_write(args: argparse.Namespace) -> int:
    reviews_dir = args.vault / _SUBDIR / _SECTIONS["reviews"]
    slug = canonical_slug(args.slug)
    if not slug:
        raise SystemExit("--slug 不能为空，且必须含字母或数字（例：--slug rag）。")
    # `--window` is machine-read by the next run's search, so a typo here
    # propagates into next week's query. Two full dates, or nothing. A bare
    # single date is also rejected: PyYAML would resolve it to a date object and
    # quietly change the field's type on the way back in.
    if args.window and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[ \t]*[~–—-][ \t]*\d{4}-\d{2}-\d{2}", args.window
    ):
        raise SystemExit(f"--window 需要 'YYYY-MM-DD ~ YYYY-MM-DD'，收到 {args.window!r}。")

    conflicts: list[Path] = []
    if args.archive:
        path = review_archive_path(reviews_dir, slug)
        if not path.exists():
            raise SystemExit(
                f"没有 slug 为 '{slug}' 的综述档案。预期路径：{path}\n"
                f"档案在第一次有论文滚出窗口时才建立。"
            )
        expected_type = "review-archive"
    else:
        expected_type = "review"
        found, conflicts = find_reviews(reviews_dir, slug)
        if found is None:
            # Refusing is deliberate. Writing the body is the agent's job anyway,
            # and a tool that quietly created an empty review would hide the far
            # more likely explanation: the slug is wrong, and the review the
            # agent meant to update is already on disk under another one. Naming
            # the expected path is the forcing function.
            raise SystemExit(
                f"没有 slug 为 '{slug}' 的综述。预期路径：\n"
                f"  {reviews_dir / f'{_REVIEW_PREFIX}{slug}.md'}\n"
                f"先跑 `review-list` 看现有综述的 slug —— 主题已存在就改 --slug，"
                f"而不是新建文件。"
            )
        path = found

    if conflicts:
        print(
            f"  !! 另有 {len(conflicts)} 个文件也声称 '{slug}'："
            f"{', '.join(p.name for p in conflicts)}",
            file=sys.stderr,
        )

    if args.ids and not args.archive:
        # The last gate before a duplicate becomes permanent. The earlier lookup
        # ran on a guessed slug; this compares actual candidate ids against every
        # sibling, so a slip there is caught here even if it was never run.
        want = load_ids(args.ids)
        for other in iter_reviews(reviews_dir):
            if other == path:
                continue
            _, other_body = split_frontmatter(other.read_text(encoding="utf-8"))
            hit = set(want) & set(annotation_ids(other_body)[0])
            ratio = len(hit) / len(want) if want else 0.0
            if len(hit) >= _DUPLICATE_MIN_OVERLAP and ratio >= _DUPLICATE_MIN_RATIO:
                message = (
                    f"{other.name} 已覆盖本次候选集的 {len(hit)}/{len(want)}（{ratio:.0%}）—— "
                    f"这就是同一主题。\n更新 {other.name}，不要另起一个；确实要分家时加 --force。"
                )
                if not args.force:
                    raise SystemExit(message)
                print(f"  !! {message}", file=sys.stderr)

    report = stamp_review(
        path,
        expected_type=expected_type,
        topic=args.topic,
        window=args.window,
        source=args.source,
        citation_format=args.citation_format,
        language=args.language,
        themes=_split_terms(args.themes),
        force=args.force,
        dry_run=args.dry_run,
    )

    if args.dry_run and report["header"]:
        print("  (dry-run) 新 frontmatter：", file=sys.stderr)
        for line in report["header"].splitlines():
            print(f"  {line}", file=sys.stderr)

    before, after = report["papers"]["before"], report["papers"]["after"]
    delta = "" if before is None else f" ({after - before:+d})"
    print(f"  [review] {report['action']}: {path.name}", file=sys.stderr)
    print(f"  [review] papers: {before} -> {after}{delta}", file=sys.stderr)
    if before is not None and after < before:
        print(
            f"  !! papers 减少 {before - after} 篇 —— 是删掉注释了吗？"
            f"删除允许，但必须在汇报里说明删了哪些、为什么。",
            file=sys.stderr,
        )

    retention = report["retention"]
    if retention["retire_count"]:
        names = ", ".join(f"{e['id']}({e['date']})" for e in retention["retire"][:8])
        print(
            f"  !! {retention['retire_count']} 篇已滚出 {retention['years']} 年窗口"
            f"（早于 {retention['cutoff']}）：{names}"
            + (" …" if retention["retire_count"] > 8 else ""),
            file=sys.stderr,
        )
        print(
            f"     → 浓缩进 {Path(retention['archive']).name} 后从本文件删除，"
            f"再重跑一次 review-write",
            file=sys.stderr,
        )
    for line in report["warnings"]:
        print(f"  !! {line}", file=sys.stderr)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_review_list(args: argparse.Namespace) -> int:
    _warn_if_section_missing(args.vault, "reviews")
    reviews_dir = args.vault / _SUBDIR / _SECTIONS["reviews"]
    reviews = [review_summary(p) for p in iter_reviews(reviews_dir)]
    payload: dict = {"reviews": reviews, "count": len(reviews)}

    if args.ids:
        want = load_ids(args.ids)
        want_set = set(want)
        for review in reviews:
            _, body = split_frontmatter(Path(review["path"]).read_text(encoding="utf-8"))
            have = set(annotation_ids(body)[0])
            missing = [i for i in want if i not in have]
            review["overlap"] = {
                "count": len(want_set & have),
                # Share of *this run's* candidates already in the review, because
                # the question being asked is "does this review already cover
                # what I just found?". 0.0 when there are no candidates: `count`
                # carries the truth and a ratio would be a division by zero.
                "ratio": round(len(want_set & have) / len(want_set), 3) if want_set else 0.0,
                "missing_sample": missing[:5],
                "missing_count": len(missing),
            }
        # The answer to "which review do I update?" is the top row, so sort by it
        # and say so, leaving no doubt that the order is meaningful.
        reviews.sort(key=lambda r: (-r["overlap"]["count"], r["path"]))
        payload["sorted_by"] = "overlap.count"
        payload["candidates"] = len(want)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _global_options(*, subcommand: bool) -> argparse.ArgumentParser:
    """The `--vault` / `--dry-run` pair, usable before *or* after the subcommand.

    `paperctl.py --vault X list` and `paperctl.py list --vault X` both work.
    Two things make that work, and both are easy to undo by accident:

    * The subcommand's copy defaults to ``SUPPRESS``, so when the flag is absent
      argparse leaves the attribute alone instead of resetting it. Subparsers
      parse into a fresh namespace and copy every attribute back over the outer
      one, so a plain default here silently discards a `--vault` given *before*
      the subcommand.
    * The two copies have to be separate parsers, never ``set_defaults`` on a
      shared one -- ``set_defaults`` mutates the action objects, and ``parents=``
      shares those objects across every parser that lists it.
    """
    common = argparse.ArgumentParser(add_help=False)
    vault_default = (
        Path(os.environ[VAULT_ENV]).expanduser() if os.environ.get(VAULT_ENV) else None
    )
    common.add_argument(
        "--vault",
        type=Path,
        default=argparse.SUPPRESS if subcommand else vault_default,
        help=f"Obsidian vault root (default: ${VAULT_ENV})",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS if subcommand else False,
        help="Report actions without writing",
    )
    return common


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0], parents=[_global_options(subcommand=False)]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[_global_options(subcommand=True)], help=help)

    add("vault-init", "Create the vault directory structure").set_defaults(func=cmd_vault_init)

    p_domain = add("domain", "Print a domain's enabled venues and arXiv categories")
    p_domain.add_argument("name")
    p_domain.set_defaults(func=cmd_domain)

    p_check = add("card-check", "Dedupe check; exit 1 if the card already exists")
    p_check.add_argument("--source", required=True)
    p_check.add_argument("--id", required=True)
    p_check.set_defaults(func=cmd_card_check)

    p_write = add("card-write", "Create or merge paper cards")
    p_write.add_argument("--json", type=Path, help="JSON file; omit to read stdin")
    p_write.add_argument(
        "--domain",
        help="Registry domain id this batch was searched under (e.g. ai); recorded on every card",
    )
    p_write.set_defaults(func=cmd_card_write)

    p_enrich = add(
        "card-enrich", "Merge topic terms / domains into existing cards; never touches the body"
    )
    p_enrich.add_argument("--json", type=Path, help="JSON file; omit to read stdin")
    p_enrich.add_argument(
        "--replace",
        action="store_true",
        help="Replace topic_terms instead of merging (an empty list clears them)",
    )
    p_enrich.set_defaults(func=cmd_card_enrich)

    p_list = add("list", "List existing paper cards")
    p_list.add_argument("--domain", help="Unused today; reserved for filtering")
    p_list.set_defaults(func=cmd_list)

    p_review_find = add(
        "review-find", "Review identity lookup; exit 1 if it exists, 2 if ambiguous"
    )
    p_review_find.add_argument(
        "--slug",
        required=True,
        help="e.g. rag; slr-rag, slr-rag.md and slr-rag-20260928 are also accepted",
    )
    p_review_find.set_defaults(func=cmd_review_find)

    p_review_write = add("review-write", "Stamp a review's frontmatter; never touches the body")
    p_review_write.add_argument("--slug", required=True)
    p_review_write.add_argument("--topic")
    p_review_write.add_argument(
        "--themes",
        help="Comma-separated short theme labels, in the order of the body's `### Theme N` "
        "headings; these are the terms `card-enrich` puts on the cards",
    )
    p_review_write.add_argument(
        "--window",
        help="Coverage span. Quote it: '2025-09-28 ~ 2026-09-28' (a bare ~ expands in zsh)",
    )
    p_review_write.add_argument("--source")
    p_review_write.add_argument("--citation-format")
    p_review_write.add_argument("--language", help="Defaults to 'en' for a new review")
    p_review_write.add_argument(
        "--archive",
        action="store_true",
        help="Stamp slr-<slug>-archive.md (the out-of-window digest) instead of the review",
    )
    p_review_write.add_argument(
        "--ids",
        type=Path,
        help="Candidate ids; refuses if a sibling review already covers them",
    )
    p_review_write.add_argument(
        "--force",
        action="store_true",
        help="Write despite an incomplete annotation parse or a duplicate-topic warning",
    )
    p_review_write.set_defaults(func=cmd_review_write)

    p_review_list = add("review-list", "List living reviews, optionally with overlap vs candidates")
    p_review_list.add_argument("--ids", type=Path, help="Candidate JSON/text file; '-' reads stdin")
    p_review_list.set_defaults(func=cmd_review_list)

    args = parser.parse_args(argv)
    if getattr(args, "vault", None) is None:
        # Every subcommand works inside `args.vault / _SUBDIR`, so there is
        # nothing useful to do without one. Refusing in one place keeps the
        # sentence in one place too, instead of ten call sites each inventing
        # their own way to say it.
        parser.error(
            f"the vault root is required: pass --vault PATH or set ${VAULT_ENV}. "
            'It is the vault root -- the directory containing "AI Workspace/资讯检索", '
            "not that directory itself."
        )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
