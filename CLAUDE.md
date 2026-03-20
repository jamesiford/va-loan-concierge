# CLAUDE.md — VA Loan Concierge
## Multi-Agent Demo | Azure Microsoft Foundry (New)

---

## Project Overview

This project is a demonstration of Microsoft Foundry's multi-agent capabilities for a
**VA mortgage lender**. It showcases two distinct Foundry capabilities working together
in a coordinated agent workflow:

- **Foundry IQ** — grounded, knowledge-base-backed question answering across multiple sources
- **MCP (Model Context Protocol)** — live tool invocation for real-time calculations and actions

A Veteran borrower interacts with a single conversational interface. Behind the scenes, an
orchestrator routes their query to one or both specialized agents and synthesizes a unified response.

### The Demo Scenario
A Veteran asks about refinancing their existing VA loan:
> *"I'm thinking about refinancing — am I eligible for an IRRRL, and if so, can you show me
> what I'd save and book a call with someone?"*

This single query triggers both agents:
1. The **VA Loan Advisor Agent** answers eligibility questions from the knowledge base
2. The **Loan Action Agent** runs a savings calculator and schedules an appointment via MCP tools
3. The **Orchestrator** combines both responses into one cohesive reply

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Browser (React UI)                  │
│                                                      │
│  ┌──────────────────┐   ┌────────────────────────┐  │
│  │   Chat Input     │   │   Agent Flow Log       │  │
│  │  (prompt + send) │   │  (reasoning/handoffs)  │  │
│  └────────┬─────────┘   └────────────────────────┘  │
└───────────┼─────────────────────────────────────────┘
            │ HTTP POST /api/chat (SSE stream)
            ▼
┌───────────────────────┐
│   FastAPI Backend     │  Streams agent events as SSE
│   (api/server.py)     │
└──────────┬────────────┘
           │
           ▼
┌─────────────────────┐
│    Orchestrator      │  Routes queries, emits stream events
│   (main.py)         │
└──────────┬──────────┘
           │
     ┌─────┴──────┐
     │            │
     ▼            ▼
┌─────────┐  ┌─────────────┐
│ Advisor │  │   Action    │
│  Agent  │  │    Agent    │
│         │  │             │
│ Foundry │  │  MCP Tools  │
│   IQ    │  │             │
└─────────┘  └─────────────┘
    │              │
    ▼              ▼
Knowledge      Tool Results
Base Docs    (Calculator +
             Scheduler)
