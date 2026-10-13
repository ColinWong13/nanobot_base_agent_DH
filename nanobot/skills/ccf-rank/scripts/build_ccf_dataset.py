#!/usr/bin/env python
"""Build a searchable CCF rank dataset from the official PDF."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

RANK_RE = re.compile(r"[一二三]、\s*([ABC])\s*类")
ROW_START_RE = re.compile(r"^(\d+)\s+\S+")
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
UPPER_TOKEN_RE = re.compile(r"^[A-Z0-9][A-Z0-9+&./-]*$")
ORG_TOKENS = {"ACM", "IEEE", "USENIX", "AAAI", "SIAM", "CVF", "IFIP", "CCF"}

PUBLISHERS = [
    "Springer-Nature",
    "Taylor & Francis",
    "MIT Press",
    "Cambridge University Press",
    "Oxford University Press",
    "World Scientific",
    "IEEE/ACM",
    "ACM/IEEE",
    "CCF/Springer",
    "Springer",
    "Elsevier",
    "USENIX",
    "Morgan Kaufmann",
    "Kluwer",
    "Pergamon",
    "Wiley",
    "AAAI",
    "SIAM",
    "IOS Press",
    "ACM",
    "IEEE",
    "CCF",
]


def normalize(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("－", "-")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_area_line(line: str) -> bool:
    if not (line.startswith("(") and line.endswith(")")):
        return False
    core = line[1:-1].strip()
    if not core:
        return False
    if re.fullmatch(r"\d{4}年", core):
        return False
    if "原" in core and len(core) <= 12:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in core)


def split_entry(entry: str) -> tuple[str, str, str]:
    publisher = ""
    left = entry

    for p in PUBLISHERS:
        if left.endswith(f" {p}"):
            publisher = p
            left = left[: -(len(p) + 1)].strip()
            break

    tokens = left.split()
    if not tokens:
        return "", "", publisher

    abbr_tokens: list[str] = []
    for tok in tokens:
        if UPPER_TOKEN_RE.match(tok):
            abbr_tokens.append(tok)
            if len(abbr_tokens) >= 4:
                break
            continue
        break

    # Trim noisy org token tails like "TOCS ACM" or "CVPR IEEE/CVF".
    if (
        len(abbr_tokens) >= 2
        and abbr_tokens[0] not in ORG_TOKENS
        and (abbr_tokens[1] in ORG_TOKENS or "/" in abbr_tokens[1])
    ):
        abbr_tokens = abbr_tokens[:1]

    if not abbr_tokens:
        abbr = tokens[0]
        fullname = " ".join(tokens[1:]).strip()
    else:
        abbr = " ".join(abbr_tokens)
        fullname = " ".join(tokens[len(abbr_tokens) :]).strip()

    if not fullname:
        fullname = left

    return abbr, fullname, publisher


def build_records(pdf_path: Path) -> list[dict]:
    reader = PdfReader(str(pdf_path))

    mode: str | None = None
    rank: str | None = None
    area: str | None = None
    buffer: str | None = None
    records: list[dict] = []

    for page_no, page in enumerate(reader.pages, start=1):
        lines = [normalize(x) for x in (page.extract_text() or "").splitlines() if normalize(x)]

        for line in lines:
            if "推荐国际学术期刊" in line:
                mode = "journal"
                continue
            if "推荐国际学术会议" in line:
                mode = "conference"
                continue

            rank_match = RANK_RE.search(line)
            if rank_match:
                rank = rank_match.group(1)
                continue

            if is_area_line(line):
                area = line[1:-1].strip()
                continue

            if "序号" in line and ("期刊简称" in line or "会议简称" in line):
                continue

            if ROW_START_RE.match(line):
                buffer = line
            elif buffer is not None:
                buffer = f"{buffer} {line}"
            else:
                continue

            url_match = URL_RE.search(buffer)
            if not url_match:
                continue

            url = url_match.group(0)
            left = normalize(buffer[: url_match.start()])

            idx_match = re.match(r"^(\d+)\s+(.*)$", left)
            if not idx_match:
                buffer = None
                continue

            index = int(idx_match.group(1))
            entry = idx_match.group(2).strip()

            abbr, fullname, publisher = split_entry(entry)
            aliases = sorted({abbr, abbr.split()[0] if abbr else ""} - {""})

            records.append(
                {
                    "type": mode,
                    "rank": rank,
                    "area": area,
                    "index": index,
                    "abbreviation": abbr,
                    "full_name": fullname,
                    "publisher": publisher,
                    "entry": entry,
                    "url": url,
                    "page": page_no,
                    "aliases": aliases,
                }
            )
            buffer = None

    # Fill leading missing area values using nearest known area in each type block.
    next_area: dict[str, str] = {}
    for rec in reversed(records):
        t = rec.get("type")
        a = rec.get("area")
        if t and a:
            next_area[t] = a
        elif t and not a and t in next_area:
            rec["area"] = next_area[t]

    return records


def write_json(path: Path, data: Iterable[dict]) -> None:
    path.write_text(json.dumps(list(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_exclusions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules: list[dict] = []
    for item in raw:
        rules.append(
            {
                "abbreviation": normalize(str(item.get("abbreviation", ""))).upper(),
                "url": str(item.get("url", "")).strip(),
                "type": str(item.get("type", "")).strip(),
                "rank": str(item.get("rank", "")).strip(),
            }
        )
    return rules


def should_exclude(record: dict, rules: list[dict]) -> bool:
    for rule in rules:
        ok = True
        if rule.get("abbreviation"):
            ok = ok and record.get("abbreviation", "").upper() == rule["abbreviation"]
        if rule.get("url"):
            ok = ok and record.get("url", "") == rule["url"]
        if rule.get("type"):
            ok = ok and record.get("type", "") == rule["type"]
        if rule.get("rank"):
            ok = ok and record.get("rank", "") == rule["rank"]
        if ok:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CCF dataset JSON from a CCF catalog PDF")
    parser.add_argument("pdf", type=Path, help="Path to CCF catalog PDF")
    parser.add_argument(
        "--year",
        default="2026",
        help="CCF catalog year, used for default output/exclusion paths",
    )
    parser.add_argument("--out", type=Path, help="Output JSON path")
    parser.add_argument(
        "--exclude",
        type=Path,
        help="Optional JSON list of entries to exclude (abbreviation/url)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "manifest.json",
        help="Path to references manifest JSON",
    )
    args = parser.parse_args()
    year = str(args.year).strip()
    references_root = Path(__file__).resolve().parents[1] / "references"
    out_path = args.out or (references_root / year / "rankings.json")
    exclude_path = args.exclude or (references_root / year / "excluded_venues.json")

    records = build_records(args.pdf)
    exclude_rules = load_exclusions(exclude_path)
    if exclude_rules:
        records = [r for r in records if not should_exclude(r, exclude_rules)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, records)

    manifest = {"default_year": year, "years": [year]}
    if args.manifest.exists():
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {"default_year": year, "years": [year]}
    years = sorted({str(y) for y in manifest.get("years", []) if str(y).strip()} | {year})
    manifest["years"] = years
    numeric_years = sorted([y for y in years if re.fullmatch(r"\d{4}", y)], key=int)
    manifest["default_year"] = numeric_years[-1] if numeric_years else year
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stats: dict[str, int] = {"journal": 0, "conference": 0}
    for r in records:
        if r["type"] in stats:
            stats[r["type"]] += 1

    print(f"wrote {len(records)} records to {out_path}")
    print(f"journal={stats['journal']} conference={stats['conference']}")


if __name__ == "__main__":
    main()
