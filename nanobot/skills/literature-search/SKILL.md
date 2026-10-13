---
name: literature-search
description: The main 资讯检索 pipeline — turn a research interest into paper cards in the Obsidian vault plus an abstract-level literature review. Use when the user asks to find, track, or review recent work in a field, wants papers collected into their vault, or asks what is new in a research area.
---

# literature-search

The main pipeline. **This skill is a thin wrapper**: retrieval is done by the
external search skills, synthesis by `systematic-literature-review`. What this
skill owns is the part in between — deciding *what* to search, deduping, and
writing cards into the vault.

```
用户需求
  → venue-registry      决定查哪些 venue / arXiv 分类
  → literature-search-arxiv / -openalex   （外部技能，各自带限速）
  → paperctl.py         去重 + 写论文卡
  → systematic-literature-review          （外部技能，五阶段，摘要级）
  → 综述回写 vault
  → paperctl.py card-enrich   把综述的主题词回填到卡上
```

## Step 0 — resolve the domain

Never start from a blank query. Read the registry first:

```bash
python3 scripts/paperctl.py domain ai        # or: finance
```

Returns `arxiv_cats`, `enabled_venues` (with tiers), and `confirmed`. Use the
`arxiv_cats` as the search scope and the venues as the tier map for whatever
comes back.

If the user names a field with no domain, use the **`venue-registry`** skill to
propose one before searching. If they name no field at all, ask once.

## Step 1 — retrieve

Call the external search skill for the domain:

| Domain | Primary skill | Why |
|---|---|---|
| `ai` | `literature-search-arxiv` | preprint culture — newest work lands here first |
| `finance` | `literature-search-openalex` | **JF / JFE / RFS are not on arXiv**; arXiv's q-fin is only quant-finance preprints |

Three hard-won constraints from those skills:

- **Keep queries to 2–3 core keywords.** A quoted multi-word query is an exact
  phrase match, and a too-long phrase collapses the result set *silently* —
  measured: `"diffusion models in computer vision"` → 4 papers, versus
  `"diffusion models" --category cs.CV` → 50. Push field qualifiers into the
  category/filter argument, not the query string.
- **OpenAlex must be filtered `type:article`**, or the results fill with
  editorials and association announcements that have no abstracts.
- **Most papers legitimately end up with no `venue_tier`, and that is the
  correct answer.** `normalize.py` only tiers an arXiv paper when its `comment`
  positively claims acceptance at a main conference. Measured 2026-09-27 on 60
  recent `cs.CL` papers: 3 tiered. The other 57 were either unpublished
  preprints or said things like *"submitted to ICASSP 2027"*, *"preprint for
  ICASSP 2027 submission"*, or *"Accepted at the REALM **Workshop** at EMNLP"* —
  a workshop tier is a promotion the paper did not earn, and `venue: ICASSP` on
  a paper that was merely submitted is a factual error. **Do not "fix" a low
  tier rate by loosening the gate.** If a run tiers nothing at all, that is
  also plausible; say so rather than padding it.

**arXiv visibility lags submission by ~2 days.** A paper does not appear in the
search API until about two days after submission (measured 2026-09-28: Monday
submissions became visible Wednesday morning, Beijing time). An empty
`submittedDate:[today TO today]` result therefore only means "everything visible
today is already in the vault" — it is a coverage check, not proof nothing was
submitted; and an incremental window that stops at today will silently miss the
newest 1–2 days of papers until the next run.

## Step 2 — dedupe

Take the returned JSON and normalise each paper to the shape below, then write
them in one call. `paperctl` checks each against the vault by `source` +
`source_id` and reports `created` vs `updated`:

```bash
python3 scripts/paperctl.py card-write --json papers.json --domain ai
```

Pass `--domain` with the domain resolved in Step 0. It is recorded on every card
as `domains: [...]`, which is what lets the knowledge page group cards by the
discipline they were collected for. Cheap now, unrecoverable later: nothing else
in the pipeline remembers which search produced a card.

To check a single paper without writing, use `card-check` — **it exits 1 when
the card already exists**, so a shell `if` can branch on it.

Normalised paper shape (`abstract` is the field that matters — it is the raw
material for the review):

```json
{
  "source": "arxiv",
  "source_id": "2005.11401",
  "title": "...",
  "abstract": "<原文摘要，逐字保留>",
  "authors": ["..."],
  "year": 2020,
  "url": "https://arxiv.org/abs/2005.11401",
  "pdf_url": "https://arxiv.org/pdf/2005.11401",
  "categories": ["cs.CL", "cs.IR"],
  "venue": "NeurIPS",
  "venue_tier": "A",
  "one_liner": "<中文一句话提要，agent 生成>"
}
```

## Step 3 — review

Hand the abstracts to **`systematic-literature-review`** for the five-phase
flow. That skill does thematic synthesis across papers and formats citations.
Then save the review to `20-Reviews/` under the vault path below.

**Check for an existing review before handing anything over.** `20-Reviews/` is
one living document per topic, not one per run:

```bash
python3 scripts/paperctl.py review-find --slug <topic-slug>   # exit 1 = exists
```

Exit 1 means this run **updates** that file — same file, more papers. Exit 0
means read `review-list`'s `topic` fields before concluding the topic is new: a
review of "Retrieval-Augmented Generation" may be stored as `rag`, and a guessed
slug simply misses it. That miss is how two reviews of one topic came to exist
on 2026-09-28.