```

---

## Agent Descriptions

### 1. VA Loan Advisor Agent (`agents/advisor_agent.py`)
- **Capability**: Foundry IQ — grounded RAG across multiple knowledge sources
- **Purpose**: Answers VA loan eligibility, product, and process questions with cited,
  accurate responses grounded in authoritative documents
- **Knowledge Base Sources** (3 simulated document sets):
  - `knowledge/va_guidelines.md` — VA eligibility rules, COE requirements, IRRRL rules,
    funding fee tables, entitlement calculations, Minimum Property Requirements (MPRs)
  - `knowledge/lender_products.md` — Lender loan products: IRRRL, Cash-Out Refi,
    VA Jumbo, VA Renovation; lender-specific overlays and requirements
  - `knowledge/loan_process_faq.md` — Common borrower questions, homebuying process steps,
    myths and misconceptions, edge cases (deployed borrowers, second-time use, appraisal gaps)
- **Behavior**: Always cites which knowledge source supports each answer; declines to
  speculate on information not found in the knowledge base; defers action requests to the
  Action Agent

### 2. Loan Action Agent (`agents/action_agent.py`)
- **Capability**: MCP — live tool invocation via MCP server
- **Purpose**: Performs real-time calculations and scheduling actions on behalf of the Veteran
- **MCP Tools** (2 simulated tools):
  - `refi_savings_calculator` — Given current rate, new rate, loan balance, and remaining
    term, returns monthly savings, annual savings, and break-even timeline
  - `appointment_scheduler` — Given a preferred day/time and loan officer name, returns a
    confirmed appointment slot with a confirmation number
- **Behavior**: Always surfaces tool inputs and outputs transparently; confirms actions
  with the user before booking; returns structured results for the orchestrator to format

### 3. Orchestrator (`main.py`)
- **Purpose**: Entry point and coordinator; receives the user query, determines which
  agent(s) to invoke, collects results, and synthesizes a single unified response
- **Routing Logic**:
  - Knowledge/eligibility questions → Advisor Agent only
  - Calculator/scheduling requests → Action Agent only
  - Mixed queries (like the demo scenario) → both agents in sequence, results merged
- **Response Format**: Presents advisor answer first (context/eligibility), then action
  results (savings figures, appointment confirmation), in a single readable reply

---

## Frontend UI (`ui/`)

### Overview
A React single-page application that provides the chat interface for the demo. The UI is
split into two panels side-by-side on desktop (stacked on mobile):

- **Left panel — Chat**: Conversation history between the Veteran and the concierge.
  Shows the user's prompt and the final synthesized response in a clean message thread.
- **Right panel — Agent Flow Log**: A real-time, streaming log that visualizes the
  reasoning and handoff chain as it happens — which agent is active, what tools were
  called, what sources were consulted, and when control passes between agents.

### UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🏠  VA Loan Concierge                             [status dot] │  ← Header
├──────────────────────────────┬──────────────────────────────────┤
│                              │                                  │
│      CHAT                    │      AGENT FLOW LOG              │
│                              │                                  │
│  ┌────────────────────────┐  │  ┌──────────────────────────┐   │
│  │  [User message]        │  │  │ ⬡ Orchestrator           │   │
│  └────────────────────────┘  │  │   Analyzing query...     │   │
│                              │  │   → Routing: BOTH agents │   │
│  ┌────────────────────────┐  │  └──────────────────────────┘   │
│  │  [Concierge response]  │  │  ┌──────────────────────────┐   │
│  │  (final answer)        │  │  │ 📚 Advisor Agent         │   │
│  └────────────────────────┘  │  │   Querying: va_guidelines│   │
│                              │  │   Querying: lender_prods │   │
│                              │  │   ✓ IRRRL eligible       │   │
│                              │  └──────────────────────────┘   │
│                              │  ┌──────────────────────────┐   │
│                              │  │ ⚙️  Action Agent          │   │
│                              │  │   Tool: refi_calculator  │   │
│                              │  │   Tool: appt_scheduler   │   │
│                              │  │   ✓ Confirmed: THU 2pm   │   │
│                              │  └──────────────────────────┘   │
│                              │  ┌──────────────────────────┐   │
│                              │  │ ⬡ Orchestrator           │   │
│                              │  │   Synthesizing response  │   │
│                              │  │   ✓ Complete             │   │
│                              │  └──────────────────────────┘   │
│                              │                                  │
├──────────────────────────────┴──────────────────────────────────┤
│  [ Type your question here...                    ] [Send →]     │  ← Input bar
└─────────────────────────────────────────────────────────────────┘
```

### Agent Flow Log Event Types
Each event in the log has a **type**, **icon**, **agent label**, and **message**. The
backend streams these as Server-Sent Events (SSE); the UI renders them as they arrive.

| Event Type | Icon | Color | Meaning |
|---|---|---|---|
| `orchestrator_start` | ⬡ | Indigo | Orchestrator received query, analyzing intent |
| `orchestrator_route` | → | Indigo | Routing decision: which agent(s) will respond |
| `advisor_start` | 📚 | Amber | Advisor Agent activated |
| `advisor_source` | 🔍 | Amber | Querying a specific knowledge source |
| `advisor_result` | ✓ | Green | Advisor returned a result |
| `action_start` | ⚙️ | Blue | Action Agent activated |
| `action_tool_call` | 🔧 | Blue | MCP tool being invoked (shows tool name + inputs) |
| `action_tool_result` | ✓ | Green | MCP tool returned a result (shows key outputs) |
| `handoff` | ⇄ | Purple | Control passed between agents |
| `orchestrator_synthesize` | ⬡ | Indigo | Orchestrator merging results |
| `complete` | ✓ | Green | Full response ready |
| `error` | ✗ | Red | Something went wrong |

### SSE Stream Format
The backend (`api/server.py`) streams newline-delimited JSON events to the UI:

