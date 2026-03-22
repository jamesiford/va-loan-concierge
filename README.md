# VA Loan Concierge

A multi-agent demo for a VA mortgage lender built on **Microsoft Azure AI Foundry**. The application showcases three distinct Foundry capabilities — **Foundry IQ** (grounded knowledge-base RAG), **MCP** (live tool invocation via a custom Azure Function), and **Work IQ Calendar** (Microsoft-hosted MCP for M365 calendar management) — working together in a coordinated agent workflow.

Two orchestration paths share the same sub-agents:
- **React UI demo** — Python backend with real-time SSE streaming and an Agent Flow Log
- **Copilot Studio / Teams** — Foundry Workflow Agent (declarative YAML, no container needed)

---

## What It Does

A Veteran borrower interacts with a single chat interface. A single query like:

> *"I'm thinking about refinancing — am I eligible for an IRRRL, and can you show me what I'd save and schedule a call for Thursday?"*

…triggers a multi-agent pipeline that:

1. Answers VA loan eligibility questions with **cited, knowledge-base-grounded responses**
2. Runs a **live refinance savings calculator** using real amortization math
3. **Books a consultation appointment** with a loan officer
4. **Creates a calendar event** on the Veteran's M365 calendar via Work IQ
5. Streams every step of the reasoning — agent activations, tool calls, source citations — to a real-time Agent Flow Log in the UI

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React UI)                        │
│                                                                   │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐ │
│  │      Chat Panel      │   │        Agent Flow Log            │ │
│  │  (conversation)      │   │   (live reasoning trace)         │ │
│  └──────────┬───────────┘   └──────────────────────────────────┘ │
└─────────────┼───────────────────────────────────────────────────┘
              │ POST /api/chat  (SSE stream)
              ▼
┌─────────────────────────┐
│     FastAPI Backend     │   Streams SSE events to the UI
│     (api/server.py)     │
└────────────┬────────────┘
             │
             ▼
┌────────────────────────┐
│      Orchestrator      │   LLM-driven routing via Foundry agent
│  (orchestrator_agent)  │   Foundry portal: va-loan-orchestrator
└────────┬───────────────┘
         │
    ┌────┼──────────┬──────────────┐
    │    │          │              │
    ▼    ▼          ▼              ▼
┌──────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Advis-│ │Calcul- │ │Scheduler │ │Calendar  │
│ or   │ │ ator   │ │  Agent   │ │  Agent   │
│Agent │ │ Agent  │ │          │ │          │
│      │ │        │ │Custom MCP│ │Work IQ   │
│Fndry │ │Custom  │ │appt_     │ │Calendar  │
│  IQ  │ │  MCP   │ │scheduler │ │CreateEvt │
└──┬───┘ └───┬────┘ └────┬─────┘ └────┬─────┘
   │         │           │            │
   ▼         ▼           ▼            ▼
 Azure AI  Savings    Appointment   M365
 Search KB Calculator Booking      Calendar
 (3 docs)
