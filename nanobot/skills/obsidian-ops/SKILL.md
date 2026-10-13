---
name: obsidian-ops
description: Operational details for running the Obsidian CLI apps (obsidian / obsidian-agent) through nanobot. Use whenever operating Obsidian via its CLI apps — notes, search, diary, Canvas, vault writes — or when a vault path or connection issue comes up.
---

# Obsidian CLI Operational Notes

Complements the `cli-app-obsidian` and `cli-app-obsidian-agent-cli` plugin skills.

## Execution and install

- Use `run_cli_app` with `name="obsidian"` (binary `cli-anything-obsidian`, v1.1.1) or `name="obsidian-agent-cli"` (binary `obsidian-agent`, v0.1.1); do not invoke through shell unless the user explicitly asks.
- Both install via pip; make sure their entry points are on `PATH` (a user-level pip install lands in `~/Library/Python/3.x/bin` on macOS, `~/.local/bin` on Linux).

## Connection (verified 2026-09-24)

- obsidian-agent config: `api_url=https://127.0.0.1:27124`, API key saved in its config, `verify_ssl=false`.
- The default `http://127.0.0.1:27123` is unreachable — the Local REST API plugin only enables HTTPS; always use the https URL.
- Verified authenticated OK on Obsidian 1.13.7 + Local REST API with MCP v5.2.0.

## Vault

- Vault path: `$OBSIDIAN_VAULT` — the same variable the knowledge index and `paperctl.py` read, so setting it once moves all three together. There is no default. `obsidian-agent` also registers a vault path of its own; keep the two in step.
- REST API reads/writes land directly in this folder — no sync layer.
- Archive AI-generated notes under `AI Workspace/` in the vault.
- Kanban, Tasks, and backlink analysis require additional Obsidian plugins not yet installed.

## Example

```bash
obsidian-agent --json --help   # prefer --json for machine-readable output
```
