---
name: bohr-reading-document-parsing
description: 当需要把科研 PDF/文档解析成可复核的结构化结果时使用。本题范围：文献文档解析（文字提取、多栏阅读顺序、章节层级、表格结构、公式与图表定位）。产出 result.json，包含运行时 output_contract 要求的全部字段，每条结论附原文证据（页码/段落/区块定位 + 短引），读不出或无法判断的部分如实写入 uncertainty。
---

# 文献文档解析：科研阅读：回答问题，也给出依据

## 用途

本题属于 **literature-reading（reading）** 赛道，题目是「文献文档解析」。目标能力：把一份真实科研 PDF 解析成**可继续处理、可回查原文**的结构化结果，而不是给一段"看起来像全文"的文本。

重点覆盖四个问题（题面原文）：

- **提得全**：正文、图表题注、脚注与参考文献逐字提取，不漏行、不丢段，不把页眉页脚混进正文。
- **排得对**：双栏 / 多栏 / 跨栏 / 跨页内容按原版面顺序输出，不串栏、不错行、不把相邻段落拼成一句。
- **拆得清**：章节层级、表格行列与单元格归属、公式上下标与希腊字母还原成可继续处理的结构。
- **核得回**：每段文字、每张表格都能指回原文页码与区块；读不出的部分如实标注，不靠猜补齐。

图表与公式按**结构元素**识别，不要求理解其科学含义。允许聚焦一种版式或一个问题，不要求开发完整 PDF 解析系统。

本 Skill 在 DeepSeek Harness 中被加载到 `/skills/weekly-skill`。
Harness 会在 3 个固定科研案例上分别调用它；每个案例的输入是
`/input/case.json`（含 `task_instruction` 与 `output_contract`）、`task.md`
与同目录下的科研材料（可能是真实 PDF，且**没有预先抽取的答案层**）。

## 任务要求（来自题面）

1. 先识别输入材料（PDF / 文本 / 表格 / 图注）与任务边界，读取实际文件，不依据文件名或领域标签臆测内容。
2. 逐字提取正文，修正双栏/多栏阅读顺序，分离页眉、页脚、边注与正文。
3. 识别章节层级（标题、摘要、各节、参考文献）并保留编号与顺序。
4. 解析表格的行、列、合并单元格与多层表头，给出单元格级定位；跨页续表要合并并标注来源页。
5. 记录公式编号与原文对照，保留上下标、希腊字母与特殊符号。
6. 定位图与表及其题注，标出所在页码/区块；图内文字读不出时不要猜测。
7. 对未报告、无法判断、材料冲突和 OCR 不确定项明确说明。

本题可预知的契约键（来自题面「Skill 运行后的输出要求」，另有部分键按**同赛道兄弟题的公开接口推断**；**实际以运行时 `/input/case.json` 为准**，下表仅供预热）：

- `case_id`
- `case_identifiers`
- `sections`
- `text_blocks`
- `tables`
- `figures`
- `formulas`
- `claims`
- `evidence`
- `coverage`
- `status`
- `uncertainties`

题面只规定了输出内容的四类要求（解析结果、证据与边界、运行状态、输入标识），没有规定固定的 JSON 键名；因此**不要硬编码**，按运行时契约键名语义填充。

## 交付物

result.json（契约齐全）、run-review.md（证据索引 + 不确定性清单）、anomaly-report.json（异常自报，输入提供 `target-fields.json` 时）。

交付物的**内容契约**由运行时 `output_contract` 决定（见下）；下面「交付物落盘
要求」给出的是必须真实存在的**文件**。

## 执行方式

入口脚本：`scripts/sk_entry.py`。它会读取 `/input`，产出 `/app/output/result.json`。

```bash
# 在案例环境中执行（Harbor 会自动调用；手动复现同一条命令）
python /skills/weekly-skill/scripts/sk_entry.py \
  --input /input --work /app/work --out /app/output
```

执行结束后必须存在且可解析：

- `/app/output/result.json` —— 契约字段齐全的最终结果
- `/app/output/run-review.md` —— 人类可读的证据索引与不确定性清单（复核用）

### 两阶段工作流（重要：脚本只做取证，判断由你做）

脚本是**确定性**的：它读材料、切段落、建证据索引、按契约键名填字段。它**不做**
领域判断 —— 哪些文字块该归入哪一节、表格单元格怎么归属、公式编号怎么对应、
交付物该说什么，这些必须由你（执行 Agent）来做。所以本 Skill 的完整用法是
**跑两次**：

```bash
# 阶段 A：脚本取证，产出结果骨架 + 任务单
python /skills/weekly-skill/scripts/sk_entry.py \
  --input /input --work /app/work --out /app/output

# 阶段 B：你读 /app/work/agent_tasks.json，写 /app/work/agent_judgement.json

# 阶段 C：脚本再跑一次，把你的判断校验后合并进 result.json
python /skills/weekly-skill/scripts/sk_entry.py \
  --input /input --work /app/work --out /app/output
```

