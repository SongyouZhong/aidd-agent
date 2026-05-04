# TDP-43 × 阿尔茨海默症 Agent 测试方案

## 背景

TDP-43（TAR DNA-binding protein 43）是一个 RNA/DNA 结合蛋白，最初作为 ALS/FTLD 的标志性病理蛋白被发现，但近年大量研究表明其在阿尔茨海默症（AD）中也扮演重要角色。据估计，约 25-50% 的 AD 患者脑中可检测到 TDP-43 病理（称为 LATE — Limbic-predominant Age-related TDP-43 Encephalopathy）。

这使得 "TDP-43 × AD" 成为一个理想的 Agent 测试问题：
- **跨学科**：涉及分子生物学、神经病理学、遗传学、药物化学
- **多数据库交叉**：需要 PubMed + UniProt + ChEMBL + arXiv
- **知识前沿**：LATE 分类系统在 2019 年才正式提出，测试 Agent 是否能检索最新文献
- **可验证**：关键结论有明确的 PMID/DOI 可追溯

## 测试目标

1. **功能验证**：Agent 的 ReAct 循环、工具调用、hot-loading 是否正常工作
2. **科学质量**：回答的准确性、完整性、可溯源性
3. **方案对比**：同一复合策略下 3 种不同方案的表现差异
4. **过程可追溯**：完整记录 Agent 每一步的处理过程，确保可复现和可审计

> [!NOTE]
> **固定模型**：所有测试统一使用 `gemini-3.1-pro-preview` 模型。

---

## 执行过程全量追踪 (Execution Tracing)

> [!IMPORTANT]
> 测试脚本会记录 Agent 执行的 **每一个步骤**，包括所有中间过程和工具返回的原始数据，确保实验完全可复现。

### 追踪的事件类型

| 事件类型 | 记录内容 | 说明 |
|---------|---------|------|
| `LLM_REQUEST` | System Prompt、用户消息、历史上下文、传入的 tool schemas | 每次调用 LLM 前的完整输入 |
| `LLM_RESPONSE` | 模型回复全文（含 `<thought>` + `<answer>`）、tool_calls 列表、grounding_metadata | 模型的完整输出 |
| `TOOL_CALL` | 工具名称、输入参数 | Agent 决定调用哪个工具 |
| `TOOL_RESULT` | 工具返回的完整内容（PubMed 论文列表、UniProt 蛋白表、ChEMBL 分子表等） | 工具的原始输出 |
| `TOOL_SEARCH` | 搜索 query、匹配到的 deferred tools 列表 | tool_search 的详情 |
| `HOT_LOAD` | 新挂载的工具名称 | 动态加载事件 |
| `SUBAGENT_START` | 子代理的 trace_id、任务描述 | 子代理启动 |
| `SUBAGENT_END` | 子代理的完整 sidechain transcript（所有轮次） | 子代理执行全过程 |
| `COMPACTION` | 压缩前后的 message 数量和 token 数、摘要内容 | Auto-Compaction 事件 |
| `CITATION` | 注入的引用列表、grounding chunks | 引用注入详情 |
| `ERROR` | 异常类型、堆栈信息 | 任何异常 |

### 实现方式 — TracingProvider 包装器

通过 `TracingProvider` 包装 `GeminiProvider`，拦截 `generate()` 调用记录输入输出；同时 monkey-patch `_execute_tool_call` 记录工具调用过程。每次运行产出：
- `*.json` — 机器可读的完整 trace（含所有搜索结果原文）
- `*_trace.md` — 人类可读的分步执行日志

---

## 复合测试策略：3 种方案

> 围绕同一个核心科学问题（TDP-43 × AD），设计 3 种**复杂度递增**的方案，对比 Agent 在不同工作模式下的表现。

### 共同的研究主题

```
核心问题：TDP-43 蛋白在阿尔茨海默症发病机制中的角色
覆盖维度：
  - TDP-43 的正常生理功能与结构
  - TDP-43 在 AD 脑中的病理表现（磷酸化、截断、聚集）
  - TDP-43 病理与 Tau/Amyloid-β 病理的交互作用
  - LATE（边缘系统为主的年龄相关 TDP-43 脑病）的概念及分期
  - 潜在的治疗靶点和药物开发方向
```

---

### 方案 A：多工具 ReAct 链式推理（单轮 · 主 Agent 独立完成）

> **核心测试点**：Agent 的工具编排能力 — 能否在一轮对话中自主发现并调用多个数据源

```
Prompt: "我在研究 TDP-43 与阿尔茨海默症的关系。请帮我：
1. 搜索 PubMed 找到该领域的关键综述文章
2. 查询 UniProt 获取 TDP-43 (TARDBP) 的蛋白功能信息
3. 在 ChEMBL 中搜索是否有针对 TDP-43 的小分子化合物
4. 在 arXiv 搜索最新的 AI/ML 在 TDP-43 相关疾病中的应用

最后综合以上信息，给出一份结构化分析报告。"
```

