# 综述契约

> **Field names are frozen.** Phase 3's knowledge graph reads this frontmatter
> directly. Renaming a key is a breaking change; adding one is not.

**一份综述是活的。** 同一主题只有一份 `slr-<topic_slug>.md`，逐年就地更新，
不是每次提问产生一份新报告。2026-09-28 的 bug——agent 搜了 80 篇、写了
968 行，完全没察觉两天前已有同主题的 25 篇综述——根因就是没有这份契约：
论文卡有身份键、有 `card-check`、有冻结字段，综述三样都没有。

## 文件名

```
20-Reviews/slr-<topic_slug>.md            # 综述本体，就地更新
20-Reviews/slr-<topic_slug>-archive.md    # 窗口外论文档案
```

**文件名不带日期。** 活文档带创建日期，第二次更新时那个日期就成了假信息——
读者看到 `slr-rag-20260928.md` 会以为它只覆盖到 9-28，而它其实一直在长。
创建日期在 frontmatter 的 `created` 里，那里才是它该待的地方。

`<topic_slug>`：小写、非字母数字转连字符、折叠连续连字符、截断 60 字符。
旧格式的 `-<YYYYMMDD>` 后缀在归一化时被剥掉，所以 `slr-rag-20260928` 与
`slr-rag` 是同一个 slug，迁移期两者不会各算一份。

## Frontmatter

```yaml
---
type: review
topic: "Retrieval-Augmented Generation (RAG)"   # 人类可读，可改
topic_slug: rag                                  # 身份键，创建时定死
papers: 81                                       # 由 review-write 从正文算出
window: 2026-08-28 ~ 2026-09-28                  # 实际覆盖区间
source: arxiv
citation_format: APA
language: en
created: 2026-09-27
updated: 2026-10-05
themes: [图结构 RAG, 安全与投毒]                  # 短标签，顺序对应正文的 ### Theme N
---
```

`type` 取 `review` 或 `review-archive`。`language` 创建时定下、后续更新沿用，
所以一份综述内部不会中英混排。

**`window` 写的是实际检索覆盖的区间，不是保留期。** 搜了一个月就写一个月。
写「近两年」而实际只搜过一个月，等于宣称覆盖了没搜过的时段——正是本契约要
消灭的同一类漂移。`window.end` 是下一次检索的水位线。

## `themes` —— 主题词表，正文标题的短名

`themes` 是一个**逗号分隔的短标签列表**，顺序对应正文里 `### Theme 1`…
`### Theme N` 的出现顺序。它有两个用途，缺一不可：

- **卡片靠它归类。** `card-enrich` 把短标签写进论文卡的 `topic_terms`，
  知识页的「按主题」维度就是按它分组的。
- **图谱拿它当节点名。** 节点标签只能放得下几个字。

**为什么要单独存短名，而不是从正文标题推。** 推不出来：`安全——投毒攻击面
扩大，防御走向工具化` 的短名是 `安全与投毒`，`垂直领域落地与本地部署` 的短名
是 `垂直领域落地`——没有规则能生成这两个。写进去是唯一诚实的做法。

对应的正文标题留在正文里，页面把两者一起显示：短名进图，长标题进页面标题。

```bash
python3 scripts/paperctl.py review-write --slug rag --themes "图结构 RAG,安全与投毒"
```

不传 `--themes` 就保持原样——和其它 agent 字段一样只增不改。

## 字段归属（谁能写）

| 字段 | 归属 | 更新行为 |
|---|---|---|
| `papers` `topic_slug` `updated` | **工具** | 每次写入重算 / 覆盖 |
| `topic` `window` `source` `citation_format` `language` `themes` | **agent** | 有值才覆盖，缺则保留旧值 |
| `created` | **用户** | 仅在创建时设置（旧文件的 `generated` 会被吸收过来） |
| 其它未列出的键 | **用户** | 原样透传，不解析、不丢弃 |
| `## 我的笔记` 之后的正文 | **用户** | **逐字保留** |

`topic_slug` 用 `setdefault` 而非赋值：文件名与存储 slug 不一致时覆盖它，
会把综述从调用者刚刚找到它的那个身份下面挪走。改名不该伪装成写入的副作用。

## `papers` 从正文推导，不许手写

`review-write` 每次写入都从正文数一遍标识行，覆盖 frontmatter 里的
`papers`。**正文是唯一真相源，`papers` 只是它的缓存。**

不把 81 个 id 的清单也存进 frontmatter，是因为那份清单会和读者实际看到的
注释漂移；而正文才是下一次合并的依据。模型手打的计数，早晚会错，而一个错的
计数会让下一轮的去重看起来像是成功了。

