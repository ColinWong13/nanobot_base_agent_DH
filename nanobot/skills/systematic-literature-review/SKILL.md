---
name: systematic-literature-review
description: Use this skill when the user wants a systematic literature review, survey, or synthesis across multiple academic papers on a topic. Also covers annotated bibliographies and cross-paper comparisons. Searches arXiv and outputs reports in APA, IEEE, or BibTeX format. Not for single-paper tasks — reviewing one paper is a different job.
---

# Systematic Literature Review Skill

## Overview

This skill produces a structured **systematic literature review (SLR)** across multiple academic papers on a research topic. Given a topic query, it searches arXiv, extracts structured metadata (research question, methodology, key findings, limitations) from each paper in parallel, synthesizes themes across the full set, and emits a final report with consistent citations.

This skill does **breadth-first synthesis across many papers**. If the user hands you one paper and asks "review this paper", that is a deep peer review of a single paper — do not use this skill for it.

> **Adapted for nanobot.** This skill was ported from bytedance/deer-flow. The workflow is unchanged; the subagent delegation in Phase 3 has been rewritten for nanobot's `spawn` tool. See [Runtime notes](#runtime-notes-nanobot) at the end before deviating from the instructions below.

## When to Use This Skill

Use this skill when the user wants any of the following:

- A literature survey on a topic ("survey transformer attention variants", "review the literature on diffusion models")
- A synthesis across multiple papers ("what do recent papers say about X", "compare methodologies across papers on Y")
- A systematic review with consistent citation format ("do an SLR on Z in APA format")
- An annotated bibliography on a topic
- An overview of research trends in a field over a time window

Do **not** use this skill when:

- The user provides exactly one paper and asks to review it
- The user asks a factual question that does not require synthesizing multiple sources (answer directly)
- The user wants general web research without academic rigor (use standard web search)

## Workflow

The workflow has five phases. Follow them in order.

### The invariant this workflow exists to protect

**One topic, one review.** `20-Reviews/slr-<topic-slug>.md` is a *living document*: every run **merges** new papers into it. Asking about the same topic twice produces "`slr-rag.md` went from 81 to 94 papers" — never a second file.

This went wrong on 2026-09-28. An agent searched 80 papers, wrote 968 lines to `slr-rag-20260928.md`, and never noticed a 25-paper review of the same topic from two days earlier. The cause was not inattention — *nothing in this workflow asked it to look*. So Phase 1 now starts with a **mandatory** lookup, and Phase 3 is gated by an identity check against the actual candidate ids rather than a guessed slug.

Full contract: [../literature-search/references/review-card.md](../literature-search/references/review-card.md).

### Phase 1: Plan

**Step zero — does this topic already have a review?** Do this before anything else, because the answer changes the rest of the run: a first run searches wide, an update searches only what arrived since the existing review's `window.end`. Resolve the script as `<literature-search>/scripts/paperctl.py` (the sibling skill directory) and the vault as described under *Output location* below.

```bash
python3 <literature-search>/scripts/paperctl.py --vault <vault> review-find --slug <topic-slug>
```

| Exit | Meaning | What to do |
|---|---|---|
| **1** | The review exists | This is an **update**. Read the file, tell the user you are updating it and from how many papers, and derive the search window in Phase 2 from its `window.end`. |
| **0** | No review | A first run. The window is whatever the user asked for. |
| **2** | Two files claim this slug | Resolve it first — `review-list` shows both. Do not pick a winner; ask the user which is the keeper. |

`review-find` normalises the slug, so `RAG`, `slr-rag`, `slr-rag.md` and `slr-rag-20260928` all find the same review. **But it cannot guess a slug you got wrong.** A review of "Retrieval-Augmented Generation" may well be stored as `rag`, and looking up `retrieval-augmented-generation` returns exit 0 and looks exactly like "no review yet" — which is how the 2026-09-28 duplicate happened. So when `review-find` returns 0, **run `review-list` and read the `topic` fields before concluding the topic is new.** Comparing human-readable topics is the only thing that catches a slug you would not have guessed.

