#!/usr/bin/env python3
"""Build `workspace/registry/domains.json` from local, offline reference data.

Two sources, neither of which touches the network:

* **ai**      — the CCF venue dataset shipped by the `ccf-rank` skill.
* **finance** — `references/finance_venues.json`, whose ISSNs were verified
                against OpenAlex and whose tiers record their own provenance.

This is a build-time tool, not a runtime one: rerun it when the CCF dataset is
refreshed or the finance seed is edited.

**Everything the user edits survives a rebuild.** The generated venue list is
only the *base*; the prior file's curation is merged onto it:

* a venue's ``enabled`` flag, matched by name
* a venue's ``tier``, via ``overrides.tier`` -- and every generated row carries
  ``base_tier``, the tier the source gives it *this* run, so restoring is
  ``tier = base_tier`` and needs no help from this script
* venues the user added -- rows carrying ``origin: "user"``
* venues the user deleted, via ``overrides.removed`` (a tombstone, so a later
  dataset refresh cannot resurrect a venue the user rejected)
* ``label`` / ``aliases`` / ``arxiv_cats`` on the seeded domains
* any domain that is not seeded here, passed through untouched

``--force`` therefore means "discard the curation and take the sources as they
are", which is the only sense left once nothing is gated.

Usage:
    python3 scripts/build_registry.py                     # write domains.json
    python3 scripts/build_registry.py --dry-run           # report, write nothing
    python3 scripts/build_registry.py --force             # discard user curation
    python3 scripts/build_registry.py --out /tmp/x.json   # rebuild elsewhere
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
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
_CCF_YEAR = "2026"
# A sibling skill, found beside this one rather than under the workspace: both
# layouts keep their skills in a common parent, so this path holds whether the
# pair is installed in the package or sitting in a workspace.
_CCF_RANKINGS = _SKILL_DIR.parent / "ccf-rank" / "references" / _CCF_YEAR / "rankings.json"
_FINANCE_SEED = _SKILL_DIR / "references" / "finance_venues.json"

# arXiv categories per domain. These drive retrieval far more than the venue
# list does for CS (preprint culture), so they are worth getting right.
_AI_ARXIV_CATS = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.IR", "cs.NE", "cs.MA", "cs.RO"]
_FINANCE_ARXIV_CATS = ["q-fin.PM", "q-fin.ST", "q-fin.TR", "q-fin.RM", "q-fin.GN", "q-fin.EC"]

# CCF areas folded into the 'ai' domain, with the tier that starts enabled.
_AI_AREAS = {
    "人工智能": {"A"},
    "数据库/数据挖掘/内容检索": {"A"},
    "计算机图形学与多媒体": {"A"},
}

# The upstream CCF dataset is extracted from a PDF and ~3% of records carry a
# mangled abbreviation ('SIG- METRICS', 'AAAI AAAI'). Writing one of those into
# the registry produces a venue named after its own publisher, so they are
# reported at build time instead of being silently accepted.
_CORRUPT_PATTERNS = (
    (re.compile(r"-\s"), "连字符后跟空格（PDF 换行残留）"),
    (re.compile(r"\s(ACM|IEEE|CCF)$"), "尾部重复出版商名"),
    (re.compile(r"^(\w+)\s+\1$"), "重复词"),
)

# Hand-checked repairs for corrupt abbreviations in the areas we seed. Dropping
# these outright would silently remove CCF-A venues (AAAI, ACM MM) from the
# registry, which is worse than the corruption itself. Keyed on the mangled
# form exactly as it appears in the dataset; the value is the correct name.
_ABBREVIATION_REPAIRS = {
    "AAAI AAAI": "AAAI",
    "ACM MM ACM": "ACM MM",
    "IEEE VIS IEEE": "IEEE VIS",
    "INTER- SPEECH": "INTERSPEECH",
}

# A single Titlecase word ('Natural', 'Computer') is how a *split* venue name
# looks in the abbreviation column, but it is also how a handful of one-word
# journal names legitimately look ('Algorithmica', 'Cognition'). See
# `repair_split_name` for the rule that tells them apart.
_TITLECASE_ONLY = re.compile(r"^[A-Z][a-z]+$")

# Second corruption class, measured 2026-09-27: the PDF extraction split a
# journal's name across two columns --
#     abbreviation='Computer', full_name='Speech & Language'
# -- so the registry ended up with a venue literally named 'Computer'. That is
# not merely cosmetic: `normalize.py` matches abbreviations case-sensitively
# against arXiv comments, and 'Natural language processing' in a comment
# matched the venue 'Natural' (Natural Computing, CCF-C). Three unrelated RAG
# papers were tiered off the words 'Natural' and 'Computer'.
#
# The rule, in order:
#   1. abbr == full_name        -> a duplicated column, not a split. Keep abbr.
#   2. full_name starts with abbr -> the *publisher* over-captured into
#      full_name ('Cybersecurity 中国科学院信...'). Keep abbr.
#   3. abbr is Titlecase-only   -> the name was split. Rejoin the two columns.
# Anything else is the normal shape ('TOCS' + 'ACM Transactions on ...') and
# is left alone.
#
# Third corruption class, same root cause: a full_name that wraps to a second
# line in the PDF pushes its continuation word into the *next* row's
# abbreviation column. 'EAAI' lost the last word of its name this way, and the
# row below it -- really the journal 'Expert Systems' (dblp `journals/es/`) --
# was left holding the orphan word 'Intelligence' as its abbreviation.
_FULL_NAME_REPAIRS = {
    "Engineering Applications of Artificial": "Engineering Applications of Artificial Intelligence",
}

# Rule-3 survivors whose abbreviation is genuinely the venue's whole short name,
# so rejoining the two columns would produce 'Middleware International
# Middleware Conference ACM/IFIP/USENIX'. These map to the true name instead.
# Hand-checked; 'Intelligence' is the column-bleed row described above.
_SPLIT_NAME_KEEP_ABBR = {
    "Middleware": "Middleware",
    "Internetware": "Internetware",
    "Eurographics": "Eurographics",
    "Networking": "Networking",
    "Intelligence": "Expert Systems",
}


def flag_corrupt(abbreviation: str) -> str | None:
    """Return a human-readable reason if *abbreviation* looks like a PDF artifact."""
    for pattern, reason in _CORRUPT_PATTERNS:
        if pattern.search(abbreviation):
            return reason
    return None


def repair_split_name(abbreviation: str, full_name: str) -> str | None:
    """Return the venue's real name if *abbreviation* is a split fragment.

    Returns None when the record has the normal `abbr` + `full_name` shape and
    needs no repair.
    """
    if abbreviation == full_name:
        return abbreviation
    if full_name.startswith(abbreviation):
        return abbreviation
    if abbreviation in _SPLIT_NAME_KEEP_ABBR:
        return _SPLIT_NAME_KEEP_ABBR[abbreviation]
    if _TITLECASE_ONLY.match(abbreviation):
        return f"{abbreviation} {full_name}"
    return None


def load_ccf_venues() -> tuple[list[dict], list[tuple[str, str]]]:
    """Return (venues, suspects) for the AI domain from the CCF dataset."""
    if not _CCF_RANKINGS.exists():
        raise SystemExit(
            f"找不到 CCF 数据集：{_CCF_RANKINGS}\n"
            "请先确认 ccf-rank 技能已安装，或用 --ccf-rankings 指定路径。"
        )
    records = json.loads(_CCF_RANKINGS.read_text(encoding="utf-8"))

    venues: list[dict] = []
    suspects: list[tuple[str, str]] = []
    seen: set[str] = set()

    for record in records:
        area = record.get("area")
        rank = record.get("rank")
        if area not in _AI_AREAS or rank not in {"A", "B", "C"}:
            continue

        abbreviation = (record.get("abbreviation") or "").strip()
        full_name = (record.get("full_name") or "").strip()
        full_name = _FULL_NAME_REPAIRS.get(full_name, full_name)
        if not abbreviation or not full_name:
            continue

        # Repair the corrupt abbreviations we have hand-checked; report the rest.
        if abbreviation in _ABBREVIATION_REPAIRS:
            abbreviation = _ABBREVIATION_REPAIRS[abbreviation]
        elif reason := flag_corrupt(abbreviation):
            suspects.append((f"{abbreviation} ({full_name[:40]})", reason))
            continue

        # A repaired name is the venue's whole name, so its `full_name` column
        # is either a fragment of it ('of Cryptology') or a duplicate of it
        # ('Networks'). Keep both out of the match index: `full_name` matches
        # case-insensitively, and a bare 'networks' would fire on every paper
        # that mentions a network.
        repaired = repair_split_name(abbreviation, full_name)
        name, full_name = (repaired, "") if repaired else (abbreviation, full_name)

        if name in seen:
            continue
        seen.add(name)

        venues.append(
            {
                "name": name,
                "full_name": full_name,
                "type": record.get("type"),
                "tier": rank,
                "area": area,
                "enabled": rank in _AI_AREAS[area],
                "origin": f"ccf-{_CCF_YEAR}",
            }
        )

    venues.sort(key=lambda v: (v["tier"], v["type"], v["name"]))
    return venues, suspects


def load_finance_venues() -> tuple[list[dict], list[tuple[str, str]]]:
    """Return (venues, suspects) for the finance domain from the verified seed."""
    if not _FINANCE_SEED.exists():
        raise SystemExit(f"找不到金融 seed：{_FINANCE_SEED}")
    seed = json.loads(_FINANCE_SEED.read_text(encoding="utf-8"))
    venues = [
        {
            "name": entry["name"],
            "issn": entry["issn"],
            "type": "journal",
            "tier": entry["tier"],
            "tier_source": entry["tier_source"],
            # A* and A are list-verified, so they start on; B is editorial.
            "enabled": entry["tier"] in {"A*", "A"},
            "origin": "ft50/utd24" if entry["tier_source"].startswith("ft50") else "field",
        }
        for entry in seed.get("venues", [])
    ]
    return venues, []


# The domains this script generates, and the source each one rebuilds from.
# A domain in the file that is *not* named here has no upstream, so it is
# passed through untouched -- which is what makes a hand-made domain survive.
_SEEDED = (
    {
        "key": "ai",
        "label": "人工智能 / AI",
        "aliases": ["AI", "人工智能", "机器学习", "深度学习", "NLP", "计算机视觉"],
        "arxiv_cats": _AI_ARXIV_CATS,
        "origin": f"ccf-{_CCF_YEAR}",
        "load": load_ccf_venues,
    },
    {
        "key": "finance",
        "label": "金融 / Finance",
        "aliases": ["金融", "金融学", "公司金融", "资产定价", "Finance"],
        "arxiv_cats": _FINANCE_ARXIV_CATS,
        "origin": "finance-seed",
        "load": load_finance_venues,
    },
)

# Domain fields the user owns once the domain exists: a rebuild only seeds them
# the first time. `arxiv_cats` in particular drives retrieval, so an edit there
# must not be reverted by the next refresh.
_USER_OWNED_FIELDS = ("label", "aliases", "arxiv_cats")


def carry_overrides(prior: dict) -> dict:
    """Return the prior file's override ledger, normalised, never pruned.

    A tier override or a tombstone can outlive the venue it names -- a later CCF
    refresh may bring that venue back -- and dropping either would silently undo
    a decision the user already made. Pruning is the UI's job, on purpose.
    """
    overrides = prior.get("overrides")
    if not isinstance(overrides, dict):
        return {"tier": {}, "removed": []}
    tier = overrides.get("tier")
    removed = overrides.get("removed")
    return {
        "tier": {
            name: value
            for name, value in (tier if isinstance(tier, dict) else {}).items()
            if isinstance(name, str) and isinstance(value, str) and value
        },
        "removed": [n for n in removed if isinstance(n, str)] if isinstance(removed, list) else [],
    }


def merge_prior_venues(base: list[dict], prior: dict) -> list[dict]:
    """Layer the prior file's curation onto a freshly generated venue list.

    `base` is mutated in place -- its dicts are freshly built by the loaders and
    owned by this call. The result is the *effective* list, so every consumer
    keeps reading one array with no knowledge of the override ledger.
    """
    ledger = carry_overrides(prior)
    tier_overrides = ledger["tier"]
    removed = set(ledger["removed"])
    prior_rows = {
        row["name"]: row
        for row in prior.get("venues") or []
        if isinstance(row, dict) and row.get("name")
    }

    merged: list[dict] = []
    for venue in base:
        if venue["name"] in removed:
            continue
        # Remember what the source says *this run*, before any override touches
        # it. This is the value "restore the source tiers" puts back -- recording
        # the old value inside the override instead would freeze a snapshot that
        # the next dataset refresh silently falsifies.
        venue["base_tier"] = venue["tier"]
        row = prior_rows.get(venue["name"])
        if row is not None and "enabled" in row:
            venue["enabled"] = bool(row["enabled"])
        merged.append(venue)

    # A venue the user added has no source to regenerate it from, so the row
    # itself is carried forward rather than kept in a second list. It carries no
    # `base_tier`: there is no source tier for it to be restored to.
    known = {venue["name"] for venue in merged}
    for row in prior.get("venues") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if row.get("origin") == "user" and name and name not in known and name not in removed:
            known.add(name)
            merged.append(row)

    # Tier overrides apply last: that way they also reach the user-added rows,
    # and the user's tier wins whatever the source says about the venue today.
    for venue in merged:
        override = tier_overrides.get(venue["name"])
        if isinstance(override, str) and override:
            venue["tier"] = override

    merged.sort(key=lambda v: (v.get("tier") or "", v.get("type") or "", v.get("name") or ""))
    return merged


def _load_existing() -> dict:
    """Return the prior file's `domains` mapping, or {} if there is no usable one."""
    if not _REGISTRY.exists():
        return {}
    try:
        existing = json.loads(_REGISTRY.read_text(encoding="utf-8")).get("domains")
    except json.JSONDecodeError:
        return {}
    return existing if isinstance(existing, dict) else {}


