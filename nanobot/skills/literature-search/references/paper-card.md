# 论文卡契约

> **Field names are frozen.** Phase 3's knowledge graph reads this frontmatter
> directly. Renaming a key is a breaking change; adding one is not.

## 文件名

```
<年份>-<短标题>-<source>-<source_id>.md
```

例：`2020-retrieval-augmented-generation-for-knowledge-intensive-nlp-t-arxiv-200511401.md`

短标题：小写、非字母数字转连字符、折叠连续连字符、截断 60 字符。`source_id`
里的 `.` 在文件名中被去掉（`2005.11401` → `200511401`），但 frontmatter 里
的 `source_id` **保留原点**。

## Frontmatter

```yaml
---
type: paper
title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP"
authors: [Patrick Lewis, Ethan Perez]
year: 2020
venue: NeurIPS
venue_tier: A            # CCF A/B/C，或 FT50 的 A*/A/B，或 "-"
source: arxiv
source_id: "2005.11401"
arxiv_id: "2005.11401"   # 仅 source=arxiv 时
topics: [cs.CL, cs.IR]   # arXiv 分类，来自数据源
url: https://arxiv.org/abs/2005.11401
pdf_url: https://arxiv.org/pdf/2005.11401
doi: ""                  # 预印本常缺，留空不猜
added: 2026-09-27
updated: 2026-09-27
status: unread           # unread | skimmed | read
topic_terms: [图结构 RAG] # 主题词，综述给的
domains: [ai]            # 哪次检索收来的（注册表里的领域 id）
---
```

`topics` 与 `topic_terms` 是两回事，别混：

| | 来源 | 粒度 | 谁写 |
|---|---|---|---|
| `topics` | 数据源的 `categories` | arXiv 分类（`cs.CL`） | 检索流程，每次覆盖 |
| `topic_terms` | 综述的 `### Theme N` 段落 | 研究主题（`安全与投毒`） | 综述写完后由 `card-enrich` 回填 |

`topics` 是**引用**——同一篇论文换个库查还是这个值。`topic_terms` 是**判断**——
同一篇论文换个综述就可能归到别的主题下。图谱用前者连学科，用后者连主题；
`cs.AI` 这种分类一篇论文带着，如果拿它连主题，81 篇里有 24 篇会连成一个死团。

新键排在 `status` 之后，不插在 `topics` 旁边：其余字段按写入顺序落盘，
把它们插进 `_CARD_ORDER` 会让 vault 里每张卡的 frontmatter 重排一遍，
为了两行改动换来一个满屏 diff。

## 字段归属（谁能写）

| 字段 | 归属 | 更新行为 |
|---|---|---|
| `title` `authors` `year` `source` `source_id` `topics` `url` `updated` | **agent** | 每次写入覆盖 |
| `venue` `venue_tier` `pdf_url` `doi` | **agent** | 有值才覆盖，缺则保留旧值 |
| `topic_terms` `domains` | **agent / 综述** | **只增不减**：并集合并、去重 |
| `added` `status` | **用户** | 仅在创建时设置；更新时保留 |
| 其它未列出的键 | **用户** | 原样透传，不解析、不丢弃 |
| `## 我的笔记` 之后的正文 | **用户** | **逐字保留** |

## 正文

```markdown
## 摘要（原文）

<arXiv summary / OpenAlex abstract 还原文本，逐字保留，不翻译、不摘要>

## 一句话提要

<agent 生成的中文一句话>

## 我的笔记

<!-- 用户手写区，agent 不得覆写 -->
```

生成段落只有「摘要」和「一句话提要」两个。**从 `## 我的笔记` 起到文件末尾
的整段内容在每次更新时被完整复制过去**——包括用户自己加的小标题、待办、
链接。若卡片没有「我的笔记」标题但有手写内容，该内容同样被保留。

## 去重

**键 = `source` + `source_id`。** 理由：

- **不能用标题**：同一篇论文在 v1/v2 之间标题会被重排；不同论文也可能撞标题
  （已实测：两篇不同 arXiv id 共用完全相同的标题，正确的行为是**分成两张卡**）。
- **不能用 DOI**：预印本常常没有 DOI，用它会退化成"每次都新建卡片"。

`paperctl card-check` 在卡片已存在时 **exit 1**，便于 shell 分支判断。

## 主题词怎么来

主题词不是检索时就能知道的——它来自**写在这些卡之后**的综述。所以它是单独一趟：

```bash
python3 scripts/paperctl.py card-enrich --json terms.json
```

`terms.json` 是 `[{"source": "arxiv", "source_id": "...", "topic_terms": [...],
"domains": [...]}]`。这趟**只动 frontmatter，正文一个字节都不碰**——
卡能靠检索结果重建，回填的主题词和你的笔记不能，所以它用原子写。

对不上的 `source_id` 会进结果的 `missing` 里，**不会凭空建卡**：对不上意味着
综述引用了一篇 vault 里没有的东西，照引用建卡只会把这个缺口盖住。

合并是并集，因为综述是活文档：同一主题再综述一次，新主题词必须能加上去，
而不是把上一趟的主题词挤掉。加错了要退回，用 `--replace`（传空列表即清空）。

## 不做什么

- **不下载 PDF、不做 OCR。** 本流程按设计只吃摘要（§7）。OpenAlex 的
  `download-pdf` 单次 $0.01 = 无 key 时的全天额度。
- **不覆写「我的笔记」。** 这是本契约里唯一一条绝对规则。