Then confirm the following with the user. If any of these are unclear, ask **one** clarifying question that covers the missing pieces. Do not ask one question at a time.

- **Topic**: the research area in plain English (e.g. "transformer attention variants").
- **Scope**: how many papers (default 20, hard upper bound 50), optional time window (e.g. "last 2 years"), optional arXiv category (e.g. `cs.CL`, `cs.CV`).
- **Citation format**: APA, IEEE, or BibTeX (default APA if the user does not specify and does not seem to be writing for a specific venue).
- **Output location**: where to save the final report. Default: `<vault>/AI Workspace/资讯检索/20-Reviews/`. The vault root is the one `paperctl.py` uses — `--vault`, else `$OBSIDIAN_VAULT`, else the value recorded in the `obsidian-ops` skill. Never invent a path here: `20-Reviews/` is one of the three sections `paperctl.py vault-init` creates, and everything downstream reads the **section tree** rather than the filesystem at large — a report dropped in an ad-hoc directory is not part of it. Note that `paperctl.py list` reads `10-Papers/` only and will not show a review wherever you put it, so it is not a way to check this; use `ls` on `20-Reviews/`.

If the user says "50+ papers", politely cap it at 50 and explain that synthesis quality degrades quickly past that — for larger surveys they should split by sub-topic.

### Phase 2: Search arXiv

**If Phase 1 found an existing review, search the gap, not the whole topic.** Read its `window` field (`2026-08-28 ~ 2026-09-28`), start the search at that end date minus a **14-day overlap**, and pass it as `--start-date`. The overlap is deliberate: arXiv's `published` timestamps lag their announcement, so a paper announced just before the old cutoff can carry a `published` date just after it, and starting exactly at `window.end` would skip it. Two weeks is cheap — the duplicate it finds is caught for free by the merge in Phase 4, whereas one it misses stays missing forever.

Call the bundled search script. Do **not** try to scrape arXiv by other means and do **not** write your own HTTP client — this script handles URL encoding, Atom XML parsing, and id normalization correctly.

Resolve the script path relative to this skill's directory (the directory containing this `SKILL.md`):

