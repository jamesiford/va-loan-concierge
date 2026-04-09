# Copilot Instructions — VA Loan Concierge

## Project Overview

Multi-agent demo for a VA mortgage lender using **Microsoft Foundry** (new, `azure-ai-projects` 2.x).
Five specialized agents orchestrated via a Python backend, streamed to a React UI via SSE.

- **Advisor Agent** — Foundry IQ (grounded RAG from 11 knowledge docs via Azure AI Search KB)
- **Calculator Agent** — MCP tool (`refi_savings_calculator`) via Azure Function App
- **Scheduler Agent** — MCP tool (`appointment_scheduler`) via same Function App
- **Calendar Agent** — Work IQ Calendar MCP (`CreateEvent` on M365)
- **Newsletter Agent** — Foundry IQ (queries KB for weekly market digest)
- **Orchestrator** — LLM-based routing → sub-agent calls → SSE event streaming

## Architecture

```
React UI → POST /api/chat (SSE) → FastAPI → Orchestrator → [Advisor|Calculator|Scheduler|Calendar|Newsletter]
```

- Backend: `api/server.py` (FastAPI + uvicorn, port 8000)
- Frontend: `ui/` (React 18 + Vite + Tailwind, port 5173, proxies /api → :8000)
- MCP Server: `mcp-server/` (Azure Function App, JSON-RPC at /mcp)
- Workflow: `workflow.yaml` (Foundry Workflow Agent for Teams/Copilot Studio path)
- IaC: `infra/` (Bicep + azd, next-gen Foundry resource model)

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI, uvicorn, `azure-ai-projects >= 2.0.1` |
| Frontend | React 18, Vite, Tailwind CSS v3, lucide-react |
| Auth | `azure-identity` (`DefaultAzureCredential`) — never API keys |
| MCP | Custom Azure Function App + Work IQ Calendar (Microsoft-hosted) |
| KB | Foundry IQ via MCPTool → Azure AI Search (vectorized blob storage) |
| State | Cosmos DB NoSQL (serverless, async via `azure.cosmos.aio`, 10-min TTL) |
| Observability | OpenTelemetry → Azure Monitor + Foundry portal tracing |
| IaC | Bicep + `azd up` (next-gen `CognitiveServices/accounts` kind `AIServices`) |

**IMPORTANT**: This uses the **new** Foundry API (`azure-ai-projects` 2.x / Responses API).
NOT compatible with classic Foundry SDK (1.x / Threads+Runs). Do NOT import classic patterns.

## Coding Conventions

- All agent calls are **async/await** — no synchronous blocking
- **Type hints required** on all function signatures
- Each agent is a self-contained async class in its own file under `agents/`
- Env vars loaded via `python-dotenv` — never hardcode endpoints, model names, or credentials
- Use `logging` (not `print`) for all runtime output
- MCP tool inputs/outputs use plain dicts (JSON); agents parse `response.output`
- Knowledge base docs are plain Markdown in `knowledge/`
- Prefer minimal diffs — don't refactor code unrelated to the task
- Ask before introducing new dependencies
- All tests must pass before completion (`pytest tests/` — 114 tests)

## SSE Stream Format

Backend streams newline-delimited JSON events. The UI depends on these exact `type` values:

| Event Type | Agent Color | Purpose |
|---|---|---|
| `orchestrator_start` | Navy | Query received |
| `orchestrator_route` | Navy | Routing decision |
| `plan` | Gray | Agent chain preview |
| `advisor_start/source/result` | Amber | Advisor lifecycle |
| `calculator_start/tool_call/tool_result` | Blue | Calculator lifecycle |
| `scheduler_start/tool_call/tool_result` | Teal | Scheduler lifecycle |
| `calendar_start/tool_call/tool_result` | Rose | Calendar lifecycle |
| `newsletter_start/tool_call/tool_result/complete` | — | Newsletter lifecycle |
| `handoff` | Gray | Agent transition |
| `partial_response` | — | Per-agent content (has `agent`, `label`, `content`) |
| `await_input` | Navy | HIL pause (has `conversation_id`, `suggestions`) |
| `complete` | Green | Response ready |
| `error` | Red | Failure |

## Human-in-the-Loop (HIL)

Two HIL flows managed via `api/conversation_state.py` (Cosmos DB + in-memory fallback):

1. **Calculator HIL**: When `profile_id=None` + `needs_calculator`, pause to collect loan details.
   Up to 3 retries. Skip keywords: `skip`, `move on`, `don't calculate`, `no calc`, `forget it`,
   `never mind`, `use defaults`, `default`.