```

### Agent Roles

| Agent | Foundry Name | Capability | Purpose |
|---|---|---|---|
| Orchestrator | `va-loan-orchestrator` | New Foundry agent (Responses API) | LLM-driven routing — classifies each query and decides which agent(s) to invoke |
| VA Loan Advisor | `va-loan-advisor-iq` | Foundry IQ via MCPTool | Answers eligibility, product, and process questions grounded in 3 knowledge sources |
| Loan Calculator | `va-loan-calculator-mcp` | Custom MCP via MCPTool | Runs refinance savings calculations via Azure-hosted MCP tools |
| Loan Scheduler | `va-loan-scheduler-mcp` | Custom MCP via MCPTool | Books consultation appointments with loan officers via Azure-hosted MCP tools |
| Calendar | `va-loan-calendar-mcp` | Work IQ Calendar via MCPTool | Creates calendar events on the Veteran's M365 calendar after appointment booking |
| Workflow | `va-loan-concierge-workflow` | Foundry Workflow Agent | Declarative orchestration for Copilot Studio / Teams (routes to all sub-agents) |

---

## Key Features

### Foundry IQ — Grounded Knowledge Base (Advisor Agent)

The Advisor Agent connects to an **Azure AI Search Knowledge Base** created in the Foundry portal. It uses the MCP protocol with `ProjectManagedIdentity` auth — no API keys.

**Knowledge sources (3 documents):**
- `va_guidelines.md` — VA eligibility rules, COE requirements, IRRRL rules, funding fee tables, entitlement, MPRs
- `lender_products.md` — Lender loan products, IRRRL, Cash-Out Refi, VA Jumbo, overlays
- `loan_process_faq.md` — Borrower FAQ, process steps, myths, edge cases (deployed borrowers, second-time use)

Every factual claim in the response includes a **citation marker** (`【idx†source】`) that is extracted, resolved to a filename, and streamed to the UI as a source chip in the Agent Flow Log.

### Custom MCP Server — Live Tool Invocation (Calculator + Scheduler Agents)

The Calculator and Scheduler agents each connect to an **Azure Function App** (`mcp-server/`) that implements the MCP JSON-RPC protocol directly over HTTP. No `mcp` Python package is required — the Function App handles `initialize`, `tools/list`, `tools/call`, and `ping` as a plain HTTP trigger.

**MCP Tools:**

**`refi_savings_calculator`** (Calculator Agent) — Real amortization math (not hardcoded):
- Inputs: `current_rate`, `new_rate`, `balance`, `remaining_term`, `funding_fee_exempt`
- Computes: monthly payment delta, annual savings, break-even timeline, lifetime savings net of closing costs
- Applies actual VA IRRRL closing cost structure ($4,050 base + 0.5% funding fee, waived if disability-exempt)
- Returns whether the **VA net tangible benefit test** passes (break-even ≤ 36 months)

**`appointment_scheduler`** (Scheduler Agent) — Books a consultation slot:
- Inputs: `preferred_day`, `preferred_time`, optional `loan_officer`
- Normalizes fuzzy inputs ("morning", "afternoon", "thurs")
- Returns a confirmed slot with loan officer name, calendar date, and a stable confirmation number
- Appointment type is context-aware: "IRRRL review and rate lock" for existing loan holders, "VA Loan Consultation" for first-time buyers

### Work IQ Calendar — M365 Calendar Integration (Calendar Agent)

The Calendar Agent connects to **Microsoft's Work IQ Calendar MCP server** — a Microsoft-hosted MCP endpoint for M365 calendar management. After the Scheduler Agent confirms an appointment, the Calendar Agent calls `CreateEvent` to place it on the Veteran's calendar.

### LLM-Driven Routing

The Orchestrator classifies each query by calling the `va-loan-orchestrator` Foundry agent via the Responses API. The response is a JSON routing decision `{"needs_advisor": bool, "needs_calculator": bool, "needs_scheduler": bool}`. Keyword matching serves as a fallback if the LLM call fails. When scheduling is needed, the Calendar Agent runs automatically after the Scheduler Agent.

### Real-Time SSE Streaming

Every step of the agent pipeline emits a structured event streamed to the browser as **Server-Sent Events**. The UI renders each event as it arrives — no polling.

| Event Type | Meaning |
|---|---|
| `orchestrator_start` | Query received, analyzing intent |
| `orchestrator_route` | Routing decision emitted |
| `plan` | Agent chain plan shown to user |
| `advisor_start` | Advisor Agent activated |
| `advisor_source` | Knowledge source queried / citation found |
| `advisor_result` | Advisor answer ready |
| `calculator_start` | Calculator Agent activated |
| `calculator_tool_call` | Calculator MCP tool invoked (shows tool name + inputs) |
| `calculator_tool_result` | Calculator MCP tool returned (shows key outputs) |
| `scheduler_start` | Scheduler Agent activated |
| `scheduler_tool_call` | Scheduler MCP tool invoked (shows tool name + inputs) |
| `scheduler_tool_result` | Scheduler MCP tool returned (shows key outputs) |
| `calendar_start` | Calendar Agent activated |
| `calendar_tool_call` | Work IQ Calendar tool invoked (shows tool name + inputs) |
| `calendar_tool_result` | Work IQ Calendar tool returned |
| `handoff` | Control passed between agents |
| `complete` | Full response ready |

### Demo Borrower Profiles

Three selectable borrower profiles inject personalized context into every agent query, making the demo more realistic and demonstrating how the same pipeline handles different scenarios:

| Profile | Background | Demo Scenario |
|---|---|---|
| **Marcus T.** | Army Veteran, 10% service-connected disability, existing VA loan at 6.8% | IRRRL flagship — funding fee exempt, full savings calc + booking |
| **Sarah K.** | Navy Veteran, first-time VA buyer, no existing loan | Purchase eligibility — correctly blocked from IRRRL (no existing loan), gets "VA Loan Consultation" appointment type |
| **Lt. James R.** | Active duty, OCONUS deployed, second VA loan use | Second-use eligibility + refi calc on a higher balance |

When no profile is selected, agents are instructed to gather personal details conversationally.

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| API server | FastAPI + uvicorn (SSE streaming) |
| Foundry SDK | `azure-ai-projects >= 2.0.1` (new-agent API — not classic) |
| Auth | `azure-identity` (`DefaultAzureCredential`) |
| MCP server | Azure Functions v2 (plain HTTP trigger, no `mcp` package) |
| ARM provisioning | `requests` — RemoteTool connection PUT at startup |
| Env management | `python-dotenv` |
| Tests | `pytest` — 98 tests across all agents |

### Frontend

| Component | Technology |
|---|---|
| Framework | React 18 + Vite |
| Styling | Tailwind CSS v3 |
| Streaming | Native `fetch` with SSE parsing |
| Fonts | Poppins (header) + DM Sans (body) |
| Dev proxy | Vite → FastAPI on port 8000 |

---

## Project Structure

```
va-loan-concierge/
├── main.py                      # Thin CLI entry point — imports Orchestrator + profiles
├── profiles.py                  # DEMO_PROFILES + context injection helpers
├── workflow.yaml                # Foundry Workflow Agent definition (Copilot Studio / Teams)
├── deploy_workflow.py           # Registers sub-agents + uploads workflow to Foundry
├── requirements.txt
│
├── agents/
│   ├── orchestrator_agent.py    # Orchestrator — LLM routing + sub-agent coordination
│   ├── advisor_agent.py         # Foundry IQ KB via MCPTool + ARM connection provisioning
│   ├── calculator_agent.py      # Custom MCP — refi savings calculator
│   ├── scheduler_agent.py      # Custom MCP — appointment booking
│   └── calendar_agent.py       # Work IQ Calendar MCP — M365 calendar events
│
├── api/
│   └── server.py                # FastAPI — POST /api/chat SSE endpoint
│
├── mcp-server/
│   ├── function_app.py          # Azure Function HTTP trigger — MCP JSON-RPC handler
│   ├── server.py                # Tool implementations + MCP inputSchema definitions
│   ├── host.json                # routePrefix: "" → endpoint at /mcp
│   └── requirements.txt         # azure-functions only
│
├── knowledge/
│   ├── va_guidelines.md
│   ├── lender_products.md
│   └── loan_process_faq.md
│
├── tools/                       # Reference implementations (not imported by agents)
│   ├── refi_calculator.py
│   └── appointment_scheduler.py
│
├── ui/
│   └── src/
│       ├── App.jsx              # Root layout + borrower profile state
│       ├── components/
│       │   ├── BorrowerProfile.jsx  # Profile selector + detail card
│       │   ├── ChatPanel.jsx        # Conversation thread + demo query buttons
│       │   ├── ChatMessage.jsx      # Message bubble (user, assistant, plan, handoff)
│       │   ├── ChatInput.jsx        # Textarea + send button
│       │   ├── AgentFlowLog.jsx     # Streaming event log panel
│       │   ├── FlowEvent.jsx        # Single log row
│       │   └── StatusDot.jsx        # Header status indicator
│       └── hooks/
│           └── useAgentStream.js    # SSE connection, mock mode, profile_id injection
│
└── tests/
    ├── conftest.py
    ├── test_advisor_agent.py
    ├── test_calculator_agent.py
    ├── test_scheduler_agent.py
    ├── test_calendar_agent.py
    └── test_orchestrator.py
