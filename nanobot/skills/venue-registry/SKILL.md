---
name: venue-registry
description: Maintain the domain registry that records which venues are authoritative for a research field, and which arXiv categories to search. Use when the user expresses interest in a new field, asks which journals or conferences matter in an area, wants to add or remove a venue, or when another skill needs to know what to search for a domain.
---

# venue-registry

Answers "for this field, what counts as an authoritative venue, and where do I
search?" — and keeps that answer in a file both the agent and the UI can edit.

## Where the data lives

`~/.nanobot/workspace/registry/domains.json`

**Deliberately not in Obsidian and not in `MEMORY.md`:**

- It has a schema, is read on every retrieval run, and will be edited by a form
  in the frontend. A `.md` file would need a parser and would break the moment
  someone reformats it.
- `MEMORY.md` is injected into the system prompt on *every* turn
  (`nanobot/agent/context.py:127-130`). A near-static list of 200 venues would
  bill every conversation for tokens it never uses.

## Data sources — both local, both offline

| Domain | Source | Tiers |
|---|---|---|
| `ai` | the **`ccf-rank`** skill's CCF dataset | A / B / C |
| `finance` | `references/finance_venues.json` | A\* / A / B |

⚠️ **The two domains use different standards — do not mix them.** CCF is the
China Computer Federation's CS venue list; it says **nothing** about finance,
economics, or any other field. Finance uses FT50 / UTD24, with the weaker field
journals marked `tier_source: "field"` because those tiers are editorial rather
than list-verified.

## Commands

```bash
# Rebuild the registry from local data (never hits the network)
python3 scripts/build_registry.py --dry-run     # report
python3 scripts/build_registry.py               # write

# Verify proposed journal ISSNs against OpenAlex (the ONLY network call here)
uv run scripts/verify_issns.py references/finance_candidates.json --json
```

`build_registry.py` **preserves `enabled` state** on a `confirmed: true` domain,
matching venues by name, so a rebuild will not wipe the user's checkboxes. Use
`--force` only when you intend to discard them.

## Workflow: the user is interested in a new field

1. **Look first.** `python3 scripts/build_registry.py --dry-run` shows what
   already exists. Two domains are seeded (`ai`, `finance`); do not invent a
   third without the user asking.
2. **If the domain exists**, read it:

   ```bash
   python3 ../literature-search/scripts/paperctl.py domain ai
   ```

   This returns the enabled venues, their tiers, and the arXiv categories. Use
   it directly — do not re-derive the venue list by hand.
3. **If the domain does not exist**, propose one rather than building it
   silently. A proposal needs: a label, aliases, arXiv categories, and a venue
   list **with a stated origin** for every tier. Say where each tier came from.
   Write it with `confirmed: false`.
4. **Ask the user to confirm.** Until `confirmed: true`, treat the domain as a
   draft — the frontend will show it as unconfirmed.

## Rules

- **Never guess a tier.** If a venue's rank is unknown, leave `tier` as `"-"`.
  A venue mislabelled as CCF-A is worse than one with no tier, because the
  tier is what decides whether a paper gets surfaced.
- **Never scrape a ranking table at runtime.** Both standards are static lists;
  a CCF revision is a deliberate re-seed, not a live lookup.
- **Skip corrupt abbreviations.** The upstream CCF dataset is extracted from a
  PDF and ~3% of records carry mangled abbreviations (`SIG- METRICS`,
  `AAAI AAAI`). `build_registry.py` repairs the ones we have hand-checked and
  reports the rest instead of importing them. **Do not "fix" a reported
  abbreviation by taking its `aliases` entry** — several aliases are just the
  publisher name (`IEEE VIS IEEE` → `IEEE`), which would put a venue in the
  registry named after its own publisher. Surface it to the user instead.
- **A venue's `enabled` flag is the user's call.** The agent may propose
  flipping it; only change it on request.

## Layout

```
registry/domains.json          # the registry itself
scripts/build_registry.py      # rebuild from local data
scripts/verify_issns.py        # OpenAlex ISSN verification (network)
references/finance_venues.json # verified finance seed
references/finance_candidates.json # raw proposals, pre-verification
```