### Extracting metadata at scale (subagent pattern)

For big batches (a month of arXiv ≈ 80 papers), do not read every abstract in
the main context. Validated pattern (RAG round, 2026-09-28 — reusable for any
topic's weekly report):

1. Split the papers into JSON files of ~5 papers each.
2. Spawn one subagent per file (`spawn`, `wait=true`): it reads its file,
   extracts the metadata, and writes back `out_batch_*.json`.
3. The main agent only synthesizes the collected outputs.

## Step 3.5 — backfill the theme terms

The review's `### Theme N` headings are the only place a paper's *research
theme* is ever recorded — the search that made the card knew nothing about
themes, and its arXiv category (`cs.AI`) is far too coarse to browse by.

First declare the vocabulary on the review, as short labels in heading order:

```bash
python3 scripts/paperctl.py review-write --slug rag --themes "图结构 RAG,安全与投毒"
```

Then copy the same terms onto the cards:

```bash
python3 scripts/paperctl.py card-enrich --json terms.json
```

Build `terms.json` from the review you just wrote: for each theme section,
collect the `arXiv:<id>` references in its prose, and emit
`{"source": "arxiv", "source_id": "<id>", "topic_terms": ["<short term>"]}`.

Two things to get right:

- **Shorten the heading into a term.** The graph draws it as a node label, so
  `安全与投毒` rather than `安全——投毒攻击面扩大，防御走向工具化`. The long
  form stays in the review, which is where someone goes for the argument.
- **Most themes leave papers unnamed.** Measured on the first review: of 81
  cards the six theme passages named 53; the other 28 were in the review (every
  card has a `## Per-Paper Annotations` block) but no theme sentence cited their
  id. Assign those by reading each card's `## 一句话提要` against the theme
  headings. `card-enrich` reports any id it cannot find as `missing` rather than
  creating a card, so a typo surfaces instead of inventing one.

## Step 4 — report

Reply with: how many papers were found, how many were new, the vault path, and
the review's executive summary. Do not paste the full review into chat.

## Vault layout

Root: `$OBSIDIAN_VAULT` — the same variable the knowledge index and
`obsidian-ops` read, so configuring it once moves all three. There is no
default; `--vault` overrides it for a single call.

```
AI Workspace/资讯检索/
├── 10-Papers/    # 论文卡，一篇一文件
├── 20-Reviews/   # 摘要级综述，一主题一文件 slr-<topic-slug>.md，就地更新
│   └── slr-<topic-slug>-archive.md   # 滚出两年窗口的论文浓缩档案
└── 30-Weekly/    # 每周问询周报（Phase 2）
```

`python3 scripts/paperctl.py vault-init` creates this structure.

Reviews have their own contract, [references/review-card.md](references/review-card.md),
alongside the paper card's. The two rules that matter most: a review's filename
carries **no date** (it is updated for years), and every annotation block's first
line is an **identifier line** (`**arXiv**: [id](https://arxiv.org/abs/id)`) —
that is the line the tooling counts to derive `papers` and the next run merges
against.

## The paper card contract

Read `references/paper-card.md` for the full field-by-field spec. The rules
that are easy to get wrong:

- **Dedupe on `source` + `source_id`.** Never the title — titles get
  re-typeset between versions — and never the DOI, which preprints lack.
- **`## 我的笔记` is the user's.** Everything from that heading onward is
  preserved byte-for-byte on every update. Never write into it, never reorder
  it, never "tidy" it.
- **Unknown frontmatter keys survive.** A card may carry keys added by hand or
  by a future version; they are round-tripped.
- **`status` belongs to the user** (`unread` / `skimmed` / `read`). Set it on
  creation only; do not reset it on an update.
- **No PDF downloads.** This pipeline is abstract-level by design. Do not call
  any `download_paper` / `download-pdf` tool — `download-pdf` on OpenAlex costs
  $0.01, which is the entire no-key daily budget.

## Commands

Run everything from the agent's workspace root — the `exec` working directory,
which is `agents.defaults.workspace` in the config (`~/.nanobot/workspace` by
default). This skill's own scripts live in `scripts/`, beside this `SKILL.md`;
the skills list at the top of your context gives the directory that sits in. If
`uv` is not on `PATH`, it is usually at `~/.local/bin/uv` — prepend
`$HOME/.local/bin` before any `uv run`.

```bash
python3 scripts/paperctl.py vault-init              # create the directory tree
python3 scripts/paperctl.py domain ai               # enabled venues + arXiv cats
python3 scripts/paperctl.py card-check --source arxiv --id 2005.11401
python3 scripts/paperctl.py card-write --json papers.json --domain ai
python3 scripts/paperctl.py card-enrich --json terms.json  # 主题词回填，只动 frontmatter
python3 scripts/paperctl.py list                    # what's already in the vault
python3 scripts/paperctl.py review-find --slug rag  # exit 1 = 该主题已有综述
python3 scripts/paperctl.py review-list             # 全部综述；--ids 可查候选集重叠
python3 scripts/paperctl.py review-write --slug rag # 盖章：重算 papers、刷新 updated
```

All commands accept `--vault <path>` and `--dry-run` (where meaningful).