```

---

## Prerequisites

- Python 3.12+ (3.13 recommended; 3.11 has an f-string backslash limitation that affects `advisor_agent.py`)
- Node.js 18+
- Azure CLI — `az` must be on your PATH
- [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) v4+ — only needed to deploy the MCP server
- An Azure AI Foundry project with:
  - A model deployment (e.g. `gpt-4.1`)
  - A Foundry IQ Knowledge Base (Azure AI Search-backed index)
  - An Azure Function App deployed from `mcp-server/`
  - A Work IQ Calendar connection (for the Calendar Agent)

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
# Foundry Project
FOUNDRY_PROJECT_ENDPOINT=https://<your-project>.services.ai.azure.com
FOUNDRY_MODEL_DEPLOYMENT=gpt-4o
AZURE_SUBSCRIPTION_ID=<subscription-id>
FOUNDRY_PROJECT_RESOURCE_ID=/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/.../projects/...

# Foundry IQ Knowledge Base (Advisor Agent)
ADVISOR_KNOWLEDGE_BASE_NAME=kb-va-loan-guidelines
ADVISOR_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
ADVISOR_MCP_CONNECTION=kb-va-loan-demo-mcp

# Custom MCP Server / Azure Function App (Calculator + Scheduler Agents)
MCP_TOOLS_ENDPOINT=https://<function-app>.azurewebsites.net/mcp
MCP_TOOLS_CONNECTION=va-loan-action-mcp-conn

# Work IQ Calendar (Calendar Agent)
SCHEDULER_CALENDAR_ENDPOINT=https://<workiq-calendar-mcp-url>
SCHEDULER_CALENDAR_CONNECTION=WorkIQCalendar
```