```bash
python3 <skill-dir>/scripts/arxiv_search.py \
  "<topic>" \
  --max-results <N> \
  [--category <cat>] \
  [--sort-by relevance] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**IMPORTANT — extract 2-3 core keywords before searching.** Do not pass the user's full topic description as the query. Before calling the script, mentally reduce the topic to its 2-3 most essential terms. Drop qualifiers like "in computer vision", "for NLP", "variants", "recent" — those belong in `--category` or `--start-date`, not in the query string.

**Query phrasing — keep it short.** The script wraps multi-word queries in double quotes, so arXiv treats them as an **exact phrase** match (`all:"..."`). This means:

- `"diffusion models"` → exact 2-word phrase → good, returns plenty of on-topic papers.
- `"diffusion models in computer vision"` → exact 5-word phrase → **the result set collapses**. Measured on 2026-09-27 with a cap of 50: the long phrase returned **4 papers**, while `"diffusion models" --category cs.CV` returned **50** (hit the cap). Same topic, >12× narrower.

Note the failure is *not* an error — you get a small, valid result set, not zero. That is exactly what makes it dangerous: the run looks successful, and since the guidance below says never to pad a short result set, the user silently receives 4 papers when they asked for 20.

Use **2-3 core keywords** as the query, and use `--category` to narrow the field instead of stuffing field names into the query. Examples:

| User says | Good query | Bad query |
|---|---|---|
| "diffusion models in computer vision" | `"diffusion models" --category cs.CV` | `"diffusion models in computer vision"` |
| "transformer attention variants" | `"transformer attention"` | `"transformer attention variants in NLP"` |
| "graph neural networks for molecules" | `"graph neural networks" --category cs.LG` | `"graph neural networks for molecular property prediction"` |

The script prints a **JSON array** to stdout — bare, with no `status` / `results_count` envelope (do not look for one; parse the top level as a list). Each element has: `id`, `title`, `authors`, `abstract`, `published`, `updated`, `categories`, `pdf_url`, `abs_url`.

**Sort strategy**:

- **Always use `relevance` sorting** — arXiv's BM25-style scoring ensures results are actually about the user's topic. `submittedDate` sorting returns the most recently submitted papers in the category regardless of topic relevance, which produces mostly off-topic results.
- When the user asks for "recent" papers or gives a time window, use `--sort-by relevance` **combined with `--start-date`** to constrain the time range while keeping results on-topic. For example, "recent diffusion model papers" → `--sort-by relevance --start-date 2024-01-01`, not `--sort-by submittedDate`.
- `submittedDate` sorting is only appropriate when the user explicitly asks for chronological order (e.g. "show me papers in the order they were published"). This is rare.
- `lastUpdatedDate` is rarely useful; ignore it unless the user asks.

**Run the search exactly once.** Do not retry with modified queries if the results seem imperfect — arXiv's relevance ranking is what it is. Retrying with different query phrasings wastes tool calls and risks hitting the recursion limit. If the results are genuinely empty (0 papers), tell the user and suggest they broaden their topic or remove the category filter.

**If the script returns fewer papers than requested**, that is the real size of the arXiv result set for the query. Do not pad the list — report the actual count to the user and proceed. **One exception:** if the shortfall is large (you asked for 20 and got 4), check your query against the phrasing guidance above before accepting it — a too-long query is the most likely cause, and re-running once with a shorter query is warranted. A large shortfall is a signal about the *query*, not about arXiv's coverage.

**If it returns exactly `--max-results`, the window was truncated — split it.** This is the opposite signal and the more dangerous one, because a full result set looks like success. Truncation drops one end of the window silently; under `submittedDate` it drops the **oldest**, which is exactly the end an update just extended the window to cover. Not hypothetical: the 2026-09-28 run lost `2609.28575` this way, and the review still reported success. Split the window in half and run both halves — a shorter window returns fewer papers, so nothing is lost.

**If the script fails** (network error, non-200 from arXiv), tell the user which error and stop. Do not try to fabricate paper metadata.

**Do not save the search results to a file** — the JSON stays in your context for Phase 3. The only file saved during the entire workflow is the final report in Phase 5.

### Phase 3: Extract metadata in parallel

**Gate first — confirm this run is not a duplicate, using the actual ids.** Phase 1's lookup ran on a slug you guessed; this runs on the papers you actually found, so it catches the near-miss that a slug lookup cannot. Do it here, before spending subagents on extraction, because extraction is the expensive phase and a duplicate caught before it costs nothing.

Write the candidate ids to a file (a JSON array of ids, or the normalised paper list — both are accepted) and compare against every review in the vault:

```bash
python3 <literature-search>/scripts/paperctl.py --vault <vault> review-list --ids <candidates.json>
```

Read `overlap` on each row. `count` is how many of your candidates that review already covers; `ratio` is that share of your candidate set.

- **A high `ratio` against one review means this is that topic.** Merge into it — do not create a second file. `review-write --ids` enforces the same rule (it refuses at ≥10 overlapping papers and ≥60%), but only after you have paid for extraction.
- **`ratio` near 0 does not prove the topics differ.** arXiv and OpenAlex ids never intersect, so a review retrieved from OpenAlex shows `ratio: 0.0` against an identical arXiv topic. When the `source` fields differ, compare `topic` — never the ratio.
- **No review scores meaningfully** → genuinely a new topic. Proceed as a first run.

**You MUST delegate extraction to subagents via the `spawn` tool — do not extract metadata yourself.** This is non-negotiable. Specifically, do NOT do any of the following:

- ❌ Write `python -c "papers = [...]"` or any Python/bash script to process papers
- ❌ Extract metadata inline in your own context by reading abstracts one by one
- ❌ Use any tool other than `spawn` for this phase

Instead, you MUST call `spawn` with `wait=true` to run subagents. The reason: extracting 10-50 papers in your own context consumes too many tokens and degrades synthesis quality in Phase 4. Each subagent runs in an isolated context with only its batch of papers, producing cleaner extractions.

Split papers into batches of ~5, then for each batch call `spawn` once. `wait=true` makes the call return the subagent's final message directly into this turn, which is what the synthesis step needs. Set `label` to something like `extract:batch-1` so the run is legible in the WebUI.

**Concurrency: up to 4 subagents run in parallel.** nanobot's `SubagentManager` gates subagents with an `asyncio.Semaphore` sized by `maxConcurrentSubagents` (default 4; check `~/.nanobot/config.json` if unsure). **Extra dispatches are queued, not dropped** — nanobot queues them and runs them as slots free up, so you will never silently lose a batch. The round strategy below is therefore a **latency and visibility** choice, not a correctness requirement.

**Round strategy — use this decision table, do not compute the split yourself**:

| Paper count | Batches of ~5 papers | Rounds | Per-round subagent count |
|---|---|---|---|
| 1–5 | 1 batch | 1 round | 1 subagent |
| 6–10 | 2 batches | 1 round | 2 subagents |
| 11–15 | 3 batches | 1 round | 3 subagents |
| 16–20 | 4 batches | 1 round | 4 subagents |
| 21–25 | 5 batches | 2 rounds | 4 + 1 |
| 26–30 | 6 batches | 2 rounds | 4 + 2 |
| 31–35 | 7 batches | 2 rounds | 4 + 3 |
| 36–40 | 8 batches | 2 rounds | 4 + 4 |
| 41–45 | 9 batches | 3 rounds | 4 + 4 + 1 |
| 46–50 | 10 batches | 3 rounds | 4 + 4 + 2 |

**Prefer rounds over one giant dispatch.** You *could* dispatch all 10 batches in a single turn and let the semaphore sort it out — nothing would be lost — but that blocks the whole turn with no intermediate visibility, and a failure in batch 9 surfaces only at the very end. Rounds give you a checkpoint after each group.

If the paper count lands between rows (e.g. 23 papers), round up to the next row's layout but only dispatch as many batches as you actually need — the decision table gives you the shape, not a rigid prescription.

**Do the batching at the main-agent level**: you already have every paper's abstract from Phase 2, so each subagent receives pure text input. Subagents should not need to access the network or the sandbox — their only job is to read text and return JSON. Do not ask subagents to re-run `arxiv_search.py`; that would waste tokens and risk rate-limiting.

**What each subagent receives**, as the `task` string:

```
Execute this task: extract structured metadata and key findings from the
following arXiv papers.

