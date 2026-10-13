# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

It holds two families:

- **Upstream skills** — the ones nanobot has always shipped.
- **Research skills** — the digital-humanities / information-retrieval layer
  this fork adds. Their scripts are Python, most of them expect an Obsidian
  vault, and several read and write the same vault tree.

A skill in your workspace (`~/.nanobot/workspace/skills/<name>/`) **shadows** a
built-in one of the same name, so anything here can be replaced locally without
touching the installed package.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

When skills reference large local documentation or logs, prefer nanobot's built-in
`grep` tool to narrow the search space before loading full files.
Use `grep(output_mode="count")` / `files_with_matches` for broad searches first,
use `head_limit` / `offset` to page through large result sets,
and `grep(glob="*.md")` to filter by file name pattern.

## Configuration the research skills need

Two things, neither of which has a default, because both are the user's:

- **`OBSIDIAN_VAULT`** — the Obsidian vault root. The knowledge pages in the
  WebUI and `literature-search`'s `paperctl.py` read the same variable, so
  setting it once moves both. It is the *vault root*, the directory containing
  `AI Workspace/资讯检索`, not that subdirectory itself.
- **The workspace root** — `agents.defaults.workspace` in
  `~/.nanobot/config.json`, `~/.nanobot/workspace` by default. It is where the
  registry and the agent's own files live.

Three of the operational skills (`obsidian-ops`, `feishu-cli-ops`,
`wecom-cli-ops`) document third-party CLI apps. They are inert unless those
apps are installed; nothing here depends on them.

## Attribution

The upstream skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s
skill system. The skill format and metadata structure follow OpenClaw's conventions
to maintain compatibility.

The research skills below are original to this fork. They are not covered by
OpenClaw's conventions and do not use its metadata.

## Available Skills

### Upstream

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `clawhub` | Search and install skills from ClawHub registry |
| `skill-creator` | Create new skills |
| `cron` | Schedule reminders and recurring tasks |
| `image-generation` | Generate and iteratively edit saved image artifacts |
| `memory` | Search past conversations in the agent's history log |
| `my` | Inspect and adjust the agent's runtime state |
| `update-setup` | One-time setup wizard for the upgrade skill |

### Research layer

| Skill | Description |
|-------|-------------|
| `literature-search` | The pipeline itself: research interest → paper cards + a review in the vault. Owns `paperctl.py` and the card contracts. |
| `literature-search-arxiv` | Search arXiv, extract metadata and abstracts. |
| `literature-search-openalex` | Query OpenAlex for papers, authors, venues and bibliometrics. |
| `systematic-literature-review` | Run an SLR end to end and write the review into `20-Reviews/`. |
| `venue-registry` | Maintain the domain registry — which venues count for a field, and how they are ranked. |
| `ccf-rank` | Query the CCF venue ranking dataset. Note: the bundled dataset has known extraction damage (see the main README). |
| `weekly-digest` | Write the weekly `30-Weekly/` digest; runs on a cron by default. |
| `obsidian-markdown` | Obsidian Flavored Markdown — wikilinks, embeds, callouts, properties. |
| `obsidian-ops` | Operational notes for driving Obsidian through its CLI apps. |
| `cli-qr-auth` | Finish a CLI app's QR / device-code login over chat. |
| `feishu-cli-ops` | Operational notes for `lark-cli`. |
| `wecom-cli-ops` | Operational notes for `wecom-cli`. |