```json
{"type": "orchestrator_start", "message": "Analyzing your query..."}
{"type": "orchestrator_route", "message": "Routing to: Advisor Agent + Action Agent"}
{"type": "advisor_start", "message": "VA Loan Advisor activated"}
{"type": "advisor_source", "message": "Querying: va_guidelines.md"}
{"type": "advisor_source", "message": "Querying: lender_products.md"}
{"type": "advisor_result", "message": "IRRRL eligibility confirmed (2 sources cited)"}
{"type": "handoff", "message": "Advisor → Action Agent"}
{"type": "action_start", "message": "Loan Action Agent activated"}
{"type": "action_tool_call", "message": "refi_savings_calculator", "inputs": {"current_rate": 6.8, "new_rate": 6.1, "balance": 320000, "remaining_term": 27}}
{"type": "action_tool_result", "message": "Monthly savings: $142 | Break-even: 19 months"}
{"type": "action_tool_call", "message": "appointment_scheduler", "inputs": {"day": "Thursday", "time": "2:00 PM"}}
{"type": "action_tool_result", "message": "Confirmed: Thu Mar 26 @ 2:00 PM | Ref #LOAN-84921"}
{"type": "orchestrator_synthesize", "message": "Merging advisor + action results..."}
{"type": "complete", "message": "Response ready"}
{"type": "final_response", "content": "...the full synthesized answer text..."}
```

### UI Tech Stack

| Component | Technology | Notes |
|---|---|---|
| Framework | React 18 + Vite | Fast dev server, HMR |
| Styling | Tailwind CSS | Utility-first, responsive |
| Streaming | `EventSource` / `fetch` with SSE | Real-time log updates |
| State | React `useState` + `useReducer` | No external state lib needed |
| Icons | `lucide-react` | Consistent icon set |
| Fonts | `Inter` (body) + `DM Serif Display` (headings) | Clean professional pairing |

### Design Tokens (CSS Variables)
```css
--color-brand-red:   #C8102E;   /* Primary brand red */
--color-brand-navy:  #002244;   /* Deep navy — primary dark */
--color-brand-gold:  #B8941F;   /* Warm gold accent */
--color-surface:     #F8F7F4;   /* Off-white — main background */
--color-panel:       #FFFFFF;   /* Chat/log panel background */
--color-border:      #E5E2DC;   /* Subtle warm border */
--color-advisor:     #B45309;   /* Amber — Advisor Agent events */
--color-action:      #1D4ED8;   /* Blue — Action Agent events */
--color-orchestrator:#4F46E5;   /* Indigo — Orchestrator events */
--color-success:     #15803D;   /* Green — completed events */
```

### Key UI Behaviors
- **Streaming log**: Each SSE event appends a new row to the Agent Flow Log in real time,
  with a brief fade-in animation. The log auto-scrolls to the latest event.
- **Thinking indicator**: While a response is in progress, a pulsing indicator appears in
  the active agent's log row.
- **Tool call expansion**: `action_tool_call` events show a collapsed input summary by
  default; clicking expands to show the full structured inputs and outputs.
- **Source citation chips**: `advisor_source` events render as small pill badges showing
  which knowledge document was consulted.
- **Responsive layout**: On screens < 768px, the two panels stack vertically. The Agent
  Flow Log moves above the chat input, collapsed by default with a toggle to expand.
- **Conversation history**: Multiple turns are preserved in the chat panel. Each new
  query clears the Agent Flow Log and starts a fresh trace for that turn.
- **Demo query buttons**: Three pre-set query buttons appear above the input bar for
  quick demo use:
  - "Am I eligible for an IRRRL?"
  - "Can I use my VA loan a second time?"
  - "Refinance + book a call for Thursday" ← flagship demo query

---

## Azure / Foundry Resources

| Resource | Environment Variable | Notes |
|---|---|---|
| Foundry Project Endpoint | `PROJECT_ENDPOINT` | From Foundry portal → Overview → Endpoints |
| Model Deployment Name | `MODEL_DEPLOYMENT_NAME` | e.g. `gpt-4o` or `gpt-4.1` |
| Azure Subscription ID | `AZURE_SUBSCRIPTION_ID` | Used for DefaultAzureCredential scope |
| Foundry MCP Endpoint | `MCP_ENDPOINT` | `https://mcp.ai.azure.com` (cloud-hosted MCP) |
| Knowledge Base Index | `KNOWLEDGE_BASE_NAME` | Foundry IQ index name for advisor agent |

Authentication: `DefaultAzureCredential` for local dev (requires `az login` before running).
Never use API keys in code — always use credential objects.

---

## Project Structure