Papers:
[Paper 1]
arxiv_id: 1706.03762
title: Attention Is All You Need
authors: Ashish Vaswani, Noam Shazeer, ...
published: 2017-06-12
abstract: <full abstract text>

[Paper 2]
arxiv_id: ...
...

For each paper, return a JSON object with these fields:
- arxiv_id (string)
- title (string)
- authors (list of strings)
- published_date (string, YYYY-MM-DD)
- research_question (1 sentence, what problem the paper tackles)
- methodology (1-2 sentences, how they tackle it)
- key_findings (3-5 bullet points, what they actually found)
- limitations (1-2 sentences, what they acknowledge or what is obviously missing)

Return the result as a JSON array, one object per paper, in the same
order as the input. Do not include any text outside the JSON — no
preamble, no markdown fences, just the array.
```

**Parsing subagent results**: `spawn` with `wait=true` returns the subagent's final message content **verbatim** — there is no status prefix to strip. Parse it directly as JSON. (If the subagent wrapped its answer in ``` fences despite the instruction, strip the fences first.) If a batch returns unparseable JSON, log it, note which papers were affected, and continue with the remaining batches — do not fail the whole synthesis on one bad batch.

After all rounds complete, flatten the per-batch arrays into a single list of paper metadata objects, preserving order.