def build(force: bool) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = _load_existing()
    suspects: list[str] = []
    domains: dict[str, dict] = {}

    for spec in _SEEDED:
        base, found = spec["load"]()
        suspects.extend(f"{name} → {reason}" for name, reason in found)
        prior = {} if force else (existing.get(spec["key"]) or {})

        entry: dict = {
            "label": spec["label"],
            "aliases": list(spec["aliases"]),
            "arxiv_cats": list(spec["arxiv_cats"]),
            "origin": spec["origin"],
            # No longer a gate: nothing downstream consults this, so a rebuild
            # cannot switch preservation off. It records that the user read the
            # list, nothing more.
            "confirmed": bool(prior.get("confirmed")),
            "updated_at": now,
            "venues": merge_prior_venues(base, prior),
            "overrides": carry_overrides(prior),
        }
        # Seed these only on the first build; afterwards they are the user's.
        for field in _USER_OWNED_FIELDS:
            if prior.get(field):
                entry[field] = prior[field]
        domains[spec["key"]] = entry

    # Any other domain was made by hand and has no source to rebuild from, so it
    # goes back exactly as it came. `--force` means "take only what the sources
    # say", which is the one case where it is dropped along with the rest.
    if not force:
        for key, prior in existing.items():
            if key not in domains and isinstance(prior, dict):
                domains[key] = prior

    return {"version": 1, "domains": domains, "_suspects": suspects}


