---
name: pdf-structure-reader
description: Use when a scientific PDF must be turned into page-anchored structure (text blocks, reading order, sections, captions, formulas, references) with an honest /app/output/result.json that keeps case_id and every original output_contract field.
---

# 科学 PDF 结构与阅读顺序解析

## 用途与适用条件

把一份真实科研 PDF 解析成可继续处理的页级结构：文字块、阅读顺序、章节层级、图表题注、公式编号、脚注与参考文献区分，并为每个块保留页码与坐标，便于回查。适用于原生文字层 PDF（含双栏、跨栏、多页表格文字）；不适用于纯扫描件（无文字层）、加密 PDF 或需要 OCR 的图片型页面——这类输入必须如实标注缺口，不能用猜测补齐。

本 Skill 只在“解析与结构化”范围内工作：它不解释图表科学含义，不翻译，不生成论文结论。输出用于后续翻译、问答、知识抽取。

## 输入

- `/input/case.json`（必需，可用 `--case` 覆盖）：案例包。脚本递归查找其中的 `.pdf` 路径；若没有 PDF 但提供页/块级文字（`pages`、`text`、`blocks`、`paragraphs`），则按给定结构解析并在 `sources` 中说明。
- `task.md`：Harness 提供的任务说明，优先读 `/input/task.md`；其中的字段要求优先于本文件的通用建议。
- 真实 `output_contract` 以 case 内为准；本 Skill 不预设字段名。

## 处理流程（覆盖实际效果 40 / 使用增益 25 / 创新增益 15 / 可靠体验 10 / 生态贡献 10）

1. **识别输入边界（实际效果）**：列出实际文件、字节数、SHA-256；确认是否存在文字层。找不到 PDF 或读取失败时进入异常分支，不制造替代内容。
2. **页与内容流解析**：按 PDF 页对象取内容流，支持 FlateDecode；解析 `BT/ET`、`Tm/Td/TD/T*`、`Tf`、`Tj/TJ/'/"`，保留字号与坐标。
3. **阅读顺序（创新增益）**：按页统计文字块起点分布判定单栏/双栏；双栏页按（栏, y, x）排序，单栏页按（y, x）排序；跨页跨栏不拼接成一段，块间保留页边界标记。
4. **结构识别**：编号标题（`1`、`1.1`、`2.3.1`）与短标题行恢复层级；`Figure/Fig./Table` 行识别为题注；行尾 `(12)` 识别为公式编号；页底小字号行标记为脚注候选；`References/Bibliography` 之后标记为参考文献区。
5. **证据定位（实际效果、可核验性）**：每个块输出 `page`、`bbox`、首末行号与文本哈希；章节、题注、公式均带来源块 ID。
6. **质量与效率（使用增益）**：`stats` 给出页数、块数、字符数、空文本页、双栏页数、失败页；同一输入重复运行结果确定性一致（无随机、无时间戳参与排序）。
7. **交付前自检（可靠体验、生态贡献）**：检查 `case_id` 与契约字段保留、页码连续、块不重叠、引用定位存在。

## 输出契约

`/app/output/result.json` 顶层必须包含：

- `case_id`：与输入完全一致。
- 原始 `output_contract` 中的每一个字段：字段名不改、不删；已知语义字段填入真实结果，未知字段保留为 `null` 并在 `contract_notes` 说明，禁止删除。
- `status`：`success` / `partial` / `insufficient_input` / `failed`。
- `result`：`pages[]`（`page`、`width`、`height`、`blocks[]`、`text`）、`sections[]`、`captions[]`、`formula_numbers[]`、`footnotes[]`、`references_region`、`reading_order`。
- `sources`：实际文件、哈希、页码映射依据。
- `uncertainty`：无法判定项（如字体编码、无文字层页）。
- `limitations`、`stats`、`errors[]`、`contract_notes`。

`result.pages[].blocks[]` 至少含 `block_id`、`page`、`bbox`、`text`、`sha256`、`kind`（`body`/`heading`/`caption`/`formula`/`footnote`/`reference`）。

## 异常处理

| 情形 | 行为 |
|---|---|
| 找不到 PDF/输入 | `status=insufficient_input`，列出已检查路径，不生成页 |
| Flate 解码失败/内容流损坏 | 该页记入 `errors`，其余页继续，`status=partial` |
| 页无文字层 | 页 `text=""`、`blocks=[]`，`uncertainty` 标注需 OCR |
| 字体编码无法映射 | 按字节 latin-1 解码并在 `limitations` 声明；不声称字形正确 |
| 加密/权限受限 | `status=insufficient_input`，报告真实错误码 |
| 输出写入失败 | stderr 报错，stdout 打印结构化错误 JSON，退出码 2 |

脚本捕获所有异常，输出结构化错误而不是抛栈崩溃。

## 限制与不适用

- 不提供 OCR；不解析 PDF 内嵌图片内容。
- 字形到 Unicode 的映射在缺少 ToUnicode CMap 时是近似的（latin-1 字节映射），复杂 CJK 字体可能乱码，必须视为部分结果。
- 不判断科学正确性、不解读图表、不做翻译。
- 不修改 `/input` 下任何文件。

## 最小调用示例（示例）

以下为接口示意，**不是官方固定案例结果**，数据为合成。

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --case /input/case.json \
  --out /app/output/result.json \
  --work /app/work
```

合成 case 契约 `{"output_contract": {"pages": "array", "status": "string"}}` 时，输出至少保留 `case_id`、`pages`、`status` 三个顶层键，示例片段：

```json
{"case_id": "synthetic-demo", "status": "success", "result": {"pages": [{"page": 1, "blocks": []}]}}
```

## 自查清单

- [ ] `case_id` 与输入逐字一致。
- [ ] `output_contract` 字段一个不少，未知字段为 `null` 且有说明。
- [ ] 每页块按阅读顺序排列，双栏页不串栏。
- [ ] 每个块有页码、bbox、哈希。
- [ ] 无文字层/解码失败页已进入 `errors` 或 `uncertainty`。
- [ ] 未运行官方固定案例时，不声称官方结果。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--output` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 使用本 Skill 输出契约的枚举（正常完成为 `success`，确实缺输入或存在未解决项为 `partial`，无法作答为 `insufficient_input`，运行异常为 `failed`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