### Phase 4: Synthesize and format

Now produce the final SLR report. Two things happen here: cross-paper synthesis (thematic analysis) and citation formatting.

**On an update, you are merging — not writing from scratch.** The existing review already holds a synthesis of its papers, and the user has read it. Concretely:

1. **Read the existing review** (Phase 1 located it), and read `slr-<slug>-archive.md` if it exists. The archive holds the papers that aged out of the two-year window, condensed. They are *not* covered papers any more, but they are still evidence about the field — treat them as background and do not re-add them to the review body.
2. **Drop the duplicates.** Any candidate whose id already appears in the review's annotations is already covered. Do not extract it, do not re-annotate it, and do not count it as new.
3. **Revise the prose sections to absorb the new papers.** The Executive Summary, Themes, Convergences, and Gaps should read as one synthesis of the *whole* set, old and new. Do not append a "New since last update" section, and do not leave a theme that a new paper has invalidated. If new papers contradict an earlier conclusion, the earlier conclusion changes.
4. **Insert the new annotations into `## Per-Paper Annotations`**, keeping the section's existing order, and add their reference entries to `## References`. Both the annotation and the reference entry are required — an annotation without a reference entry leaves a dangling citation.
5. **Use Edit, not Write.** Rewriting the file wholesale is how annotations get silently lost, and `papers` is the only thing that would notice. The risk is real enough to be named in the contract as the largest one the tooling cannot prevent.
6. **Never touch `## 我的笔记`** or anything after it.

Report what changed: "`slr-rag.md`: 81 → 94 papers (+13)". If the count went *down*, say so and say why — `review-write` will warn about it, and the warning is addressed to you, not to be passed along unread.

**Cross-paper synthesis**: the report must do more than list papers. At minimum, identify:

- **Themes**: 3-6 recurring research directions, approaches, or problem framings across the set.
- **Convergences**: findings that multiple papers agree on.
- **Disagreements**: where papers reach different conclusions or use incompatible methodologies.
- **Gaps**: what the collective literature does not yet address (often stated explicitly in the "limitations" fields).

If the paper set is too small or too heterogeneous to support thematic synthesis (e.g. 5 papers on wildly different sub-topics), say so explicitly in the report — do not force themes that are not there.

**Citation formatting**: the exact format depends on user preference. Read **only** the template file that matches the user's requested format, not all three:

- [templates/apa.md](templates/apa.md) — APA 7th edition. Default for social sciences and most CS journals. Use when the user requests APA or does not specify a format.
- [templates/ieee.md](templates/ieee.md) — IEEE numeric citations. Use when the user targets an IEEE conference or journal, or explicitly asks for IEEE.
- [templates/bibtex.md](templates/bibtex.md) — BibTeX entries. Use when the user mentions BibTeX, LaTeX, or wants machine-readable references. **Important**: arXiv papers are cited as `@misc`, not `@article` — the BibTeX template covers this explicitly.

Each template contains both the citation rules and a full report structure (executive summary, themes, per-paper annotations, references, methodology section). Follow the template's structure verbatim for the report body, then fill in content from your Phase 3 metadata.

### Phase 5: Save and present

The file is `<output-location>/slr-<topic-slug>.md` — **no date in the name.** A living document with a creation date in its filename misleads the first time it is updated: `slr-rag-20260928.md` reads as "covers up to 28 September" while it keeps growing. The creation date lives in the `created` field.

**A first run** writes the whole file, then stamps it:

```bash
python3 <literature-search>/scripts/paperctl.py --vault <vault> review-write --slug <topic-slug> \
  --topic "<Human-readable topic>" --window '<YYYY-MM-DD> ~ <YYYY-MM-DD>' \
  --source arxiv --citation-format APA --language en --ids <candidates.json>
```