---

## Running & Deployment

### 1. Local Development — Full Stack (UI + Backend)

The standard way to run the demo. The Vite dev server proxies `/api` to FastAPI on port 8000.

```bash
# Authenticate — required for DefaultAzureCredential (picks up az CLI token)
az login

# Install Python dependencies (first time or after requirements.txt changes)
pip install -r requirements.txt

# Terminal 1 — start the FastAPI backend
uvicorn api.server:app --reload --port 8000

# Terminal 2 — install Node deps (first time only), then start Vite
cd ui
npm install        # first time only
npm run dev
# → UI available at http://localhost:5173
```

---

### 2. CLI Only (No UI)

Runs the flagship demo query end-to-end in the terminal. Useful for verifying the full agent pipeline without the UI.

```bash
az login
pip install -r requirements.txt

# Run the flagship IRRRL scenario (default query in main.py)
python main.py

# Or pass a custom query
python main.py --query "Can I use my VA loan benefit a second time?"
python main.py --query "Am I eligible for an IRRRL?" --profile marcus
```

---

### 3. Tests

```bash
pytest tests/     # 98 tests — all agents mocked, no Azure calls
```

---

### 4. Deploy the MCP Server (Azure Function App)

The MCP server lives in `mcp-server/` and must be deployed to an Azure Function App before the Calculator and Scheduler agents can call it. Deploy whenever you change tool implementations in `mcp-server/server.py`.

```bash
# Authenticate
az login

# Install Azure Functions Core Tools if not already present
# https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local

# Deploy to your Function App
cd mcp-server
func azure functionapp publish <your-function-app-name>

# The MCP endpoint will be at:
# https://<your-function-app-name>.azurewebsites.net/mcp
# (not /api/mcp — routePrefix is "" in host.json)

# After deploying, update MCP_TOOLS_ENDPOINT in .env to match
```

