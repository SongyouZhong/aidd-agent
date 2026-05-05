# AIDD Agent Platform — API 接口文档

> **Base URL**: `http://localhost:8000/api/v1`
> **认证方式**: JWT Bearer Token（除注册/登录外，所有接口均需 `Authorization: Bearer <token>` 请求头）
> **内容类型**: `application/json`（文件上传接口使用 `multipart/form-data`）

---

## 目录

1. [通用说明](#1-通用说明)
2. [认证 API (`/auth`)](#2-认证-api)
3. [会话 API (`/sessions`)](#3-会话-api)
4. [消息 API (`/sessions/{id}/messages`)](#4-消息-api)
5. [文件上传 API (`/files`)](#5-文件上传-api)
6. [靶点发现 API (`/targets`)](#6-靶点发现-api)
7. [追踪 API (`/messages/{id}/traces`)](#7-追踪-api)
8. [流式对话 API (`/chat`) — SSE](#8-流式对话-api--sse)
9. [健康检查](#9-健康检查)
10. [通用错误码](#10-通用错误码)

---

## 1. 通用说明

### 1.1 请求格式

- 所有 REST 请求体使用 JSON，`Content-Type: application/json`
- 文件上传使用 `Content-Type: multipart/form-data`
- 路径参数中的 ID 均为 UUID v4 格式

### 1.2 响应格式

成功响应直接返回资源对象或数组。错误响应统一格式：

```json
{
  "detail": "错误描述信息"
}
```

### 1.3 分页

部分列表接口支持 `limit` / `offset` 查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 50 | 每页数量，最大 100 |
| `offset` | int | 0 | 偏移量 |

### 1.4 认证

除 `/auth/register`、`/auth/login`、`/health` 外，所有接口需要在请求头中携带：

```
Authorization: Bearer <access_token>
```

---

## 2. 认证 API

### 2.1 用户注册

```
POST /api/v1/auth/register
```

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `username` | string | ✅ | 3–64 字符 | 用户名，全局唯一 |
| `password` | string | ✅ | 6–128 字符 | 密码 |

**请求示例：**

```json
{
  "username": "researcher01",
  "password": "securePass123"
}
```

**响应 `201 Created`：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "username": "researcher01",
    "created_at": "2026-05-05T07:00:00Z"
  }
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `409 Conflict` | 用户名已存在 |
| `422 Unprocessable Entity` | 参数校验失败 |

---

### 2.2 用户登录

```
POST /api/v1/auth/login
```

**请求体：** 同注册接口

**响应 `200 OK`：** 同注册接口响应格式

**错误：**

| 状态码 | 说明 |
|--------|------|
| `401 Unauthorized` | 用户名或密码错误 |

---

### 2.3 获取当前用户信息

```
GET /api/v1/auth/me
```

**请求头：** `Authorization: Bearer <token>`

**响应 `200 OK`：**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "username": "researcher01",
  "created_at": "2026-05-05T07:00:00Z"
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `401 Unauthorized` | Token 无效或过期 |

---

## 3. 会话 API

### 3.1 获取会话列表

```
GET /api/v1/sessions
```

**响应 `200 OK`：**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "EGFR 靶点研究",
    "created_at": "2026-05-05T06:00:00Z",
    "updated_at": "2026-05-05T07:00:00Z"
  }
]
```

> 按 `updated_at` 降序排列，仅返回当前用户的会话。

---

### 3.2 创建会话

```
POST /api/v1/sessions
```

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `title` | string | 否 | 最大 255 字符 | 不传则默认 `"新对话"` |

**请求示例：**

```json
{
  "title": "TDP-43 与阿尔茨海默病研究"
}
```

**响应 `201 Created`：**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "TDP-43 与阿尔茨海默病研究",
  "created_at": "2026-05-05T07:00:00Z",
  "updated_at": "2026-05-05T07:00:00Z"
}
```

---

### 3.3 重命名会话

```
PATCH /api/v1/sessions/{session_id}
```

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | UUID | 会话 ID |

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `title` | string | ✅ | 1–255 字符 | 新标题 |

**响应 `200 OK`：** 返回更新后的会话对象

**错误：**

| 状态码 | 说明 |
|--------|------|
| `403 Forbidden` | 非会话拥有者 |
| `404 Not Found` | 会话不存在 |

---

### 3.4 删除会话

```
DELETE /api/v1/sessions/{session_id}
```

**响应 `204 No Content`：** 无响应体

> 同时清除该会话的 Redis 缓存。

**错误：**

| 状态码 | 说明 |
|--------|------|
| `403 Forbidden` | 非会话拥有者 |
| `404 Not Found` | 会话不存在 |

---

## 4. 消息 API

### 4.1 获取会话历史消息

```
GET /api/v1/sessions/{session_id}/messages
```

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | UUID | 会话 ID |

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int | 50 | 返回最近 N 条消息 |

**响应 `200 OK`：**

```json
[
  {
    "id": "msg-uuid-001",
    "role": "user",
    "content": "请帮我分析 EGFR 靶点的相关文献",
    "metadata": {},
    "token_count": 25,
    "created_at": "2026-05-05T07:01:00Z"
  },
  {
    "id": "msg-uuid-002",
    "role": "assistant",
    "content": "好的，我将为您搜索 EGFR 相关文献...",
    "metadata": {
      "grounding_sources": ["https://pubmed.ncbi.nlm.nih.gov/12345678"]
    },
    "token_count": 1200,
    "created_at": "2026-05-05T07:01:15Z"
  }
]
```

> 消息存储在 Redis（热缓存）+ SeaweedFS（冷存储）中，API 层自动协调读取。

---

## 5. 文件上传 API ⭐ 新增

文件上传功能允许用户将本地文件（PDF 论文、CSV 数据、分子结构文件等）上传到项目/会话中，供 Agent 在对话中引用和分析。

文件存储在 SeaweedFS 对象存储中，元数据记录在 PostgreSQL。

### 5.1 上传文件

```
POST /api/v1/sessions/{session_id}/files
```

**请求格式：** `multipart/form-data`

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | UUID | 目标会话 ID |

**表单字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `file` | File | ✅ | 要上传的文件 |
| `description` | string | 否 | 文件描述（最大 500 字符） |

**文件限制：**

| 约束 | 值 |
|------|-----|
| 单文件最大 | 50 MB |
| 允许的 MIME 类型 | `application/pdf`, `text/csv`, `text/plain`, `application/json`, `image/png`, `image/jpeg`, `chemical/x-mol`, `chemical/x-sdf`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| 每会话最大文件数 | 20 |

**cURL 示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/sessions/{session_id}/files" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/paper.pdf" \
  -F "description=EGFR inhibitor review paper"
```

**响应 `201 Created`：**

```json
{
  "id": "file-uuid-001",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "paper.pdf",
  "original_filename": "EGFR_inhibitor_review_2025.pdf",
  "mime_type": "application/pdf",
  "size": 2048576,
  "description": "EGFR inhibitor review paper",
  "s3_key": "sessions/550e8400-.../files/file-uuid-001/paper.pdf",
  "download_url": "http://localhost:8000/api/v1/sessions/.../files/file-uuid-001/download",
  "created_at": "2026-05-05T07:05:00Z"
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `400 Bad Request` | 文件为空 |
| `403 Forbidden` | 非会话拥有者 |
| `404 Not Found` | 会话不存在 |
| `413 Payload Too Large` | 文件超过 50 MB |
| `415 Unsupported Media Type` | 不支持的文件类型 |
| `422 Unprocessable Entity` | 文件数量超过上限 |

---

### 5.2 获取会话文件列表

```
GET /api/v1/sessions/{session_id}/files
```

**响应 `200 OK`：**

```json
[
  {
    "id": "file-uuid-001",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "paper.pdf",
    "original_filename": "EGFR_inhibitor_review_2025.pdf",
    "mime_type": "application/pdf",
    "size": 2048576,
    "description": "EGFR inhibitor review paper",
    "download_url": "http://localhost:8000/api/v1/sessions/.../files/file-uuid-001/download",
    "created_at": "2026-05-05T07:05:00Z"
  }
]
```

---

### 5.3 获取单个文件信息

```
GET /api/v1/sessions/{session_id}/files/{file_id}
```

**响应 `200 OK`：** 返回单个文件对象（格式同列表项）

---

### 5.4 下载文件

```
GET /api/v1/sessions/{session_id}/files/{file_id}/download
```

**响应 `302 Found`：** 重定向到 SeaweedFS 预签名 URL（有效期 10 分钟）

或

**响应 `200 OK`：** 直接流式返回文件内容

| Header | 值 |
|--------|-----|
| `Content-Type` | 文件原始 MIME 类型 |
| `Content-Disposition` | `attachment; filename="原始文件名"` |

---

### 5.5 删除文件

```
DELETE /api/v1/sessions/{session_id}/files/{file_id}
```

**响应 `204 No Content`：** 无响应体

> 同时删除 SeaweedFS 中的文件对象和 PostgreSQL 中的元数据记录。

**错误：**

| 状态码 | 说明 |
|--------|------|
| `403 Forbidden` | 非会话拥有者 |
| `404 Not Found` | 文件不存在 |

---

### 5.6 文件存储架构

```
SeaweedFS (S3 兼容)
└── aidd-data/                          (Bucket)
    └── sessions/{session_id}/
        ├── messages.jsonl              (对话记录)
        ├── memory.md                   (上下文压缩摘要)
        ├── files/                      ⭐ 新增：用户上传文件
        │   ├── {file_id}/{filename}    (原始文件)
        │   └── ...
        └── traces/                     (Agent Trace)
            └── raw_outputs/
```

**PostgreSQL 文件元数据表：**

```sql
CREATE TABLE session_files (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename    VARCHAR(255) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    mime_type   VARCHAR(128) NOT NULL,
    size        BIGINT NOT NULL,
    description TEXT,
    s3_key      VARCHAR(1024) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_session_files_session_id ON session_files(session_id);
CREATE INDEX ix_session_files_user_id ON session_files(user_id);
```

---

## 6. 靶点发现 API

### 6.1 启动靶点发现

```
POST /api/v1/targets/discover
```

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `query` | string | ✅ | 1–128 字符 | 基因符号或靶点名称 |
| `session_id` | UUID | 否 | — | 关联的会话 ID |

**请求示例：**

```json
{
  "query": "EGFR",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应 `201 Created`：**

```json
{
  "id": "report-uuid-001",
  "target_id": "target-uuid-001",
  "version": 1,
  "content": {
    "basic_info": { "name": "EGFR", "gene_symbol": "EGFR", "organism": "Homo sapiens" },
    "proteins": [...],
    "pathways": [...],
    "drugs": [...],
    "diseases": [...],
    "literature": [...]
  },
  "notes": ["Discovered 3 UniProt entries", "Found 12 related drugs"],
  "created_at": "2026-05-05T07:10:00Z"
}
```

---

### 6.2 获取靶点列表

```
GET /api/v1/targets?limit=50&offset=0
```

**响应 `200 OK`：**

```json
[
  {
    "id": "target-uuid-001",
    "name": "EGFR",
    "gene_symbol": "EGFR",
    "organism": "Homo sapiens",
    "uniprot_ids": ["P00533"],
    "description": "Epidermal Growth Factor Receptor",
    "created_at": "2026-05-05T07:10:00Z",
    "updated_at": "2026-05-05T07:10:00Z"
  }
]
```

---

### 6.3 获取单个靶点

```
GET /api/v1/targets/{target_id}
```

**响应 `200 OK`：** 返回 TargetSummary 对象

---

### 6.4 获取靶点报告

```
GET /api/v1/targets/{target_id}/report
```

**响应 `200 OK`：** 返回最新的 TargetReportResponse 对象

---

## 7. 追踪 API

### 7.1 获取消息追踪步骤

```
GET /api/v1/messages/{message_id}/traces
```

**响应 `200 OK`：**

```json
[
  {
    "id": "trace-uuid-001",
    "message_id": "msg-uuid-002",
    "step_number": 1,
    "step_type": "think",
    "prompt_sent": "...",
    "llm_response": "...",
    "token_count_in": 1234,
    "token_count_out": 567,
    "latency_ms": 245,
    "created_at": "2026-05-05T07:01:10Z"
  },
  {
    "id": "trace-uuid-002",
    "message_id": "msg-uuid-002",
    "step_number": 2,
    "step_type": "act",
    "tool_call": {
      "name": "query_pubmed",
      "arguments": { "query": "EGFR inhibitor 2025", "max_papers": 5 }
    },
    "tool_result": { "total": 5, "papers": [...] },
    "raw_data_uri": "s3://aidd-data/sessions/.../traces/raw_outputs/tc-001.json",
    "latency_ms": 1200,
    "created_at": "2026-05-05T07:01:12Z"
  }
]
```

---

## 8. 流式对话 API — SSE

> **协议选型说明**：采用 SSE（Server-Sent Events）而非 WebSocket。这与 ChatGPT、Claude、Gemini 三大主流 AI 产品的技术方案一致。SSE 基于标准 HTTP，鉴权通过 `Authorization` 请求头完成，且浏览器原生支持自动重连，对 Nginx/CDN 代理完全透明。

### 8.1 发送消息（流式响应）

```
POST /api/v1/chat
```

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `session_id` | UUID | ✅ | — | 会话 ID |
| `content` | string | ✅ | 1–50000 字符 | 用户消息内容 |
| `plan_mode` | bool | 否 | — | Plan mode 开关（先展示计划再执行） |
| `file_ids` | UUID[] | 否 | — | 引用的上传文件 ID 列表 |

**请求示例：**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "请帮我分析 EGFR 靶点的相关文献",
  "plan_mode": false,
  "file_ids": ["file-uuid-001"]
}
```

**响应：** `200 OK`，`Content-Type: text/event-stream`

响应为 SSE 流，每个事件格式为 `data: {json}\n\n`，流结束以 `data: [DONE]\n\n` 标记。

### 8.2 SSE 事件定义

| 事件 (`event` 字段) | 触发时机 | `data` 字段 | 说明 |
|---------------------|----------|-------------|------|
| `message_start` | Agent 开始处理 | `message_id` | 本轮回复的消息 ID |
| `content_delta` | 每个 token/chunk | `delta` | 文本增量片段（打字机效果） |
| `thinking_delta` | 模型思考中 | `delta` | `<thought>` 标签内内容（前端折叠显示） |
| `tool_use_start` | 工具调用开始 | `tool_name`, `tool_call_id`, `args` | 前端显示 "🔍 Searching PubMed..." |
| `tool_use_end` | 工具调用完成 | `tool_call_id`, `result_summary` | 前端更新为完成状态 |
| `citation` | 引用产生 | `index`, `url`, `title` | 角标引用 |
| `message_end` | 生成结束 | `message_id`, `usage` | Token 用量统计 |
| `error` | 出错 | `code`, `message` | 错误信息 |

### 8.3 SSE 事件流示例

```
data: {"event": "message_start", "data": {"message_id": "msg-uuid-002"}}

data: {"event": "content_delta", "data": {"delta": "根据"}}

data: {"event": "content_delta", "data": {"delta": " PubMed 检索"}}

data: {"event": "tool_use_start", "data": {"tool_name": "query_pubmed", "tool_call_id": "call-001", "args": {"query": "EGFR inhibitor", "max_papers": 5}}}

data: {"event": "tool_use_end", "data": {"tool_call_id": "call-001", "result_summary": "找到 5 篇论文"}}

data: {"event": "content_delta", "data": {"delta": "以下是 EGFR 相关的最新研究..."}}

data: {"event": "citation", "data": {"index": 1, "url": "https://pubmed.ncbi.nlm.nih.gov/12345678", "title": "EGFR inhibitors in NSCLC"}}

data: {"event": "message_end", "data": {"message_id": "msg-uuid-002", "usage": {"input_tokens": 1234, "output_tokens": 567}}}

data: [DONE]
```

### 8.4 停止生成

无需额外接口。前端通过 `AbortController` 中断 `fetch` 请求即可：

```javascript
const controller = new AbortController();
fetch("/api/v1/chat", { ..., signal: controller.signal });

// 用户点击停止按钮
controller.abort();
```

后端 `StreamingResponse` 在客户端断开后自动清理。

### 8.5 错误处理

| 场景 | 处理方式 |
|------|----------|
| 请求阶段错误 (401/404) | 标准 HTTP 错误响应（非 SSE） |
| 流中间错误 (LLM 超时) | 发送 `error` 事件后关闭流 |
| 客户端中断 | 后端自动停止 Agent 执行 |

---

## 9. 健康检查

```
GET /health
```

> 注意：此接口不在 `/api/v1` 前缀下。

**响应 `200 OK`：**

```json
{
  "status": "ok",
  "env": "dev"
}
```

---

## 10. 通用错误码

| HTTP 状态码 | 说明 | 常见场景 |
|:-----------:|------|----------|
| `400` | Bad Request | 请求格式错误、文件为空 |
| `401` | Unauthorized | Token 缺失/无效/过期 |
| `403` | Forbidden | 访问非本人资源 |
| `404` | Not Found | 资源不存在 |
| `409` | Conflict | 用户名重复等冲突 |
| `413` | Payload Too Large | 上传文件过大 |
| `415` | Unsupported Media Type | 不支持的文件类型 |
| `422` | Unprocessable Entity | 参数校验失败 |
| `500` | Internal Server Error | 服务端异常 |
| `503` | Service Unavailable | LLM 服务不可用 |

### 错误响应格式

```json
{
  "detail": "Session 550e8400-... not found"
}
```

---

## 附录 A：数据模型速查

### User

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `username` | string(64) | 唯一用户名 |
| `created_at` | datetime | 创建时间 |

### Session

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | UUID → users.id | 所属用户 |
| `title` | string(255) | 会话标题 |
| `s3_prefix` | string(512) | SeaweedFS 存储前缀 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### SessionFile ⭐ 新增

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `session_id` | UUID → sessions.id | 所属会话 |
| `user_id` | UUID → users.id | 上传用户 |
| `filename` | string(255) | 存储文件名 |
| `original_filename` | string(500) | 原始文件名 |
| `mime_type` | string(128) | MIME 类型 |
| `size` | bigint | 文件大小 (bytes) |
| `description` | text | 文件描述 |
| `s3_key` | string(1024) | S3 存储路径 |
| `created_at` | datetime | 上传时间 |

### Target

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `name` | string(128) | 靶点名称 |
| `gene_symbol` | string(64) | 基因符号 |
| `organism` | string(128) | 物种 |
| `uniprot_ids` | string[] | UniProt ID 列表 |
| `description` | text | 描述 |

### TargetReport

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `target_id` | UUID → targets.id | 关联靶点 |
| `version` | int | 版本号 |
| `content` | JSONB | 报告内容 |
| `notes` | string[] | 备注 |
| `created_at` | datetime | 创建时间 |

---

## 附录 B：文件上传与 Agent 集成流程

```
用户上传文件 → SeaweedFS 存储 → PostgreSQL 记录元数据
       ↓
用户发送消息 (携带 file_ids) → POST /api/v1/chat (SSE)
       ↓
Agent 接收消息 → 通过 file_ids 从 SeaweedFS 读取文件内容
       ↓
Agent 使用文件内容作为上下文进行推理 → SSE 流式返回结果
```

**支持的文件类型与 Agent 处理方式：**

| 文件类型 | MIME | Agent 处理 |
|----------|------|------------|
| PDF 论文 | `application/pdf` | 提取文本，作为上下文注入 |
| CSV 数据 | `text/csv` | 解析为结构化数据，支持统计分析 |
| 纯文本 | `text/plain` | 直接作为上下文 |
| JSON | `application/json` | 解析后作为结构化输入 |
| 图片 | `image/png`, `image/jpeg` | 多模态分析（依赖 Gemini Vision） |
| 分子文件 | `chemical/x-mol`, `chemical/x-sdf` | 解析分子结构用于药物分析 |
| Excel | `application/vnd.openxmlformats-...` | 解析为表格数据 |