```
va-loan-concierge/
│
├── CLAUDE.md                    # This file
├── README.md                    # Human-readable project overview
├── .env                         # Local secrets — never commit
├── .env.example                 # Committed template with empty values
├── .gitignore                   # Excludes .env, __pycache__, .venv, node_modules
├── requirements.txt             # Python dependencies (backend)
│
├── main.py                      # Orchestrator entry point (CLI mode)
│
├── api/
│   ├── __init__.py
│   └── server.py                # FastAPI server — exposes /api/chat SSE endpoint
│
├── agents/
│   ├── __init__.py
│   ├── advisor_agent.py         # Foundry IQ / knowledge base agent
│   └── action_agent.py          # MCP tools agent
│
├── tools/
│   ├── __init__.py
│   ├── refi_calculator.py       # Simulated refi savings calculator tool
│   └── appointment_scheduler.py # Simulated appointment scheduling tool
│
├── knowledge/
│   ├── va_guidelines.md         # Knowledge source 1: VA rules and eligibility
│   ├── lender_products.md       # Knowledge source 2: Lender loan products
│   └── loan_process_faq.md      # Knowledge source 3: Borrower FAQ and edge cases
│
├── ui/                          # React frontend
│   ├── package.json
│   ├── vite.config.js           # Vite dev server; proxies /api to FastAPI on :8000
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx              # Root layout: header + two-panel split
│       ├── index.css            # Tailwind directives + CSS custom properties
│       ├── components/
│       │   ├── ChatPanel.jsx    # Conversation message thread
│       │   ├── ChatMessage.jsx  # Individual message bubble (user or concierge)
│       │   ├── ChatInput.jsx    # Prompt textarea + send button + demo query buttons
│       │   ├── AgentFlowLog.jsx # Streaming event log panel
│       │   ├── FlowEvent.jsx    # Single log row with icon, label, message
│       │   └── StatusDot.jsx    # Header connection/activity indicator
│       └── hooks/
│           └── useAgentStream.js # Custom hook: manages SSE connection + event state
│
└── tests/
    ├── test_advisor_agent.py
    ├── test_action_agent.py
    └── test_orchestrator.py
```

---

## Tech Stack

**Backend**

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| API Server | `FastAPI` + `uvicorn` — serves SSE stream to UI |
| Foundry SDK | `azure-ai-projects >= 2.0.0b4` (new Foundry API — NOT classic) |
| Authentication | `azure-identity` (`DefaultAzureCredential`) |
| MCP | `azure-ai-projects` MCP client + cloud-hosted MCP at `mcp.ai.azure.com` |
| Env management | `python-dotenv` |
| Testing | `pytest` |

**Frontend**

| Component | Technology |
|---|---|
| Framework | React 18 + Vite |
| Styling | Tailwind CSS v3 |
| Streaming | Native `fetch` with SSE (`EventSource`) |
| Icons | `lucide-react` |
| HTTP (dev proxy) | Vite proxy → FastAPI on port 8000 |

> **Important**: This project uses the **new Microsoft Foundry API** (`azure-ai-projects` 2.x).
> It is NOT compatible with the classic Foundry SDK (`azure-ai-projects` 1.x). Do not import
> or reference classic Foundry patterns.

---

## Coding Conventions

- All agent calls are **async/await** throughout — no synchronous blocking calls
- **Type hints required** on all function signatures
- Each agent is a self-contained class in its own file under `/agents/`
- Environment variables are always loaded via `python-dotenv` at the top of `main.py`
- MCP tool inputs and outputs use **typed dataclasses** — no raw dict passing between agents
- Knowledge base documents are plain Markdown in `/knowledge/` for readability and easy updating
- Never hardcode endpoint URLs, model names, or credentials — always from `.env`
- Use `logging` (not `print`) for all runtime output except the final user-facing response

---

## Key Commands

```bash
# ── Azure Auth (required before any backend run) ──────────────────
az login

# ── Backend ───────────────────────────────────────────────────────
# Install Python dependencies
pip install -r requirements.txt

# Start the FastAPI server (required for UI)
uvicorn api.server:app --reload --port 8000

# Run CLI demo only (no UI, uses flagship IRRRL scenario)
python main.py

# Run CLI with a custom query
python main.py --query "Can I use my VA loan benefit a second time?"

# Run tests
pytest tests/

# ── Frontend ──────────────────────────────────────────────────────
# Install Node dependencies (first time only)
cd ui && npm install

# Start Vite dev server (proxies /api → localhost:8000)
npm run dev
# → UI available at http://localhost:5173

# Build for production
npm run build

# ── Run everything (two terminals) ───────────────────────────────
# Terminal 1:  uvicorn api.server:app --reload --port 8000
# Terminal 2:  cd ui && npm run dev
```

---

## Demo Script (for presentations)

The default `python main.py` run executes the flagship demo query:

> *"I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL,
> and can you show me what I'd save and schedule a call for Thursday?"*