> **Auth note:** The Function App uses `AuthLevel.ANONYMOUS` — no function key is required. The MCP connection registered via ARM uses `authType: "None"`.

---

### 5. Deploy the Workflow Agent (Copilot Studio / Teams)

The workflow agent provides a second orchestration path — declarative, no container needed. It uses the same sub-agents as the Python backend.

```bash
az login
python deploy_workflow.py
```

This registers all five sub-agents (orchestrator, advisor, calculator, scheduler, calendar) and uploads `workflow.yaml` as a `WorkflowAgentDefinition`.

Test in the Foundry portal: **Build → Agents → va-loan-concierge-workflow → Playground**

> **Note:** Workflow agents are in preview. The deploy script injects the required `Foundry-Features: WorkflowAgents=V1Preview` header automatically.

---

### 6. Azure RBAC Requirements

These role assignments are required for the agents to access Azure services using Managed Identity / service principal auth.

| Resource | Role | Assigned To | Why |
|---|---|---|---|
| Azure AI Services (Foundry hub) | `Azure AI User` | Service principal / Managed Identity | Foundry data plane: create/version agents, call Responses API |
| Azure AI Services (Foundry hub) | `Contributor` | Service principal | ARM management plane: PUT RemoteTool connections |
| Azure AI Search service | `Search Index Data Reader` | Foundry project managed identity | Advisor Agent KB queries |
| Azure OpenAI resource | `Cognitive Services OpenAI User` | Search service managed identity | KB indexer skillset |

> **Note:** `Contributor` alone is not sufficient for Foundry data plane operations (creating agents, calling the Responses API). `Azure AI User` is the correct role (not `Azure AI Developer`).

The search service auth mode must be set to `aadOrApiKey` (not `apiKeyOnly`) — otherwise bearer token auth returns 403.

```bash
# Assign Search Index Data Reader to the Foundry project's managed identity
az role assignment create \
  --role "Search Index Data Reader" \
  --assignee <foundry-project-managed-identity-object-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Search/searchServices/<search-service>

# Assign Cognitive Services OpenAI User to the search service's managed identity
az role assignment create \
  --role "Cognitive Services OpenAI User" \
  --assignee <search-service-managed-identity-object-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<openai-resource>
```

---

## Demo Script

Run the flagship scenario from the CLI:

```bash
python main.py
```

Default query:
> *"I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, and can you show me what I'd save and schedule a call for Thursday?"*

Expected output:
1. Orchestrator classifies as mixed (advisor + calculator + scheduler)
2. Advisor answers IRRRL eligibility from KB with source citations
3. Calculator Agent runs `refi_savings_calculator` → monthly savings, break-even, VA benefit test result
4. Scheduler Agent calls `appointment_scheduler` → confirmed slot with reference number
5. Calendar Agent calls `CreateEvent` → appointment added to M365 calendar
6. Orchestrator synthesizes a single unified response

Or use the UI for the full streaming experience with the Agent Flow Log.

---

## What This Demo Proves

| Capability | Demonstrated By |
|---|---|
| Foundry IQ / grounded RAG | Advisor Agent answering from 3 knowledge sources with inline citations |
| Custom MCP server | Azure Function App implementing MCP JSON-RPC — no SDK dependency |
| Work IQ Calendar | Calendar Agent creating M365 events via Microsoft-hosted MCP |
| Multi-agent orchestration | Single query routed to four specialized agents, responses synthesized |
| LLM-driven routing | Orchestrator Foundry agent classifies intent via Responses API |
| New Foundry agent API | All five agents registered via `create_version` + `PromptAgentDefinition` |
| Real-time streaming | Every agent step streamed to the browser as SSE events |
| Profile-aware responses | Borrower context injected per-query; calculator uses real loan parameters |
| Governed, citable AI | Every factual claim traces back to a specific knowledge document |
| Workflow agent | Declarative YAML orchestration for Copilot Studio / Teams — same sub-agents, no container |