`review-list` 同时给出 `papers`（推导）与 `papers_declared`（文件里写的），
两者不一致就是「改过正文但没重跑 `review-write`」——留这个字段就是为了让漂移
可见，而不是悄悄纠正它。

## 标识行 —— 让一切成立的那一行

`## Per-Paper Annotations` 一节内，**每个注释块的第一行**必须是：

```markdown
**arXiv**: [2609.28575](https://arxiv.org/abs/2609.28575)
```

- 标签宽松（`**DOI**: [...]` 也可以用），但**必须带 `](url)` 链接目标**，且
  文字与 URL 必须指同一篇——不一致会静默把这段文字挂到另一张存在的卡上。
- 旧格式 `` `2609.23056` · cs.CL · 未定级 `` 同样被接受，否则合并后的正文有
  105 个注释而 `papers` 只算 80，且完全无声。
- 扫描**限定在 `## Per-Paper Annotations` 一节内**。实测：`^### ` 全文数那份
  80 篇的综述是 86，多出的 6 个是 `### Theme N`；限定该节后正好 80。
- 计数按规范化后的 id 比较（去掉 `v3` 后缀、`arXiv:` 前缀、URL 包装），否则
  同一篇论文会被数成三个。接受的形状：`2609.28575`、`cs.CL/0701001`、
  `10.1234/xyz`、`W2963008344`。

**解析出 problems 时拒绝写入 `papers`。** 悄悄写错的计数比并行综述更糟——
文件看起来完全正常。缺标识行、id 重复、文字与 URL 不符，以及「一节有内容却
解析出 0 个标识」，都会中止写入并指出是第几个块。明知故犯时用 `--force`。

## 一主题一份

**身份 = `topic_slug`，由 frontmatter 的 `topic_slug` 或文件名任一声明。**
文件名兜底是有意的：没有 frontmatter 的综述也必须能被找到——`split_frontmatter`
对无 frontmatter 的文件返回 `({}, text)`，只扫 frontmatter 的做法对它是瞎的。

`topic_slug` 永不从 `topic` 推导。从可变的人类字符串推导身份，正是一个主题
长出两个 slug 的机制（`Retrieval-Augmented Generation` 会得到
`retrieval-augmented-generation`，与 `rag` 是两个字符串，代码永远无法知道
它们是同一件事——所以才有下面那个重叠数字）。

| 命令 | 行为 |
|---|---|
| `review-find --slug rag` | 存在 **exit 1**；不存在 exit 0；两个文件同 slug → **exit 2** 且不猜赢家 |
| `review-list [--ids F]` | 列出全部综述；带 `--ids` 时按 `overlap.count` 降序 |
| `review-write --slug rag` | 盖章。**文件不存在就报错并打印预期路径，不创建** |

`review-write` 拒绝创建文件是刻意的：写正文本来就是 agent 的活，而一个会悄悄
建出空综述的工具，会掩盖远更可能的解释——slug 错了，agent 想更新的那份综述
就在盘上，只是叫别的名字。

**最后一道闸**：`review-write --ids` 在写之前比对同目录所有综述，命中 ≥10 篇
且占比 ≥60% 就直接拒绝并点名「这就是同一主题，更新 `<file>`」。agent 前面
所有步骤都跳过，这道闸仍然拦得住。

## 归档与淘汰

- **淘汰规则**：论文发表时间早于 `window.end` 减 2 年。
- **日期来源**依次尝试：arXiv id 自带的 `YYMM`（`2609.xxxxx` → 2026-09）→
  注释标题里的 `(2026)`。旧式 id `archive/0701001` 的两位年是 19xx 还是 20xx
  按 ≥91 分界。都取不到就报「日期未知」，**不猜**。
- 只有年份时按 **12 月**算：按 1 月算会把还在窗口内的论文提前淘汰。多留一年
  可恢复，提前淘汰不可恢复。
- 被淘汰的注释**浓缩**进 `slr-<slug>-archive.md`（同样用标识行，因此同一套
  解析原样复用），然后从综述正文删除。正文里用
  `[[slr-rag-archive|窗口外论文档案]]` 链过去。
- **档案只增不淘汰**，且它本身不是综述：`review-list` 不列它，
  `review-find --slug rag-archive` 返回不存在。

## 不做什么

- **不下载 PDF、不做 OCR。** 按设计只吃摘要。
- **不覆写「我的笔记」。** 与论文卡同一条绝对规则。
- **不用 Write 整篇重写正文。** 用 Edit 增量改——整篇重写会丢注释，而这是
  本契约拦不住的最大残余风险，只有 `papers` 下降时的告警能暴露它。
- **不因为 `overlap.ratio` 低就断定是两个主题。** `source` 不同（arXiv vs
  OpenAlex）时 id 永不相交，重叠率显示 0.0 而主题其实相同——那时要看 topic，
  不能看 ratio。
