# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is the **backend** of the AIDD Agent platform — a FastAPI service that exposes an AI-driven drug-discovery (AIDD) agent over a REST/SSE API. It orchestrates a LangGraph-based multi-agent system for biomedical research and a specialized "target discovery" pipeline.

## Tech stack

- **Python 3.12**, managed via **conda/mamba** (`environment.yml`). There is no `pyproject.toml`/`requirements.txt`.
- **FastAPI + Uvicorn** (async) for the HTTP/SSE layer.
- **LangGraph + LangChain Core** for agent orchestration.
- **LLM providers** (`app/agent/llm_provider.py`, selected by `LLM_PRIORITY`): Google Gemini (`google-genai`), DeepSeek, and a local **OpenAI-compatible vLLM** endpoint (Qwen) used as a circuit-breaker fallback when the primary returns 429/503.
- **PostgreSQL** (SQLAlchemy 2.0 async + asyncpg) for relational metadata; **Alembic** (sync psycopg2) for migrations.
- **Redis** hot cache + **SeaweedFS S3** (aiobotocore) cold storage for conversation messages and raw tool-output traces.
- **Neo4j** for GraphRAG (WikiPathways), via `langchain-neo4j` / `langchain-community`.

## Common commands

All commands assume the conda env is active (`mamba activate aidd-agent`) and run from the repo root.

```bash
# Install dependencies (creates the `aidd-agent` env)
mamba env create -f environment.yml

# Start middleware (Postgres, Redis, SeaweedFS) — note: Neo4j is NOT in compose
docker compose up -d

# Run DB migrations (Alembic reads the URL from app.core.config, not alembic.ini)
alembic upgrade head
alembic revision --autogenerate -m "message"   # create a new migration

# Run the dev server (loads .env, defaults to host 0.0.0.0 port 8899, reload on)
python run.py
python run.py --no-reload --port 8899
# API docs: http://localhost:8899/api/v1/docs ; health: GET /health
```

`pytest.ini` is present (`asyncio_mode = auto`, session-scoped loop) but **there are currently no test files or `tests/` directory in the repo**, and there is no configured linter/formatter (no ruff/flake8/black config). Do not invent test or lint commands. The `scripts/` directory holds standalone diagnostic scripts (`check_gemini_models.py`, `testDeepseek.py`, `rerender_md.py`), not a test suite. The README references `scripts/test_tdp43_ad.py` and an `init_seaweedfs_bucket.py`, but **those files do not exist**.

## Configuration

- All settings are centralized in `app/core/config.py` (`pydantic-settings` `Settings`, read from process env / `.env`). Derived properties `database_url_async`, `database_url_sync`, `redis_url`, and `cors_origins_list` live here. Copy `.env.example` to `.env` for local dev.
- **Exception:** Neo4j connection params are read with raw `os.getenv` in `app/tools/graph_rag.py` (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) — they are NOT in `Settings`.

## Architecture

### Layering (`app/`)

`api/` (FastAPI routers, one per resource: auth, projects, sessions, messages, chat, files, targets, traces, tasks, events) → `services/` (business logic) → `models/` (SQLAlchemy ORM) + `storage/` (Redis/S3) + `agent/` (LangGraph). `schemas/` holds HTTP-layer Pydantic models; `core/` holds config, JWT security, exceptions; `db/` holds the async engine/session. `main.py` (`create_app()`) wires every router under `API_V1_PREFIX` (`/api/v1`) and a lifespan that eagerly inits S3 + Redis and reaps stale tasks on startup.

### Chat request flow (the primary runtime path)

`POST /api/v1/chat` (`app/api/chat.py`) authenticates via JWT, resolves the session, then returns a `StreamingResponse` of SSE events produced by `chat_service.stream_chat()` (`app/services/chat_service.py`). This is a **manual ReAct loop** (not a prebuilt LangGraph agent) that:

1. Loads history via `storage/manager.py` (Redis hot cache, SeaweedFS cold fallback).
2. Streams LLM tokens (`get_default_provider()`), emits `content_delta` SSE events.
3. Executes tool calls from `app/tools` and loops (capped at `MAX_TOOL_ROUNDS = 10`), persisting raw tool output as S3 traces.
4. Applies **auto-compaction** (`app/agent/context_manager.py`) when context exceeds `AUTOCOMPACT_THRESHOLD_PERCENT`.

### Tools and dynamic loading

`app/tools/registry.py` (`default_registry`) splits tools into **CORE** (always in the system prompt) and **DEFERRED** (mounted on demand). The LLM calls `tool_search` (`search_tool.py`) to discover deferred tools by keyword; nodes call `bind_active(state)` to materialize the active tool subset. Tool modules wrap external biomedical APIs: `literature.py` (PubMed/arXiv), `semantic_scholar.py`, `structure.py` (UniProt/PDB/AlphaFold/InterPro), `disease.py` (OpenTargets/Monarch/QuickGO), `pathway.py` (KEGG/Reactome/STRING), `drug.py`/`peptide.py` (ChEMBL/PubChem/GtoPdb), and `graph_rag.py` (Neo4j GraphRAG).

### Target Discovery sub-graph

`app/agent/target_discovery_graph.py` is a **fixed-node LangGraph** pipeline: `literature → composition → function → pathway → drugs → synthesize → END`. Each node runs a bounded ReAct loop (`MAX_NODE_STEPS = 6`) with its own tool subset and per-node timeouts, and is designed to always produce a partial report on failure. It is **not invoked directly by the API** — it is wrapped as a tool (`run_target_discovery` in `app/tools/deep_research.py`) that the chat agent calls; the tool submits the graph as a **background task** (`services/background_runner.py`, `services/task_registry.py`) and forwards node progress through `progress_callback`. The resulting `TargetReport` is rendered to Markdown by `services/report_renderer.py`.

### How it connects to sibling repos

- **aidd-agent-front-react** (frontend): consumes the REST + SSE API; allowed origins are set via `CORS_ORIGINS` (defaults include Vite ports 5173/61824).
- **aidd-agent-model** (LLM serving): the local vLLM/Qwen fallback provider points at `QWEN_BASE_URL` (an OpenAI-compatible endpoint served by that repo).
- **aidd-agent-GraphRAG** (Neo4j knowledge graph): queried by `app/tools/graph_rag.py` over Bolt using `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`.
- **aidd-agent-remark-renderer** (Markdown→PDF microservice): `GET /api/v1/.../files/{id}/pdf` (`app/api/files.py`) reads Markdown from S3 and POSTs it to `{REMARK_RENDERER_URL}/render` to return PDF bytes.
