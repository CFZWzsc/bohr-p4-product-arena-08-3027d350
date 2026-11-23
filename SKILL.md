---
name: pdf-structure-reader
description: Use when a scientific PDF must be turned into page-anchored structure (text blocks, reading order, sections, captions, formulas, references) with an honest /app/output/result.json that keeps case_id and every original output_contract field.
---

# 科学 PDF 结构与阅读顺序解析

## 用途与适用条件

把一份真实科研 PDF 解析成可继续处理的页级结构：文字块、阅读顺序、章节层级、图表题注、公式编号、脚注与参考文献，并为每个块保留页码与坐标，便于回查。

分工：脚本只做**版式与结构**（确定性、可复跑）。案例要求的问题回答、字段抽取、翻译、核验或知识结构化，由调用 Agent 在同一 `result.json` 的 `answers` 中完成，每条结论定位到 `page` + `block_id`（必要时附原文 `quote`）；不解读图表科学含义，不补造材料外内容。

适用于原生文字层 PDF（含双栏、跨栏、多页表格文字），或 case 内给定的页/块级文字；不适用于纯扫描件（无文字层）、加密 PDF 或需 OCR 的图片型页面——这类输入如实标注缺口，不猜补。

## 输入

- `/input/case.json`（必需，`--case` 可覆盖）：脚本递归查找 `.pdf` 路径；没有 PDF 但提供 `pages`、`text`、`blocks`、`paragraphs` 时按给定结构解析，并在 `sources` 说明。
- `task.md`：优先读 `/input/task.md`，缺失不阻塞；其中字段要求优先于本文件。
- 真实 `output_contract` 以 case 内为准，本 Skill 不预设字段名。

## 处理流程

1. **识别输入边界**：列出文件、字节数、SHA-256；确认是否有文字层。找不到 PDF 或读取失败进入异常分支，不制造替代内容。
2. **页与内容流解析**：按页对象取内容流，支持 FlateDecode；解析 `BT/ET`、`Tm/Td/TD/T*`、`Tf`、`Tj/TJ/'/"`，保留字号与坐标。
3. **阅读顺序**：按页统计文字块起点分布判定单栏/双栏；双栏页按（栏, y, x）排序，单栏页按（y, x）排序；`blocks` 数组顺序即阅读顺序，`two_column` 标记版式；跨页不拼成一段。
4. **结构识别**：编号标题（`1`、`1.1`、`2.3.1`）与短标题行恢复层级；`Figure/Fig./Table` 行识别为题注；行尾 `(12)` 识别为公式编号；页底小字号行标记为脚注；`References/Bibliography` 之后的块归入 `references_region`。
5. **证据定位**：每个块输出 `page`、`bbox`、行数与文本哈希；章节、题注、公式、脚注都带来源块 ID。
6. **质量统计**：`stats` 给出页数、块数、字符数、空文本页、双栏页数；同一输入重复运行结果一致（无随机、无时间戳参与排序）。
7. **交付前自检**：见文末清单。

## 输出契约（字段 → 类型 → 含义/示例）

`/app/output/result.json` 顶层：

| 字段 | 类型 | 含义 / 示例 |
|---|---|---|
| `case_id` | string | 与输入逐字一致：`"case-b"` |
| `status` | string | `success`｜`partial`｜`insufficient_input`（含无法判断/拒答）｜`failed` |
| `result.pages[]` | array | `{"page":1,"width":612.0,"height":792.0,"two_column":false,"blocks":[...],"text":"..."}` |
| `result.pages[].blocks[]` | array | `{"block_id":"p01-b02","page":1,"bbox":[72.0,700.0,300.0,712.0],"text":"1 Introduction","sha256":"...","kind":"heading","size":10.0,"line_count":1}`；多 PDF 时 `block_id` 加 `d01-` 前缀；仅给定块级文字时 `bbox` 为 `null` |
| `result.sections[]` | array | `{"section_id":"S01","title":"1 Introduction","level":1,"parent_id":null,"page":1,"block_id":"p01-b02"}` |
| `result.captions[]` | array | `{"caption_id":"C01","kind":"figure_caption","text":"Figure 2. ...","page":3,"block_id":"p03-b05"}` |
| `result.formula_numbers[]` | array | `{"formula_label":"12","text":"... (12)","page":1,"block_id":"p01-b03"}` |
| `result.footnotes[]` | array | `{"text":"...","page":4,"block_id":"p04-b09"}` |
| `result.references_region` | array | `{"page":2,"block_id":"p02-b01"}`：参考文献区实际覆盖的块 |
| `answers` | array | **Agent 必补**：`{"question_id":"q1","answer":"...","page":2,"block_id":"p02-b04","quote":"原文句"}`；案例无提问时为 `[]` |
| `sources` | array | `{"path":"paper.pdf","bytes":123456,"sha256":"..."}` |
| `uncertainty` | array | `{"item":"ocr_needed","detail":"pages without extractable text","pages":[3]}`：未报告/不确定项带位置；无法判断不写成事实 |
| `limitations` / `errors` / `stats` | array / array / object | 边界声明；运行错误（含 `path`）；页数/块数/字符数/空页/双栏页 |
| `contract_notes` | object | 未映射的合同字段名及原因 |

