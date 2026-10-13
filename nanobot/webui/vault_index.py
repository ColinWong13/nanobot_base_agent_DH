"""Read the Obsidian vault's literature workspace for the WebUI knowledge pages.

The `literature-search` skill owns the writing; this module is the read side.
It serves both knowledge pages from one scan:

* the **browse page** groups cards by the discipline they were collected for,
  by research theme, by time, and by the questions that asked for them;
* the **graph page** draws the same cards, themes and disciplines as nodes.

The graph is deliberately *not* built here. Edges are a pure function of the
facts below (a card carries its terms and its discipline), so shipping the facts
and letting the page derive its edges avoids keeping two representations of one
dataset in step.

Three things shape the code more than speed does:

* **The vault is the user's.** Every access here is a read. The only thing that
  may write there is the skill, and it is careful about it.
* **A card that does not parse must not take the page down.** Cards are
  hand-editable, so a malformed one is skipped and *counted* -- the page can say
  "one card could not be read" instead of rendering an empty screen that looks
  like an empty vault.
* **The scan is cached by fingerprint.** 85 small files is nothing, but the page
  polls, and a rebuild that happens on every request is a rebuild nobody needed.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml
from loguru import logger

from nanobot.config.paths import get_workspace_path

# The vault path is `paperctl.py`'s fact, and it reads the same variable -- the
# env var is the contract between the two copies. Setting it in the gateway's
# environment moves both at once. Neither copy carries a default: a vault is the
# user's own directory, and guessing one would render an empty page instead of
# saying that nobody has said where it is.
VAULT_ENV = "OBSIDIAN_VAULT"
_SUBDIR = "AI Workspace/资讯检索"
_PAPERS_DIR = "10-Papers"
_REVIEWS_DIR = "20-Reviews"
_WEEKLY_DIR = "30-Weekly"

_INDEX_VERSION = 1

_SUMMARY_HEADING = "## 摘要（原文）"
_ONELINER_HEADING = "## 一句话提要"

# `### Theme 1: 图结构 RAG 的"性价比"之争`. The digits are optional so a heading
# written without a number still pairs with its declared term.
_THEME_HEADING = re.compile(r"^###[ \t]+Theme[ \t]*\d*[ \t]*[:：][ \t]*(.+?)[ \t]*$", re.M)

_FRONTMATTER_END = re.compile(r"^---[ \t]*$", re.M)

# One sentence, not the whole abstract: the browse page shows a line or two per
# card and 81 abstracts would be a megabyte of payload nobody reads.
_ONELINER_MAX = 240

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"fingerprint": None, "payload": None}


# --- where the vault is -----------------------------------------------------


class VaultNotConfiguredError(RuntimeError):
    """Raised when ``OBSIDIAN_VAULT`` is unset.

    Deliberately a different failure from a ``FileNotFoundError`` on the vault.
    That one means the variable is set and names a directory that is not there
    yet -- a ``vault-init`` away from working. This one means nobody has said
    where the vault is, and no amount of creating directories fixes it, so the
    two must not be reported with the same sentence.
    """


def vault_root() -> Path:
    """Return the Obsidian vault root, honouring ``OBSIDIAN_VAULT``."""
    configured = os.environ.get(VAULT_ENV)
    if not configured:
        raise VaultNotConfiguredError(
            f"{VAULT_ENV} is not set, so there is no vault to read. Set it to your "
            'Obsidian vault root -- the directory containing "AI Workspace/资讯检索", '
            "not that directory itself -- and restart the gateway so it sees it."
        )
    return Path(configured).expanduser()


def workspace_dir() -> Path:
    """Return the literature subdirectory the skill maintains."""
    return vault_root() / _SUBDIR


# --- the cached index -------------------------------------------------------


def read_knowledge_index() -> dict[str, Any]:
    """Return the whole knowledge index, rebuilding it only when the vault moved.

    Raises ``FileNotFoundError`` when the workspace is not there; the caller
    turns that into a 404 naming the path, because "the vault is elsewhere" is a
    configuration answer, not a server fault.
    """
    root = workspace_dir()
    if not root.is_dir():
        raise FileNotFoundError(root)

    fingerprint = _fingerprint(root)
    with _CACHE_LOCK:
        if _CACHE["fingerprint"] == fingerprint and _CACHE["payload"] is not None:
            return _CACHE["payload"]
        # Built inside the lock. It is a handful of milliseconds for a vault
        # this size, and holding the lock means the payload stored under a
        # fingerprint is always the payload that fingerprint describes -- which
        # is the whole point of having one.
        payload = _build(root, fingerprint)
        _CACHE["fingerprint"] = fingerprint
        _CACHE["payload"] = payload
        return payload


def invalidate_cache() -> None:
    """Drop the cached scan. For tests, and for a caller that just wrote."""
    with _CACHE_LOCK:
        _CACHE["fingerprint"] = None
        _CACHE["payload"] = None


def _fingerprint(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Identify the vault's current state by every file's path, mtime and size.

    mtime alone would miss an edit that lands inside one filesystem timestamp
    tick; size alone would miss an edit that swaps one word for another.
    """
    entries: list[tuple[str, int, int]] = []
    for path in sorted(root.rglob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            # Vanished mid-walk. Its absence is already reflected in the list.
            continue
        entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def _build(root: Path, fingerprint: tuple[tuple[str, int, int], ...]) -> dict[str, Any]:
    papers, skipped = _read_papers(root / _PAPERS_DIR)
    reviews = _read_reviews(root / _REVIEWS_DIR)
    weekly = _read_weekly(root / _WEEKLY_DIR)
    return {
        "version": _INDEX_VERSION,
        "vault": str(vault_root()),
        "workspace": str(root),
        "fingerprint": str(hash(fingerprint)),
        "papers": papers,
        "topics": _topic_table(papers, reviews),
        "domains": _domain_table(papers),
        "reviews": reviews,
        "weekly": weekly,
        "skipped": skipped,
        "counts": {
            "papers": len(papers),
            "topics": len({term for paper in papers for term in paper["topic_terms"]}),
            "domains": len({d for paper in papers for d in paper["domains"]}),
            "reviews": len(reviews),
            "weekly": len(weekly),
            "skipped": len(skipped),
        },
    }


# --- frontmatter ------------------------------------------------------------


def _split(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter, body)``; a file without one yields ``({}, text)``."""
    if not text.startswith("---"):
        return {}, text
    end = _FRONTMATTER_END.search(text, 3)
    if end is None:
        return {}, text
    block = text[3 : end.start()]
    body = text[end.end() :].lstrip("\n")
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as e:
        raise ValueError(f"frontmatter 不是合法 YAML：{e}") from e
    if parsed is None:
        return {}, body
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter 不是键值表")
    return parsed, body


def _as_list(value: Any) -> list[str]:
    """Coerce a frontmatter value to a list of strings.

    Deliberately the same tolerance as `paperctl._as_list`: a card edited by
    hand may hold a bare string where the contract says list, and the page
    should show it rather than drop it.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_text(value: Any) -> str | None:
    """Render a frontmatter scalar, mapping a YAML date back to a string.

    PyYAML resolves a bare `added: 2026-09-27` to a `date`, which is not
    JSON-serialisable and would fail the response where the card is fine.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _section(body: str, heading: str, *, limit: int | None = None) -> str:
    """Return one `## ` section's text from a card body."""
    start = body.find(heading)
    if start == -1:
        return ""
    start = body.find("\n", start)
    if start == -1:
        return ""
    rest = body[start + 1 :]
    match = re.search(r"^##[ \t]", rest, re.M)
    text = (rest[: match.start()] if match else rest).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


# --- papers -----------------------------------------------------------------


def _read_papers(
    papers_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    papers: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if not papers_dir.is_dir():
        return papers, skipped

    for path in sorted(papers_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = _split(text)
        except (OSError, ValueError) as e:
            # Counted, not swallowed: a card the page cannot read is something
            # the page has to be able to admit to.
            logger.warning("vault_index: 跳过无法解析的卡片 {}：{}", path.name, e)
            skipped.append({"path": path.name, "reason": str(e)})
            continue

        declared = _as_text(meta.get("type"))
        if declared is not None and declared != "paper":
            continue

        papers.append(
            {
                "id": _as_text(meta.get("source_id") or meta.get("arxiv_id")) or path.stem,
                "title": _as_text(meta.get("title")) or path.stem,
                "year": _as_int(meta.get("year")),
                "venue": _as_text(meta.get("venue")),
                "venue_tier": _as_text(meta.get("venue_tier")),
                "status": _as_text(meta.get("status")),
                # arXiv categories, straight from the source.
                "topics": _as_list(meta.get("topics")),
                # Research themes, from the review. The two are different axes
                # and the page treats them differently -- see paper-card.md.
                "topic_terms": _as_list(meta.get("topic_terms")),
                "domains": _as_list(meta.get("domains")),
                "added": _as_text(meta.get("added")),
                "updated": _as_text(meta.get("updated")),
                "one_liner": _section(body, _ONELINER_HEADING, limit=_ONELINER_MAX),
                "url": _as_text(meta.get("url")),
                "path": _relative(path),
            }
        )
    return papers, skipped


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(vault_root()))
    except ValueError:  # a vault path that does not contain its own files
        return str(path)


# --- reviews ----------------------------------------------------------------


def _read_reviews(reviews_dir: Path) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    if not reviews_dir.is_dir():
        return reviews

    for path in sorted(reviews_dir.glob("slr-*.md")):
        if path.stem.endswith("-archive"):
            # An archive is a retention artefact: its papers are still cards in
            # 10-Papers, so the browse page already shows them. Listing it again
            # would double-count them under a name nobody browses by.
            continue
        try:
            meta, body = _split(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("vault_index: 跳过无法解析的综述 {}：{}", path.name, e)
            continue

        reviews.append(
            {
                "slug": _as_text(meta.get("topic_slug")) or path.stem.removeprefix("slr-"),
                "topic": _as_text(meta.get("topic")) or path.stem,
                "papers": _as_int(meta.get("papers")),
                "window": _as_text(meta.get("window")),
                "created": _as_text(meta.get("created")),
                "updated": _as_text(meta.get("updated")),
                "themes": _pair_themes(_as_list(meta.get("themes")), body, path.name),
                "path": _relative(path),
            }
        )
    return reviews


def _pair_themes(
    declared: list[str], body: str, filename: str
) -> list[dict[str, str]]:
    """Pair the declared short labels with the body's `### Theme N` headings.

    The two lists are positional, which is a real coupling and is documented in
    `references/review-card.md`. When their lengths disagree the pairing is a
    guess, so it is refused: the headings become the labels instead. A page
    showing a long label is a cosmetic problem; a page showing the *wrong* label
    is a false claim about the user's own work.
    """
    headings = [match.group(1) for match in _THEME_HEADING.finditer(body)]
    if declared and len(declared) == len(headings):
        return [{"term": term, "title": title} for term, title in zip(declared, headings)]
    if declared and len(declared) != len(headings):
        logger.warning(
            "vault_index: {} 声明了 {} 个 themes，正文有 {} 个 Theme 标题，"
            "对不上就不猜，改用正文标题",
            filename,
            len(declared),
            len(headings),
        )
    return [{"term": heading, "title": heading} for heading in headings]


# --- weekly digests ---------------------------------------------------------


def _read_weekly(weekly_dir: Path) -> list[dict[str, Any]]:
    weekly: list[dict[str, Any]] = []
    if not weekly_dir.is_dir():
        return weekly

    for path in sorted(weekly_dir.glob("*.md"), reverse=True):
        try:
            meta, _ = _split(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("vault_index: 跳过无法解析的周报 {}：{}", path.name, e)
            continue
        weekly.append(
            {
                "week": _as_text(meta.get("week")) or path.stem,
                "range": _as_text(meta.get("range")),
                "papers_added": _as_int(meta.get("papers_added")),
                "path": _relative(path),
            }
        )
    return weekly


# --- derived tables ---------------------------------------------------------


def _topic_table(
    papers: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The theme vocabulary, joined from both sides.

    Membership comes from the cards, because that is what `card-enrich` wrote
    and therefore what the graph will draw. The long title and the review it
    belongs to come from the review, because that is where the argument is.
    A term a card carries but no review declares still gets a row: it is on a
    card, so the page has to be able to show it.
    """
    titles: dict[str, str] = {}
    slugs: dict[str, str] = {}
    for review in reviews:
        for theme in review["themes"]:
            titles.setdefault(theme["term"], theme["title"])
            slugs.setdefault(theme["term"], review["slug"])

    counts = Counter(term for paper in papers for term in paper["topic_terms"])
    terms = sorted(set(titles) | set(counts), key=lambda t: (-counts[t], t))
    return [
        {
            "term": term,
            "title": titles.get(term, term),
            "review": slugs.get(term),
            "count": counts[term],
        }
        for term in terms
    ]


def _domain_table(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(domain for paper in papers for domain in paper["domains"])
    labels = _domain_labels()
    return [
        {"id": domain, "label": labels.get(domain, domain), "count": count}
        for domain, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _domain_labels() -> dict[str, str]:
    """Map domain id to its current label, read from the venue registry.

    Read rather than stored on the card, so renaming a domain on the domains
    page renames it here too, and a card collected years ago is not stuck
    carrying the label it was written under.

    A missing registry is not an error: this page is about the vault, and it
    must render even when no registry has ever been built. The id stands in for
    the label, which is what the page would have shown anyway.
    """
    path = get_workspace_path() / "registry" / "domains.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    domains = raw.get("domains")
    if not isinstance(domains, dict):
        return {}
    return {
        str(key): str(value.get("label") or key)
        for key, value in domains.items()
        if isinstance(value, dict)
    }


# --- past questions ---------------------------------------------------------

# The sidebar's rows are every conversation the user has had, across every
# channel, and most are setup chatter -- "我装了feishu", "连上了吗" -- which on
# a page about accumulated knowledge is noise.
_INQUIRY_MARKERS = ("paperctl.py", "literature-search", "资讯检索")

# The agent writes these into the session itself when it resumes work. They are
# not questions anybody asked.
_FRAMING_PREFIXES = (
    "Continue the active task",
    "You are running Dream",
)

# The session-level test below decides whether a conversation *ran* the
# pipeline; this decides which of its messages the page should show. Without it
# the feishu round -- which really did collect the vault's cards -- would be
# presented as having explored "可以了", "不要" and "？".
#
# Length, not a question marker. Measured on the real transcripts, the chatter
# is short ("可以了" 3, "不要" 2, "怎么用" 3, "连上了吗" 4) and the real requests
# are not ("我想看 RAG 最新进展" 12). A marker test is worse in both directions:
# it keeps "怎么用" and drops "我想看 RAG 最新进展", which is the one message in
# that session worth showing.
_MIN_QUESTION_CHARS = 8

_MAX_QUESTIONS_PER_SESSION = 8
_MAX_QUESTION_CHARS = 200


def read_inquiries(
    rows: Iterable[dict[str, Any]],
    *,
    papers: Iterable[dict[str, Any]] = (),
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return past questions that ran the literature pipeline, newest first.

    ``rows`` is `session_list_index.list_webui_sessions`' output -- this reads
    the session files the sidebar already indexed rather than walking the
    session store a second time.

    ``papers`` is what makes the day's context, and it is joined **by date, on
    purpose**. The tempting precision -- reading each session's own `card-write`
    output back to see exactly which cards it wrote -- does not survive contact
    with the transcripts: tool results are truncated mid-payload, so a session
    that wrote 80 cards shows 23 in its JSON block and 48 in its progress lines,
    overlapping and totalling 71. The middle is simply gone, and reporting 71
    would understate the harvest in a way nobody could detect.

    So each inquiry carries `library_that_day` -- what entered the vault that
    day, named for what it is. It is a fact about the library, not a claim about
    the question, and the UI must present it that way.
    """
    by_date: dict[str, list[str]] = {}
    for paper in papers:
        added = (paper.get("added") or "")[:10]
        if added:
            by_date.setdefault(added, []).append(str(paper.get("id")))

    inquiries: list[dict[str, Any]] = []
    for row in rows:
        if len(inquiries) >= limit:
            break
        key = str(row.get("key") or "")
        if key.startswith("dream:"):
            continue
        path = row.get("path")
        if not path:
            continue
        questions = _read_session(Path(path))
        if not questions:
            continue

        created = _as_text(row.get("created_at"))
        updated = _as_text(row.get("updated_at"))
        day = (updated or created or "")[:10]
        inquiries.append(
            {
                "key": key,
                "channel": key.split(":", 1)[0] or None,
                "title": row.get("title") or questions[0],
                "created_at": created,
                "updated_at": updated,
                "questions": questions,
                "library_that_day": {
                    "date": day or None,
                    "papers": sorted(by_date.get(day, [])),
                },
            }
        )
    return inquiries


def _read_session(path: Path) -> list[str]:
    """Return the questions worth showing from one session file, else ``[]``.

    A session counts as an inquiry only if it **ran** the pipeline -- a record
    whose tool *call* names it -- rather than merely mentioning it. The
    difference is not academic: `dream:` consolidation sessions read whole
    transcripts, so their tool *results* are full of the pipeline's words while
    they have never run a thing. Testing the calls and not the results is what
    keeps them off the page.

    The test needs the parsed records, so unlike a raw-text grep it cannot skip
    the JSON decode. The files are small (the largest here is 333KB) and this
    runs once per session behind the index cache.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not any(marker in text for marker in _INQUIRY_MARKERS):
        return []

    questions: list[str] = []
    ran_pipeline = False

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue

        calls = record.get("tool_calls")
        if calls and not ran_pipeline:
            blob = json.dumps(calls, ensure_ascii=False)
            ran_pipeline = any(marker in blob for marker in _INQUIRY_MARKERS)

        if record.get("role") != "user":
            continue
        content = record.get("content")
        if isinstance(content, list):
            # A multimodal turn: keep the text parts, drop the attachments.
            content = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        question = _as_question(content)
        if question and question not in questions:
            questions.append(question)

    return questions[:_MAX_QUESTIONS_PER_SESSION] if ran_pipeline else []


def _as_question(content: Any) -> str | None:
    """Return a user message worth showing, or ``None`` if it is not one."""
    question = str(content or "").strip()
    if not question or question.startswith(_FRAMING_PREFIXES):
        return None
    if len(question) < _MIN_QUESTION_CHARS:
        return None
    if len(question) > _MAX_QUESTION_CHARS:
        question = question[:_MAX_QUESTION_CHARS].rstrip() + "…"
    return question