> **重跑前先移走阶段 A 的 `result.json`**（例如
> `mv /app/output/result.json /app/work/phase-a-result.json`）。脚本会优先采纳
> 旧 `result.json` 里已有的契约键；若不先移走，你通过 `contract_fields` 写入的
> 领域内容会被阶段 A 的骨架覆盖。

**阶段 A 之后**，`/app/work/agent_tasks.json` 会告诉你：

| 字段 | 内容 |
|---|---|
| `contract_keys` / `contract_semantics` | 本案例的契约键，以及每个键该装什么 |
| `evidence_anchors` | 全部段落 id + 原文短引（你的证据只能从这里取） |
| `draft_claims` / `open_questions` | 脚本机械抽到的候选论断与待答问题 |
| `what_to_judge` | 本题需要你判断的四件事 |
| `how_to_write_the_judgement` | 判断文件的结构与规则 |

**阶段 B** —— 有两种写法，**任选其一**：

**(a) 写判断文件**（推荐，校验最严格）—— `/app/work/agent_judgement.json`：

```json
{
  "case_id": "必须与 case.json 一致",
  "claims": [
    {"text": "你判断为结论的陈述",
     "evidence": [{"paragraph_id": "P002", "quote": "原文里逐字出现的片段"}]}
  ],
  "answers": [
    {"question": "被问的问题", "answer": "你的回答",
     "evidence": [{"paragraph_id": "P002", "quote": "原文里逐字出现的片段"}]}
  ],
  "deliverable": "本题最终交付物的正文",
  "contract_fields": {"契约键名": "该键的内容（可选，直接填契约键）"},
  "uncertainties": [
    {"kind": "machine_readable_category", "item": "具体对象",
     "detail": "客观描述", "resolution": "你做了什么或为何无法继续"}
  ]
}
```

**(b) 直接写 `/app/output/result.json`** —— 也支持，脚本会把你写进去的契约键
**取出来**（先留底，再合并），同样过引文校验。你的 `result.json` 不会被覆盖。

> 两种写法都会被采纳；**不要**两个都不做 —— 那就只剩机械抽取，`status` 停在 `partial`。

**阶段 C 的校验闸门（脚本强制执行）**：

- 每条 `quote` 必须能在材料原文里**逐字找回**（允许空白差异）—— 找不到就**退回**，
  并把退回理由写进 `uncertainty`；
- 每条 claim / answer 必须至少有一个证据锚点 —— 没有锚点的条目被退回；
- `contract_fields` 的值不能是 `null` 或空容器 —— 空值被退回；
- 被退回的条目**不会**进入最终结果，脚本保留自己的确定性抽取作为兜底。

> 判断可以自由，**证据不可以自由**。这条闸门是本 Skill 的可信度基础。

只有完成阶段 B，脚本才会把 `status` 从 `partial` 升到 `answered`；否则结果里的
`uncertainty` 会保留一条 `judgement_pending`，如实说明"只做了机械抽取，尚未判断"。

### 脚本职责

| 脚本 | 职责 |
|---|---|
| `scripts/sk_entry.py` | 入口：定位输入、发现材料、执行 `topic.run()`、装配 `result.json`、自检并写复核产物 |
| `scripts/sk_base.py` | 公共库：契约解析、材料发现、证据构造、结果装配、自检工具 |
| `scripts/topic.py` | 题目逻辑：读材料 → 建证据索引 → 按契约键名语义产出字段 → 校验并合并你的判断 |
| `scripts/specialize.py` | reading / writing 引擎：逐 `field_id` 抽取（四态状态）；可编辑稿件 + 改动记录 + 来源映射 |
| `scripts/artifacts.py` | graphics 引擎：实体—连接—步骤 IR → 分层 SVG → 渲染 PNG + 来源记录 |
| `scripts/pptxgen.py` | slides 引擎：stdlib-only 真实 PPTX + 逐页 SVG/PNG + 独立讲稿备注 |

**这些引擎会真的写文件。** 每条赛道具体落盘哪些文件、每个文件里有什么、
如何回挂到契约键，见 `references/artifact-pipeline.md`。

### 运行时契约是唯一权威

`output_contract` **只在运行时可见**（`/input/case.json`）。
不要硬编码任何字段名，也不要凭题面示例臆造字段：

1. 读取 `/input/case.json` 的 `output_contract`；
2. 对每个契约键，按**键名语义**判断它应该承载什么（证据 / 结论 / 不确定性 /
   交付物 / 覆盖度 / 变更记录 …）；
3. 产出对应内容，**不允许**留下 `null` 或"未产出"占位；
4. 若该键确实无法从材料得出，填入结构化的"无法判断"条目（带 `kind`、`item`、
   `detail`、`resolution`），而不是留空。

## 交付物落盘要求

除 `result.json` 外，**可编辑的交付物源文件与其渲染预览必须真实存在**：

| 赛道 | 必须落到 `/app/output` 的文件 |
|---|---|
| reading | `result.json`（契约齐全的结构化结果） |
| reading | `run-review.md`（证据索引 + 不确定性清单） |
| reading | `answers[]` / `target_fields[]`：若输入提供 `target-fields.json`，则逐 `field_id` 一项，状态取 `reported` / `not_reported` / `source_conflict` / `extraction_failed` |
| reading | `anomaly-report.json` —— 异常自报：各状态计数、逐条异常原因、正文与表格取值冲突、每个取值的表格行列定位 |

