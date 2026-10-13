---
name: ccf-rank
description: Query CCF (China Computer Federation) venue rankings for conferences and journals using year-partitioned reference data. Use when users ask for CCF level (A/B/C), category/domain, or rank verification for a venue abbreviation/full name (for example ICML, CVPR, TOCS), or request batch lookup/comparison across venues or years.
---

# ccf-rank

Answer CCF ranking questions quickly and consistently.

> **Scope:** CCF ranks **computer science** venues only. It says nothing about
> finance, economics, or other fields — use FT50 / UTD24 / ABS for those.

## Data source

- Dataset index: `references/manifest.json`
- Year data: `references/<year>/rankings.json` (678 venues: 298 journals, 380 conferences)
- Year exclusions: `references/<year>/excluded_venues.json`

## Query workflow

1. Look a venue up by name or abbreviation:

   ```bash
   python3 scripts/query_ccf_rank.py "NeurIPS"
   ```

   Output is JSON. Uses the latest available year unless `--year <YYYY>` is given.

2. Narrow ambiguous queries by type/rank:

   ```bash
   python3 scripts/query_ccf_rank.py "neural information" --type conference --rank A --top 20
   ```

3. **Enumerate** venues when you need a whole set rather than one lookup — this is
   what the domain registry is built from:

   ```bash
   python3 scripts/query_ccf_rank.py --list --type conference --rank A --area 人工智能 --top 100
   ```

   `--list` skips fuzzy scoring and returns everything matching the filters.
   It requires at least one of `--type` / `--rank` / `--area`, since the full
   set is 678 venues.

4. For several venues, run per venue and return a compact table of
   `venue`, `type`, `rank`, `area`, `url`.

5. If several matches score alike, show the top few and ask the user to disambiguate.

## Scoring

`score_record()` is a faithful port of upstream `query_ccf_rank.mjs`. Bonuses **stack**:

| Condition | Points |
|---|---|
| query equals the abbreviation | +130 |
| query equals an alias | +100 |
| query is a substring of the full name | +70 |
| query is a substring of the entry line | +60 |
| every query token appears in the entry line | +40 |
| rank is A (tie-break only, requires score > 0) | +1 |

So `NeurIPS` scores 331 (130+100+60+40+1), not 131 — the bonuses are cumulative.

## Output rules

- Always include `type` (`conference` or `journal`) and `rank` (`A`/`B`/`C`).
- Include the CCF `area` (Chinese) when available.
- Include the canonical full name and the DBLP URL from the dataset.
- If no confident match is found, say so and list the closest candidates.

## ⚠️ Data quality: 22 records have corrupt abbreviations

The upstream dataset is extracted from the official CCF PDF, and **22 of 678 records
(3.2%) have a malformed `abbreviation`** — line-break artifacts and duplicated
publisher tokens:

```
'SIG- METRICS'      should be SIGMETRICS
'INTER- SPEECH'     should be INTERSPEECH
'JCOMPLEXI TY'      should be JCOMPLEXITY
'AAAI AAAI'         should be AAAI
'ACM MM ACM'        should be ACM MM
'CCF- THPC CCF'     should be CCF THPC
```

**Do not trust `aliases` as a fallback.** Several corrupt records carry an alias
that is merely the *publisher* name — `'ACM SIGOPS ATC'` → alias `ACM`,
`'IEEE VIS IEEE'` → alias `IEEE`, `'CCF TPCI CCF'` → alias `CCF`. Writing those
into a registry produces a venue literally named after its publisher.

**When writing to the domain registry, pick the alias that looks like a real
abbreviation, and when in doubt surface the raw record to the user for
confirmation rather than guessing.** A spot-check of CCF-A venues is cheap;
a silently mislabelled venue is expensive.

## Update workflow (new CCF version)

1. Replace the PDF with the newer official CCF version.
2. Rebuild the year dataset:

   ```bash
   python3 scripts/build_ccf_dataset.py "/absolute/path/to/new.pdf" --year 2028
   ```

   (Requires the extraction dependencies that script declares.)
3. Update `references/<year>/excluded_venues.json` if the PDF has deleted entries
   that text extraction cannot detect from styling alone.
4. Spot-check representative venues (`ICML`, `NeurIPS`, `CVPR`, `TOCS`) and re-run
   the corrupt-abbreviation scan above.
