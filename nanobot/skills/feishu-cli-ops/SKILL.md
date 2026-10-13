---
name: feishu-cli-ops
description: Operational details for running the Feishu/Lark CLI app (lark-cli) through nanobot. Use whenever operating Feishu via the feishu CLI app — auth login/whoami, messaging, docs, calendar, or any lark-cli command.
---

# Feishu CLI Operational Notes

Complements the `cli-app-feishu` plugin skill.

## Execution and environment

- Prefer `run_cli_app` with `name="feishu"`; do not invoke through shell unless the user explicitly asks.
- Binary: `lark-cli`, normally a global npm install. A bare `exec` shell may not have node or npm's global bin directory on `PATH`; if `command -v lark-cli` comes up empty, prefix the call with `PATH="$(npm prefix -g)/bin:$PATH"`.

## Auth

- Login is a device flow; generate a QR image with `lark-cli auth qrcode "<url>" --output <png>` and deliver it via `message` — see the `cli-qr-auth` skill.

## Messaging

- The current user token lacks `im:message.send_as_user`, so sending as the user's own identity fails; send with the bot identity (`--as bot`).