`--window` is the range you actually searched, as two full dates. Not the retention period — writing "the last two years" when you searched one month claims coverage you never had. `--slug` is required and is never derived from `--topic`: a mutable human string cannot be an identity key. Pass `--ids` so the duplicate gate runs on your real candidate set.

**An update** uses the same command. `review-write` does not create files — if the slug is wrong it exits 1 and prints the path it expected, which is exactly the moment to go back to `review-list` rather than invent a new name.

If `review-write` refuses because the body has parsing problems, **fix the body** — do not reach for `--force`. It refuses only when the recomputed `papers` is *known* to be wrong, and a silently wrong count is worse than a loud failure: nothing about the file looks broken, so the next run's dedupe quietly misbehaves.

There is no `present_files` tool in nanobot — report the file path in chat instead.

**In the chat message**, show a short preview so the user immediately sees value without opening the file:

1. **Executive summary** — the 3–5 sentence paragraph from the top of the report, verbatim.
2. **Themes list** — bullet list of the themes from the Phase 4 synthesis (theme names + one-line gloss, not the full theme sections).
3. **What changed, and a pointer to the file** — for a first run, "Full report with 20 papers … saved to `slr-transformer-attention.md`". For an update, lead with the delta: "`slr-rag.md`: 81 → 94 papers (+13). New papers reinforced Theme 2 and opened a gap in long-context evaluation." Name any paper you *removed* and why.

Do **not** dump the full 2000+ word report inline — per-paper annotations, references, and methodology belong in the file. The preview is there to let the user judge the report at a glance and decide whether to open it.

## Examples

**Example 1: Typical SLR request**

User: "Do a systematic literature review of recent transformer attention variants, 20 papers, APA format."

Your flow:
1. Phase 1: `review-find --slug transformer-attention` → exit 0. To be sure the slug is not a near-miss, `review-list` and read the `topic` fields — nothing matches. Then confirm topic, scope (20 papers, default time window), format (APA). Ask **one** clarification only if something is missing (e.g. "Any particular time window, or should I default to the last 3 years?").
2. Phase 2: `arxiv_search.py "transformer attention" --max-results 20 --sort-by relevance --start-date 2023-01-01`. Returns 20 of 20 requested — that is the cap, so split the window and run both halves before trusting the set.
3. Phase 3: `review-list --ids candidates.json` → no review scores meaningfully, so this is genuinely new. Then 20 papers → 1 round of 4 subagents × 5 papers. Aggregate.
4. Phase 4: read `templates/apa.md`, write the report using its structure, fill in themes + per-paper annotations from Phase 3 metadata. Each annotation's first line is its identifier line.
5. Phase 5: write `slr-transformer-attention.md` in the vault's `20-Reviews/` directory (Phase 1's output location), then `review-write --slug transformer-attention … --ids candidates.json` to stamp the frontmatter, then report the path.

**Example 2: Small-set request with ambiguity**

User: "Survey a few papers on diffusion models for me."

Your flow:
1. Phase 1: "a few" is ambiguous. Ask one question: "How many papers would you like — 10, 20, or 30? And any citation format preference (APA is the default)?"
2. User responds "10, BibTeX".
3. Phase 2: `arxiv_search.py "diffusion models" --max-results 10 --category cs.CV`.
4. Phase 3: 10 papers → single round, 2 subagents × 5 papers.
5. Phase 4: read `templates/bibtex.md`, format with `@misc` entries (not `@article`).
6. Phase 5: save and report the path.

**Example 3: Out-of-scope request**

User: "Here's one paper (https://arxiv.org/abs/1706.03762). Can you review it?"

This is a single-paper peer review, not a literature survey. Do not use this skill for it.

**Example 4: Second run on a topic that already has a review**

Three weeks after Example 1, the user asks: "Anything new on transformer attention variants?"