**Expected output flow:**
1. Orchestrator identifies this as a mixed query (knowledge + action)
2. Advisor Agent answers IRRRL eligibility from `va_guidelines.md` and `lender_products.md`,
   with source citations
3. Action Agent calls `refi_savings_calculator` with demo loan parameters, then calls
   `appointment_scheduler` for Thursday
4. Orchestrator prints a unified response showing:
   - Eligibility answer with cited sources
   - Monthly/annual savings figures with break-even timeline
   - Appointment confirmation with confirmation number

---

## What This Demo Proves

| Capability | Demonstrated By |
|---|---|
| **Foundry IQ / grounded RAG** | Advisor Agent answering from 3 knowledge sources with citations |
| **Multi-source knowledge base** | VA guidelines + lender products + borrower FAQ all queried simultaneously |
| **MCP tool invocation** | Action Agent calling calculator and scheduler as structured MCP tools |
| **Multi-agent orchestration** | Single user query routed to two agents, responses synthesized |
| **Governed, citable AI** | Every factual claim traces back to a specific knowledge document |
| **Actionable AI** | Demo ends with a real output (savings numbers + booked appointment) |

---

## UI Reference Prototype

The file `va-loan-concierge-ui.jsx` in the project root is a **fully working UI prototype**
that defines the exact target design and behavior for the frontend. It is a self-contained
single-file reference — NOT the production implementation.

When building the `ui/` frontend, Claude Code must:
- **Match the visual design exactly** — colors, layout, typography, spacing, component
  structure, and animations as implemented in the prototype
- **Replicate all behaviors** — streaming event rendering, auto-scroll, tool call expansion,
  demo query buttons, responsive panel toggle, pulsing indicators, fade-in animations
- **Use the same color values** — the `colors` object in the prototype is the source of
  truth; map these directly to the CSS custom properties in `index.css`
- **Preserve the event type handling** — the `EVENT_CONFIG` map in the prototype defines
  icons, labels, and colors for every SSE event type; replicate this in `FlowEvent.jsx`
- **Keep the simulated stream logic** — the `buildStream()` function in the prototype
  defines the demo query scenarios and event sequences; port this into `useAgentStream.js`
  as the fallback/mock mode, switchable via a `VITE_MOCK_MODE=true` env variable

The prototype may be deleted once the `ui/` implementation is complete and verified to
match it visually and behaviorally.
```

**When to invoke it with Claude Code:**

Don't reference it during the scaffold or knowledge/agent phases — it's only relevant when you get to the frontend. When you're ready to build the UI, use this prompt:

> *"Read `va-loan-concierge-ui.jsx` in the project root. This is the reference prototype for the frontend. Now implement the `ui/` folder — build each component in `ui/src/components/` to match the prototype exactly, split across the individual files defined in CLAUDE.md. Port `buildStream()` into `useAgentStream.js` as mock mode."*

**One more thing to add to `.gitignore`:**
```
# Reference prototype — not part of the build
va-loan-concierge-ui.jsx

---

## Notes for Claude Code

**Backend**
- When scaffolding agent code, always check `requirements.txt` first to confirm package
  versions before importing
- The `/knowledge/` markdown files should be populated with realistic but clearly simulated
  content — they do not need to reflect actual current VA rates or real lender pricing
- MCP tools in `/tools/` are **simulations** — they return hardcoded or lightly randomized
  realistic values; no real API calls are made in this demo
- When adding new agents, follow the pattern established in `advisor_agent.py` —
  async class, typed inputs/outputs, logging throughout
- `api/server.py` must emit SSE events using the exact `type` values defined in the
  **SSE Stream Format** table above — the UI's `useAgentStream.js` hook depends on them
- If asked to modify the orchestrator routing logic, always update this CLAUDE.md to
  reflect the change

**Frontend**
- All UI components live in `ui/src/components/` — one component per file
- The `useAgentStream` hook owns all SSE connection logic; components only consume its
  state — do not add fetch/EventSource calls directly inside components
- Use the CSS custom properties defined in `index.css` (the design token table above)
  for all colors — do not hardcode hex values in components
- The Agent Flow Log must render events in arrival order and auto-scroll to the bottom
  on each new event
- `FlowEvent.jsx` must handle all event types listed in the **Agent Flow Log Event Types**
  table — unknown types should render a generic fallback row, not throw an error
- Tailwind classes only — no inline styles, no CSS modules, no styled-components
- The Vite dev proxy in `vite.config.js` should forward `/api` to `http://localhost:8000`
  so the UI and backend can run on separate ports in development

---

## Current Status / Planned Upgrades

