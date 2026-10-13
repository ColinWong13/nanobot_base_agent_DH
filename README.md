# PRA — personal research assistant

![The PRA landing page](images/pra-hero.png)

PRA is a personal research assistant for digital-humanities and
information-retrieval work. It runs on your own machine, answers in the chat
apps you already use, and keeps what you read searchable.

It is a fork of **[nanobot](https://github.com/HKUDS/nanobot)**, an open-source
agent framework. The assistant core — providers, channels, tools, sessions,
memory, the WebSocket gateway, the OpenAI-compatible API — is upstream's and
tracks it. What this fork adds is in [The research layer](#the-research-layer)
and [The interface](#the-interface).

## What it does

**Lives where you already talk.** Seventeen channel integrations ship in the
box: Telegram, Discord, Slack, Feishu, WeChat, WeCom, DingTalk, QQ, Matrix,
WhatsApp, MS Teams, Mattermost, MoChat, email, Signal, NapCat, and the
WebSocket channel that backs the browser workbench itself. No new app to open.

**Reads your library.** Point it at an Obsidian vault and it indexes the notes
you already have, in place, without moving a file. See
[the knowledge index](#the-knowledge-index).

**Keeps a map of the field.** A registry of research domains, the venues you
would publish in, and how you rank them — editable from the browser. See
[the registry](#the-domains-and-venue-registry).

**Draws what you have.** The knowledge page renders the index as a graph of
disciplines, themes and papers.

**Works while you sleep.** Scheduled jobs and automations keep collecting, and
have it waiting when you come back.

**Any model you like.** Anthropic, OpenAI-compatible, OpenAI Responses, Azure,
Bedrock, GitHub Copilot, or a local endpoint — switchable from Settings.

## The research layer

Four things upstream does not have. The first three are pages in the WebUI; the
fourth is a tool the agent gets.

### The knowledge index

`nanobot/webui/vault_index.py` reads an Obsidian vault and serves a single
JSON index at `GET /api/webui/knowledge`. It expects this layout:

```
<vault>/
└── AI Workspace/资讯检索/
    ├── 10-Papers/     *.md      one card per paper
    ├── 20-Reviews/    slr-*.md  one file per literature review
    └── 30-Weekly/     *.md      weekly digests, newest first
```

The vault root is `OBSIDIAN_VAULT`. Everything below it — the subdirectory and
all three directory names — is a constant at the top of `vault_index.py`. Only
the root is configurable, so pointing this at a vault that is not laid out this
way means editing those constants. It is a reader for one pipeline's output,
not a general Obsidian browser.

A paper card is Markdown with YAML frontmatter. `type` must be `paper` or be
absent; `source_id` (or `arxiv_id`), `title`, `year` and `venue` are read from
the frontmatter, and the body carries `## 摘要（原文）` and `## 一句话提要`
sections. Theme headings inside a review are matched as
`### Theme 1: <name>` — the number is optional.

The index is cached and rebuilt only when the vault's file fingerprint changes.
Cards that fail to parse are counted and reported rather than dropped silently,
so a page that shows fewer papers than you expect can tell you why.

The knowledge page presents the index along **four dimensions** — by theme, by
discipline, by time, and by question. The fourth one is the odd one: it scans
your own past WebUI sessions for conversations that actually called the
literature pipeline, and lists them against the library as it stood that day.
It matches on the tool *call*, not on anything the tool returned, so the
agent's own memory-consolidation sessions do not show up as research you did.

> [!IMPORTANT]
> **The pipeline ships with the app.** Fetching from arXiv and OpenAlex,
> summarising, writing the frontmatter and maintaining the registry all live
> under [`nanobot/skills/`](nanobot/skills/) — see [The skills](#the-skills).
> What the knowledge page needs from you is a vault for them to write into.
> With none configured it says so, rather than showing an empty page.

### The domains and venue registry

`nanobot/webui/domains_api.py` manages a registry of research domains. Each
domain lists venues with a tier, and each venue can be enabled or disabled —
so the set of places worth reading or submitting to is something you edit, not
something compiled into the code.

The registry is a JSON file the agent owns:

```
~/.nanobot/workspace/registry/domains.json
```

It is **not** committed and **not** shipped — a fresh install has no registry
until you or the agent creates one. The page lives under Settings → Domains,
and every edit on it is a real write to that file through
`/api/webui/domains/*`.

Each venue row keeps three separate things, and the distinction matters: what
the **source** says its tier is (`base_tier`), what **you** decided
(`overrides`), and the **materialised** list everything downstream reads. A
rebuild re-derives the list from the source and then re-applies your overrides
on top, so your decisions survive a refresh of the underlying data.

To be clear about what that buys you:

- A **tier** change to a generated venue is durable — it is replayed.
- Changes to a generated venue's **name, type, area or ISSN** are not; only
  rows you added by hand keep those.
- Deleting a **generated** domain is not durable either. It comes back on the
  next rebuild, and the code and the page both say so.

> [!NOTE]
> The program that rebuilds the registry ships as a skill —
> `venue-registry/scripts/build_registry.py` — along with the CCF rankings
> dataset it can build from, `ccf-rank/references/2026/rankings.json`. The
> registry *file* is still yours: it is not committed, and a fresh install has
> none until you or the agent makes one.

### The graph

The knowledge page has a graph view: `discipline`, `theme` and `paper` nodes,
laid out with cytoscape's fCoSE. Edges connect a discipline to its themes, a
theme to its papers, and a discipline straight to any paper no theme claimed —
so nothing floats unattached. Node size grows with the square root of how much
the node holds. It is a pure function of the same index the list view uses,
which means there is no second source of truth to drift.

The graph is **disciplines, themes and papers only**. It does not extract
methods or authors from your notes, and it does not read wikilinks.

cytoscape is a ~500 kB dependency, so it is code-split into its own
`graph-vendor` chunk that the app shell never downloads. A build that
accidentally pulls it into the entry chunk fails rather than silently costing
every user half a megabyte.

### Remembering something on purpose

`nanobot/agent/tools/remember.py` gives the agent a tool for writing a note to
long-term memory mid-conversation, instead of waiting for the automatic
consolidation pass. The note is tagged — `skip`, `correction`, `permanent`,
`durable` or `ephemeral` — because the consolidation pass routes on those tags.
It is offered only in the main conversation, never to a subagent.

### The skills

Twelve skills ship in [`nanobot/skills/`](nanobot/skills/), beside the eleven
upstream ones. They are what actually *do* the research — the pages above only
display what these produce.

| Skill | What it does |
|---|---|
| `literature-search` | The pipeline itself. Owns `paperctl.py` and the card contracts. |
| `literature-search-arxiv` | Search arXiv; metadata and abstracts. |
| `literature-search-openalex` | Query OpenAlex; papers, authors, venues, bibliometrics. |
| `systematic-literature-review` | Run a review end to end into `20-Reviews/`. |
| `venue-registry` | Build and maintain the domain registry. |
| `ccf-rank` | Query the bundled CCF venue rankings. |
| `weekly-digest` | Write `30-Weekly/`; on a cron by default. |
| `obsidian-markdown` | Obsidian Flavored Markdown syntax. |
| `obsidian-ops` | Driving Obsidian through its CLI apps. |
| `cli-qr-auth` | Finishing a CLI login over chat. |
| `feishu-cli-ops` | `lark-cli` operational notes. |
| `wecom-cli-ops` | `wecom-cli` operational notes. |

Three of them document third-party CLI apps and do nothing unless you have those
apps installed. The rest need only Python and a vault.

**A workspace skill shadows a built-in one of the same name.** To change one of
these, copy it to `~/.nanobot/workspace/skills/<name>/` and edit the copy: your
version wins, and updating the package will not overwrite it. This is also how
you would replace one outright.

> [!WARNING]
> **The bundled CCF dataset is known to be damaged.** Of its 678 entries, around
> 65 carry venue names broken by PDF extraction — an abbreviation split across a
> line break, leaving entries named `Natural`, `Computer`, `Journal` and `Ad`.
> It ships as-is rather than silently patched, and
> `venue-registry/scripts/build_registry.py` hand-repairs the ones that matter.
> If a venue name looks like a fragment of a longer one, it is. The dataset can
> be rebuilt from CCF's own published list with
> `ccf-rank/scripts/build_ccf_dataset.py`.

## The interface

The WebUI was rebuilt on Material Design 3: one token layer, a purple seed
scheme, a ten-step radius ladder, elevation shadows, and a type scale — all in
`webui/src/globals.css`, which is the only stylesheet in the app.

Two things worth knowing:

- The landing page at `/home` is a self-contained HTML file with its own copy
  of the tokens. It deliberately does not import the app's stylesheet: it is
  the page that has to work when nothing else does. The copy is a duplication
  and says so in the file.
- The app is at `/`. Routing is hash-based. `/home` is the only separate page.

There are 10 UI locales (`webui/src/i18n/locales/`). The landing page carries 3
of them — English, Simplified Chinese and Traditional Chinese. That is not an
oversight: its strings are prose rather than labels, and inventing marketing
copy in seven languages nobody here can proofread is worse than falling back to
English.

## Status

This is a personal research project, developed in the open. It is not a
product, there are no releases, and it is not on PyPI.

Forked from nanobot **v0.3.5**. The last upstream commit before the fork's own
work is `4420ad58`.

Being honest about the edges:

- The knowledge index is built against one particular vault layout, described
  above. It is not generalised, and it will not guess at yours.
- The pipeline that produces paper cards ships as skills, but nothing runs it
  for you. Cards appear when you ask for a search, or when you put the weekly
  job on a cron.
- `OBSIDIAN_VAULT` has **no default**. A vault is your directory and there is no
  path that could be right for anyone but its owner; unset, the knowledge page
  says so instead of reading somewhere that is not there.
- The registry **file** ships empty by design — it is yours, and it is not
  committed. The program that builds one and the dataset it reads both ship.
- The bundled CCF rankings dataset has known extraction damage, described above.
- The `confirmed` flag on a domain records that you read the list. It gates
  nothing.
- The interface is fully localised, but the research layer's vocabulary is not.
  The headings it looks for inside your notes — `## 摘要（原文）`,
  `## 一句话提要`, `### Theme 1:` — are Chinese strings, because that is the
  vault it was written against. Pointing it at notes in another language means
  editing the constants in `vault_index.py`.

Planned and **not** implemented: more literature sources (bioRxiv, Europe PMC,
Semantic Scholar, Crossref), browser-driven scraping for sites without an API,
packaging the literature pipeline as an MCP server, and a canvas-style research
map. Vector retrieval is explicitly out of scope — retrieval here is over the
index, not over embeddings.

## Requirements

- **Python 3.11 or newer.**
- **Node.js with npm, or Bun.** Required, not optional — see below.
- A model provider: an API key for a hosted provider, or a local endpoint.

Git is needed to clone. Nothing else.

## Install

The WebUI ships as source, not as a prebuilt bundle (`nanobot/web/dist` is
gitignored), so a checkout has to build it. `nanobot webui` does that
automatically on first run and whenever the frontend source is newer than the
build — which is why Node or Bun is a hard requirement and not a
contributor-only concern.

```bash
git clone https://github.com/ColinWong13/nanobot_base_agent_DH.git
cd nanobot_base_agent_DH

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e .

nanobot webui
```

That builds the frontend, starts the gateway, and opens the browser workbench
at **http://127.0.0.1:8765**.

Configure a provider and model in **Settings → Models**, then send `Hello!`
before configuring anything else. The WebUI handles the first run; you do not
need to edit JSON to get one reply.

Using `uv` instead of `python -m venv` works the same way:

```bash
uv venv && uv pip install -e .
```

> [!WARNING]
> **Do not install this fork from PyPI, and do not use upstream's one-line
> installer.** Both install the package `nanobot-ai`, and that name belongs to
> upstream nanobot. `pip install nanobot-ai` and `uv tool install nanobot-ai`
> will give you upstream, without any of the research layer. Install from your
> clone.

If PyPI is slow where you are, a mirror helps a great deal:

```bash
python -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## Run

```bash
nanobot webui      # gateway + browser workbench, builds the frontend if stale
nanobot            # terminal agent
nanobot status     # what is configured, what is running
nanobot gateway    # gateway only, no browser
```

The gateway serves the WebUI and the HTTP API on **8765**. The OpenAI-compatible
API (`/v1/chat/completions`, `/v1/models`) is available from `nanobot serve`.

## Tests

```bash
pytest                            # from the repo root; covers Python and channel tests
cd webui && bun run test          # frontend, vitest run (npm run test works too)
```

Two things to know before you read the results:

- The test for the registry rebuilder **skips itself** when the workspace skill
  it loads is absent — which it is on any fresh clone. Skipped is not the same
  as passed.
- A session-scoped guard fails the run if any test touches the live
  `~/.nanobot/workspace/registry/domains.json`. Your real registry is never
  written to by the test suite.

## Configuration

Three things are yours to fill in. The repository ships no API keys, no channel
credentials and no vault path. Everything lives under `~/.nanobot/`:

| Path | What it is |
|---|---|
| `~/.nanobot/config.json` | providers, models, channels, settings |
| `~/.nanobot/workspace/` | the agent's working directory |
| `~/.nanobot/workspace/registry/domains.json` | the domains and venue registry |
| `~/.nanobot/workspace/skills/` | workspace skills — not under version control |

### Your model

**Settings → Models**, or `agents.defaults` in `config.json`. These providers
are upstream's — Anthropic, OpenAI-compatible, OpenAI Responses, Azure,
Bedrock, GitHub Copilot, or a local endpoint — and so is their configuration.
[Upstream's README](docs/upstream-nanobot.md) is the reference for it, and it is
accurate here because none of that code changed.

Open Settings → Models, paste a key, pick a model, send `Hello!`. You should not
have to edit JSON to get one reply.

### Your channels

The same: every channel is upstream's. Configure them in **Settings →
Channels**, or under `channels` in `config.json`; upstream's documentation under
[`docs/`](docs/) covers each one, credentials and webhooks included.

Nothing is enabled until you enable it. A fresh install reaches you through the
WebUI and nowhere else.

### Your vault

The one setting this fork adds.

```bash
export OBSIDIAN_VAULT="/path/to/your/vault"
```

It must be the **vault root** — the directory *containing* `AI Workspace/资讯检索`,
not that subdirectory itself. Set it in the gateway's environment rather than in
one terminal only: the gateway reads it per request and will not see a variable
exported somewhere else. Unset, the knowledge page says so.

Then let the skill create the tree inside it:

```bash
python3 nanobot/skills/literature-search/scripts/paperctl.py vault-init
```

It takes the root from `$OBSIDIAN_VAULT`, or `--vault PATH`. With the vault set,
**Settings → Knowledge** shows your cards instead of a prompt to configure one.

## Why "nanobot" still appears in places

The product is PRA. The *identifiers* are still nanobot, deliberately, because
renaming them breaks things rather than rebranding them:

- the Python package and import paths (`nanobot.*`),
- the distribution name (`nanobot-ai`),
- the config directory (`~/.nanobot/`),
- the CLI command (`nanobot`) and its banner,
- localStorage keys in the browser (`nanobot-webui.theme`, `nanobot.locale`),
- the `X-Nanobot-Auth` request header, and the service worker's cache prefixes.

Renaming the storage keys alone would silently reset every existing user's
theme, language and sidebar layout. Renaming the auth header would break the
handshake between the WebUI and its own gateway. The split is: **user-visible
text says PRA; anything that is a key, a path or a protocol stays nanobot.**

So if you see "nanobot" in this repository, it is either an identifier on that
list or documentation inherited from upstream.

## Upstream, attribution and license

PRA is a fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot). The
overwhelming majority of this codebase is the upstream project and its
contributors' work; this fork adds a research layer and an interface on top.

The upstream README is preserved at
[`docs/upstream-nanobot.md`](docs/upstream-nanobot.md), and upstream's own
documentation is intact under [`docs/`](docs/) — it describes the architecture,
channels, providers and configuration accurately, because those parts are
unchanged.

Licensed under the MIT License. Copyright (c) 2025-present Xubin Ren and the
nanobot contributors; see [LICENSE](LICENSE).