- 原始 `output_contract` 每个字段名都保留；结构类同义名（`document`/`structure`/`parsed`、`references`、`evidence`/`anchors`、`page_count`、`figures`、`tables`、`text`）按别名填入真实结果；仍无法映射的写 `null` 并在 `contract_notes` 说明，不得删除。
- `blocks[].kind` ∈ `body`/`heading`/`caption`/`formula`/`footnote`/`reference`。

## 异常处理

| 情形 | 行为 |
|---|---|
| 找不到 PDF/输入 | `status=insufficient_input`，列出已检查路径，不生成页 |
| Flate 解码失败/内容流损坏 | 该页记入 `errors`，其余页继续，`status=partial` |
| 页无文字层 | 页 `text=""`、`blocks=[]`，`uncertainty` 记 `ocr_needed` 与页码 |
| 字体编码无法映射 | 按字节 latin-1 解码并在 `limitations` 声明；不声称字形正确 |
| 加密/权限受限 | `status=insufficient_input`，报告真实错误码 |
| 输出写入失败 | stderr 报错，stdout 打印结构化错误 JSON，进程仍以 0 结束 |

脚本捕获所有异常，输出结构化错误而不是抛栈崩溃。

## 限制与不适用

- 不提供 OCR；不解析 PDF 内嵌图片内容。
- 缺少 ToUnicode CMap 时字形到 Unicode 是近似的（latin-1 字节映射），复杂 CJK 字体可能乱码，必须视为部分结果。
- 不判断科学正确性、不解读图表。

## 最小调用示例（示例）

以下为接口示意，**不是官方固定案例结果**，数据为合成。

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --case /input/case.json --out /app/output/result.json --work /app/work
```

输出节选（键名与实际运行一致）：

```json
{"case_id":"synthetic-demo","status":"success","result":{"pages":[{"page":1,"blocks":[{"block_id":"p01-b01","page":1,"bbox":[72.0,700.0,220.0,712.0],"text":"1 Introduction","sha256":"...","kind":"heading"}]}],"sections":[{"section_id":"S01","title":"1 Introduction","level":1,"parent_id":null,"page":1,"block_id":"p01-b01"}],"references_region":[]},"answers":[{"question_id":"q1","answer":"...","page":1,"block_id":"p01-b01","quote":"1 Introduction"}],"uncertainty":[],"contract_notes":{}}
```

## 交付顺序与自检

1. `python scripts/run_skill.py --case <输入> --out <输出>`（`--output` 等价；默认 `/input/case.json` → `/app/output/result.json`）。
2. 脚本只产出结构骨架。案例若要求问答、抽取、翻译、核验或知识结构化，Agent 必须写入 `answers`，覆盖 case 中的每个问题/条目，每条带 `page` + `block_id`（必要时 `quote`）；材料不足的条目进 `uncertainty` 并说明原因，不得静默跳过。
3. 自检：`case_id` 一致；`output_contract` 每字段存在；无 `pending`/`TODO`/空占位；每块有页码、哈希（`bbox` 可空但需说明）；无文字层/解码失败页进入 `errors` 或 `uncertainty`；不联网、不伪造数据、不声称官方结果。