**预期行为**：
- Agent 依次调用 4 个工具
- 先用 core 工具（`query_pubmed`, `query_arxiv`），再通过 `tool_search` hot-load `query_uniprot` 和 `query_chembl`
- 最终产出结构化多节报告

**评估重点**：
- 工具调用次序是否合理
- hot-loading 是否正确触发
- 信息是否正确综合（不混淆不同来源）
- 报告结构和引用质量

---

### 方案 B：Deep Research 子代理（单轮 · 委派给子代理）

> **核心测试点**：Agent-Tool Duality — 子代理能否独立完成深度研究并正确回传结果

```
Prompt: "请启动深度研究子代理，全面调查 TDP-43 在阿尔茨海默症发病机制中的角色，
包括：
- TDP-43 的正常生理功能
- TDP-43 在 AD 脑中的病理表现（磷酸化、截断、聚集）
- TDP-43 病理与 Tau/Amyloid-β 病理的交互作用
- LATE（边缘系统为主的年龄相关 TDP-43 脑病）的概念及分期
- 潜在的治疗靶点和药物开发方向

需要交叉比对至少 PubMed 和 UniProt 的数据。"
```

**预期行为**：
- 父 Agent 调用 `deep_research_agent` 工具
- 子 Agent 独立完成多轮检索（sidechain transcript 完整记录）
- 子 Agent 结果通过 ToolMessage 返回，父 Agent 整合并注入引用

**评估重点**：
- 子代理是否独立完成研究（检查 sidechain transcript）
- 父 Agent 是否正确整合子代理结果
- 整体执行时间是否在 5min timeout 内
- 引用链的完整性

---

### 方案 C：多轮渐进式探索（5 轮对话 · 模拟真实研究流程）

> **核心测试点**：多轮上下文保持 + Auto-Compaction + 渐进深入能力

```
Turn 1: "TDP-43 是什么蛋白？它的主要功能是什么？"
Turn 2: "这个蛋白在哪些神经退行性疾病中有病理作用？"
Turn 3: "特别是在阿尔茨海默症中，TDP-43 的具体病理机制是什么？"
Turn 4: "LATE 是什么概念？与传统 AD 有什么区别？"
Turn 5: "基于以上讨论，有哪些针对 TDP-43 的药物研发策略？请引用最新的文献。"
```

**预期行为**：
- 前几轮积累上下文，后续轮次基于之前的知识深入
- 如果 token 数接近阈值，Auto-Compaction 应触发
- Session Memory 应保留关键信息

**评估重点**：
- 上下文是否在多轮间正确保持
- 是否有不必要的重复搜索
- Auto-Compaction 触发后是否丢失关键信息
- 最后一轮的总结质量

---

### 3 种方案对比维度

| 维度 | 方案 A（多工具） | 方案 B（子代理） | 方案 C（多轮） |
|------|----------------|-----------------|---------------|
| 工具编排 | ⭐⭐⭐ 主要测试点 | ⭐ 由子代理处理 | ⭐⭐ 分散在各轮 |
| 深度研究 | ⭐⭐ 单次检索 | ⭐⭐⭐ 主要测试点 | ⭐⭐ 渐进积累 |
| 上下文管理 | ⭐ 单轮无需 | ⭐ 子代理隔离 | ⭐⭐⭐ 主要测试点 |
| 执行时间（预估） | ~30-60s | ~60-180s | ~120-300s |
| API 调用量 | 中等 | 较多 | 最多 |

---

## 评分标准 (Scoring Rubric)

### 科学准确性 (0-10)
- **9-10**: 所有关键事实正确，引用最新文献 (2020+)，提到 LATE
- **7-8**: 大部分事实正确，少量过时信息
- **5-6**: 基本框架正确但缺乏深度
- **3-4**: 存在明显事实错误
- **0-2**: 大量错误或完全离题

### 引用质量 (0-10)
- **9-10**: 每个关键结论都有 PMID/DOI，引用真实可查
- **7-8**: 多数结论有引用，偶有格式问题
- **5-6**: 有部分引用但不够系统
- **0-2**: 无引用或全部无法验证

### 工具使用 (0-10)
- **9-10**: 策略精准，先 PubMed 后 hot-load 数据库，无冗余调用
- **7-8**: 工具使用合理但有 1-2 次冗余
- **5-6**: 基本能用对工具但策略不够高效
- **0-2**: 未使用工具或使用完全错误

---

## 实现方案

### 测试脚本结构