平台提供的 `office-renderer` / `pdf-render-tool` / `latex-compiler` 可用来渲染预览。
**只有规格描述、没有真实文件，等于没交付** —— 评审要打开文件看。

### 导出前合规检查（pre-export compliance）

导出件落盘后，本 Skill 会**自动核对**并在 `*-export-checks.json` 里留档，
让评审不必逐个打开文件猜：

| 检查维度 | 记什么 |
|---|---|
| 目标格式 | 期望的 SVG / PNG / PDF 是否齐全、各自字节数、是否是**真矢量** |
| 画布与分辨率 | 像素尺寸 → pt → mm 换算，实测 dpi，目标 dpi |
| 字体 | 字体清单、嵌入情况、中文回退策略、是否存在方框/缺字风险 |
| 色彩空间 | 色彩空间标注（sRGB 等）与是否有嵌入配置 |
| 线宽 / 分层 | 线宽是否过细、图层是否可拆、图层清单 |
| 数据一致性 | 图上出现的数值与源数据表的比对结果 |
| 讲稿隔离 | 备注文字是否混进页面文字（逐页最大重叠片段） |
| 人工确认 | 需人眼确认的项一律标 `pending_human_review`，**不代签** |

失败的检查项会**原样保留为 fail**，不会被改写成通过；不可用的工具（如运行时
没有矢量转换器或 LibreOffice）也如实记为 `unavailable`，不做假成功。

## 质量红线

- **逐字提取**：正文、题注、脚注、参考文献按原文输出，不改写、不润色、不合并句子。
- **阅读顺序**：双栏/多栏按原版面顺序输出；不串栏、不错行、不把相邻段落拼成一句。
- **页眉页脚隔离**：页眉、页脚、边注、页码不混进正文；确需保留时标注其版式角色。
- **表格到单元格级**：给出表 id + 行号 + 列名 + 单元格原文；合并单元格与多层表头说明归属；跨页续表合并并标注来源页。
- **公式保真**：保留上下标、希腊字母与特殊符号；按公式编号给出原文对照，不擅自转写语义。
- **图表可定位**：每张图/表给出所在页码或区块与题注原文；图内文字无法读取时标注为不可读。
- **扫描件**：OCR 结果标注为推断并保留置信/失败说明；无文字层时 `status=unsupported`，不伪造文本。
- 每条 claim 都有 paragraph_id + 原文 quote。

通用红线（违反即失分）：

- **不编造**：材料没有的数字、引用、图表、方法、结论，一律不写。写不出来就进
  `uncertainty`，并在 `status_reason` 里说明。
- **可回溯**：每条结论必须能指回原文的段落 id 与短引；引文必须是原文片段，
  不做改写、不做拼接。
- **不提前交卷**：材料可能读不全。若只读到部分文件，`status` 应为 `partial`，
  并在 `coverage.not_read` 写明未读的部分。
- **不自评**：不要在结果里写"质量良好""得分很高"这类自评语句。

## 失败与边界

| 情况 | 正确处理 |
|---|---|
| 材料是扫描件、无文本层 | 用 `scripts/sk_base.py` 的 PDF 解析；仍无文本则 `status=unsupported` 并在 `uncertainty` 写明"无文本层" |
| 材料是图片/图表 | 用平台提供的 `pdf-render-tool` / `ocr-tool`；OCR 结果标注为推断 |
| 材料格式未知 | 记录文件路径与可读性，不猜测内容 |
| 契约键无法解读 | 产出该键的结构化说明而非空值，并记录在 `uncertainty` |

详见 `references/failure-modes.md` 与 `references/evidence-discipline.md`。

## 自检

`result.json` 写完后由 `scripts/sk_entry.py` 自动自检（结构、契约覆盖、
证据完整性）。自检失败时以 `partial` 提交并在 `status_reason` 写明原因，
不要伪造 `answered`。

除自动自检外，人工复核以下各项：章节层级是否连续、表格单元格是否可归属、
公式编号是否齐全、图表是否都有题注定位、页眉页脚是否已隔离、未读部分是否
写入 `coverage.not_read`。

```bash
python /skills/weekly-skill/scripts/sk_selftest.py --input /input
```

## 参考

- `references/evidence-discipline.md` —— 证据与不确定性纪律
- `references/contract-handling.md` —— 运行时契约的读法与字段语义表
- `references/two-phase-workflow.md` —— 两阶段工作流协议与校验闸门
- `references/failure-modes.md` —— 常见失败模式与正确退路
- `references/artifact-pipeline.md` —— 每条赛道真实落盘哪些文件、怎么回挂契约键
- `assets/result-schema.md` —— `result.json` 的字段说明
- `assets/policy.json` —— 不编造承诺与来源声明
- `examples/demo-case/` —— 一个可离线复现的最小案例