def _write_atomic(path: Path, text: str) -> None:
    """Write *text* to *path* through a same-directory temp file and a rename.

    The same discipline as the API side's `_write_text_atomic`, reimplemented
    rather than imported: this script runs standalone with whatever `python3` is
    on PATH. A half-written registry is the one failure the merge cannot undo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build registry/domains.json")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Discard the user's curation and take the sources as they are",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required with --force: confirms the destructive rebuild",
    )
    parser.add_argument("--ccf-rankings", type=Path, help="Override the CCF dataset path")
    parser.add_argument("--out", type=Path, help="Override the output path")
    args = parser.parse_args(argv)

    if args.force and not args.yes and not args.dry_run:
        raise SystemExit("--force 会丢弃全部手动改动（勾选、tier、手加的 venue/领域）。\n"
                         "确认要这么做就再加 --yes；先看看会丢什么就加 --dry-run。")

    global _CCF_RANKINGS, _REGISTRY
    if args.ccf_rankings:
        _CCF_RANKINGS = args.ccf_rankings
    if args.out:
        _REGISTRY = args.out

    payload = build(force=args.force)
    # Read, never pop: this used to be popped for printing and so never reached
    # the file, which left the API's `_suspects` permanently empty and the page's
    # warning strip permanently dead.
    suspects = payload["_suspects"]

    for key, domain in payload["domains"].items():
        venues = domain.get("venues") or []
        enabled = sum(1 for v in venues if v.get("enabled"))
        ledger = domain.get("overrides") or {}
        kept = len(ledger.get("tier") or {}) + len(ledger.get("removed") or [])
        kept_text = f"  保留改动 {kept} 处" if kept else ""
        print(
            f"  {key:<10} {len(venues):>3} 个 venue"
            f"（启用 {enabled}）  arXiv 分类 {len(domain.get('arxiv_cats') or [])} 个"
            f"{kept_text}"
        )

    if suspects:
        print(f"\n⚠️  {len(suspects)} 条 CCF 记录因缩写损坏被跳过（需人工确认）：")
        for item in suspects:
            print(f"    - {item}")

    if args.dry_run:
        print("\n[dry-run] 未写入。")
        return 0

    # Keep the previous file beside the new one. This script is the only thing
    # that rewrites the whole registry, and its failure mode is silent loss, so
    # one generation of undo is worth two lines.
    if _REGISTRY.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = _REGISTRY.with_name(f"{_REGISTRY.name}.bak-{stamp}")
        backup.write_bytes(_REGISTRY.read_bytes())
        print(f"\n（上一版已备份到 {backup.name}）")

    _write_atomic(_REGISTRY, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"\n✅ 已写入 {_REGISTRY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
