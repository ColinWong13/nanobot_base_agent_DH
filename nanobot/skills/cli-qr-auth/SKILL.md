---
name: cli-qr-auth
description: Finish a CLI app's interactive login (QR code / device-code scan) remotely over chat. Use when a CLI app such as wecom or feishu (lark-cli) needs the user to scan a QR or open a verification URL and is not at the terminal: run auth in a background session, turn the URL into a QR image, deliver it via message, then verify.
---

# CLI QR / Device-Code Auth Over Chat

## Steps

1. Run the auth command in a background `exec` session (set `yield_time_ms` to capture early output) so it stays alive while waiting for the scan; a foreground call gets killed (exit -15) when the session ends.
   - wecom: `wecom auth init --noninteractive`
   - feishu: `lark-cli auth login`
2. Extract the verification URL (and QR, if the CLI prints one) from the session output.
3. Generate a QR image for the URL:
   - feishu: `lark-cli auth qrcode "<url>" --output /tmp/auth-qr.png`
   - other CLIs: `python3 -c "import qrcode; qrcode.make('<url>').save('/tmp/auth-qr.png')"` (python3 has the `qrcode` module installed), or fall back to sending the raw URL.
4. Deliver the QR PNG through the `message` tool (`media` parameter) together with the URL as fallback and which mobile app to scan with (WeCom app / Feishu app). Wait for the user to confirm the scan.
5. Verify, then report: `wecom auth show`, `lark-cli whoami`.

## Notes

- Never block the main flow on the scan; poll the background session after the user confirms.
- Letting a poll on the session time out kills it (exit -9/-15) and invalidates the QR code; re-run `auth init` to get a fresh one.
- Re-run `auth init` only after killing any previous waiting session, to avoid stale QR codes.

## Example

```bash
wecom auth init --noninteractive
# → prints QR + URL https://work.weixin.qq.com/ai/qc/gen?source=wecom_cli_external&scode=...
lark-cli auth qrcode "<url>" --output /tmp/auth-qr.png
# → deliver QR via message, user scans with WeCom app
wecom auth show   # confirm identity
```