```
scripts/
  test_tdp43_ad.py          # 主测试入口（TracingProvider + 3 方案执行 + 评估 + 报告）
  results/                  # 测试产出目录（自动创建）
    planA_20260502_180000.json          # 方案 A 的完整 trace
    planA_20260502_180000_trace.md      # 方案 A 的人类可读 trace log
    planB_20260502_181000.json
    planB_20260502_181000_trace.md
    planC_20260502_182000.json
    planC_20260502_182000_trace.md
    tdp43_ad_report.md                  # 最终对比报告
```

### [NEW] [test_tdp43_ad.py](file:///home/songyou/projects/aidd-agent-backend/scripts/test_tdp43_ad.py)

一个完整的测试脚本，包含：

1. **`TraceCollector` 类** — 收集所有执行事件，持久化为 JSON + Markdown
2. **`TracingProvider` 类** — 包装 `GeminiProvider`，拦截并记录每次 `generate()` 的输入输出
3. **`traced_execute_tool_call()` 函数** — 包装 `_execute_tool_call`，记录工具调用的完整输入输出
4. **`run_plan_a/b/c()` 函数** — 3 种方案的具体执行逻辑，自动注入 Tracing
5. **`evaluate_result()` 函数** — 自动化评估
6. **`generate_report()` 函数** — 输出对比表格到 Markdown 文件
7. **CLI 入口** — 支持 `--plan a,b,c` 参数选择运行哪些方案

### 关键实现细节

- **固定模型**：统一使用 `gemini-3.1-pro-preview`
- 使用真实 `GeminiProvider`（非 Fake），直接调用 Gemini API
- 工具调用走真实的 PubMed/arXiv/UniProt/ChEMBL API
- **全量过程记录**：LLM 调用的输入 prompt 和完整响应、工具调用的参数和原始返回结果、hot-loading 事件、子代理 sidechain、Auto-Compaction 事件，全部记录到 trace
- 结果持久化到 `scripts/results/` 目录（JSON trace + Markdown trace log + 对比报告）

### 自动评估指标

| 指标 | 自动检测方式 |
|------|-------------|
| `has_tdp43_mention` | 回答中是否包含 "TDP-43" 或 "TARDBP" |
| `has_late_mention` | 是否提到 "LATE" 或 "Limbic-predominant" |
| `has_tau_interaction` | 是否讨论了 TDP-43 与 Tau 的关系 |
| `citation_count` | 正则匹配 `[PMID:\d+]` 和 `[DOI:...]` 的数量 |
| `tool_call_count` | 统计 ToolMessage 数量 |
| `hot_loaded_tools` | 检查 hot_loaded set 的内容 |
| `response_time_sec` | 端到端执行时间 |
| `answer_length_chars` | 回答字符数 |

---

## 预期输出

运行完成后在 `scripts/results/` 下产出：

| 文件 | 说明 |
|------|------|
| `planA_*.json` | 方案 A 完整 trace（机器可读，含搜索结果原文） |
| `planA_*_trace.md` | 方案 A 分步执行日志（人类可读） |
| `planB_*.json` / `planB_*_trace.md` | 方案 B |
| `planC_*.json` / `planC_*_trace.md` | 方案 C |
| `tdp43_ad_report.md` | 最终 3 方案对比报告 |

对比报告示例：

```
| 方案 | 用时 | LLM调用 | 工具调用 | 引用数 | TDP-43 ✓ | LATE ✓ | 评分 |
|------|------|--------|---------|--------|----------|--------|------|
| A-多工具 | 45s | 4 | 8 | 7 | ✅ | ✅ | 8/10 |
| B-子代理 | 90s | 8 | 14 | 12 | ✅ | ✅ | 9/10 |
| C-多轮 | 180s | 6 | 10 | 8 | ✅ | ✅ | 7/10 |
```

---

## Open Questions

> [!WARNING]
> **API 配额**：方案 B（子代理）和方案 C（5 轮对话）会消耗较多 API 调用。你的 Gemini API key 的 RPM/QPM 限制是多少？是否需要加入 rate limiting？

> [!NOTE]
> **中间件依赖**：方案 B（子代理 sidechain 存档）需要 SeaweedFS；方案 C（多轮）理想情况下需要 PostgreSQL 做持久化。目前它们不是必须的（代码已做 graceful fallback），但如果需要完整测试，是否要启动 `docker-compose up`？

> [!NOTE]
> **执行顺序**：建议按 A → B → C 顺序依次执行，复杂度递增。如果某方案失败不影响后续方案独立运行。

---

## Verification Plan

### Automated Tests
1. `python scripts/test_tdp43_ad.py --plan a` — 先跑方案 A 确保基础流程通畅
2. 依次执行方案 B、C，每个方案独立记录结果
3. 最终生成对比报告

### Manual Verification
- 抽查 3-5 个 PMID 引用，确认文献真实存在
- 检查 TDP-43 相关结论的科学准确性
- 对比 3 种方案的回答质量和过程效率差异
