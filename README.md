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

## Getting Started

### Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`)
- [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) (`azd`)
- Python 3.12+
- Node.js 18+
- An Azure subscription with permissions to create resources
- An M365 Copilot license (only needed for the Calendar Agent's Work IQ Calendar integration)

### Provision Infrastructure (`azd up`)

The entire Azure infrastructure is defined as code. A single command provisions everything, deploys the MCP server, and registers all Foundry agents.

```bash
# 1. Clone and enter the repo
git clone https://github.com/<org>/va-loan-concierge.git
cd va-loan-concierge

# 2. Authenticate with Azure
az login
azd auth login

# 3. Provision + deploy everything
azd up
```

`azd up` will prompt you for:
- **Environment name** — e.g. `valc-demo-abc123` (becomes the suffix for all resource names)
- **Azure subscription** — select from your available subscriptions
- **Azure region** — select from the curated list (eastus, eastus2, westus3, swedencentral, northcentralus)

This creates the following Azure resources:

| Resource | Name | Purpose |
|---|---|---|
| Resource Group | `rg-{env}` | Container for all resources |
| AI Services | `ais-{env}` | Foundry + OpenAI models + connections (next-gen) |
| AI Project | `proj-{env}` | Foundry project (agents live here) |
| AI Search | `srch-{env}` | Knowledge base index for Advisor Agent |
| Function App | `func-{env}` | Custom MCP server (calculator + scheduler tools) |
| Storage Account | `st{env}` | KB document blobs + Function App runtime |
| App Insights | `appi-{env}` | Monitoring + diagnostics |
| Log Analytics | `log-{env}` | Required by App Insights |

Plus 12 RBAC role assignments and 2 RemoteTool project connections — all automated.

After provisioning completes, `azd up` automatically:
1. Uploads the 3 knowledge documents to blob storage
2. Creates an AI Search data source, index, and indexer (pulls from blob → indexes automatically)
3. Provisions RemoteTool connections for the KB MCP and custom MCP endpoints
4. Deploys the MCP server code to the Function App
5. Registers all 5 Foundry agents and uploads the workflow definition

> **Updating knowledge sources:** To add or update documents, upload new files to the `knowledge-base` blob container and re-run the Search indexer. No redeployment needed.

### Configure Work IQ Calendar (Manual Step)

The Calendar Agent requires a Work IQ Calendar connection, which needs an M365 Copilot license and must be configured in the Foundry portal:

1. Open the Foundry portal → your project → **Connections**
2. Add a **Work IQ Calendar** connection
3. Copy the MCP endpoint URL and connection name, then set them:

```bash
azd env set SCHEDULER_CALENDAR_ENDPOINT <endpoint-url>
azd env set SCHEDULER_CALENDAR_CONNECTION <connection-name>
azd deploy    # re-deploys to pick up the calendar connection
```

> **Note:** The demo works without the Calendar Agent — the Advisor, Calculator, and Scheduler agents function independently. The calendar step will simply be skipped if this connection is not configured.

### Run the Demo

```bash
# Install Python dependencies
pip install -r requirements.txt

# Terminal 1 — start the FastAPI backend
uvicorn api.server:app --reload --port 8000

# Terminal 2 — start the React UI
cd ui
npm install        # first time only
npm run dev
# → Open http://localhost:5173
```

The UI provides three demo query buttons for quick testing. Select a borrower profile (Marcus, Sarah, or James) and click a query to see the full agent pipeline in action.

### Tear Down

```bash
azd down
```

This deletes the resource group and all resources within it. Clean, no orphans.

---

## Alternative: CLI-Only Mode

Run the flagship query end-to-end in the terminal without the UI:

```bash
az login
pip install -r requirements.txt

# Default flagship IRRRL scenario
python main.py

# Custom query
python main.py --query "Can I use my VA loan benefit a second time?"
```

---

## Running Tests

```bash
pytest tests/     # 98 tests — all agents mocked, no Azure calls needed
```

---

## Project Structure

```
va-loan-concierge/
├── azure.yaml                   # azd project definition (services + hooks)
├── main.py                      # Thin CLI entry point
├── profiles.py                  # DEMO_PROFILES + context injection helpers
├── workflow.yaml                # Foundry Workflow Agent definition
├── deploy_workflow.py           # Registers sub-agents + uploads workflow
├── requirements.txt
│
├── infra/                       # Infrastructure-as-code (Bicep)
│   ├── main.bicep               # Orchestrator — wires all modules
│   ├── main.parameters.json     # Maps azd env values to Bicep params
│   ├── modules/
│   │   ├── ai-services.bicep    # AI Services account (Foundry + OpenAI + connections)
│   │   ├── ai-project.bicep     # AI Project (child of AI Services)
│   │   ├── search.bicep         # AI Search (aadOrApiKey auth)
│   │   ├── function-app.bicep   # MCP server Function App
│   │   ├── storage.bicep        # Storage (KB blobs + Function App runtime)
│   │   ├── monitoring.bicep     # Log Analytics + App Insights
│   │   └── rbac.bicep           # All role assignments
│   └── hooks/
│       ├── postprovision.sh     # Uploads KB docs to blob, creates Search indexer, provisions connections
│       └── postdeploy.sh        # Writes .env, registers Foundry agents
│
├── agents/
│   ├── orchestrator_agent.py    # Orchestrator — LLM routing + sub-agent coordination
│   ├── advisor_agent.py         # Foundry IQ KB via MCPTool
│   ├── calculator_agent.py      # Custom MCP — refi savings calculator
│   ├── scheduler_agent.py       # Custom MCP — appointment booking
│   └── calendar_agent.py        # Work IQ Calendar MCP — M365 calendar events
│
├── api/
│   └── server.py                # FastAPI — POST /api/chat SSE endpoint
│
├── mcp-server/                  # Azure Function App — custom MCP server
│   ├── function_app.py          # HTTP trigger — MCP JSON-RPC handler
│   ├── server.py                # Tool implementations + inputSchema definitions
│   ├── host.json                # routePrefix: "" → endpoint at /mcp
│   └── requirements.txt
│
├── knowledge/                   # Knowledge base source documents
│   ├── va_guidelines.md         # VA eligibility rules, IRRRL, funding fees
│   ├── lender_products.md       # Lender loan products and overlays
│   └── loan_process_faq.md      # Borrower FAQ and edge cases
│
├── ui/                          # React frontend
│   └── src/
│       ├── App.jsx              # Root layout + borrower profile state
│       ├── components/
│       │   ├── BorrowerProfile.jsx  # Profile selector + detail card
│       │   ├── ChatPanel.jsx        # Conversation thread
│       │   ├── ChatMessage.jsx      # Message bubble (user, assistant, plan, handoff)
│       │   ├── ChatInput.jsx        # Textarea + send button + demo query buttons
│       │   ├── AgentFlowLog.jsx     # Streaming event log panel
│       │   ├── FlowEvent.jsx        # Single log row
│       │   └── StatusDot.jsx        # Header status indicator
│       └── hooks/
│           └── useAgentStream.js    # SSE connection + profile_id injection
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

## Key Features

### Foundry IQ — Grounded Knowledge Base (Advisor Agent)

The Advisor Agent connects to an **Azure AI Search Knowledge Base** via MCP with `ProjectManagedIdentity` auth — no API keys.

**Knowledge sources (3 documents):**
- `va_guidelines.md` — VA eligibility rules, COE requirements, IRRRL rules, funding fee tables
- `lender_products.md` — Lender loan products, IRRRL, Cash-Out Refi, VA Jumbo, overlays
- `loan_process_faq.md` — Borrower FAQ, process steps, myths, edge cases

Every factual claim includes a **citation marker** (`【idx†source】`) resolved to a filename and streamed to the UI as a source chip.

### Custom MCP Server — Live Tool Invocation (Calculator + Scheduler)

An **Azure Function App** (`mcp-server/`) implements the MCP JSON-RPC protocol over HTTP. No `mcp` Python package required.

**`refi_savings_calculator`** — Real amortization math:
- Monthly payment delta, annual savings, break-even timeline, lifetime savings net of closing costs
- Applies VA IRRRL closing cost structure ($4,050 base + 0.5% funding fee, waived if disability-exempt)
- Reports whether the **VA net tangible benefit test** passes (break-even ≤ 36 months)

**`appointment_scheduler`** — Books a consultation slot:
- Normalizes fuzzy inputs ("morning", "afternoon", "thurs")
- Returns confirmed slot with loan officer name, calendar date, and confirmation number
- Appointment type is context-aware: "IRRRL review and rate lock" vs. "VA Loan Consultation"

### Work IQ Calendar — M365 Integration (Calendar Agent)

After the Scheduler confirms an appointment, the Calendar Agent calls `CreateEvent` on the **Work IQ Calendar MCP server** to place it on the Veteran's M365 calendar.

### Demo Borrower Profiles

Three selectable profiles inject personalized context into every agent query:

| Profile | Background | Demo Scenario |
|---|---|---|
| **Marcus T.** | Army Veteran, 10% disability, existing VA loan at 6.8% | IRRRL flagship — fee exempt, full savings calc + booking |
| **Sarah K.** | Navy Veteran, first-time buyer, no existing loan | Purchase eligibility — blocked from IRRRL, gets "VA Loan Consultation" |
| **Lt. James R.** | Active duty, OCONUS deployed, second VA loan use | Second-use eligibility + refi on higher balance |

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| API server | FastAPI + uvicorn (SSE streaming) |
| Foundry SDK | `azure-ai-projects >= 2.0.1` (new-agent API) |
| Auth | `azure-identity` (`DefaultAzureCredential`) |
| MCP server | Azure Functions v2 (plain HTTP trigger) |
| Infrastructure | Bicep + Azure Developer CLI (`azd`) |
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
| Infrastructure-as-code | `azd up` provisions everything; `azd down` tears it all down |
| Profile-aware responses | Borrower context injected per-query; calculator uses real loan parameters |
| Governed, citable AI | Every factual claim traces back to a specific knowledge document |
| Workflow agent | Declarative YAML orchestration for Copilot Studio / Teams |

---

## Roadmap

### Completed

| Phase | Name | What It Does |
|---|---|---|
| 0 | Foundation | Refactored orchestrator, profiles, CLI entry point |
| 1 | Foundry IQ Knowledge Base | Advisor Agent grounded in Azure AI Search KB via MCP (3 knowledge sources, cited responses) |
| 2 | Azure-Hosted MCP Server | Calculator + Scheduler agents calling tools via custom Azure Function App MCP endpoint |
| 3 | Workflow Agent | Declarative YAML orchestration deployed to Foundry for Copilot Studio / Teams path |
| 4 | Infrastructure-as-Code | Full `azd up` / `azd down` flow — Bicep modules, hooks, 12 RBAC assignments, zero manual steps |

### Planned

| Phase | Name | Goal | Key Changes |
|---|---|---|---|
| **5** | **Web App Deployment** | Deploy to Azure App Service — accessible at a public URL | New `web-app.bicep`, `predeploy.sh` (React build), static file mount in FastAPI, 5 MI role assignments |
| **6** | **Observability** | End-to-end tracing in Azure portal + Foundry | OpenTelemetry + Azure Monitor exporter, per-agent trace spans, conversation audit logging, 90-day retention |
| **7** | **Authentication** | Entra ID Easy Auth — system knows who the user is | App registration via hook, `X-MS-CLIENT-PRINCIPAL` header extraction, Work IQ Calendar delegated auth |
| **8** | **Network Isolation** | VNet + private endpoints for financial institution compliance | New `network.bicep` (VNet, 3 subnets, NSG, 3 PEs, 3 DNS zones), disable public access on all backend services, Function App moves to shared B1 plan, MI-based storage auth |

Phases are numbered in recommended execution order. Each phase is independently deployable after Phase 5.
