#!/usr/bin/env python3
"""Query the CCF (China Computer Federation) venue ranking dataset.

Python port of the upstream `query_ccf_rank.mjs`, with two additions:

* ``--list``  — skip the fuzzy scoring and just enumerate venues matching the
  filters. Needed when building a domain registry ("every CCF-A AI conference")
  rather than looking one venue up by name.
* ``--area``  — filter on the Chinese ``area`` field.

Scoring is reproduced exactly from the upstream JavaScript; see ``score_record``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_YEAR = "2026"


def load_manifest(skill_dir: Path = _SKILL_DIR) -> dict:
    """Returns the manifest, falling back to a sane default if it is unusable."""
    manifest_path = skill_dir / "references" / "manifest.json"
    fallback = {"default_year": _DEFAULT_YEAR, "years": [_DEFAULT_YEAR]}
    if not manifest_path.exists():
        return fallback
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

    years = [str(y) for y in manifest.get("years", []) if isinstance(y, (str, int))]
    valid = sorted((y for y in years if re.fullmatch(r"\d{4}", y)), reverse=True)
    return {
        "default_year": valid[0] if valid else str(manifest.get("default_year", _DEFAULT_YEAR)),
        "years": years or [_DEFAULT_YEAR],
    }


def norm(value: object) -> str:
    """Lowercases, turns ``-``/``_`` into spaces, and collapses whitespace."""
    text = str(value if value is not None else "")
    return re.sub(r"\s+", " ", text.lower().replace("-", " ").replace("_", " ")).strip()


def score_record(record: dict, query: str) -> int:
    """Scores one record against *query*.

    Mirrors the upstream JavaScript exactly: exact abbreviation hits outrank
    aliases, which outrank full-name and entry substring hits, with a token
    bonus and a tie-break nudge for A-rank venues.
    """
    q = norm(query)
    q_compact = q.replace(" ", "")

    abbreviation = norm(record.get("abbreviation"))
    full_name = norm(record.get("full_name"))
    entry = norm(record.get("entry"))
    aliases = [norm(a) for a in (record.get("aliases") or [])]

    score = 0

    if q == abbreviation or q_compact == abbreviation.replace(" ", ""):
        score += 130
    if q in aliases or q_compact in [a.replace(" ", "") for a in aliases]:
        score += 100
    if q and q in full_name:
        score += 70
    if q and q in entry:
        score += 60

    tokens = [t for t in q.split(" ") if t]
    if tokens and all(t in entry for t in tokens):
        score += 40

    if score > 0 and record.get("rank") == "A":
        score += 1

    return score


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    manifest = load_manifest()
    parser = argparse.ArgumentParser(
        description="Look up CCF conference/journal rankings.",
    )
    parser.add_argument("query", nargs="?", help="Venue name or abbreviation")
    parser.add_argument("--year", default=manifest["default_year"], help="Dataset year")
    parser.add_argument("--type", choices=["conference", "journal"], help="Restrict to a type")
    parser.add_argument("--rank", choices=["A", "B", "C"], help="Restrict to a rank")
    parser.add_argument("--area", help="Substring match against the Chinese area field")
    parser.add_argument("--top", type=int, default=8, help="Max results (default 8)")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Enumerate matches instead of scoring; requires --type/--rank/--area",
    )
    parser.add_argument("--data", help="Override path to rankings.json")
    return parser.parse_args(argv)


def resolve_data_path(args: argparse.Namespace) -> Path:
    if args.data:
        return Path(args.data).expanduser().resolve()
    return _SKILL_DIR / "references" / args.year / "rankings.json"


def select(records: list[dict], args: argparse.Namespace) -> list[tuple[int, dict]]:
    """Applies filters and returns ``(score, record)`` pairs, best first."""
    kept: list[tuple[int, dict]] = []
    for record in records:
        if args.type and record.get("type") != args.type:
            continue
        if args.rank and record.get("rank") != args.rank:
            continue
        if args.area and args.area.lower() not in str(record.get("area", "")).lower():
            continue

        if args.list:
            kept.append((0, record))
            continue

        score = score_record(record, args.query or "")
        if score > 0:
            kept.append((score, record))

    if args.list:
        kept.sort(key=lambda pair: str(pair[1].get("abbreviation") or ""))
        return kept

    # Two stable passes: abbreviation descending, then score descending. The
    # second sort dominates, giving score-primary / abbreviation-secondary order.
    kept.sort(key=lambda pair: str(pair[1].get("abbreviation") or ""), reverse=True)
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return kept


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.list and not args.query:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Provide a query, or use --list with --type/--rank/--area.",
                },
                indent=2,
            )
        )
        return 2

    data_path = resolve_data_path(args)
    if not data_path.exists():
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"No dataset at {data_path}. Check --year or --data.",
                },
                indent=2,
            )
        )
        return 1

    records = json.loads(data_path.read_text(encoding="utf-8"))
    matches = select(records, args)

    payload = {
        "status": "success",
        "query": args.query,
        "year": args.year,
        "filters": {"type": args.type, "rank": args.rank, "area": args.area},
        "total_matches": len(matches),
        "returned": min(args.top, len(matches)),
        "matches": [
            {
                "score": score,
                "type": record.get("type"),
                "rank": record.get("rank"),
                "abbreviation": record.get("abbreviation"),
                "full_name": record.get("full_name"),
                "area": record.get("area"),
                "publisher": record.get("publisher"),
                "url": record.get("url"),
                "aliases": record.get("aliases") or [],
            }
            for score, record in matches[: args.top]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
