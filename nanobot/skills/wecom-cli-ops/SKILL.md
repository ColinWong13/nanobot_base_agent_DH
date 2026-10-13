---
name: wecom-cli-ops
description: Operational details for running the WeCom CLI app (wecom-cli) through nanobot. Use whenever operating WeCom via the wecom CLI app — auth (init/show), calendar, chat, contact, disk, doc, mail, media, message, meeting, sheet, smartpage, smartsheet, or todo commands.
---

# WeCom CLI Operational Notes

Complements the `cli-app-wecom` plugin skill.

## Execution

- Always run through `run_cli_app` with `name="wecom"` (binary `wecom-cli`); do not invoke through shell unless the user explicitly asks.
- For a raw `exec`, make sure node and npm's global bin directory are on `PATH`; if a bare shell cannot find them, prefix the call with `PATH="$(npm prefix -g)/bin:$PATH"`.

## Command groups

auth, calendar, chat, contact, disk, doc, mail, media, message, meeting, sheet, smartpage, smartsheet, todo

## Auth

- `auth` has only `init` and `show` subcommands (no `status`); verify with `auth show`.
- `auth init --noninteractive` prints a QR + verification URL and blocks until the user scans it with the WeCom app. Run it in a background session and deliver the QR remotely — see the `cli-qr-auth` skill.

## JSON output

Put `--json` after the subcommand; a global `--json` before the subcommand is rejected as an unexpected argument. Exception: `auth show` does not accept `--json` at all.
