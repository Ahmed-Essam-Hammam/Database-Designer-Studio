# 🗄️ DB Studio — AI-Powered Database Platform

> **Design, modify, and query your databases through natural language. No SQL expertise required.**

DB Studio is a full-stack, LLM-powered database platform built with Streamlit and LangGraph. It enables users to create production-ready databases from plain-English descriptions, safely modify existing schemas using natural language, and interactively query any SQLite database through a conversational chat interface — all backed by Azure Blob Storage for persistent, cloud-native database management.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
   - [Feature 1 — Create Database](#feature-1--create-database)
   - [Feature 2 — Modify Database](#feature-2--modify-database)
   - [Feature 3 — Chat with Database](#feature-3--chat-with-database)
4. [Project Structure](#project-structure)
5. [Tech Stack & Dependencies](#tech-stack--dependencies)
6. [Configuration & Environment Variables](#configuration--environment-variables)
7. [Installation & Local Setup](#installation--local-setup)
8. [Running with Docker](#running-with-docker)
9. [Deployment — Azure App Service](#deployment--azure-app-service)
10. [Workspace Lifecycle & State Machine](#workspace-lifecycle--state-machine)
11. [Agent Pipelines In Depth](#agent-pipelines-in-depth)
12. [Data Models](#data-models)
13. [Shared Infrastructure](#shared-infrastructure)
14. [Observability & Tracing](#observability--tracing)
15. [Human-in-the-Loop Design](#human-in-the-loop-design)
16. [Known Limitations & Notes](#known-limitations--notes)

---

## Overview

DB Studio takes a **three-feature, single-entrypoint** approach. All three capabilities share a unified `Workspace` state object, common Azure Blob Storage infrastructure, an ERD renderer, and a PDF report generator. The entry point (`app.py`) acts as a pure router — it owns the page layout, workspace lifecycle, and state-based navigation, while each feature's UI logic lives in its own dedicated app file (`feature1_app.py`, `feature2_app.py`, `feature3_app.py`).

The platform supports the full database lifecycle:

```
Natural Language Input
        │
        ▼
 ┌──────────────┐     ┌─────────────────┐     ┌────────────────────┐
 │  Create DB   │────►│   Modify DB     │────►│  Chat with DB      │
 │  (Feature 1) │     │  (Feature 2)    │     │  (Feature 3)       │
 └──────────────┘     └─────────────────┘     └────────────────────┘
        │                     │                        │
        └─────────────────────┴────────────────────────┘
                              │
                    Azure Blob Storage
                    (SQLite .db files)
```

---

## Architecture

```
app.py                         ← Entry point & router (Streamlit)
├── feature1_app.py            ← Feature 1 UI (Create DB)
├── feature2_app.py            ← Feature 2 UI (Modify DB)
├── feature3_app.py            ← Feature 3 UI (Chat with DB)
│
├── Features/
│   ├── Feature1_create_db/    ← 5-agent pipeline (LangChain + custom orchestrator)
│   │   ├── agents/            ← 5 specialist LLM agents
│   │   ├── services/          ← Orchestrator + LLM service factory
│   │   ├── memory/            ← Session persistence + approval records
│   │   ├── utils/             ← ERD visualizer, report generator, DB builder
│   │   ├── models.py          ← All Pydantic domain models
│   │   └── validators.py      ← Rule-based schema validators
│   │
│   ├── Feature2_modify_db/    ← LangGraph 4-node workflow
│   │   ├── agents/            ← Clarifier, Modifier, Validator, Executor
│   │   ├── graph.py           ← LangGraph graph definition & routing
│   │   ├── state.py           ← GraphState TypedDict
│   │   └── utils/             ← Blob storage, DB utils, ERD, PDF, memory
│   │
│   └── Feature3_chat_db/      ← LangGraph 8-node query agent
│       ├── core/              ← Runtime DB, schema builder, SQL validation
│       ├── graph/             ← Graph builder & router
│       ├── nodes/             ← intent_router, generate_sql
│       ├── retrieval/         ← Hybrid BM25 + dense few-shot retriever
│       ├── observability/     ← Node-level tracing decorator
│       ├── prompts/           ← All prompt templates
│       ├── execution/         ← SQL executor + history management
│       └── state.py           ← DBDesignerState dataclass
│
├── shared/
│   ├── config.py              ← Pydantic Settings, LLM/embeddings factories
│   ├── workspace.py           ← Workspace model + WorkspaceState enum
│   ├── blob_storage.py        ← Azure Blob upload/download/URL helpers
│   ├── cache.py               ← TTLCache (in-memory, thread-safe)
│   ├── db_utils.py            ← SQLite schema extraction utilities
│   ├── erd/                   ← Shared interactive ERD renderer (HTML/SVG/JS)
│   ├── pdf_report.py          ← ReportLab PDF report generator
│   ├── sidebar.py             ← Sidebar UI component (shared across features)
│   └── workspace.py           ← Workspace dataclass & state enum
│
├── orchestrator/
│   └── router.py              ← Top-level routing logic helper
│
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Features

### Feature 1 — Create Database

**Entry Mode:** `Create DB`

The most sophisticated pipeline in the application. Takes a free-form natural-language description (in English or Arabic) and produces a fully normalised SQLite database, an interactive ERD diagram, and a PDF design report, with a human-in-the-loop approval gate before any SQL is written.

#### Pipeline Stages

The pipeline runs in two phases separated by a mandatory human approval gate:

**Pre-Approval Phase**

1. **Requirement Analyzer (Agent 1)** — Parses the user's description into structured entities, attributes, relationships, and domain classification using an LLM. Handles English and Arabic input. Returns a `RequirementAnalysis` Pydantic object.

2. **Suggestion Agent (Agent 2)** — Takes the requirement analysis and produces a full `SuggestionPlan`: suggested entities with typed attributes, normalised relationships, optional features (e.g. audit logging), and a design rationale. Enforces 3NF, ensures every entity has a UUID primary key, and guards against SQL reserved word conflicts. Incorporates a RAG context slot for similar-schema retrieval (optional).

3. **Human Approval Gate** — The UI presents the suggestion plan (entities, relationships, ERD preview) and waits for explicit user approval, rejection, or modification. The user can iterate on the plan as many times as needed before approving. Each modification request invokes the **Plan Modifier** sub-agent which merges changes into the existing plan while preserving unchanged entities.

**Post-Approval Phase**

4. **Schema Designer (Agent 3)** — Converts the approved `SuggestionPlan` into a `DatabaseSchema`: full `CREATE TABLE` DDL with UUID primary keys, foreign key columns, `created_at` timestamps, and index definitions. Immediately runs inline validation and applies production fixes.

5. **Validation Agent (Agent 4)** — Hybrid two-layer validation:
   - **Rule-based layer** (`validators.py`): checks for duplicate tables/columns, missing foreign keys, reserved keyword conflicts, unsupported SQL types, relationship consistency.
   - **LLM-based layer**: semantic validation in domain context — checks logical consistency, structural completeness, and business-domain appropriateness. Returns structured issues with CRITICAL / FIXABLE / INFO severity and optionally a corrected schema. Low-value noise patterns (enum suggestions, N+1 warnings) are filtered out.
   - If the validation agent produces a corrected schema, it re-validates the correction in a second pass.

6. **Query Generator (Agent 5)** — Generates four CRUD queries (INSERT, SELECT, UPDATE, DELETE) per table plus a set of analytical JOIN queries across tables, returning a `QuerySet`.

7. **SQLite Database Builder** — Materialises the final DDL into a `.db` file, uploads it to Azure Blob Storage, and returns a download URL.

8. **Final Report Generator** — Produces a structured report dict and a downloadable PDF (via ReportLab) covering requirement analysis, suggestion plan, schema, validation results, and generated queries.

#### ERD Diagram

An interactive ERD is rendered as self-contained HTML using the shared `erd/renderer.py`. It features:
- Crow's-foot notation for relationship cardinality
- Colour-coded column badges: PK 🔑, FK 🔗, UNIQUE ◈, INDEX ⬡, NOT NULL ✦
- Draggable table cards
- SVG Bézier curve edges with auto-layout grid placement
- Live zoom + pan
- View nodes rendered with dashed borders

---

### Feature 2 — Modify Database

**Entry Mode:** `Upload & Modify`

A LangGraph-orchestrated 4-node workflow that safely modifies an existing SQLite database using natural language instructions.

#### LangGraph Workflow

```
START
  │
  ▼
[clarifier] ──needs_more──► PAUSE (UI asks user for clarification)
  │ enough_info
  ▼
[modifier]  ←──────────────────────────────┐
  │                                        │
  ▼                                        │
[validator] ──issues (< MAX iterations)────┘
  │ approved OR max iterations reached
  ▼
PAUSE for human review (UI shows plan, waits for approval)
  │
  ├── approved ──► [executor] ──► END (committed to blob)
  │
  └── rejected/edit ──► [modifier] (human feedback injected)
```

**Node Descriptions:**

- **Clarifier** — Determines if the user's modification request is clear enough to proceed. If ambiguous, it formulates a clarifying question and pauses, sending control back to the UI. Accumulated Q&A pairs are passed to the Modifier.

- **Modifier** — Generates a structured modification plan: a plain-English description, an ordered list of SQLite-safe SQL statements, and any warnings about data loss or irreversibility. Handles all SQLite-specific constraints: only `ADD COLUMN` / `RENAME` are natively supported; full table migration (CREATE + copy + DROP + RENAME) is used for other schema changes. Includes robust JSON repair strategies (3 fallback parse strategies) for LLM output that contains malformed JSON.

- **Validator** — Validates the proposed SQL statements against the current schema. Returns approval status, issues, and feedback. Feeds back into the Modifier up to `MAX_CORRECTION_ATTEMPTS` times.

- **Executor** — Executes the approved SQL statements against the SQLite database in Azure Blob Storage. Creates a timestamped backup blob before execution. Records each change in the session's `modification_history`.

#### Database Ingestion

Users upload a `.db`, `.sqlite`, or `.sqlite3` file. The platform ingests it by:
1. Uploading to the `BLOB_CONTAINER_ACTIVE` Azure container.
2. Extracting the full DDL schema string.
3. Writing a temporary local copy for the session.

---

### Feature 3 — Chat with Database

**Entry Mode:** `Connect & Chat` (or after creating/modifying a DB)

A production-grade, LangGraph-orchestrated natural language query agent. Users ask questions in plain English; the agent generates SQL, validates it, self-corrects if needed, executes it, and returns a natural-language answer alongside the raw SQL and result table.

#### LangGraph Graph

```
build_schema_context
        │
        ▼
retrieve_fewshots
        │
        ├──(analytical + complex)──► optional_decompose_query ──┐
        │                                                       │
        └───────────────────────────────────────────────────────┘
        ▼
generate_sql
        │
        ▼
validate_sql
        │
        ├──(HARD_ERROR, attempts < MAX)──► self_correct ──► validate_sql
        │
        ├──(format_result)──► format_result ──► END
        │
        └──(request_clarification)──► request_clarification ──► END
```

**Node Descriptions:**

- **build_schema_context** — Loads the database schema (from cache or live connection), compresses it into a DDL summary string, and extracts table names for downstream nodes. Schema snapshots are cached by `schema_id:version` key.

- **retrieve_fewshots** — Runs the **Hybrid BM25 + Dense Few-Shot Retriever** to find the most relevant SQL example patterns from a curated pattern library. Uses **Reciprocal Rank Fusion (RRF)** to merge BM25 and dense (Azure OpenAI embeddings) rankings. Supports complexity filtering, table count filtering, and optional bounded feedback adjustment. Results are cached per request using a composite key (schema version, query text, intent, complexity, dialect, top_k).

- **optional_decompose_query** — For complex analytical queries, generates a lightweight CTE plan (base → aggregated → final) to guide the SQL generator toward properly structured CTEs.

- **generate_sql** — Generates SQL using the schema DDL, retrieved examples, intent, and CTE plan. Returns a structured `SQLGenerationOutput` (classification, complexity, strategy, query, confidence, needs_clarification, proposed_artifact).

- **validate_sql** — Validates the generated SQL using:
  - `sqlglot` AST parsing for syntax correctness
  - Table/column existence checks against the schema snapshot
  - JOIN validity checks
  - Identifier normalisation
  - Safety cap enforcement (result row limits)

- **self_correct** — If validation fails with a retryable error, sends the bad SQL + error list back to the LLM with a structured correction prompt. Corrections are cached per (SQL hash, error signature, schema version, dialect). Attempts are counted; after `MAX_CORRECTION_ATTEMPTS`, the pipeline falls through to clarification.

- **format_result** — Normalises the validated SQL using `identifier_normalizer.py` to match exact stored identifier casing with dialect-correct quoting.

- **request_clarification** — Returns a user-facing clarification message derived from the validation errors or the intent router's resolved context.

#### Intent Router

Before the graph runs, an `intent_router` node (outside the graph) classifies the user query:
- **accept** — a valid database question; proceed to graph
- **clarify** — ambiguous or underspecified; return clarification message
- **reject** — out-of-scope or unsafe; return rejection message

This avoids graph initialization cost (~2ms) for the most common non-query paths and provides a safety layer independent of SQL generation.

#### Hybrid Retriever

The `HybridFewShotRetriever` uses:
- **Dense retrieval**: Azure OpenAI Embeddings with cosine similarity
- **BM25 retrieval**: `rank_bm25.BM25Okapi` for keyword recall
- **RRF fusion**: configurable `rrf_k`, `dense_weight`, `bm25_weight`
- **Optional filters**: complexity, max table count, dialect
- **Feedback adjustment**: bounded positive/negative feedback loop with time decay

The pattern library (`retrieval/pattern_library.py`) contains canonical SQL examples seeded at startup.

---

## Project Structure

```
Database-Designer-Studio-main/
│
├── app.py                          Main Streamlit router & workspace lifecycle
├── feature1_app.py                 Feature 1 UI — input, suggestion, results phases
├── feature2_app.py                 Feature 2 UI — modification chat interface
├── feature3_app.py                 Feature 3 UI — chat interface & query results
├── requirements.txt
├── Dockerfile
├── .env.example
│
├── Features/
│   ├── __init__.py
│   │
│   ├── Feature1_create_db/
│   │   ├── __init__.py
│   │   ├── models.py               All Pydantic models (entities, schema, validation, etc.)
│   │   ├── validators.py           Rule-based schema validation logic
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── requirement_analyzer.py   Agent 1 — NL → structured requirements
│   │   │   ├── suggestion_agent.py       Agent 2 — requirements → design plan
│   │   │   ├── schema_designer.py        Agent 3 — plan → DDL schema
│   │   │   ├── validation_agent.py       Agent 4 — hybrid schema validation
│   │   │   └── query_generator.py        Agent 5 — schema → CRUD + analytical queries
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py     Pipeline controller (pre/post approval phases)
│   │   │   └── llm_service.py      LLM factory wrapper for Feature 1
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   └── session_store.py    Session save/load + approval recording
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── erd_visualizer.py   Pyvis-based ERD diagram + SQL DDL generator
│   │       └── report_generator.py Final design report builder
│   │
│   ├── Feature2_modify_db/
│   │   ├── __init__.py
│   │   ├── graph.py                LangGraph workflow definition
│   │   ├── state.py                GraphState TypedDict
│   │   ├── config.py               Feature 2 config + LLM factory
│   │   ├── agents/
│   │   │   ├── clarifier.py        Clarification intent detection node
│   │   │   ├── modifier.py         SQL modification plan generator node
│   │   │   ├── validator.py        SQL plan validator node
│   │   │   └── executor.py         SQL execution + blob backup node
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── blob_storage.py     Azure Blob helpers (upload/download/backup)
│   │       ├── db_utils.py         SQLite schema extraction + ingestion
│   │       ├── erd_data.py         ERD data extraction from live DB
│   │       ├── erd_renderer.py     ERD HTML renderer (Feature 2 local copy)
│   │       ├── file_import.py      File upload + format validation
│   │       ├── memory.py           Modification history + prompt formatting
│   │       └── pdf_report.py       Modification report PDF generator
│   │
│   └── Feature3_chat_db/
│       ├── __init__.py
│       ├── Queryagent.py           Top-level agent orchestrator + all node implementations
│       ├── state.py                DBDesignerState dataclass + supporting types
│       ├── core/
│       │   ├── identifier_normalizer.py  Identifier casing normalisation
│       │   ├── runtime_db.py             Live DB connection + schema cache
│       │   ├── schema_builder.py         Schema → compressed DDL string
│       │   ├── sql_utils.py              Safety cap + utility functions
│       │   ├── sql_validation.py         sqlglot-based SQL validation
│       │   └── validation_engine.py      Validation result helpers + retry logic
│       ├── execution/
│       │   └── executor.py               SQL execution + history appending
│       ├── graph/
│       │   ├── __init__.py
│       │   ├── builder.py                LangGraph graph compiler
│       │   └── router.py                 Conditional edge routing functions
│       ├── nodes/
│       │   ├── generate_sql.py           SQL generation node
│       │   └── intent_router.py          Intent classification + safety node
│       ├── observability/
│       │   └── tracing.py                NodeTracer context manager + decorator
│       ├── prompts/
│       │   └── templates.py              All prompt template builders
│       ├── retrieval/
│       │   ├── hybrid_retriever.py       BM25 + Dense RRF retriever
│       │   └── pattern_library.py        Seed SQL example pattern library
│       └── utils/
│           ├── __init__.py
│           └── validation_utils.py       Hashing, dialect helpers, error signature
│
├── orchestrator/
│   └── router.py                   Top-level feature routing helper
│
└── shared/
    ├── __init__.py
    ├── blob_storage.py             Azure Blob upload/download/URL with TTL cache
    ├── cache.py                    TTLCache — thread-safe in-memory key-value cache
    ├── config.py                   Pydantic Settings — all env vars + LLM/embeddings factories
    ├── db_utils.py                 SQLite schema extraction (shared)
    ├── erd/
    │   ├── __init__.py
    │   ├── data.py                 ERD data extraction from DatabaseSchema
    │   └── renderer.py             Interactive HTML ERD renderer (pure HTML/CSS/JS)
    ├── import_paths.py             sys.path bootstrap for feature modules
    ├── pdf_report.py               ReportLab PDF report generator (shared)
    ├── sidebar.py                  Sidebar UI: workspace info, schema view, history
    └── workspace.py                Workspace Pydantic model + WorkspaceState enum
```

---

## Tech Stack & Dependencies

| Category | Library / Service |
|---|---|
| **UI Framework** | Streamlit |
| **LLM Orchestration** | LangChain, LangGraph |
| **LLM Provider** | Azure OpenAI (GPT-4.1-mini default) |
| **Embeddings** | Azure OpenAI (`text-embedding-3-small` default) |
| **SQL Parsing & Validation** | sqlglot |
| **Dense Retrieval** | Azure OpenAI Embeddings + NumPy |
| **Keyword Retrieval** | rank_bm25 (BM25Okapi) |
| **Vector Store** | ChromaDB |
| **Data Validation** | Pydantic v2, pydantic-settings |
| **Database** | SQLite (via Python `sqlite3` + SQLAlchemy) |
| **Cloud Storage** | Azure Blob Storage (`azure-storage-blob`) |
| **ERD Rendering** | Pyvis (Feature 1), pure HTML/SVG/JS (shared ERD renderer) |
| **Graph Visualization** | streamlit-agraph, networkx, pyvis |
| **PDF Generation** | ReportLab |
| **Data Processing** | Pandas, openpyxl |
| **Charts** | Plotly |
| **Environment** | python-dotenv |
| **Tokenization** | tiktoken |
| **CI/CD** | GitHub Actions → Azure App Service |
| **Containerization** | Docker (Python 3.10-slim) |

---

## Configuration & Environment Variables

Copy `.env.example` to `.env` and fill in the required values:

```env
# ── Azure OpenAI ────────────────────────────────────────────────────────────
AZURE_OPENAI_API_KEY=""              # Required
AZURE_OPENAI_ENDPOINT=""             # Required — e.g. https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=""           # Chat deployment name (default: gpt-4.1-mini)
AZURE_OPENAI_API_VERSION=""          # e.g. 2024-05-01-preview
AZURE_OPENAI_EMBEDDING_DEPLOYMENT="" # Embedding deployment name (default: text-embedding-3-small)

# ── Azure Blob Storage ───────────────────────────────────────────────────────
AZURE_STORAGE_CONNECTION_STRING=""   # Required (or use account name+key or SAS below)
# Alternatives:
# AZURE_STORAGE_ACCOUNT_NAME=""
# AZURE_STORAGE_ACCOUNT_KEY=""
# AZURE_STORAGE_ACCOUNT_URL=""
# AZURE_BLOB_SAS_TOKEN=""

BLOB_CONTAINER_ACTIVE=""             # Container for live databases (default: db-active)
BLOB_CONTAINER_BACKUPS=""            # Container for backups (default: <active>-backups)

# ── Database ─────────────────────────────────────────────────────────────────
DB_URL=""                            # Optional — pre-existing database URL for Feature 3

# ── Agent Tuning ─────────────────────────────────────────────────────────────
MAX_CORRECTION_ATTEMPTS=3            # SQL self-correction retries (Feature 3)
CONFIDENCE_THRESHOLD=0.5             # Minimum confidence for SQL generation

# ── Retriever Configuration (Feature 3) ─────────────────────────────────────
RETRIEVER_TOP_K=3                    # Final number of examples returned
RETRIEVER_DENSE_TOP_K=10             # Dense retrieval candidate pool size
RETRIEVER_BM25_TOP_K=10              # BM25 candidate pool size
# Additional: RETRIEVER_RRF_K, RETRIEVER_DENSE_WEIGHT, RETRIEVER_BM25_WEIGHT
# RETRIEVER_COMPLEXITY_FILTER, RETRIEVER_MAX_TABLES_FILTER

# ── Observability (optional) ─────────────────────────────────────────────────
LANGSMITH_TRACING=false
LANGSMITH_ENDPOINT=""
LANGSMITH_API_KEY=""
LANGSMITH_PROJECT=""

# ── Feature Flags ────────────────────────────────────────────────────────────
REQUIRE_HUMAN_APPROVAL=false         # Require explicit approval before SQL execution in Feature 3
```

**Authentication for Azure Blob Storage** accepts one of three methods (checked in order):
1. `AZURE_STORAGE_CONNECTION_STRING`
2. `AZURE_STORAGE_ACCOUNT_NAME` + `AZURE_STORAGE_ACCOUNT_KEY`
3. `AZURE_STORAGE_ACCOUNT_URL` + `AZURE_BLOB_SAS_TOKEN`

---

## Installation & Local Setup

**Prerequisites:**
- Python 3.10+
- An Azure OpenAI resource with a chat deployment and an embedding deployment
- An Azure Storage account with at least one blob container

```bash
# 1. Clone the repository
git clone https://github.com/Ahmed-Essam-Hammam/Database-Designer-Studio.git
cd Database-Designer-Studio-main

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in AZURE_OPENAI_* and AZURE_STORAGE_* values

# 5. Run the application
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

---

## Running with Docker

```bash
# Build the image
docker build -t db-studio .

# Run with your .env file
docker run -p 8501:8501 --env-file .env db-studio
```

The Dockerfile uses `python:3.10-slim`, installs build tools (`build-essential`, `libpq-dev`), exposes port `8501`, and includes a health check against `/_stcore/health`.

---

## Deployment — Azure App Service

The repository includes two GitHub Actions workflows:

**`main.yml`** — Manual/general CI workflow:
- Checks out code, sets up Python 3.13
- Creates a virtual environment and installs dependencies (early build failure detection)
- Uploads the application artifact (excluding the `antenv/` directory)

**`main_database-designer-studio.yml`** — Automatic deployment to Azure App Service:
- Triggered on every push to `main` or manual `workflow_dispatch`
- Builds the Python app artifact
- Deploys to the `database-designer-studio` Azure Web App, Production slot
- Uses `AZUREAPPSERVICE_PUBLISHPROFILE_*` secret for authentication
- Relies on Oryx build engine on Azure for `pip install` during deployment

**Required GitHub Secret:**
- `AZUREAPPSERVICE_PUBLISHPROFILE_F25DD8092D314F94A4487907AC5B3C23` — Azure App Service publish profile

**Required App Service Environment Variables** (set in Azure Portal → Configuration):
All variables from `.env.example` must be set as Application Settings in the Azure App Service.

---

## Workspace Lifecycle & State Machine

Every user session is represented by a `Workspace` Pydantic model, stored in `st.session_state` and persisted to Azure Blob Storage. The workspace transitions through the following states:

```
ENTRY
  │
  ├──(Create DB)────────────► EMPTY ──(analysis done)──► SCHEMA_CREATED
  │                                                              │
  │                                                    (approved)│
  │                                                              ▼
  ├──(Upload & Modify)──────► EMPTY ──(file ingested)──────► DB_READY
  │                                                              │
  │                                                      ┌───────┴───────────┐
  └──(Connect & Chat)───────► EMPTY ──(connected)───┐    │                   │
                                                    │    ▼                   ▼
                                                    └► QUERY_READY      MODIFIED
                                                              │              │
                                                              └──────────────┘
                                                                    │
                                                               QUERY_READY
```

**State Descriptions:**

| State | Description |
|---|---|
| `ENTRY` | Landing page — user chooses a feature |
| `EMPTY` | Feature selected; waiting for input, file upload, or connection |
| `SCHEMA_CREATED` | Feature 1 only — requirement analysis complete, awaiting approval |
| `DB_READY` | Database connected and schema extracted; choose Modify or Chat |
| `MODIFIED` | Feature 2 active — modification workflow in progress |
| `QUERY_READY` | Feature 3 active — chat interface open |

The `Workspace` object carries all intermediate results (requirement analysis, suggestion plan, validation results, schema DDL, blob name, local DB path, query history, modification history) across Streamlit re-runs without re-executing the pipeline.

---

## Agent Pipelines In Depth

### Feature 1 — Five-Agent Chain

All agents use **LangChain's** `ChatPromptTemplate | AzureChatOpenAI | JsonOutputParser` chain pattern with `temperature=0.0` for determinism. Agent outputs are cached in `TTLCache` instances (10-minute TTL by default) keyed by input hash to avoid redundant LLM calls on Streamlit re-runs.

Each agent prompt enforces:
- Output exclusively in JSON (no markdown fences)
- No SQL reserved keyword identifiers (semantic renames enforced)
- Conservative interpretation of ambiguous inputs
- Fallback behaviour on LLM failure (stub data returned, error logged)

### Feature 2 — LangGraph Graph

The graph is compiled once as a module-level singleton (`get_graph()`). `GraphState` is a `TypedDict` with `Annotated[list, add_messages]` for LangGraph's built-in message accumulation. The human review node is a passthrough (`lambda s: s`) — the actual UI pause and state injection is handled by `feature2_app.py` outside the graph.

### Feature 3 — LangGraph Graph + Manual Fallback

The Feature 3 graph is rebuilt lazily on first invocation. A `_run_graph_manually()` fallback replicates the routing logic imperatively in case LangGraph raises an exception, ensuring the pipeline always returns a result.

The `intent_router` runs **outside** the graph as a pre-filter. It caches its output in `_router_cache` (keyed by stripped query text) to avoid repeated classification calls for the same query within a session.

---

## Data Models

All core models are defined in `Features/Feature1_create_db/models.py` as Pydantic `BaseModel` subclasses:

| Model | Description |
|---|---|
| `RequirementAnalysis` | Output of Agent 1 — entities, attributes, relationships, domain |
| `SuggestionPlan` | Output of Agent 2 — entities, relationships, optional features, rationale |
| `DatabaseSchema` | Full normalised schema — tables, relationships, normalization level, version |
| `TableDefinition` | Single table — name, columns, indexes |
| `ColumnDefinition` | Single column — name, data type, constraints, foreign key reference |
| `ValidationResult` | Agent 4 output — issues, suggestions, auto-fixes, corrected schema |
| `ValidationIssue` | Single validation finding — severity, location, message, suggestion |
| `QuerySet` | Agent 5 output — CRUD queries per table + analytical queries |
| `SessionState` | Full session for Feature 1 — all agent outputs + status machine |
| `ApprovalRecord` | Human-in-the-loop approval event with timestamp and plan snapshot |

Feature 3 defines its own state in `Features/Feature3_chat_db/state.py`:

| Model | Description |
|---|---|
| `DBDesignerState` | Central pipeline state — query, schema, SQL, validation, execution results, latency |
| `SchemaSnapshot` | Cached schema — tables, dialect, version |
| `SQLGenerationResult` | Validated SQL — query, classification, complexity, confidence |
| `ProposedArtifact` | Optional output artifact — CREATE_VIEW, SAVE_QUERY_TEMPLATE, CACHE_RESULT |

The `Workspace` model in `shared/workspace.py` is the cross-feature glue, holding a flat union of all feature outputs so they can be passed between pipeline stages without serialization complexity.

---

## Shared Infrastructure

### TTLCache (`shared/cache.py`)

A lightweight, thread-safe in-memory key-value cache with per-entry TTL expiry. Used by all five Feature 1 agents, the Feature 3 retriever, and schema summary caching to avoid redundant LLM/embedding calls across Streamlit re-runs.

### Azure Blob Storage (`shared/blob_storage.py`)

Provides `upload_db()`, `download_db()`, `get_blob_url()`, and `save_workspace()` / `load_workspace()`. Downloads are cached in a 5-minute `TTLCache`. Workspace state serialization uses Pydantic's `model_dump_json()` and is stored in a separate `workspaces` container.

The `app.py` layer adds Streamlit-level `@st.cache_data(ttl=300)` caches on top of the shared download and schema extraction functions to prevent repeated calls within a single Streamlit session.

### ERD Renderer (`shared/erd/renderer.py`)

Generates a fully self-contained, interactive HTML string (no external dependencies) that Streamlit renders via `st.components.v1.html()`. Supports crow's-foot notation, draggable cards, SVG Bézier edges, zoom/pan, column type badges, row count display, and a legend panel. Colour palette matches the app's dark-blue theme.

### PDF Report Generator (`shared/pdf_report.py`)

Uses ReportLab to produce formatted PDF reports covering requirement analysis, suggestion plan, schema details, validation results, and generated queries. Available as a download from the Feature 1 results page.

### Sidebar (`shared/sidebar.py`)

A shared sidebar component rendered on every page. Displays workspace ID, current state badge, database connection info, schema DDL preview, modification history, and a "New Workspace" button.

---

## Observability & Tracing

Feature 3 includes a structured observability layer in `observability/tracing.py`:

**`NodeTracer`** — A context manager that wraps any LangGraph node and records:
- Node name
- Input snapshot (configurable fields)
- Output snapshot
- Execution latency in milliseconds
- Success / error status
- Exception details if the node fails

**`@node_trace` decorator** — A function decorator version of `NodeTracer` that automatically captures input fields and output for any LangGraph node function.

Traces are appended to `state.trace` (a list of dicts) for the orchestrator to inspect. The `_emit()` method currently prints structured log lines; in production it should be replaced with a Langfuse or OpenTelemetry SDK call.

Latency breakdowns are tracked in `state.latency_breakdown_ms` including schema load time, cache hit/miss, retrieval time, validation time, correction loop count, and total pipeline time. The top 3 slowest nodes are computed at pipeline end for quick triage.

---

## Human-in-the-Loop Design

DB Studio applies the principle of human oversight at two critical points:

**Feature 1 — Schema Approval Gate:**
Before any SQL is generated or any database is created, the user sees the complete suggestion plan (entities, relationships, ERD preview, rationale). They can:
- **Approve** — proceed to schema generation
- **Reject** — start over
- **Modify** — describe changes in natural language; the Plan Modifier agent updates the plan and returns to the approval gate

This gate is enforced at the `orchestrator.py` level via an `ApprovalRequired` exception that halts the pipeline. The UI catches this exception, displays the plan, and re-invokes `run_post_approval_pipeline()` only after receiving explicit approval.

**Feature 2 — SQL Execution Approval:**
After the Modifier and Validator produce an approved SQL plan, the UI displays the full plan (description, SQL statements, warnings) before execution. The user must explicitly approve before the Executor node runs. If the user requests changes, natural-language feedback is injected back into the Modifier node.

A `REQUIRE_HUMAN_APPROVAL` flag in Feature 3 (default: `false`) can require explicit approval before executing any generated SQL query.
