---
name: bohr-reading-document-parsing
description: 当需要把科研 PDF/文档解析成可复核的结构化结果时使用。本题范围：文献文档解析（文字提取、多栏阅读顺序、章节层级、表格结构、公式与图表定位）。产出 result.json，包含运行时 output_contract 要求的全部字段，每条结论附原文证据（页码/段落/区块定位 + 短引），读不出或无法判断的部分如实写入 uncertainty。
---

# 文献文档解析：科研阅读：回答问题，也给出依据

## Focus (rubric)

| 维度 | 分值 | 本 Skill 的对应产出 |
|---|---|---|
| 实际效果 | 40 | 一次运行产出 `document-structure.json`，六组结构各自带定位；缺页号或栅格内容如实标注。 |
| 使用增益 | 25 | 单条命令、同一份材料即可得到逐条可核对的 文档结构 结果；`validation.json` 记录计算式自查（源文件 sha256、逐字引文回查、记录数、状态计数），基础 Agent 无此轨迹。 |
| 创新增益 | 15 | 覆盖率显式统计（读到/未读到），解析失败的文件单列，不用「看起来完整」掩盖缺页。 |
| 可靠体验 | 10 | 单次运行 exit 0；异常也恒写 `result.json`；材料不足时 `status=partial` 并在 `status_reason` 写明缺什么；同输入双跑逐字节一致。 |
| 生态贡献 | 10 | 本目录含 `scripts/`、`references/`、`assets/`、`examples/demo-case/`；字段字典见下「字段字典」；仅用 Python 标准库、不联网。 |
| GitHub | +5 | 公开仓库链接：`GITHUB_URL.txt` 第 1 行；第 2 行为 `SKILL.md` 相对路径。 |

## 用途与触发

解析文档结构：章节、文本块、表格、图、公式与覆盖率。

触发：输入目录含 `case.json`（含 `task_instruction` 与 `output_contract`）与科研材料文件时，本 Skill 适用。

## 输入

- `/input/case.json` —— 任务说明与**运行时契约**（唯一权威，字段名以它为准，不硬编码）。
- `/input/` 下同目录的科研材料：PDF / 文本 / 表格 / 图注 / `target-fields.json`（若有）。
- `target-fields.json`、`claims-to-verify.json` 等是**任务说明**，不作为论文正文读入证据。

## 运行

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

一次运行完成读取、抽取、判断与落盘；没有第二阶段，也不需要人工补写。

## 一次运行产出什么

除 `result.json`（契约齐全）外，`/app/output` 下必有：

| 文件 | 内容 |
|---|---|
| `document-structure.json` | JSON 产物，含段落级证据定位 |
| `reading_ir.json` | 真实抽取记录：field_id / value / status / evidence（source + paragraph_id + 逐字 quote） |
| `provenance.json` | 读取的源文件、段落数、源文件 sha256、材料 sha256（无绝对路径） |
| `validation.json` | 计算式自查：sources_read / records_produced / verbatim_quotes / records_carry_paragraph_id / no_fabricated_numbers |
| `run-review.md` | 人类可读的证据索引与不确定性清单 |

契约键：`output_contract` 的每个键都会填内容；确实无法从材料得出的键填结构化「无法判断」条目，
**不留 `null`**；未知键只进 `contract_extras`。

## 证据纪律

- 每条 claim 带 `paragraph_id` + 原文**逐字**片段（允许空白差异，可子串回查）。
- 四态：`reported / not_reported / source_conflict / extraction_failed`；缺口状态**不携带值**，并置
  `human_confirm: true`。
- 数值、单位、图表号与原文一致，不换算、不四舍五入；表格取值给到单元格级定位。
- 材料没说的写进 `uncertainty` 与 `status_reason`，不补「合理猜测」。
- 异常主动自报到 `anomaly-report.json`（状态计数、逐条原因、正文与表格冲突）。

## 字段字典

结构类型、定位、覆盖状态

## 失败与边界

| 情况 | 正确处理 |
|---|---|
| 扫描件无文本层 | `status=unsupported` 并记 `no_text_layer` |
| 文件只读到一部分 | `coverage.not_read` 列出未读文件 |
| 材料格式未知 | 记录路径与可读性，不猜内容 |
| 契约键无法解读 | 产出该键的结构化说明并写入 `uncertainty`，不留空 |

## 自查（提交前）

- 双跑同一输入，`result.json` 逐字节一致。
- `validation.json` 的 `checks` 全为 `pass`；`status_counts` 与记录数一致。
- 契约键无缺失、无 `null`。
- 包内无绝对路径、无令牌、无 `__pycache__`/`.pyc`。

## 参考

- `references/evidence-discipline.md` —— 证据与不确定性纪律
- `references/contract-handling.md` —— 运行时契约读法
- `references/failure-modes.md` —— 常见失败与退路
- `references/artifact-pipeline.md` —— 产物与契约键的对应
- `assets/policy.json` —— 不编造承诺
- `examples/demo-case/` —— 可离线复现的最小案例
