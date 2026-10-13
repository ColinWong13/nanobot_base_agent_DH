---
name: weekly-digest
description: Write the weekly 资讯检索 digest into the vault's 30-Weekly/ folder and report it. Runs automatically every Monday 08:30 covering the previous complete week; also use it when the user asks what was collected last week, wants a weekly summary of new paper cards, or asks to regenerate a weekly report.
---

# weekly-digest

Writes one file per week — `30-Weekly/<ISO-year>-W<week>.md` — summarising the
paper cards added during the **previous complete week**, then reports it.

**The reply is the deliverable.** A cron delivery sends whatever you reply, so
answering `已生成` or naming the path delivers nothing. The reply must itself be
the digest. (This is why the job exists as its own task rather than a silent
background write: the message is going to be sent either way, so it may as well
carry the content.)

## Step 0 — pin down the week

Compute it with `date`. **Never work it out yourself**: the gateway and the job
both run `Asia/Shanghai`, and hand-arithmetic picks the wrong week at the
Sunday-midnight boundary.

```bash
TZ=Asia/Shanghai bash -c '
  back=$(( $(date +%u) + 6 ))
  echo "week=$(date -v-${back}d +%G-W%V)"
  echo "start=$(date -v-${back}d +%Y-%m-%d)"
  echo "end=$(date -v-${back}d -v+6d +%Y-%m-%d)"
'
```

`back` steps back to the **Monday of the previous week** — 7 days when run on a
Monday, 13 on a Sunday. This offset is the whole point: the job fires on a
Monday, and on that day a bare `date +%G-W%V` names the week that is *starting*,
not the one being reported. Getting this wrong makes every file off by one week.

The file is named for the week it **covers**, never for the day it ran. So the
run on 2026-10-05 writes `2026-W40.md` covering `2026-09-28 ~ 2026-10-04`.

## Step 1 — collect what was added

`paperctl.py list` carries `added` per card, so one call is enough — no need to
grep frontmatter and then re-read each card to recover its title.

```bash
# Run from the agent's workspace root. $OBSIDIAN_VAULT must be set (see the
# literature-search skill), and paperctl.py lives in that skill's own scripts/
# directory -- substitute its real path.
VAULT="$OBSIDIAN_VAULT"
python3 <literature-search>/scripts/paperctl.py list --vault "$VAULT" > /tmp/week.json

python3 - "$START" "$END" <<'PY'
import json, sys
start, end = sys.argv[1], sys.argv[2]
papers = json.load(open("/tmp/week.json"))["papers"]
sel = [p for p in papers if p.get("added") and start <= p["added"] <= end]
print(f"{len(sel)} 篇新增")
for p in sel:
    print(f'  {p["added"]}  {p["source_id"]}  {p["title"]}')
PY
```

⚠️ `--vault` is the **Obsidian vault root**, not the `AI Workspace/资讯检索`
subdirectory inside it. Passing the subdirectory makes every lookup report
"nothing here" — the pipeline tree lives *under* the path you pass.

Compare `added` as an ISO string over a **closed** interval. On the boundary
week this is the difference between 56 papers and zero.

## Step 2 — cluster by direction

Group the titles from Step 1 into themes. Titles alone are usually enough; only
read further when a title is genuinely opaque.

**Do not read every card body to cluster them.** `## 摘要（原文）` is long, and
clustering does not need it.

## Step 3 — pick 2–3 worth a single read

For the candidates only, read the `## 一句话提要` section of the card — that one
line is written precisely for this. Give the title plus one sentence on why it
stands out.

## Step 4 — write the file

`<vault>/AI Workspace/资讯检索/30-Weekly/<week>.md`:

```markdown
---
type: weekly
week: 2026-W40
range: 2026-09-28 ~ 2026-10-04
papers_added: 56
created: 2026-10-05
---

# 2026-W40（2026-09-28 ~ 2026-10-04）

## 本周新增

56 篇。

## 方向聚类

- **主题 A**（n 篇）— 一句话说明这批在做什么。
- **主题 B**（n 篇）— ……

## 值得单读

1. **<标题>** — 为什么值得读。
2. **<标题>** — ……
```

Rewriting an existing week's file is fine — a manual re-run should correct it,
not append a second copy.

**A week with no new cards is reported as such**, not written up as an empty
digest: set `papers_added: 0`, say `本周无新增` in the body, and reply
`本周（<range>）无新增论文卡。` That is a real answer; do not pad it.

## Step 5 — reply

Reply with the digest itself: the count, the clusters, and the 2–3 picks. Keep
it to a message someone reads on a phone — the full detail is in the file.