2. **Appointment Confirmation HIL**: After scheduler books, pause for confirm/reschedule/decline.
   - Confirm (12 keywords) → Calendar Agent creates M365 event
   - Reschedule (16 keywords) → re-run scheduler with new preference
   - Decline (6 keywords) → skip calendar, appointment still confirmed
   - Unrecognized → move on without calendar event

State: `ConversationState` dataclass with `pending_action`, `calculator_retry_count`,
`user_provided_details`, etc. Persisted to Cosmos DB via `save_conversation()`.

## Orchestrator Routing

5-way classification: `needs_advisor`, `needs_calculator`, `needs_scheduler`,
`needs_newsletter`, plus `response` for general/meta queries.

Newsletter keywords: `digest`, `newsletter`, `market intel`, `weekly update`, `market update`,
`industry news`, `mortgage news`, `rate news`, `weekly digest`, `rate trends`, etc.

## Borrower Profiles (`profiles.py`)

| Profile | Scenario |
|---|---|
| `marcus` | Army, 10% disability (fee exempt), existing VA loan at 6.8% — IRRRL flagship |
| `sarah` | Navy, first-time buyer, no existing loan — purchase, no refi calc |
| `james` | Active duty, OCONUS, second VA use — higher balance, no fee exemption |

Context injection: `_profile_context_block()` prepends borrower info; `_demo_context_block()`
appends tool params. Refi calc params always injected from profile. Appointment day/time
NEVER injected (extracted from user query).

## Key Commands

```bash
# Backend
pip install -r requirements.txt
uvicorn api.server:app --reload --port 8000

# Frontend
cd ui && npm install && npm run dev   # → http://localhost:5173

# Tests
pytest tests/                         # 114 tests

# CLI demo
python main.py
python main.py --query "Can I use my VA loan a second time?"

# Evaluations
python evals/run_eval.py --all

# MCP server (local)
cd mcp-server && func host start

# Infrastructure
azd up    # provisions everything
azd down  # tears down
```

## Design Tokens (CSS Variables)

```css
--color-brand-red:   #C8102E;   --color-brand-navy:  #002244;
--color-brand-gold:  #B8941F;   --color-surface:     #F8F7F4;
--color-panel:       #FFFFFF;   --color-border:      #E5E2DC;
--color-advisor:     #92400E;   --color-calculator:  #1E40AF;
--color-scheduler:   #0E7490;   --color-calendar:    #BE185D;
--color-orchestrator:#002244;   --color-success:     #15803D;
```

Use CSS custom properties from `ui/src/index.css` — don't hardcode hex in components.
Tailwind classes only — no inline styles, CSS modules, or styled-components.

## MCP Patterns

- One MCP tool per agent per Responses API call (reliable pattern)
- `allowed_tools` uses raw MCP tool names (e.g. `CreateEvent`, NOT `mcp_CalendarTools_graph_createEvent`)
- `require_approval="never"` on all MCPTool registrations
- Each agent calls `create_version()` on startup (version increments in Foundry portal)
- MCP server at `/mcp` (not `/api/mcp`) — `routePrefix: ""` in host.json
- `mcp-server/server.py` validates all tool inputs before execution

## Current Project Status

**Complete:** Phases 1–8, 10, 13–15 (foundation, agents, KB, MCP, workflow, IaC, guardrails,
evals, observability, Cosmos state, content understanding, newsletter).

**Next:** Phase 15b (ACS email delivery for newsletter).

**Blocked on VM quota:** Phase 9 (Web App) → Phase 11 (Auth) → Phase 12 (Network) → Phase 16 (Memory).

## Important Gotchas

- `azure-ai-projects` 2.x only — NOT classic 1.x (Threads/Runs model is deprecated)
- `ConnectedAgentTool` is deprecated; `A2APreviewTool` is for cross-system only
- Foundry IQ KB created manually in portal (SDK unreliable for KB creation)
- Work IQ Calendar `allowed_tools` must use raw name `CreateEvent`
- No `conversationId` on workflow `InvokeAzureAgent` nodes (prevents history buildup)
- `mcp-server/` files are flat copies (Function App can't import from parent dirs)
  - `postprovision.ps1` syncs: `content_ingestion.py`, `newsletter_agent.py`, `feed_sources.json`
- Newsletter agent strips `【idx†source】` citation markers before rendering
- Function App uses `resolve_version()` (looks up latest) — backend is sole owner of agent registration

## Reference

Full architectural detail, phase plans, and implementation history: see `CLAUDE.md` (root).
The CLAUDE.md remains the authoritative design document for this project.