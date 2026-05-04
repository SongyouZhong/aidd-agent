# AIDD Agent Platform — Backend

> 基于 LangGraph ReAct 架构的 AI 驱动药物研发 (AIDD) 智能体后端，支持多轮对话、动态工具检索、子代理委托和自动上下文压缩。

## 目录

- [架构概览](#架构概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速启动](#快速启动)
  - [1. 前置条件](#1-前置条件)
  - [2. 启动中间件](#2-启动中间件)
  - [3. 初始化数据库](#3-初始化数据库)
  - [4. 配置环境变量](#4-配置环境变量)
  - [5. 安装 Python 环境](#5-安装-python-环境)
  - [6. 启动后端服务](#6-启动后端服务)
- [API 使用指南：完整对话流程](#api-使用指南完整对话流程)
  - [Step 1: 注册用户](#step-1-注册用户)
  - [Step 2: 登录获取 Token](#step-2-登录获取-token)
  - [Step 3: 创建会话](#step-3-创建会话)
  - [Step 4: 发送消息 & 获取回复](#step-4-发送消息--获取回复)
  - [Step 5: 会话管理](#step-5-会话管理)
- [离线模式 & 在线模式](#离线模式--在线模式)
- [内置工具](#内置工具)
- [运行测试](#运行测试)
- [开发调试工具](#开发调试工具)
  - [LangGraph Studio — 可视化 Agent 执行](#langgraph-studio--可视化-agent-执行)
  - [LangSmith — 执行追踪](#langsmith--执行追踪)
- [API 文档](#api-文档)

---

## 架构概览

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────────────────────┐
│   Frontend   │───▶│  FastAPI      │───▶│  LangGraph ReAct Agent           │
│  (REST API)  │◀───│  + JWT Auth   │◀───│  ┌─────────┐    ┌──────────┐    │
└──────────────┘    └──────┬───────┘    │  │ agent   │───▶│  tool    │    │
                           │            │  │  node   │◀───│  node    │    │
                    ┌──────┴───────┐    │  └────┬────┘    └──────────┘    │
                    │  Storage      │    │       │ no tool calls           │
                    │  ┌─────────┐  │    │  ┌────▼────┐                    │
                    │  │ Redis   │  │    │  │finalize │ → citations        │
                    │  │ (hot)   │  │    │  └─────────┘                    │
                    │  ├─────────┤  │    └──────────────────────────────────┘
                    │  │SeaweedFS│  │
                    │  │ (cold)  │  │           ┌───────────────────┐
                    │  ├─────────┤  │           │  Subagent         │
                    │  │Postgres │  │           │  (deep_research)  │
                    │  │ (meta)  │  │           │  isolated state   │
                    │  └─────────┘  │           └───────────────────┘
                    └──────────────┘
```

**核心特性：**
- **ReAct 循环**：Agent → Tool → Agent → ... → Finalize，支持多轮工具调用
- **动态工具检索 (Hot-loading)**：通过 `tool_search` 按需挂载 Deferred 工具
- **Agent-Tool 二元性**：子代理 (`deep_research_agent`) 作为工具被父代理调用，状态完全隔离
- **自动上下文压缩 (Auto-Compaction)**：两级策略 — Session Memory 快速压缩 + LLM 深度摘要
- **混合存储**：Redis 热缓存 + SeaweedFS 冷归档 + PostgreSQL 元数据
- **Gemini Grounding**：自动注入引用标记 `[N]` 和参考文献列表

---

## 技术栈

| 层级 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn |
| Agent 编排 | LangGraph + LangChain Core |
| LLM 提供者 | Google Gemini (`google-genai`) / 离线 FakeLLM |
| 数据库 | PostgreSQL 16 (用户/会话元数据) |
| 缓存 | Redis 7 (消息热缓存) |
| 对象存储 | SeaweedFS S3 (消息冷归档 + 原始工具输出) |
| 迁移 | Alembic |
| 认证 | JWT (python-jose + passlib/bcrypt) |
| 开发调试 | LangGraph Studio + LangSmith |

---

## 项目结构

```
aidd-agent-backend/
├── app/
│   ├── main.py                    # FastAPI 应用入口
│   ├── core/
│   │   ├── config.py              # Pydantic Settings（.env 加载）
│   │   ├── security.py            # JWT 签发/验证
│   │   └── exceptions.py          # 自定义异常
│   ├── api/
│   │   ├── auth.py                # POST /register, /login, GET /me
│   │   ├── sessions.py            # Session CRUD
│   │   └── deps.py                # 依赖注入 (get_current_user)
│   ├── agent/
│   │   ├── agent.py               # LangGraph ReAct 图定义 + run_once()
│   │   ├── graph.py               # LangGraph Studio 入口（module-level graph）
│   │   ├── llm_provider.py        # GeminiProvider / FakeLLMProvider
│   │   ├── subagent.py            # Agent-Tool Duality (deep_research_agent)
│   │   ├── context_manager.py     # Auto-Compaction + Circuit Breaker
│   │   ├── prompt_renderer.py     # Jinja2 系统提示渲染
│   │   ├── citations.py           # Gemini Grounding → [N] 引用注入
│   │   └── prompts/templates.py   # System / Compact 提示模板
│   ├── tools/
│   │   ├── registry.py            # Core/Deferred 工具注册表
│   │   ├── search_tool.py         # tool_search（动态工具发现）
│   │   ├── literature.py          # query_pubmed, query_arxiv (Core)
│   │   ├── database.py            # query_uniprot, query_chembl (Deferred)
│   │   ├── preprocess.py          # guarded_tool 输出截断
│   │   ├── schemas.py             # Paper / Protein / Molecule 数据模型
│   │   ├── base.py                # REST API 通用查询辅助
│   │   └── mapreduce.py           # MapReduce 风格结果聚合
│   ├── storage/
│   │   ├── manager.py             # 混合存储管理 (Redis + S3)
│   │   ├── redis_client.py        # Redis 连接管理
│   │   └── s3.py                  # SeaweedFS S3 异步客户端
│   ├── models/                    # SQLAlchemy ORM 模型
│   ├── schemas/                   # Pydantic 请求/响应模型
│   ├── services/                  # 业务逻辑层
│   └── db/                        # SQLAlchemy 引擎 & Base
├── alembic/                       # 数据库迁移
├── scripts/                       # 冒烟测试脚本 (Phase 2-5)
├── docs/                          # 设计文档
├── langgraph.json                 # LangGraph Studio / CLI 配置
├── docker-compose.yml             # 中间件 (PG + Redis + SeaweedFS)
├── environment.yml                # Conda 环境定义
└── .env.example                   # 环境变量模板
```

---

## 快速启动

### 1. 前置条件

- **Docker & Docker Compose** (中间件)
- **Conda / Mamba** (Python 环境管理)
- **可选**: Gemini API Key（没有也可以使用离线模式）

### 2. 启动中间件

```bash
cd aidd-agent-backend

# 启动 PostgreSQL、Redis、SeaweedFS（后台运行）
docker compose up -d
```

验证服务状态：
```bash
docker compose ps
# 应看到 5 个容器全部 Up:
#   aidd-postgres, aidd-redis,
#   aidd-seaweedfs-master, aidd-seaweedfs-volume,
#   aidd-seaweedfs-s3, aidd-seaweedfs-filer
```

### 3. 初始化数据库

```bash
# 初始化 SeaweedFS 存储桶
PYTHONPATH=. python scripts/init_seaweedfs_bucket.py

# 运行数据库迁移（创建 users / sessions 表）
alembic upgrade head
```

### 4. 配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，配置关键参数：
#   - GEMINI_API_KEY=your-key-here    ← 不填则使用离线模式
#   - 其他参数保持默认即可
```

**可选：配置 LangSmith 追踪**（在 `.env` 中追加，开发调试时推荐开启）：

```bash
# LangSmith tracing (dev only) — https://smith.langchain.com 免费注册
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=aidd-agent-dev
```

### 5. 安装 Python 环境

```bash
# 使用 conda/mamba 创建环境
conda env create -f environment.yml
conda activate aidd-agent

# 或者使用 mamba（更快）
mamba env create -f environment.yml
mamba activate aidd-agent
```

### 6. 启动后端服务

```bash
# 开发模式启动（自动重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 访问 API 文档：http://localhost:8000/api/v1/docs
# 健康检查：    http://localhost:8000/health
```

---

## API 使用指南：完整对话流程

以下演示使用 `curl` 完成 **注册 → 登录 → 创建会话 → 发送消息 → 获取回复** 的完整流程。

### Step 1: 注册用户

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "researcher", "password": "my_secure_password"}'
```

响应示例：
```json
{
  "access_token": "eyJhbGciOiJI...",
  "token_type": "bearer",
  "user": {
    "id": "a1b2c3d4-...",
    "username": "researcher",
    "created_at": "2026-05-02T12:00:00Z"
  }
}
```

### Step 2: 登录获取 Token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "researcher", "password": "my_secure_password"}'
```

> **保存返回的 `access_token`**，后续所有请求都需要在 Header 中携带。

```bash
# 设置环境变量便于后续使用
export TOKEN="eyJhbGciOiJI..."
```

### Step 3: 创建会话

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"title": "EGFR 靶点研究"}'
```

响应示例：
```json
{
  "id": "d5e6f7a8-...",
  "title": "EGFR 靶点研究",
  "created_at": "2026-05-02T12:01:00Z",
  "updated_at": "2026-05-02T12:01:00Z"
}
```

### Step 4: 发送消息 & 获取回复

当前版本使用 Python SDK 直接调用 Agent，示例代码如下：

```python
import asyncio
from app.agent.agent import run_once
from app.agent.llm_provider import get_default_provider
from app.agent.subagent import make_deep_research_tool

async def chat(question: str, session_id: str = None):
    """发送一条消息并获取 Agent 回复。"""
    provider = get_default_provider()

    # 可选：挂载深度研究子代理
    deep_tool = make_deep_research_tool(session_id=session_id)

    state = await run_once(
        provider,
        question,
        extra_tools={"deep_research_agent": deep_tool},
        session_id=session_id,
    )

    print("=== Agent 回复 ===")
    print(state["final_text"])
    print("\n=== 引用 ===")
    for c in state.get("citations", []):
        print(f"  [{c.index}] {c.title} — {c.url}")

    return state

# 运行
asyncio.run(chat("EGFR T790M 突变与第三代 TKI 耐药的关系是什么？"))
```

也可以直接运行内置的冒烟测试来验证完整的 Agent 循环：

```bash
# Phase 4: Prompt + ReAct + 工具调用 + 引用注入（离线，无需 API Key）
PYTHONPATH=. python scripts/smoke_phase4.py

# Phase 5: 子代理 + 自动压缩 + 熔断器（离线，无需 API Key）
PYTHONPATH=. python scripts/smoke_phase5.py
```

### Step 5: 会话管理

```bash
# 列出所有会话
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/sessions

# 重命名会话
curl -X PATCH http://localhost:8000/api/v1/sessions/{session_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"title": "EGFR 抑制剂综述 v2"}'

# 删除会话
curl -X DELETE http://localhost:8000/api/v1/sessions/{session_id} \
  -H "Authorization: Bearer $TOKEN"
```

---

## 离线模式 & 在线模式

| 模式 | 条件 | 行为 |
|---|---|---|
| **在线模式** | `.env` 中设置了 `GEMINI_API_KEY` | 使用 Gemini API，支持 Google Search Grounding 和引用注入 |
| **离线模式** | 未设置 `GEMINI_API_KEY` 或设置 `AIDD_FORCE_FAKE_LLM=1` | 使用 `FakeLLMProvider` 返回预设回复，适合开发调试和测试 |

切换到强制离线模式：
```bash
AIDD_FORCE_FAKE_LLM=1 uvicorn app.main:app --reload
```

---

## 内置工具

| 工具名 | 类型 | 说明 |
|---|---|---|
| `tool_search` | 常驻 | 动态检索 Deferred 工具，返回匹配工具的 schema |
| `query_pubmed` | Core | 搜索 PubMed 生物医学文献 |
| `query_arxiv` | Core | 搜索 arXiv 预印本 |
| `query_uniprot` | Deferred | 查询 UniProt 蛋白质知识库 |
| `query_chembl` | Deferred | 查询 ChEMBL 化合物生物活性数据 |
| `deep_research_agent` | 子代理 | 启动隔离的深度研究子代理，跨多个数据库交叉比对 |

> **Core 工具**始终在 System Prompt 中可用；**Deferred 工具**需要通过 `tool_search` 发现后动态挂载。

---

## 运行测试

```bash
# 确保中间件已启动
docker compose up -d

# Phase 2: Auth + Session CRUD + 混合存储（需要中间件）
PYTHONPATH=. python scripts/smoke_phase2.py

# Phase 3: 工具注册表 + 文献/数据库查询
PYTHONPATH=. python scripts/smoke_phase3.py

# Phase 4: Prompt 渲染 + ReAct 循环 + 引用注入（离线）
PYTHONPATH=. python scripts/smoke_phase4.py

# Phase 5: 子代理 + 自动压缩 + 熔断器（离线）
PYTHONPATH=. python scripts/smoke_phase5.py
```

---

## 开发调试工具

### LangGraph Studio — 可视化 Agent 执行

[LangGraph Studio](https://github.com/langchain-ai/langgraph-studio) 提供图形化界面，可实时查看每个 Graph 节点的输入/输出、tool call 参数，以及手动修改 input state 后触发执行，适合调试 prompt 和工具调用链。

```bash
# 安装 CLI（一次性）
pip install langgraph-cli

# 在项目根目录启动 Studio（需要 LANGCHAIN_API_KEY）
cd aidd-agent-backend
conda activate aidd-agent
langgraph dev --no-reload
```

浏览器访问终端输出的 URL（默认 `http://localhost:2024`）。

**Studio 使用说明：**
- 左侧面板选择 `agent` 图，可见 `START → agent → tool → finalize → END` 流程
- 在 **Input** 区域编辑 JSON state，修改 `messages`、`session_memory` 等字段后点 Submit 触发执行
- 右侧面板实时展示每个节点的完整输入输出（含 system prompt 和 tool call 详情）
- 支持从任意中间节点重放（Human-in-the-loop）

**示例 Input JSON：**

```json
{
  "messages": [{"type": "human", "content": "Find recent papers on TDP-43 and ALS"}],
  "session_memory": "",
  "hot_loaded": []
}
```

项目已配置好 `langgraph.json`，其入口指向 `app/agent/graph.py:graph`（使用 `GeminiProvider` 的 module-level 编译图）。

---

### LangSmith — 执行追踪

配置好 `.env` 中的 `LANGCHAIN_TRACING_V2` 和 `LANGCHAIN_API_KEY` 后，每次 agent 运行（包括通过 API 和 Studio 触发的）都会**自动**上传追踪数据到 [LangSmith](https://smith.langchain.com)，无需修改任何代码。

LangSmith Dashboard 提供：
- 完整的 LLM 调用历史（含 prompt / completion / token 用量）
- 每次 tool call 的名称、入参、返回值和耗时
- 跨会话的执行历史对比

---

## API 文档

启动服务后访问自动生成的交互式 API 文档：

- **Swagger UI**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **健康检查**: [http://localhost:8000/health](http://localhost:8000/health)

---

## License

Internal project — AIDD Agent Platform.