The end-to-end demo is working. Both agents run, SSE events stream to the UI in real time,
and the final response renders correctly with real KB grounding and citations.

---

### 1. Foundry IQ Knowledge Base (replacing FileSearch) — ✅ COMPLETE

**Implemented state:**
`AdvisorAgent` connects to an Azure AI Search Knowledge Base created in the Foundry portal
via the MCP protocol, using a `RemoteTool` project connection with `ProjectManagedIdentity`
auth. The agent is registered with `MCPTool` (not `FileSearchTool` or `AzureAISearchTool`).

**How it works:**
- `initialize()` PUTs a `RemoteTool` project connection via ARM pointing at
  `{AZURE_AI_SEARCH_ENDPOINT}/knowledgebases/{KNOWLEDGE_BASE_NAME}/mcp?api-version=2025-11-01-preview`
- The agent is registered with `MCPTool(server_label="knowledge-base", allowed_tools=["knowledge_base_retrieve"], project_connection_id=MCP_CONNECTION_NAME)`
- After the Responses API call, `response.output` contains `url_citation` annotations on
  the message item; `_extract_citations()` extracts filenames from blob URLs and emits them
  as `advisor_source` SSE events
- `_replace_citation_labels()` rewrites `【idx†source】` markers in the response text to
  `【idx†va_guidelines.md】` etc. using annotation positions

**Required env vars:**
- `KNOWLEDGE_BASE_NAME` — KB name in Azure AI Search (e.g. `kb-va-loan-guidelines`)
- `AZURE_AI_SEARCH_ENDPOINT` — search service URL (e.g. `https://search-va-loan-demo.search.windows.net`)
- `PROJECT_RESOURCE_ID` — ARM resource ID of the Foundry project
- `MCP_CONNECTION_NAME` — name for the RemoteTool connection (e.g. `kb-va-loan-demo-mcp`)

**Required Azure RBAC (on the Azure AI Search service):**
- `Search Index Data Reader` → Foundry project's managed identity
- `Cognitive Services OpenAI User` → Search service's managed identity (on the Azure OpenAI resource)
- Auth mode on the search service must be `aadOrApiKey` (not `apiKeyOnly`)

**Reference:** https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect

---

### 2. Azure-Hosted MCP Server (replacing FunctionTool) — ✅ COMPLETE

**Implemented state:**
`ActionAgent` connects to an Azure Function App (`mcp-server/`) that exposes the two tools
as an MCP-compliant HTTP endpoint. The Function App implements the MCP JSON-RPC protocol
directly (no `mcp` Python package required — pure `azure-functions` HTTP trigger). Tool
execution happens server-side; `ActionAgent` makes a single Responses API call and parses
`mcp_call` items from `response.output` to emit `action_tool_call` / `action_tool_result`
SSE events.

**How it works:**
- `initialize()` PUTs a `RemoteTool` project connection (`MCP_ACTION_CONNECTION_NAME`) via
  ARM with `authType: "None"` (anonymous Function App), then creates a new agent version
  with `MCPTool(server_url, project_connection_id, allowed_tools, require_approval="never")`
- `mcp-server/function_app.py` handles POST `/mcp` and responds to `initialize`,
  `tools/list`, `tools/call`, and `ping` JSON-RPC methods
- `mcp-server/server.py` contains the tool implementations and MCP `inputSchema` definitions
- `run()` makes a single Responses API call; `_parse_mcp_events()` extracts `mcp_call`
  output items and `_format_tool_result()` formats them into human-readable SSE messages
- All agents now always call `create_version` on startup (no reuse check) — version counter
  increments in the Foundry portal on every restart, no manual deletion needed on config changes

**Required env vars:**
- `MCP_ENDPOINT` — Function App MCP URL (e.g. `https://<app>.azurewebsites.net/mcp`)
- `MCP_ACTION_CONNECTION_NAME` — name for the RemoteTool connection (e.g. `va-loan-action-mcp-conn`)

**MCP server deployment:**
```bash
cd mcp-server
func azure functionapp publish <app-name>
```
MCP endpoint is at `/mcp` (not `/api/mcp`) due to `routePrefix: ""` in `host.json`.
The Function App uses `AuthLevel.ANONYMOUS` — no auth key required.

**Note on ASGI:** The `mcp` Python package's `AsgiFunctionApp(asgi_app=...)` constructor
is not supported on Python 3.13 Flex Consumption. The MCP JSON-RPC protocol is implemented
directly using a standard `FunctionApp` HTTP trigger instead.