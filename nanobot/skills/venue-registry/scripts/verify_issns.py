# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "polite-http",
# ]
# ///
"""Verify proposed journal ISSNs against OpenAlex.

Each candidate in the input file carries a *proposed* ISSN. This script asks
OpenAlex `sources?filter=issn:<proposed>` and reports what actually lives at
that ISSN, so a typo or a stale ISSN is caught before it reaches the registry.

Why verify by ISSN rather than search by name: OpenAlex prices a `filter` call
at $0.0001 and a full-text `search` at $0.001 — 10x. The no-key daily budget is
$0.01, so name-searching ~26 journals would blow the budget while ISSN-verify-
ing them costs about $0.0026.

Usage:
    uv run scripts/verify_issns.py references/finance_candidates.json
    uv run scripts/verify_issns.py references/finance_candidates.json --json > verified.json

Exit codes: 0 if every ISSN resolved, 1 if any candidate failed to resolve.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from polite_http import http_client

_BASE_URL = "https://api.openalex.org/"
_CLIENT = http_client.HttpClient(_BASE_URL, qps=10)

# A proposed name and OpenAlex's canonical name will not match character for
# character ("Journal of Banking & Finance" vs "Journal of Banking & Finance").
# We only need to catch gross mismatches, so compare on alphanumerics only.
def _normalise(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def resolve_issn(issn: str) -> dict | None:
    """Return the OpenAlex source at *issn*, or None if nothing lives there."""
    url = f"{_BASE_URL}sources?filter=issn:{issn}&select=id,display_name,issn_l,issn,type,host_organization_name"
    payload = json.loads(_CLIENT.fetch_bytes(url))
    results = payload.get("results") or []
    return results[0] if results else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify proposed ISSNs against OpenAlex")
    parser.add_argument("candidates", type=Path, help="JSON file with a 'candidates' array")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat a name mismatch as a failure, not just a warning",
    )
    args = parser.parse_args(argv)

    data = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = data.get("candidates") or []

    verified: list[dict] = []
    failures: list[str] = []

    for i, entry in enumerate(candidates, 1):
        name = entry["name"]
        proposed = entry["issn"]
        try:
            source = resolve_issn(proposed)
        except Exception as exc:  # network, HTTP, JSON — all mean "unverified"
            print(f"[{i}/{len(candidates)}] {name:<50} ⚠️  查询失败: {exc}", file=sys.stderr)
            failures.append(f"{name} ({proposed}): lookup error")
            continue

        if source is None:
            print(f"[{i}/{len(candidates)}] {name:<50} ❌ ISSN {proposed} 在 OpenAlex 不存在", file=sys.stderr)
            failures.append(f"{name} ({proposed}): no source at this ISSN")
            continue

        actual = source.get("display_name") or ""
        same = _normalise(name) == _normalise(actual)
        # Accept the candidate's own ISSN or any alternate ISSN OpenAlex lists
        # for the same source (journals routinely have print + electronic ISSNs).
        issns = set(source.get("issn") or []) | {source.get("issn_l") or ""}

        record = {
            "name": name,
            "proposed_issn": proposed,
            "openalex_id": source.get("id"),
            "openalex_name": actual,
            "issn_l": source.get("issn_l"),
            "issns": sorted(x for x in issns if x),
            "publisher": source.get("host_organization_name"),
            "type": source.get("type"),
            "name_match": same,
            "tier_claim": entry.get("tier_claim"),
        }
        verified.append(record)

        if same:
            mark = "✅"
        else:
            mark = "⚠️ 名称不符"
            if args.strict:
                failures.append(f"{name} ({proposed}): resolved to '{actual}'")
        print(
            f"[{i}/{len(candidates)}] {name:<50} {mark}  → {actual} | {source.get('issn_l')}",
            file=sys.stderr,
        )

    if args.json:
        json.dump(
            {"verified": verified, "failures": failures, "count": len(verified)},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
    else:
        print(f"\n核实完成：{len(verified)}/{len(candidates)} 命中", file=sys.stderr)
        if failures:
            print(f"需人工处理 {len(failures)} 条：", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
