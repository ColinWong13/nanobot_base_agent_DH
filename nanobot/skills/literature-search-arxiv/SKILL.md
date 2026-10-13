---
name: literature-search-arxiv
description: >
  Search for scientific papers, preprints, and publications on arXiv. Extract
  metadata, abstracts, and download full-text PDFs or HTML versions of papers.
  Use when the user asks to find research papers, literature, or specific arXiv
  IDs.
---

# arXiv Search and Retrieval

## Prerequisites

1.  **`uv`**: if `uv` is not on `PATH`, it is usually at `~/.local/bin/uv` —
    run `export PATH="$HOME/.local/bin:$PATH"` before any `uv run` command.
2.  **License file**: `.licenses/literature_search_arxiv_LICENSE.txt` in the
    workspace root records that the user has been shown arXiv's terms. If it is
    missing, (1) prominently notify the user to check the terms at
    https://info.arxiv.org/help/api/index.html and to always check the license
    of the papers retrieved by the skill for any restrictions, then (2) create
    the file recording the notification text and timestamp.

## Core Rules

-   **Terms of Use**: You MUST respect arXiv's Terms of Use.
    -   Maximum 1 request every 3 seconds.
    -   The provided utility scripts handle rate limiting automatically. Always
        use these scripts rather than writing your own curl/python requests.
-   If this skill is used, ensure this is mentioned in the output AND list the
    URLs of all papers that were used in producing the output.

## Utility Scripts

**1. Search and Extract Metadata**

Search arXiv and return matching papers as JSON.

```bash
uv run scripts/search_arxiv.py --query "au:einstein AND ti:relativity" \
  --max_results 5 2>/dev/null > /tmp/arxiv_search_results.json
```

> **Output shape**: the JSON written to the file is a **dict, not a top-level
> list** — the papers are under the `papers` key (`data['papers']`).

> **Important**: The tool outputs a large JSON result to stdout. Requesting 100+
> results will produce a massive JSON that might exceed your context length.
> Limit `--max_results` (e.g., 5-10) or paginate carefully using `--start`.
> Always redirect output to a file and parse it separately, otherwise terminal
> output will be truncated.

### Weekly-window recipe (validated 2026-09-28, RAG round)

For a date-window sweep (e.g. the weekly 资讯检索 run), search by submission
date and paginate:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run scripts/search_arxiv.py \
  --query '(abs:"retrieval augmented generation" OR ti:"retrieval augmented generation" OR ti:"retrieval-augmented generation") AND submittedDate:[20260828 TO 20260928]' \
  --sort_by submittedDate --sort_order descending \
  --max_results 40 --start 0 2>/dev/null > /tmp/arxiv_page.json
```

- Paginate with `--start 0 / 40 / 80 …` until a page comes back empty.
- Substitute the topic query and the `[YYYYMMDD TO YYYYMMDD]` window per run.

*Returned Metadata:* JSON results include `id`, `title`, `summary`, `published`,
`authors`, `pdf_url`, `primary_category`, `doi`, `journal_ref`, and `comment`.
Note: the `doi` field only contains DOI information in case the paper has an
external DOI and if only an arXiv-issued DOI exists, this is DOI is not
returned.

*Options:*

-   `--query`: Search string. See
    [references/query_syntax.md](references/query_syntax.md) for advanced
    syntax.
-   `--id_list`: Comma-separated list of arXiv IDs to fetch directly (e.g.,
    `1706.03762v5`).
-   `--start`: Pagination offset (default 0).
-   `--max_results`: Number of results to return (default 10).
-   `--sort_by`: `relevance`, `lastUpdatedDate`, or `submittedDate`. (Use
    `--sort_by submittedDate --sort_order descending` for the most recent
    papers).
-   `--sort_order`: `ascending` or `descending`.

**2. Download Paper (PDF or HTML)**

Download the full text of a paper to your local workspace for reading.

```bash
uv run scripts/download_paper.py --id 1706.03762 --format pdf --output attention.pdf
```

*Options:*

-   `--id`: The arXiv ID (e.g., `1706.03762` or `1706.03762v5`).
-   `--format`: `pdf` or `html`. Note: HTML is only available for newer papers.
-   `--output`: Filepath to save the downloaded document.

> **Important**: when downloading papers, make sure you download them to a
> location where you do not overwrite other files and do not clutter existing
> directory structure.

**3. Download Paper Source (tar.gz)**

Download the LaTeX source files of a paper to your local workspace. Note that
not all papers have source available.

```bash
uv run scripts/download_paper_source.py --id 2010.11645 --output source.tar.gz
```

*Options:*

-   `--id`: The arXiv ID (e.g., `2010.11645`).
-   `--output`: Filepath to save the downloaded tar.gz file.

> **Caution**: Care should be exercised when untar'ing the downloaded file for
> security and to avoid cluttering your filesystem, as archives may contain many
> files or unexpected directory structures.
>
> **Safe Extraction Requirements**: NEVER extract directly into your working
> directory! Always extract into a dedicated new directory: `bash mkdir
> paper_source && tar -xzf source.tar.gz -C paper_source`

## Reference

-   **Advanced Query Syntax**: See
    [references/query_syntax.md](references/query_syntax.md) for prefixes (au,
    ti, abs), booleans, and date filtering.

## Workflow

1.  Search for papers using `search_arxiv.py`. Review the JSON summaries.
2.  If full text is needed, use `download_paper.py` to fetch the PDF or HTML.
3.  If downloading a PDF, verify the PDF is not empty or corrupted.
4.  Read the downloaded file using standard file reading tools.