Your flow:
1. Phase 1: `review-find --slug transformer-attention` → **exit 1**. Read `slr-transformer-attention.md`: 20 papers, `window: 2023-01-01 ~ 2026-04-09`. This is an **update**, not a new review. Tell the user: "Updating the existing review — it has 20 papers."
2. Phase 2: start at `2026-04-09` minus 14 days → `--start-date 2026-03-26`, which is the `window.end` minus the overlap. No `--max-results` ceiling you can trust: if the count comes back equal to the cap, split the window.
3. Phase 3: `review-list --ids candidates.json` → `slr-transformer-attention` shows `overlap: {count: 17, ratio: 0.85}`. That confirms the identity and means 17 of your candidates are already annotated — extract only the remainder.
4. Phase 4: read the existing review; revise the Executive Summary, Themes, Convergences and Gaps to absorb the new papers rather than appending to them; insert the new annotations into `## Per-Paper Annotations` and their entries into `## References` **using Edit**; leave `## 我的笔记` alone.
5. Phase 5: `review-write --slug transformer-attention --window '2023-01-01 ~ 2026-09-28' --ids candidates.json` → `papers: 20 -> 23`. Report "`slr-transformer-attention.md`: 20 → 23 papers (+3)" and name what changed in the synthesis.

**The failure this example exists to prevent**: doing steps 2–5 against a *fresh* file named `slr-transformer-attention-20260928.md`, which is what happened on 2026-09-28 with an 80-paper review of a topic that already had one.

## Runtime notes (nanobot)

The upstream deer-flow version of this skill assumed the DeerFlow runtime. The differences that matter:

| Upstream (deer-flow) | Here (nanobot) |
|---|---|
| `task` tool, `subagent_type: "general-purpose"` | `spawn` tool with `wait=true`; no `subagent_type` |
| Max 3 subagents/turn, **extra dispatches silently dropped** | Semaphore sized by `maxConcurrentSubagents` (**default 4**); extra dispatches **queued**, never dropped |
| Results prefixed `Task Succeeded. Result: ` | Result is the subagent's **verbatim final message** — no prefix |
| `subagent_enabled: true` in `config.configurable` | `maxConcurrentSubagents` in `~/.nanobot/config.json` |
| Script at `/mnt/skills/public/...` | Script at `<skill-dir>/scripts/arxiv_search.py` |
| Output to `/mnt/user-data/outputs/` | Output to the Obsidian vault (Phase 1) |
| `present_files` tool to hand over the file | No such tool — report the file path in chat |

**Prerequisite**: subagents must be available. `spawn` requires an initialized `SubagentManager`; it is present whenever the agent runtime is running normally. If `spawn` is somehow unavailable, do not claim to execute the Phase 3 parallel plan — tell the user the parallel extraction step cannot run and offer to narrow the request to a smaller manual review.

**Synthesis, not listing.** The final report must identify themes and compare findings across papers. A report that only lists papers one after another is a failure mode — if you cannot find themes, say so explicitly instead of faking them.

**arXiv only, by design.** This skill does not query Semantic Scholar, PubMed, or Google Scholar. arXiv covers the bulk of CS/ML/physics/math preprints. For finance, economics, or other fields whose journals are not on arXiv, this skill is the wrong retrieval backend — those need OpenAlex. Separately, the `literature-search-arxiv` skill wraps a different arXiv client (DeepMind's, with `ti:`/`au:`/`abs:` field syntax) for interactive single-topic searches; using it here is not necessary and not recommended.

**Hard upper bound of 50 papers.** This is tied to the Phase 3 concurrency strategy (~5 papers per batch, at most 3 rounds). Surveys larger than 50 papers degrade in synthesis quality and are better done by splitting into sub-topics.

**The `id` field is a bare arXiv id** (e.g. `1706.03762`), not a URL and not with a version suffix. `abs_url` / `pdf_url` hold the full URLs if you need them.

**Do not download PDFs.** This workflow is abstract-level by design — Phase 3 works from the abstract text alone. Downloading and parsing full texts is explicitly out of scope: it is token-expensive and unnecessary for thematic synthesis.
