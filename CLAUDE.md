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
orchestrator routes their query to one or more specialized agents and synthesizes a unified response.

### The Demo Scenario
A Veteran asks about refinancing their existing VA loan:
> *"I'm thinking about refinancing — am I eligible for an IRRRL, and if so, can you show me
> what I'd save and book a call with someone?"*

This single query triggers all four specialized agents:
1. The **VA Loan Advisor Agent** answers eligibility questions from the knowledge base
2. The **Loan Calculator Agent** runs the refinance savings calculator via MCP tools
3. The **Loan Scheduler Agent** books an appointment via custom MCP tools
4. The **Calendar Agent** creates a calendar event on the Veteran's M365 calendar via Work IQ
5. The **Orchestrator** combines all responses into one cohesive reply

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
┌─────────────────────────┐
│       Orchestrator       │  Routes queries, emits stream events
│  (orchestrator_agent.py) │  Foundry: va-loan-orchestrator
└────────────┬────────────┘
             │
    ┌────────┼──────────┬──────────────┐
    │        │          │              │
    ▼        ▼          ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Advisor │ │Calcul- │ │Scheduler │ │Calendar  │
│ Agent  │ │ ator   │ │  Agent   │ │  Agent   │
│        │ │ Agent  │ │          │ │          │
│Foundry │ │Custom  │ │Custom    │ │Work IQ   │
│  IQ    │ │  MCP   │ │  MCP     │ │Calendar  │
└───┬────┘ └───┬────┘ └────┬─────┘ └────┬─────┘
    │          │           │            │
    ▼          ▼           ▼            ▼
 Azure AI   Savings    Appointment    M365
 Search KB  Calculator Booking       Calendar
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
  speculate on information not found in the knowledge base; defers calculation/scheduling
  requests to the Calculator or Scheduler agents

### 2. Loan Calculator Agent (`agents/calculator_agent.py`)
- **Capability**: MCP — live tool invocation via MCP server (calculation tools only)
- **Purpose**: Performs real-time refinance savings calculations on behalf of the Veteran
- **MCP Tools** (1 tool, restricted):
  - `refi_savings_calculator` — Given current rate, new rate, loan balance, and remaining
    term, returns monthly savings, annual savings, and break-even timeline
- **Behavior**: Always surfaces tool inputs and outputs transparently; presents savings
  figures clearly with break-even timeline and VA net tangible benefit test result

### 3. Loan Scheduler Agent (`agents/scheduler_agent.py`)
- **Foundry Name**: `va-loan-scheduler-mcp`
- **Capability**: MCP — live tool invocation via custom MCP server
- **Purpose**: Books consultation appointments with loan officers on behalf of the Veteran
- **MCP Tools** (1 tool, restricted):
  - `appointment_scheduler` — Given a preferred day/time, returns a confirmed appointment
    slot with loan officer name, calendar date, and confirmation number
- **Behavior**: Confirms appointment details clearly; appointment type is context-aware
  ("IRRRL review and rate lock" for existing loan holders, "VA Loan Consultation" for
  first-time buyers based on profile's `current_rate` field)

### 4. Calendar Agent (`agents/calendar_agent.py`)
- **Foundry Name**: `va-loan-calendar-mcp`
- **Capability**: Work IQ Calendar — Microsoft-hosted MCP for M365 calendar management
- **Purpose**: Creates calendar events on the Veteran's personal M365 calendar after
  the Scheduler Agent confirms an appointment
- **MCP Tools** (1 tool, restricted):
  - `CreateEvent` — Creates a calendar event with the appointment details (subject,
    start/end time, body with loan officer and confirmation number)
- **Behavior**: Called automatically by the orchestrator after a successful scheduler run;
  the orchestrator passes the appointment JSON from the scheduler's response
- **Important**: The `allowed_tools` filter uses the raw MCP tool name (`CreateEvent`),
  not the Foundry-prefixed name (`mcp_CalendarTools_graph_createEvent`). Using the
  prefixed name causes the tools list to return empty.

### 5. Orchestrator (`agents/orchestrator_agent.py`)
- **Foundry Name**: `va-loan-orchestrator`
- **Purpose**: Entry point and coordinator; receives the user query, determines which
  agent(s) to invoke, collects results, and emits per-agent partial responses
- **Routing Logic** (3-way classification: `needs_advisor`, `needs_calculator`, `needs_scheduler`):
  - Knowledge/eligibility questions → Advisor Agent only
  - Savings calculation requests → Calculator Agent only
  - Scheduling/booking requests → Scheduler Agent + Calendar Agent (auto-chained)
  - Mixed queries (like the demo scenario) → multiple agents in sequence
- **Calendar auto-chain**: When scheduling is needed, the orchestrator automatically runs
  the Calendar Agent after the Scheduler Agent, passing the confirmed appointment details
- **Chat events**: Emits `plan` (agent chain preview), `handoff` (agent transitions), and
  per-agent `partial_response` events — each rendered as a separate labeled bubble in the UI

#### Human-in-the-Loop (HIL) Flows

The orchestrator supports multi-turn conversations where it pauses to collect user input.
State is tracked in `api/conversation_state.py` (in-memory, 10-minute TTL). Each pause
emits an `await_input` SSE event with `conversation_id` for resumption.

**Calculator HIL — Loan Details Collection** (when `profile_id` is `None` and `needs_calculator`):
1. Orchestrator pauses with a 5-field prompt (balance, current rate, new rate, term, fee exemption)
2. User provides details → enriched into query → calculator runs
3. If calculator tool NOT called (missing info), retry loop:
   - Up to 3 retries with `awaiting_calculator_retry` pending action
   - User can provide more details OR say "skip" / "use defaults" / "forget it" etc.
   - After 3 failed retries, calculator is skipped automatically
4. Skip keywords (8): `skip`, `move on`, `don't calculate`, `no calc`, `forget it`,
   `never mind`, `use defaults`, `default`

**Appointment Confirmation HIL** (after scheduler books an appointment):
1. Orchestrator pauses: "Does this appointment work for you?"
2. 4-way classification (LLM with keyword fallback):
   - **Confirm** → Calendar Agent creates M365 event (requires explicit positive keywords)
   - **Reschedule** → Scheduler re-runs with new preference, loops back to confirmation
   - **Decline** → Calendar step skipped, appointment still confirmed
   - **Unrecognized** (default) → moves on without calendar event, appointment still confirmed
3. Confirm keywords (12): `yes`, `confirm`, `looks good`, `perfect`, `great`, `add it`,
   `add to`, `calendar`, `book it`, `works for me`, `sounds good`, `that works`
4. Reschedule keywords (16): `instead`, `change`, `different`, `reschedule`, `another`,
   `monday`–`saturday`, `morning`, `afternoon`, `earlier`, `later`
5. Decline keywords (6): `no thank`, `skip`, `don't`, `cancel`, `decline`, `not now`
6. Note: In the Python orchestrator, confirm is the default (LLM classifies); in the
   workflow YAML, unrecognized input defaults to "move on" (safer without LLM fallback)

**ConversationState** (`api/conversation_state.py`):
- `pending_action`: `None` | `"awaiting_profile_info"` | `"awaiting_calculator_retry"`
  | `"awaiting_appointment_confirmation"`
- `user_provided_details`: `bool` — skips `_demo_context_block` when user manually provided
  loan details (prevents profile-based context from overriding user input)
- `calculator_retry_count`: `int` — max 3 attempts before forcing skip

#### Memory Architecture — Session State vs. Long-Term Memory

The system uses **two distinct memory layers** that serve fundamentally different purposes:

| | Session State (Phase 13) | Long-Term Memory (Phase 15 — planned) |
|---|---|---|
| **What it is** | Cosmos DB conversation state | Foundry Memory Stores (preview) |
| **Purpose** | Track orchestration flow within a single conversation | Remember facts about the borrower across conversations |
| **What it stores** | Routing flags, retry counts, pending actions, agent results | Semantic facts the LLM extracts ("Marcus prefers Thursday appointments") |
| **Scope** | Single conversation, 10-minute TTL | Cross-conversation, long-lived (weeks/months) |
| **Who reads/writes** | Python orchestrator code (explicit `save_conversation()`) | The LLM automatically (retrieves relevant memories at inference time) |
| **Backend** | `azure.cosmos.aio` — direct point reads/writes | `client.beta.memory_stores` — Foundry-managed |
| **Visible in portal** | No (custom Cosmos container) | Yes (Memory section on agent definition page) |

**Why two layers:** Session state is structured and deterministic — the orchestrator needs
to know exactly which agents have run, what the retry count is, and what pending action to
resume. This cannot be left to LLM recall. Long-term memory is semantic and probabilistic —
it enriches future conversations with relevant context the LLM retrieves automatically.

**Expanded use case — Returning Veteran:**
Marcus calls for the first time and refinances via IRRRL. Session state manages the
multi-turn HIL flow (loan details → calculator → appointment → confirmation). Long-term
memory captures: "Marcus completed IRRRL refi at 6.1%, is funding-fee-exempt (10%
disability), prefers Thursday afternoon appointments, loan officer was Sarah Chen."

Three weeks later, Marcus calls back about a home equity question. Long-term memory
surfaces his prior context — the system greets him with relevant history, skips
re-collecting known details, and routes to the Advisor with enriched context. Meanwhile,
session state independently tracks the new conversation's HIL flow from scratch.

#### Orchestration Path Parity — Python vs. Workflow

The two orchestration paths (Python backend, Foundry Workflow Agent) handle state
differently by design:

| | Python Orchestrator (React UI) | Workflow Agent (Teams / Copilot Studio) |
|---|---|---|
| **Session state** | Cosmos DB (Phase 13) | Foundry workflow runtime (built-in) |
| **HIL mechanism** | `await_input` SSE + `conversation_id` resume | `Question` nodes + `GotoAction` loops |
| **State variables** | `ConversationState` dataclass (14 fields) | `Local.*` workflow variables |
| **Persistence** | Explicit `save_conversation()` at 11 points | Automatic (workflow runtime manages scope) |
| **Long-term memory** | Phase 15 planned (Foundry Memory Stores) | Same — Memory Stores are per-agent, shared across paths |

Parity is maintained at the **behavioral level** — same routing logic, same HIL flows,
same keywords, same agent capabilities. The state mechanism is intentionally different
because the two paths run in different execution environments. Adding Cosmos DB to the
workflow path would be redundant since the Foundry workflow runtime already persists
variable state across turns automatically.

Long-term memory (Phase 15) will be shared across both paths because Foundry Memory
Stores are attached to the agent definition, not the calling surface. A memory created
during a React UI session will be available when the same Veteran uses Teams, and vice versa.

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
│                              │  │ 🧮 Calculator Agent       │   │
│                              │  │   Tool: refi_calculator  │   │
│                              │  │   ✓ Savings: $142/mo     │   │
│                              │  └──────────────────────────┘   │
│                              │  ┌──────────────────────────┐   │
│                              │  │ 📅 Scheduler Agent       │   │
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
| `orchestrator_start` | ⬡ | Navy | Orchestrator received query, analyzing intent |
| `orchestrator_route` | → | Navy | Routing decision: which agent(s) will respond |
| `plan` | ⇄ | Gray | Agent chain plan shown to user (also appears in chat) |
| `advisor_start` | 📚 | Amber | Advisor Agent activated |
| `advisor_source` | 🔍 | Amber | Querying a specific knowledge source |
| `advisor_result` | ✓ | Green | Advisor returned a result |
| `calculator_start` | 🧮 | Blue | Calculator Agent activated |
| `calculator_tool_call` | 🔧 | Blue | Calculator MCP tool being invoked (shows tool name + inputs) |
| `calculator_tool_result` | ✓ | Green | Calculator tool returned a result (shows key outputs) |
| `scheduler_start` | 📅 | Teal | Scheduler Agent activated |
| `scheduler_tool_call` | 🔧 | Teal | Scheduler MCP tool being invoked (shows tool name + inputs) |
| `scheduler_tool_result` | ✓ | Green | Scheduler tool returned a result (shows key outputs) |
| `calendar_start` | 📆 | Rose | Calendar Agent activated |
| `calendar_tool_call` | 🔧 | Rose | Work IQ Calendar tool being invoked (shows tool name + inputs) |
| `calendar_tool_result` | ✓ | Green | Calendar tool returned a result |
| `handoff` | ⇄ | Gray | Control passed between agents (also appears in chat) |
| `orchestrator_synthesize` | ⬡ | Navy | Orchestrator merging results |
| `await_input` | ⏸ | Navy | Orchestrator paused — waiting for user input (HIL) |
| `calculator_note` | ⚠ | Blue | Calculator skipped/retry notice |
| `scheduler_note` | ⚠ | Teal | Scheduler notice |
| `complete` | ✓ | Green | Full response ready |
| `error` | ✗ | Red | Something went wrong |

### SSE Stream Format
The backend (`api/server.py`) streams newline-delimited JSON events to the UI:

```json
{"type": "orchestrator_start", "message": "Analyzing your query..."}
{"type": "orchestrator_route", "message": "Routing to: Advisor Agent + Calculator Agent + Scheduler Agent"}
{"type": "plan", "message": "VA Loan Advisor → Loan Calculator → Loan Scheduler → Calendar"}
{"type": "advisor_start", "message": "VA Loan Advisor activated"}
{"type": "advisor_source", "message": "Querying: va_guidelines.md"}
{"type": "advisor_source", "message": "Querying: lender_products.md"}
{"type": "advisor_result", "message": "IRRRL eligibility confirmed (2 sources cited)"}
{"type": "partial_response", "agent": "advisor", "label": "VA Loan Advisor", "content": "..."}
{"type": "handoff", "message": "Advisor → Calculator Agent"}
{"type": "calculator_start", "message": "Loan Calculator Agent activated"}
{"type": "calculator_tool_call", "message": "refi_savings_calculator", "inputs": {"current_rate": 6.8, "new_rate": 6.1, "balance": 320000, "remaining_term": 27}}
{"type": "calculator_tool_result", "message": "Monthly savings: $142 | Break-even: 19 months"}
{"type": "partial_response", "agent": "calculator", "label": "Loan Calculator", "content": "..."}
{"type": "handoff", "message": "Calculator → Scheduler Agent"}
{"type": "scheduler_start", "message": "Loan Scheduler Agent activated"}
{"type": "scheduler_tool_call", "message": "appointment_scheduler", "inputs": {"day": "Thursday", "time": "2:00 PM"}}
{"type": "scheduler_tool_result", "message": "Confirmed: Thu Mar 26 @ 2:00 PM | Ref #LOAN-84921"}
{"type": "partial_response", "agent": "scheduler", "label": "Loan Scheduler", "content": "..."}
{"type": "handoff", "message": "Scheduler → Calendar Agent"}
{"type": "calendar_start", "message": "Calendar Agent activated"}
{"type": "calendar_tool_call", "message": "CreateEvent", "inputs": {"subject": "IRRRL review", "start": "2026-03-26T14:00:00"}}
{"type": "calendar_tool_result", "message": "Calendar event created"}
{"type": "partial_response", "agent": "calendar", "label": "Calendar", "content": "..."}
{"type": "complete", "message": "Response ready"}
```

**HIL pause event (emitted when orchestrator needs user input):**
```json
{"type": "await_input", "message": "To calculate your refinance savings, I need five pieces of information...", "conversation_id": "a1b2c3d4e5f6", "input_type": "profile_info", "suggestions": ["Balance $320,000, current rate 6.8%...", "Balance $400,000, current rate 7.1%..."]}
```

The `conversation_id` is passed back on the next `POST /api/chat` to resume the paused flow.
`suggestions` are rendered as clickable buttons in the chat input area.

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
--color-advisor:     #92400E;   /* Amber — Advisor Agent events */
--color-calculator:  #1E40AF;   /* Blue — Calculator Agent events */
--color-scheduler:   #0E7490;   /* Teal — Scheduler Agent events */
--color-calendar:    #BE185D;   /* Rose — Calendar Agent events */
--color-orchestrator:#002244;   /* Navy — Orchestrator events */
--color-handoff:     #9CA3AF;   /* Gray — Plan/handoff events (muted) */
--color-success:     #15803D;   /* Green — completed events */
```

### Key UI Behaviors
- **Streaming log**: Each SSE event appends a new row to the Agent Flow Log in real time,
  with a brief fade-in animation. The log auto-scrolls to the latest event.
- **Thinking indicator**: While a response is in progress, a pulsing indicator appears in
  the active agent's log row.
- **Tool call expansion**: `calculator_tool_call`, `scheduler_tool_call`, and
  `calendar_tool_call` events show a collapsed input summary by default; clicking
  expands to show the full structured inputs.
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
- **HIL suggestion buttons**: When the orchestrator pauses for input (`await_input` event),
  clickable suggestion buttons appear above the chat input (e.g. pre-filled loan details,
  appointment confirmation options). Clicking a suggestion sends it as the user's response.
- **Multi-turn HIL**: Conversation state is preserved across turns via `conversation_id`.
  The chat panel shows the full conversation history including HIL prompts and responses.

---

## Azure / Foundry Resources

All infrastructure is provisioned via `azd up` (Bicep templates in `infra/`). Environment
variables are auto-populated by azd outputs and postprovision hooks — no manual copy/paste.

**Next-gen Foundry resource model:**
```
Microsoft.CognitiveServices/accounts (kind: AIServices)   ← ais-{env}
  ├── /deployments/gpt-4.1                                 ← LLM deployment
  ├── /deployments/text-embedding-3-small                  ← embedding deployment (vector search)
  └── /projects/proj-{env}                                 ← Foundry project
```

| Resource | Environment Variable | Set By |
|---|---|---|
| Foundry Project Endpoint | `FOUNDRY_PROJECT_ENDPOINT` | azd output |
| Model Deployment | `FOUNDRY_MODEL_DEPLOYMENT` | azd output |
| Azure Subscription ID | `AZURE_SUBSCRIPTION_ID` | azd output |
| Foundry Project Resource ID | `FOUNDRY_PROJECT_RESOURCE_ID` | azd output |
| Advisor KB Name | `ADVISOR_KNOWLEDGE_BASE_NAME` | postprovision hook |
| Advisor Search Endpoint | `ADVISOR_SEARCH_ENDPOINT` | azd output |
| Advisor MCP Connection | `ADVISOR_MCP_CONNECTION` | postprovision hook |
| MCP Tools Endpoint | `MCP_TOOLS_ENDPOINT` | azd output |
| MCP Tools Connection | `MCP_TOOLS_CONNECTION` | postprovision hook |
| Scheduler Calendar Endpoint | `SCHEDULER_CALENDAR_ENDPOINT` | **Manual** (portal) |
| Scheduler Calendar Connection | `SCHEDULER_CALENDAR_CONNECTION` | **Manual** (portal) |
| App Insights Connection String | `APPLICATIONINSIGHTS_CONNECTION_STRING` | azd output |

Authentication: `DefaultAzureCredential` for local dev (requires `az login` before running).
Never use API keys in code — always use credential objects. The AI Services account uses
`disableLocalAuth: true` (AAD-only).

---

## Project Structure

```
va-loan-concierge/
│
├── CLAUDE.md                    # This file
├── README.md                    # Human-readable project overview
├── azure.yaml                   # azd project definition (services + hooks)
├── .env                         # Local secrets — never commit (auto-generated by azd)
├── .env.example                 # Committed template with empty values
├── .gitignore                   # Excludes .env, __pycache__, .venv, node_modules
├── requirements.txt             # Python dependencies (backend)
│
├── main.py                      # CLI entry point — imports Orchestrator + profiles
├── profiles.py                  # DEMO_PROFILES + _profile_context_block + _demo_context_block
├── workflow.yaml                # Foundry Workflow Agent definition (orchestrator → advisor/calculator/scheduler/calendar)
├── deploy_workflow.py           # Registers sub-agents + uploads workflow to Foundry
│
├── infra/                       # Infrastructure-as-code (Bicep + azd hooks)
│   ├── main.bicep               # Orchestrator — wires all modules, defines outputs
│   ├── main.parameters.json     # Maps azd env values to Bicep params
│   ├── modules/
│   │   ├── ai-services.bicep    # AI Services account (Foundry + OpenAI + connections)
│   │   ├── ai-project.bicep     # AI Project (child of AI Services)
│   │   ├── search.bicep         # AI Search (aadOrApiKey auth, system MI)
│   │   ├── function-app.bicep   # MCP server Function App (Flex Consumption FC1)
│   │   ├── storage.bicep        # Storage (KB blobs + Function App runtime)
│   │   ├── monitoring.bicep     # Log Analytics + App Insights
│   │   └── rbac.bicep           # All role assignments (15 total)
│   └── hooks/
│       └── postprovision.ps1    # All post-provision: blob upload, Search index/skillset/indexer, connections, MCP deploy, .env, agent registration
│
├── api/
│   ├── __init__.py
│   ├── server.py                # FastAPI server — exposes /api/chat SSE endpoint
│   ├── telemetry.py             # OpenTelemetry setup — Azure Monitor exporter, per-agent spans
│   └── conversation_state.py    # In-memory HIL state (ConversationState dataclass, TTL-based)
│
├── agents/
│   ├── __init__.py
│   ├── orchestrator_agent.py    # Orchestrator — LLM routing + sub-agent coordination
│   ├── advisor_agent.py         # Foundry IQ / knowledge base agent
│   ├── calculator_agent.py      # MCP calculator agent (refi savings only)
│   ├── scheduler_agent.py      # MCP scheduler agent (appointment booking only)
│   └── calendar_agent.py       # Work IQ Calendar agent (M365 event creation)
│
├── tools/
│   ├── __init__.py
│   ├── refi_calculator.py       # Simulated refi savings calculator tool
│   └── appointment_scheduler.py # Simulated appointment scheduling tool
│
├── evals/                       # Agent evaluation datasets and runner
│   ├── eval_advisor.jsonl       # 15 test queries for Advisor Agent
│   ├── eval_orchestrator.jsonl  # 10 test queries for Orchestrator routing
│   └── run_eval.py              # OpenAI Evals API runner (server-side, targets agents)
│
├── scripts/
│   └── create_guardrails.ps1    # Standalone guardrail creation (also in postprovision)
│
├── knowledge/
│   ├── va_guidelines.md         # Knowledge source 1: VA rules and eligibility
│   ├── lender_products.md       # Knowledge source 2: Lender loan products
│   └── loan_process_faq.md      # Knowledge source 3: Borrower FAQ and edge cases
│
├── mcp-server/                  # Azure Function App — custom MCP server
│   ├── function_app.py          # HTTP trigger: MCP JSON-RPC handler (initialize/tools/list/tools/call)
│   ├── server.py                # Tool implementations + MCP inputSchema definitions
│   ├── host.json                # routePrefix: "" → endpoint at /mcp (not /api/mcp)
│   └── requirements.txt         # azure-functions only — no mcp package needed
│
├── ui/                          # React frontend
│   ├── package.json
│   ├── vite.config.js           # Vite dev server; proxies /api to FastAPI on :8000
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx              # Root layout: header + profile bar + two-panel split
│       ├── index.css            # Tailwind directives + CSS custom properties
│       ├── components/
│       │   ├── BorrowerProfile.jsx # Profile selector pills + collapsible detail card
│       │   ├── ChatPanel.jsx    # Conversation message thread
│       │   ├── ChatMessage.jsx  # Message bubble (user, assistant, plan, handoff)
│       │   ├── ChatInput.jsx    # Prompt textarea + send button + demo query buttons
│       │   ├── AgentFlowLog.jsx # Streaming event log panel
│       │   ├── FlowEvent.jsx    # Single log row with icon, label, message
│       │   └── StatusDot.jsx    # Header connection/activity indicator
│       └── hooks/
│           └── useAgentStream.js # SSE connection, mock mode, profile_id injection
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

## Tech Stack

**Backend**

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| API Server | `FastAPI` + `uvicorn` — serves SSE stream to UI |
| Foundry SDK | `azure-ai-projects >= 2.0.1` (new-agent API — NOT classic) |
| Authentication | `azure-identity` (`DefaultAzureCredential`) |
| MCP | `azure-ai-projects` MCPTool + custom Azure Function App (`mcp-server/`) + Work IQ Calendar |
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
- Each agent is a self-contained class in its own file under `/agents/` — including the orchestrator (`orchestrator_agent.py`)
- Environment variables are always loaded via `python-dotenv` at the top of `main.py`
- MCP tool inputs and outputs use plain dicts — the MCP server returns JSON; agents parse `response.output`
- Knowledge base documents are plain Markdown in `/knowledge/` for readability and easy updating
- Never hardcode endpoint URLs, model names, or credentials — always from `.env`
- Use `logging` (not `print`) for all runtime output except the final user-facing response

---

## Key Commands

```bash
# ── Infrastructure (first time only) ─────────────────────────────
az login
azd auth login
azd up              # provisions everything, deploys MCP server, registers agents
azd down            # tears down all resources

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
pytest tests/               # 111 tests

# ── Evaluations ───────────────────────────────────────────────────
# Run agent evaluations (server-side via OpenAI Evals API)
python evals/run_eval.py                       # advisor eval
python evals/run_eval.py --agent orchestrator  # orchestrator eval
python evals/run_eval.py --all                 # both
python evals/run_eval.py --cleanup             # delete old evals + files

# ── Frontend ──────────────────────────────────────────────────────
# Install Node dependencies (first time only)
cd ui && npm install

# Start Vite dev server (proxies /api → localhost:8000)
npm run dev
# → UI available at http://localhost:5173

# Build for production
npm run build

# ── Workflow Agent (Copilot Studio / Teams path) ─────────────────
# Deploy workflow agent to Foundry (registers sub-agents + uploads workflow)
python deploy_workflow.py
# → Test in Foundry portal: Build → Agents → va-loan-concierge-workflow → Playground

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
1. Orchestrator classifies as mixed (advisor + calculator + scheduler)
2. Advisor Agent answers IRRRL eligibility from `va_guidelines.md` and `lender_products.md`,
   with source citations
3. Calculator Agent calls `refi_savings_calculator` with demo loan parameters
4. Scheduler Agent calls `appointment_scheduler` for Thursday
5. Calendar Agent calls `CreateEvent` to add the appointment to the Veteran's M365 calendar
6. Each agent emits a labeled partial response in the chat thread

---

## What This Demo Proves

| Capability | Demonstrated By |
|---|---|
| **Foundry IQ / grounded RAG** | Advisor Agent answering from 3 knowledge sources with citations |
| **Multi-source knowledge base** | VA guidelines + lender products + borrower FAQ all queried simultaneously |
| **Custom MCP server** | Calculator and Scheduler agents calling tools via Azure Function App MCP |
| **Work IQ Calendar** | Calendar Agent creating M365 events via Microsoft-hosted MCP |
| **Multi-agent orchestration** | Single user query routed to four specialized agents, responses synthesized |
| **Governed, citable AI** | Every factual claim traces back to a specific knowledge document |
| **Actionable AI** | Demo ends with real outputs (savings numbers + booked appointment + calendar event) |

---

## Borrower Profiles

`DEMO_PROFILES` in `profiles.py` defines three demo borrowers. The profile flows from the UI
through `useAgentStream.js` → `POST /api/chat` (`profile_id` field on `ChatRequest`) →
`Orchestrator.run(query, profile_id)`.

**Context injection rules (important):**
- `_profile_context_block(profile_id)` — prepends borrower service history and loan details
  to every agent query. When `profile_id` is `None`, prepends a note telling agents to ask
  for personal details conversationally.
- `_demo_context_block(query, profile_id, target_agent)` — appends tool parameters for a
  specific agent (`"calculator"` or `"scheduler"`):
  - **Refi calc params** (balance, current_rate, new_rate, etc.) → ALWAYS inject from
    profile — the user never types these out and the agent cannot know them otherwise.
  - **Appointment day/time** → NEVER inject. The agent extracts these from the user's
    own words. Injecting hardcoded values overrides what the user asked for.
  - If `current_rate` is `None` (first-time buyer, no existing loan), skip the refi block
    and inject a note that IRRRL requires an existing VA loan.
  - **Appointment type** is context-aware: "IRRRL review and rate lock" when
    `current_rate` is set (existing loan), "VA Loan Consultation" when `None` (first-time buyer).

| Profile | Key scenario |
|---|---|
| `marcus` | Army Veteran, 10% disability (fee exempt), existing VA loan at 6.8% — IRRRL flagship |
| `sarah` | Navy Veteran, first-time buyer, no existing loan — purchase eligibility, no refi calc |
| `james` | Active duty, OCONUS deployed, second VA loan use — higher balance, no fee exemption |

---

## Notes for Claude Code

**Backend**
- When scaffolding agent code, always check `requirements.txt` first to confirm package
  versions before importing
- The `/knowledge/` markdown files should be populated with realistic but clearly simulated
  content — they do not need to reflect actual current VA rates or real lender pricing
- MCP tools in `/tools/` are **simulations** — they return hardcoded or lightly randomized
  realistic values; no real API calls are made in this demo
- When adding new agents, follow the pattern established in `advisor_agent.py` and `orchestrator_agent.py` —
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

The end-to-end demo is fully working with human-in-the-loop interactions. All four
sub-agents (advisor, calculator, scheduler, calendar) run, SSE events stream to the UI
in real time, and per-agent partial responses render correctly with real KB grounding
and citations. Multi-turn HIL flows (calculator loan details collection, appointment
confirmation/reschedule/decline) work in both the Python orchestrator and the Foundry
Workflow Agent. The workflow YAML has been hardened (simplified from 740 to ~289 lines,
Power Fx fixes, conversationId isolation, graceful HIL fallbacks) and validated in the
Foundry playground.

**Completed:** Phases 1–8 + 10 + 13 (foundation, agents, MCP, Foundry IQ, workflow agent, IaC,
guardrails, evaluations, observability, Cosmos DB state) + HIL orchestration + workflow hardening.
**Next (independent, can start now):** Phase 14 (Content Understanding).
**Blocked on Phase 9 (VM quota):** Phase 11 (auth) → 12 (network isolation).
**Blocked on Phase 11 (auth):** Phase 15 (Foundry Memory Stores — cross-session Veteran memory).
**Validated (not a phase):** Orchestration patterns confirmed as Microsoft Agent Framework
best practices — `agent_reference` + Responses API is the canonical pattern. ConnectedAgentTool
(deprecated), A2APreviewTool (cross-system only), and Microsoft Agent Framework (overkill)
are intentionally not used. See Phase 5 rationale.
Teams publishing investigated 2026-03-26 — blocked by cross-tenant limitations.

---

### Phase 7. Guardrails & Content Safety — ✅ COMPLETE

Four defense layers implemented for the customer demo:

**Layer 1: Foundry Guardrails (per-agent, REST API)**
Two custom `raiPolicy` resources created via `infra/hooks/postprovision.ps1` (step 8)
and also available standalone via `scripts/create_guardrails.ps1`:
- `va-loan-advisor-guardrail` — for the Advisor Agent. Intervention points: user input +
  output. Controls: content safety (Low severity), jailbreak detection, indirect attack
  detection, PII detection, protected material, profanity.
- `va-loan-tools-guardrail` — for Calculator + Scheduler Agents. Same controls plus tool
  call scanning and tool response scanning (agent-only intervention points).
- Assigned to agents in Foundry portal: Build > Agents > [agent] > Guardrails > Manage.
- When assigned, agent guardrail **overrides** the model's default guardrail.

**Layer 2: Content Filter as Code (Bicep)**
Custom `raiPolicy` resource inlined in `infra/modules/ai-services.bicep`:
- Attached to the gpt-4.1 model deployment via `raiPolicyName`
- Tightened thresholds: Violence/Hate/SelfHarm at Low, Sexual at Medium
- Jailbreak + Indirect Attack detection enabled and blocking
- Protected Material (text + code) scanning on completions
- Deployed automatically by `azd up` — content safety as auditable IaC

**Layer 3: Agent Instruction Guardrails**
Each agent's `*_INSTRUCTIONS` includes explicit SAFETY RULES:
- Advisor: no financial advice beyond KB, no PII disclosure, no scope creep
- Calculator: only refi calculations, no PII, flag unreasonable inputs
- Scheduler: only VA loan appointments, no PII, no system detail disclosure

**Layer 4: MCP Tool Input Validation**
`mcp-server/server.py` validates all tool inputs before execution:
- `_validate_refi_inputs()` — rates 0-20%, balance $1K-$10M, term 1-30yr
- `_validate_scheduler_inputs()` — recognized weekdays only
- Returns JSON-RPC error on validation failure (tool never executes)

---

### Phase 8. Agent Evaluations — ✅ COMPLETE

Foundry's OpenAI Evals API evaluates registered agents server-side. Queries are sent
directly to agents, responses are evaluated by builtin evaluators, and results appear
in the Foundry portal under Build > Evaluations.

**Evaluation datasets:**
- `evals/eval_advisor.jsonl` — 15 test queries for the Advisor Agent (eligibility,
  funding fees, products, edge cases, out-of-scope)
- `evals/eval_orchestrator.jsonl` — 10 test queries for routing classification
  (advisor-only, calculator-only, scheduler-only, mixed, general)

**Evaluation script:** `evals/run_eval.py`
- Uses OpenAI Evals API via `azure-ai-projects` SDK (`oai.evals.create` + `oai.evals.runs.create`)
- Targets registered agents by name using `azure_ai_agent` target type
- Inline dataset via `file_content` (avoids file upload extension detection bug)
- Advisor evaluators: task adherence, groundedness, coherence, relevance
- Orchestrator evaluators: task adherence (with routing-aware instructions), coherence
- Polls for server-side completion, prints `report_url` linking to portal results
- **Eval reuse**: if an eval with the same name already exists, adds a new run to it
  instead of creating a duplicate — enables tracking score trends across runs in the portal
- `--cleanup` flag deletes all old evals, runs, and uploaded files

**Key implementation details:**
- **ViolenceEvaluator excluded** — the `builtin.violence` safety evaluator and the
  local `ViolenceEvaluator` both require the classic Hub workspace model
  (`Microsoft.MachineLearningServices/workspaces`). Our next-gen Foundry project
  uses `CognitiveServices/accounts/.../projects`. Violence safety is handled by
  our guardrail policies (Layer 1) instead.
- **Orchestrator task instructions** — the `task_adherence` evaluator receives explicit
  instructions explaining the orchestrator's routing role, so delegating to the correct
  agent counts as adherence (not penalized for not answering directly).
- **Local evaluation SDK (`azure-ai-evaluation`)** — the `evaluate()` function's portal
  logging via `azure_ai_project` string parameter does upload to the onedp endpoint,
  but results may not render in the new portal. The OpenAI Evals API is the portal-native
  path for the new Foundry portal.

**Usage:**
```bash
python evals/run_eval.py                       # advisor eval
python evals/run_eval.py --agent orchestrator  # orchestrator eval
python evals/run_eval.py --all                 # both
python evals/run_eval.py --cleanup             # delete old evals + files
```

**Advisor baseline scores (2026-03-25):**
- Task Adherence: 87% pass
- Groundedness: 4.87/5 (100% pass)
- Coherence: 4.07/5 (93% pass)
- Relevance: 4.67/5 (93% pass)

---

### Phase 3. Foundry IQ Knowledge Base (replacing FileSearch) — ✅ COMPLETE

**Implemented state:**
`AdvisorAgent` connects to an Azure AI Search Knowledge Base created in the Foundry portal
via the MCP protocol, using a `RemoteTool` project connection with `ProjectManagedIdentity`
auth. The agent is registered with `MCPTool` (not `FileSearchTool` or `AzureAISearchTool`).

**How it works:**
- `initialize()` PUTs a `RemoteTool` project connection via ARM pointing at
  `{ADVISOR_SEARCH_ENDPOINT}/knowledgebases/{ADVISOR_KNOWLEDGE_BASE_NAME}/mcp?api-version=2025-11-01-preview`
- The agent is registered with `MCPTool(server_label="knowledge-base", allowed_tools=["knowledge_base_retrieve"], project_connection_id=ADVISOR_MCP_CONNECTION)`
- After the Responses API call, `_extract_citations()` parses `【idx†filename】` markers
  from the response text and emits them as `advisor_source` SSE events
- The agent instructions tell the model to use real filenames (e.g. `va_guidelines.md`) as
  citation labels; generic labels like `doc_0` or `source` are filtered out

**KB creation:** The Foundry IQ Knowledge Base is created **manually** in the Foundry portal
after `azd up` completes. See README.md for step-by-step instructions with exact property
values. The `azure-search-documents` SDK for programmatic KB creation is in preview and
was unreliable, so this step is portal-only.

**Required env vars:**
- `ADVISOR_KNOWLEDGE_BASE_NAME` — KB name in Azure AI Search (e.g. `kb-va-loan-guidelines`)
- `ADVISOR_SEARCH_ENDPOINT` — search service URL (e.g. `https://search-va-loan-demo.search.windows.net`)
- `FOUNDRY_PROJECT_RESOURCE_ID` — ARM resource ID of the Foundry project
- `ADVISOR_MCP_CONNECTION` — name for the RemoteTool connection (e.g. `kb-va-loan-demo-mcp`)

**Required Azure RBAC (automated by `infra/modules/rbac.bicep`):**
- `Search Index Data Reader` → AI Services + Project managed identities (on Search service)
- `Search Index Data Contributor` → AI Services + Project managed identities (on Search service)
- `Cognitive Services OpenAI User` → Search service managed identity (on AI Services account)
- `Storage Blob Data Reader` → Search service managed identity (on Storage for KB indexer)
- Auth mode on the search service must be `aadOrApiKey` (not `apiKeyOnly`)

**Reference:** https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect

---

### Phase 4. Azure-Hosted MCP Server (replacing FunctionTool) — ✅ COMPLETE

**Implemented state:**
`CalculatorAgent` and `SchedulerAgent` each connect to the Azure Function App (`mcp-server/`)
that exposes tools as an MCP-compliant HTTP endpoint. `CalendarAgent` connects to
Microsoft's **Work IQ Calendar** MCP server for M365 calendar event creation.

Each agent has exactly one MCP tool — this is a deliberate design choice. The Foundry
Responses API's LLM does NOT reliably make sequential dependent tool calls within a single
request (`max_tool_calls=2` causes the LLM to loop on the first tool or skip tool calls
entirely). One tool per agent per API call is the reliable pattern.

**How it works:**
- `initialize()` PUTs a `RemoteTool` project connection (`MCP_TOOLS_CONNECTION`) via
  ARM with `authType: "None"` (anonymous Function App), then creates a new agent version
  with `MCPTool(server_url, project_connection_id, allowed_tools, require_approval="never")`
- `CalculatorAgent` is restricted to `allowed_tools=["refi_savings_calculator"]`
- `SchedulerAgent` is restricted to `allowed_tools=["appointment_scheduler"]`
- `CalendarAgent` uses Work IQ Calendar with `allowed_tools=["CreateEvent"]`
  (**Important:** uses the raw MCP tool name, not the Foundry-prefixed name)
- `mcp-server/function_app.py` handles POST `/mcp` and responds to `initialize`,
  `tools/list`, `tools/call`, and `ping` JSON-RPC methods
- `mcp-server/server.py` contains the tool implementations and MCP `inputSchema` definitions
- `run()` makes a single Responses API call; `_parse_mcp_events()` extracts `mcp_call`
  output items and `_format_tool_result()` formats them into human-readable SSE messages
- All agents now always call `create_version` on startup (no reuse check) — version counter
  increments in the Foundry portal on every restart, no manual deletion needed on config changes

**Required env vars:**
- `MCP_TOOLS_ENDPOINT` — Function App MCP URL (e.g. `https://<app>.azurewebsites.net/mcp`)
- `MCP_TOOLS_CONNECTION` — name for the RemoteTool connection (e.g. `va-loan-action-mcp-conn`)
- `SCHEDULER_CALENDAR_ENDPOINT` — Work IQ Calendar MCP server URL (Microsoft-hosted)
- `SCHEDULER_CALENDAR_CONNECTION` — Foundry project connection name (e.g. `WorkIQCalendar`)

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

---

### Phase 5. Foundry Workflow Agent + Copilot Studio / Teams — ✅ WORKFLOW HARDENED

**Target surfaces:** M365 Copilot (Work) and Microsoft Teams via Copilot Studio native
Foundry connector.

**Two deployment paths (both use the same sub-agents):**
- **React UI demo** → Python backend (`api/server.py`) with SSE streaming — already working
- **Copilot Studio / Teams** → Foundry Workflow Agent — declarative, no container needed

**Why Workflow Agent, not Hosted Agent:**
The hosted agent approach (containerized Python orchestrator exposing `POST /responses` on
port 8088) was attempted and abandoned. Issues encountered:
- Foundry runtime requires SSE streaming (rejects plain JSON with "invalid format")
- SSE connections drop during the 17-20s orchestrator processing time
- Keepalive workarounds introduced async generator complexity without resolving the timeout
- The container debugging cycle (build → push → deploy → test) was slow and opaque

Workflow agents are **fully managed, declarative, and require no container**. They support
multi-agent orchestration natively (sequential, group chat, branching), and each agent node
can use MCPTool and KB tools. They can be published to Teams and M365 Copilot just like
hosted agents. Private networking is also supported (hosted agents do not support it during
preview).

**Why not ConnectedAgentTool / A2APreviewTool:**
- `ConnectedAgentTool` — **deprecated**. Part of the classic Foundry Agent Service API
  (Threads/Runs model). Removed from the new Foundry portal. Does not exist in
  `azure-ai-projects` 2.0.1 SDK. Classic agents retire March 31, 2027. The Python
  orchestrator + `agent_reference` + Responses API pattern is the canonical replacement
  (confirmed by Microsoft docs, Azure Architecture Center, and community implementations)
- `A2APreviewTool` — designed for **cross-system** agent-to-agent communication (Google's
  A2A protocol). Not appropriate for co-located agents in the same Foundry project. Preview
  status, adds HTTP round-trip overhead for each agent call. Each sub-agent would need to be
  deployed as a separate A2A HTTP server — significant infrastructure overhead with no benefit

**Phase 0 — Foundation** ✅ COMPLETE
- [x] Refactor: `Orchestrator` class → `agents/orchestrator_agent.py`; profiles/context
  helpers → `profiles.py`; `main.py` becomes thin CLI entry point
- [x] Write `Dockerfile` for Python backend (`python:3.13-slim`; requires Python 3.12+)
- [x] Set up service principal for local Docker auth
- [x] Clean up hosted agent artifacts (`agent_server.py`, `Dockerfile.hosted`, `azure.yaml`,
  `agent.yaml`, `infra/`)

**Phase 1 — Workflow Agent** ✅ COMPLETE
- [x] Define workflow YAML with routing logic (conditional branching)
- [x] Register Advisor Agent node with KB MCP tool
- [x] Register Calculator Agent node with refi calculator MCP tool
- [x] Register Scheduler Agent node with appointment scheduler MCP tool
- [x] Register Calendar Agent node with Work IQ Calendar MCP tool (CreateEvent)
- [x] Upload workflow via `WorkflowAgentDefinition` + `deploy_workflow.py`
- [x] Test flagship query end-to-end in Foundry portal playground
- [x] Add HIL patterns: calculator loan details collection (with retry loop + skip),
  appointment confirmation (confirm/reschedule/decline with GotoAction loops)
- [x] Parity audit: workflow YAML matches Python orchestrator logic (keywords, flow
  structure, reschedule enrichment context)
- Note: requires preview header `Foundry-Features: WorkflowAgents=V1Preview` (injected via
  custom `SansIOHTTPPolicy` in `deploy_workflow.py`)
- Note: Foundry workflow `kind: Question` nodes require `prompt` (not `question.text`)
  and `entity: StringPrebuiltEntity` for free-text input

**Phase 2 — Workflow Hardening** ✅ COMPLETE (2026-03-24)
- [x] Simplified workflow from 740 lines (7 combinatorial branches) to ~289 lines
  (4 sequential ConditionGroups — advisor, calculator, scheduler, general)
- [x] Fixed Power Fx syntax: `"keyword" in Lower(var)` not `Contains()` (unsupported)
- [x] Fixed `SendActivity.activity` — does not evaluate Power Fx; uses static strings
- [x] Added `Local.EarlyExit` flag — "done" keywords at any HIL pause skip remaining agents
- [x] Added `Local.OriginalText` — preserves user query for scheduler (LatestMessage gets
  overwritten by advisor/calculator outputs)
- [x] Removed all `conversationId` from `InvokeAzureAgent` nodes — each agent gets fresh
  context per invocation (prevents conversation history buildup that confused routing
  and prevented scheduler MCP tool execution)
- [x] Added general/meta query handling — orchestrator answers capabilities questions
  directly without invoking sub-agents (4th `response` field in routing JSON)
- [x] Added graceful HIL fallbacks — unrecognized input at any pause point gets
  "I didn't quite understand that, but no problem — we'll keep moving"
- [x] Flipped scheduler confirmation default — explicit confirm keywords required for
  calendar creation; unrecognized input moves on safely without creating events
- [x] Updated `deploy_workflow.py` orchestrator instructions to match
- [x] Updated Python orchestrator (`orchestrator_agent.py`) for parity (general query
  handling, 4-tuple classification)
- [x] All 111 tests passing

**Workflow YAML key patterns:**
- **No `conversationId`** on any `InvokeAzureAgent` node — each invocation gets a fresh
  Foundry conversation. Context is passed via enriched input messages (`Concatenate`).
  This is critical: `conversationId: =System.ConversationId` causes history buildup
  across workflow runs in the same session; `Concatenate(...)` suffixes cause "Malformed
  identifier" errors.
- **`Local.OriginalText`** saved at workflow start — `Local.LatestMessage` gets overwritten
  by each agent's output, so the scheduler needs the original to extract day/time.
- **Power Fx `in` operator** for string containment — NOT `Contains()` function.
- **`SendActivity.activity`** only accepts literal strings — no expression evaluation.
- **`elseActions` must be safe** — default paths should never trigger side effects
  (e.g., creating calendar events for confused input).

**Backlog — Copilot Studio + Teams Publishing** (investigated 2026-03-26)

**Root cause fix: Broken embedding deployment**
The `text-embedding-3-small` deployment was returning `OperationNotSupported` despite having
`embeddings: true` capability — a broken deployment state. Fix: delete and recreate via CLI.
This resolved vector search failures on the portal-created chunked index (`ks-va-loan-guidelines-index`,
21 docs), which in turn fixed the KB MCP `knowledge_base_retrieve` tool and all Advisor agent responses.

**Working channels:**
- **Foundry Playground** — fully working (admin account)
- **Bot Web Chat** — fully working (admin account), duplicate response issue (platform-level,
  activity protocol sends each response twice — not fixable from workflow YAML)

**Bot Service details:**
- Bot name: `va-loan-concierge-workflow91735` (auto-created by Foundry publish flow)
- Bot Type: SingleTenant (cannot change — ServiceIdentity type, greyed out in portal)
- Microsoft App ID: `196859d8-8487-429e-bf79-60230969de99` (ServiceIdentity)
- Channels: webchat, directline, msteams (all enabled)
- Schema Transformation Version: V1.3
- No OAuth Connection Settings configured

**Channels attempted and their blockers:**

| Channel | Result | Blocker |
|---|---|---|
| M365 Copilot (admin tenant) | Agent appears, fails silently | Copilot Chat (Basic) — custom agents require full M365 Copilot license |
| Teams search (admin tenant) | Agent not found | Not installed as Teams app, only published to M365 Copilot |
| Teams sideload (fordjames tenant) | Bot works, sign-in works, RBAC error | fordjames needs Azure AI User role on admin tenant's Foundry project; admin tenant blocks guest invitations |
| Teams sideload (admin sign-in) | OAuth 500 error | Foundry `agent-oauth` service returns 500 on cross-tenant OAuth redirect |
| Copilot Studio (fordjames tenant) | Connector blocked | Power Platform DLP policy "Personal Developer (default)" blocks Azure AI Foundry Agent Service connector |
| Change Bot Type to MultiTenant | Cannot change | ServiceIdentity type — setting greyed out in portal |
| Enable guest invitations (admin tenant) | Cannot change | Entra External Collaboration settings locked (managed sandbox tenant) |

**Key learnings for deployment:**
1. **Same-tenant deployment is critical** — the Foundry project, M365 Copilot license, and
   Teams users must all be in the same Entra tenant for seamless publishing
2. **M365 Copilot license required** — Copilot Chat (Basic) does NOT support custom agents;
   full Microsoft 365 Copilot license is required
3. **ServiceIdentity limitations** — auto-created by Foundry publish flow; cannot be changed
   to MultiTenant; cannot generate client secrets for OAuth configuration
4. **Two search indexes created** — `kb-va-loan-guidelines` (3 docs, original) and
   `ks-va-loan-guidelines-index` (21 docs, portal-created with chunking/vectors). The KB
   MCP endpoint uses the chunked index.
5. **Embedding deployment can silently break** — if vectorization errors appear on the
   portal-created index, delete and recreate the embedding model deployment

**When revisited with same-tenant setup:**
- [ ] Ensure M365 Copilot license is available in the deployment tenant
- [ ] Publish workflow agent from Foundry portal (same flow — already documented)
- [ ] Verify agent appears and responds in M365 Copilot
- [ ] Sideload Teams app manifest for direct Teams chat access
- [ ] Design Adaptive Cards: refi savings card + appointment confirmation card
- [ ] Investigate duplicate response issue in Bot Web Chat
- [ ] Verify multi-turn HIL conversation works in Teams

---

### Phase 6. Infrastructure-as-Code (`azd up` / `azd down`) — ✅ COMPLETE

**Implemented state:**
Full Azure Developer CLI flow that provisions all infrastructure, deploys code, and registers
agents with a single `azd up` command. `azd down` tears everything down cleanly.

**Resource model:** Next-gen Foundry (`Microsoft.CognitiveServices/accounts` kind `AIServices`
+ child `/projects`), NOT the v1 Hub model (`Microsoft.MachineLearningServices/workspaces`).

**What `azd up` does:**
1. Bicep provisions: AI Services account, AI Project, AI Search, Function App (Flex Consumption),
   Storage, App Insights, Log Analytics — plus 15 RBAC role assignments
2. `postprovision.ps1` (consolidated PowerShell hook):
   - Uploads knowledge docs to blob storage
   - Creates Search data source, index (with vector field), skillset (embedding generation),
     and indexer (blob → skillset → index)
   - Provisions RemoteTool connections for KB MCP and custom MCP
   - Creates Foundry guardrail policies (`va-loan-advisor-guardrail`, `va-loan-tools-guardrail`)
   - Deploys MCP server to Function App via `func azure functionapp publish --python`
   - Writes `.env` from azd env values
   - Registers all Foundry agents via `deploy_workflow.py`
3. **Manual steps after `azd up`** (see README.md):
   - Create Foundry IQ Knowledge Base in the portal (wraps the search index)
   - Assign guardrails to agents in portal (Build > Agents > [agent] > Guardrails)
   - (Optional) Configure Work IQ Calendar connection

**Implementation details:**
- Hooks are PowerShell (`.ps1`), using `shell: pwsh` in `azure.yaml` (no separate postdeploy)
- Function App uses Flex Consumption (FC1), not Y1 Consumption or shared App Service Plan
- Storage uses `allowSharedKeyAccess: false` and MI-based auth (policy requirement)
- All API versions use `2025-04-01-preview` for Foundry resources
- Search API uses `2024-11-01-preview` for data plane calls
- Foundry IQ KB creation is manual (portal) — the `azure-search-documents` SDK for
  programmatic KB creation is in preview and was unreliable
- Separate search token needed: `az account get-access-token --resource https://search.azure.com`

**Naming convention:** `{abbreviation}{environmentName}` — e.g. `ais-valc-demo-abc`,
`srch-valc-demo-abc`, `func-valc-demo-abc`.

**Region:** User-selectable during `azd up` from curated list (eastus, eastus2, westus,
westus3, swedencentral).

**Two manual steps after `azd up`:**
1. Create Foundry IQ Knowledge Base in the portal (SDK-based creation was unreliable)
2. (Optional) Work IQ Calendar connection (requires M365 Copilot license)

See README.md for detailed instructions with exact property values.

---

### Phase 9. Web App Deployment (App Service + Static Build) — DEFERRED (VM quota)

**Status:** Deferred — subscription-wide App Service VM quota is 0 for all classic tiers
(Free, Shared, Basic, Standard, Premium). Bicep modules (`web-app.bicep`) are written but
not wired into `main.bicep`. The demo runs locally for now. Flex Consumption (used by the
Function App) works because it has separate quota.

**Goal:** Deploy the FastAPI backend + React frontend as an Azure App Service so the demo
is accessible at a public URL without running locally.

**New Bicep module: `infra/modules/web-app.bicep`**
- App Service Plan: `plan-${environmentName}`, SKU **B1** (minimum required for VNet
  integration in Phase 8 — do not use Free/Shared/B0)
- App Service: `app-${environmentName}`, `kind: 'app,linux'`, `linuxFxVersion: 'PYTHON|3.12'`
- `identity.type: 'SystemAssigned'` — managed identity replaces `az login` credential
- `appCommandLine: 'uvicorn api.server:app --host 0.0.0.0 --port 8000'`
- `SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'` — Oryx runs `pip install -r requirements.txt`
- App Settings: all env vars from `.env.example` passed from `main.bicep` outputs +
  `APPLICATIONINSIGHTS_CONNECTION_STRING` + `WEB_APP_ORIGIN`
- Outputs: `webAppId`, `webAppName`, `webAppPrincipalId`, `webAppHostname`, `appServicePlanId`

**Modify: `infra/main.bicep`**
- Add `module webApp 'modules/web-app.bicep'` at Level 2 (alongside `functionApp`)
- Pass all Foundry/MCP env vars from other module outputs + monitoring connection string
- Pass `webAppPrincipalId` to `rbac` module
- New outputs: `WEB_APP_HOSTNAME`, `WEB_APP_NAME`

**Modify: `infra/modules/rbac.bicep`**
- New param: `webAppPrincipalId`
- 5 new role assignments for Web App MI (`principalType: 'ServicePrincipal'`):
  - `Cognitive Services OpenAI User` on AI Services (Responses API)
  - `Cognitive Services User` on AI Services (agent management)
  - `Search Index Data Reader` on Search (KB queries)
  - `Storage Blob Data Reader` on Storage
  - `Contributor` on resource group (ARM PUT for RemoteTool connections during `initialize()`)

**Code changes:**
- `api/server.py` — add `StaticFiles` mount (after all API routes) serving `./static/`
  with `html=True` for SPA fallback. Add dynamic CORS origin from `WEB_APP_ORIGIN` env var.
- No frontend code changes — Vite production build uses relative paths (`/api/chat`)
  which resolve correctly when served from the same origin.

**Auth note:** `DefaultAzureCredential` on App Service automatically picks up the
system-assigned managed identity — no code changes needed. The same agent initialization
code works locally (via `az login`) and in production (via MI).

---

### Phase 10. Observability — App Insights + OpenTelemetry + Audit — ✅ COMPLETE

**Two complementary tracing systems:**

**Foundry Portal Tracing (automatic — no code needed):**
Agent traces are tied to the agent/project, NOT the calling surface. Every Responses API
call — whether from the playground, CLI, or the FastAPI server — generates a trace visible
in the Foundry portal under **Tracing**. Thread IDs, tool calls, and token usage all
appear. No additional configuration needed.

**App Insights / OpenTelemetry (Phase 10 — application-level):**
Captures the HTTP request lifecycle, routing classification timing, and per-agent latency
breakdown. Complements Foundry traces with the operational/infrastructure view.

**Implemented files:**

`api/telemetry.py` (new):
- `setup_telemetry(app)` — initializes OTel `TracerProvider` with `AzureMonitorTraceExporter`
- `get_tracer()` — returns the configured tracer (or no-op if telemetry disabled)
- Instruments: FastAPI (request spans), `requests` (ARM calls), `aiohttp` (Foundry SDK)
- No-ops gracefully when `APPLICATIONINSIGHTS_CONNECTION_STRING` is absent (local dev)

`requirements.txt` — added 6 OTel packages:
- `opentelemetry-api`, `opentelemetry-sdk`
- `opentelemetry-instrumentation-fastapi`, `-requests`, `-aiohttp-client`
- `azure-monitor-opentelemetry-exporter`

`api/server.py`:
- Calls `setup_telemetry(app)` in the lifespan function before orchestrator init
- Wraps each chat request in a `chat_request` span with query, profile_id,
  conversation_id attributes

`agents/orchestrator_agent.py`:
- OTel spans around routing classification (`orchestrator.classify`) and each sub-agent
  call (`agent.advisor`, `agent.calculator`, `agent.scheduler`, `agent.calendar`)
- Trace hierarchy: `POST /api/chat` → `chat_request` → `orchestrator.classify` →
  `agent.advisor` → `agent.calculator` → `agent.scheduler` → `agent.calendar`

`infra/modules/monitoring.bicep`:
- Increased `retentionInDays` from 30 to 90 (financial compliance)

`infra/main.bicep`:
- Added `APPLICATIONINSIGHTS_CONNECTION_STRING` as azd output

`infra/hooks/postprovision.ps1`:
- Writes `APPLICATIONINSIGHTS_CONNECTION_STRING` to `.env`

**Where to look:**

| What | Where | How |
|---|---|---|
| LLM inputs/outputs, tool calls, tokens | Foundry portal → Build → Tracing | Automatic (Responses API) |
| HTTP requests, agent timing, routing | App Insights → Transaction Search | OTel spans (Phase 10) |
| Service topology | App Insights → Application Map | Auto-discovered from spans |
| Agent latency breakdown | App Insights → Performance | Per-operation timing |

**Future consideration:** For long-term audit trails beyond App Insights retention,
add a persistent conversation store (Cosmos DB or Table Storage). Out of scope for
initial implementation — App Insights + Foundry tracing covers the demo.

---

### Phase 11. Authentication — Entra ID Easy Auth — PLANNED

**Goal:** Add user authentication so the system knows who the logged-in Veteran is.
Required for Work IQ Calendar (delegated auth) and audit logging.

**Approach:** App Service Easy Auth (built-in authentication) with Microsoft Entra ID
provider. No frontend code changes — Easy Auth handles login redirect at the platform
level; `fetch` calls include the session cookie automatically.

**Modify: `infra/hooks/postprovision.ps1`** — add section after existing connection setup:
- `az ad app create` — Entra app registration with redirect URI
  `https://{WEB_APP_HOSTNAME}/.auth/login/aad/callback`, audience `AzureADMyOrg`
- `az ad sp create` — service principal for the app
- `azd env set AUTH_CLIENT_ID $APP_ID`
- `az webapp auth microsoft update` — enable Easy Auth on the App Service
- Idempotent: only runs when `AUTH_CLIENT_ID` is not already set

**Code changes:**
- `api/server.py` — add `_get_user_identity(request)` helper to extract
  `X-MS-CLIENT-PRINCIPAL-ID` and `X-MS-CLIENT-PRINCIPAL-NAME` headers injected by
  Easy Auth. Log user identity on each request (feeds Phase 6 audit trail).
- No React/frontend changes — Easy Auth redirects to Microsoft login before the SPA
  loads. After authentication, all API calls include the session cookie automatically.

**Work IQ Calendar — delegated auth:**
When the user is authenticated via Entra, the Foundry Work IQ Calendar connection can
be configured for delegated (OAuth2) permissions in the Foundry portal. This allows the
Calendar Agent to create events on the *authenticated user's* M365 calendar rather than
a service account's calendar.
- Requires M365 Copilot license on the user
- Must be configured manually in the Foundry portal (project → Connections → Work IQ
  Calendar → edit to delegated auth)

**Prerequisites:**
- Phase 5 must be complete (App Service must exist)
- User running `azd up` needs `Application Administrator` or `Cloud Application
  Administrator` directory role in Entra to create app registrations

Items:
- [ ] Modify `infra/hooks/postprovision.ps1` — add Entra app registration + Easy Auth setup
- [ ] Modify `api/server.py` — add user identity extraction + logging
- [ ] Document Work IQ Calendar delegated auth manual step
- [ ] Test: browse → redirect to Microsoft login → authenticate → query works with user logged

---

### Phase 12. Network Isolation — VNet + Private Endpoints — PLANNED

**Goal:** Lock down all backend services behind a VNet with private endpoints. Only the
App Service frontend remains publicly accessible (behind Easy Auth). Required for
financial institution compliance.

**New Bicep module: `infra/modules/network.bicep`**
- **VNet**: `vnet-${environmentName}`, address space `10.0.0.0/16`
- **Subnets**:
  - `snet-webapp` (`10.0.1.0/24`) — delegation: `Microsoft.Web/serverFarms`
  - `snet-functions` (`10.0.2.0/24`) — delegation: `Microsoft.Web/serverFarms`
  - `snet-private-endpoints` (`10.0.3.0/24`) — no delegation
- **NSG** on PE subnet: allow VNet inbound, deny internet inbound
- **Private Endpoints** (3):
  - `pe-ais-{env}` → AI Services (`privatelink.cognitiveservices.azure.com`)
  - `pe-srch-{env}` → AI Search (`privatelink.search.windows.net`)
  - `pe-st-{env}` → Storage blob (`privatelink.blob.core.windows.net`)
- **Private DNS Zones** (3) — each linked to VNet with auto-registration via zone groups
- Outputs: `vnetId`, `webAppSubnetId`, `functionsSubnetId`

**Modify existing Bicep modules — disable public access:**
- `ai-services.bicep`: `publicNetworkAccess: 'Disabled'`, `networkAcls.defaultAction: 'Deny'`
- `search.bicep`: `publicNetworkAccess: 'disabled'`
- `storage.bicep`: `publicNetworkAccess: 'Disabled'`, `allowSharedKeyAccess: false`,
  `networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }`

**Function App hosting change (important):**
The current Y1 Consumption plan does NOT support VNet integration. Rather than upgrade to
EP1 Elastic Premium (~$200/month, overkill for demo), move the Function App to the same
B1 App Service Plan created in Phase 5.
- `function-app.bicep`: remove the Y1 plan resource, add `appServicePlanId` param (from
  web-app module output), add `virtualNetworkSubnetId` + `vnetRouteAllEnabled: true`
- Replace shared-key `AzureWebJobsStorage` connection string with MI-based auth:
  `AzureWebJobsStorage__accountName: storageAccountName`

**Modify: `web-app.bicep`**
- Add `virtualNetworkSubnetId` + `vnetRouteAllEnabled: true`
- Export `appServicePlanId` output (shared with Function App)

**Modify: `infra/main.bicep`**
- Add `module network` at Level 1 (after monitoring, before AI Services)
- Add optional `trustedIp` parameter (default empty)
- Wire subnet IDs to web-app and function-app modules
- Wire web app plan ID to function-app module

**New RBAC (in `rbac.bicep`):**
- Function App MI → `Storage Blob Data Owner` on Storage (for Functions runtime)
- Function App MI → `Storage Queue Data Contributor` on Storage (Functions uses queues)

**Provisioning hook changes (`postprovision.ps1`):**
Data-plane calls (blob upload, Search index creation) will fail when public access is
disabled. Solution: if `TRUSTED_IP` is set, add the developer's IP to network rules at
the start of the hook, perform data-plane operations, then optionally remove.
```bash
azd env set TRUSTED_IP $(curl -s ifconfig.me)
azd up
```

**No application code changes.** All network changes are infrastructure-only.
`DefaultAzureCredential` continues to work — MI reaches backend services over the VNet.
ARM control-plane calls (`management.azure.com`) are public and work from inside the VNet.

Items:
- [ ] Create `infra/modules/network.bicep` (VNet, subnets, NSG, PEs, DNS zones)
- [ ] Modify `infra/modules/ai-services.bicep` — disable public access
- [ ] Modify `infra/modules/search.bicep` — disable public access
- [ ] Modify `infra/modules/storage.bicep` — disable public access + shared key
- [ ] Modify `infra/modules/function-app.bicep` — shared plan + VNet + MI storage auth
- [ ] Modify `infra/modules/web-app.bicep` — VNet integration + export plan ID
- [ ] Modify `infra/modules/rbac.bicep` — add Function App MI storage roles
- [ ] Modify `infra/main.bicep` — wire network module + trustedIp param
- [ ] Modify `infra/hooks/postprovision.ps1` — add trusted IP bypass logic
- [ ] Test: all private endpoints resolve, public access denied, `azd up` succeeds

---

### Phase 13. Persistent Conversation State — Cosmos DB — ✅ COMPLETE

**Goal:** Replace the ephemeral in-memory conversation state (`api/conversation_state.py`)
with Azure Cosmos DB for NoSQL, so HIL conversations survive server restarts and support
multi-instance scaling.

**Why Cosmos DB NoSQL Serverless:**
- Foundry's own BYO Thread Storage uses Cosmos DB internally — aligns with ecosystem
- Serverless: pay-per-RU (~$0/month for demo workload), no capacity planning needed
- Seamless migration path to Provisioned Throughput later if needed
- `disableLocalAuth: true` (RBAC-only) matches project's existing security pattern
- Native TTL support eliminates manual `_cleanup_expired()` logic

**Why not Foundry built-in state:**
- Foundry BYO Thread Storage (`enterprise_memory`) is for the Assistants/Threads API —
  this project uses the Responses API with Python-level orchestration
- Foundry Memory Stores (preview, `client.beta.memory_stores`) are for semantic long-term
  memory ("remember what the user said"), not structured orchestration state (routing flags,
  retry counts, pending actions)
- Custom Cosmos DB gives full control over schema, TTL, and query patterns

**Container design:**
- Account: Serverless NoSQL (`capabilities: [EnableServerless]`)
- Database: `va-loan-concierge`
- Container: `conversation-state`
- Partition key: `/conversation_id` (point reads = 1 RU, writes ~6 RU for 2 KB docs)
- TTL: `defaultTtl: 600` (10 min — resets on each upsert via Cosmos `_ts` field)
- Indexing: minimal — only `/conversation_id/?` and `/pending_action/?`, everything else
  excluded to save RU on writes

**RBAC (critical — Cosmos DB uses data-plane roles, NOT Azure control-plane):**
- Resource type: `Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments`
  (NOT `Microsoft.Authorization/roleAssignments` like the rest of the project)
- Role: `Cosmos DB Built-in Data Contributor` (ID `00000000-0000-0000-0000-000000000002`)
- Principals: current user (local dev) + future Web App MI (Phase 9)

**Python SDK pattern (async):**
- Package: `azure-cosmos>=4.9.0` (async via `azure.cosmos.aio`)
- Single `CosmosClient` instance for application lifetime (created in server lifespan)
- `read_item()` for point reads (1 RU) — not `query_items()` (3+ RU)
- `upsert_item()` for create-or-update (resets `_ts`, extending TTL)
- `ConversationState` dataclass shape is unchanged — only the persistence layer changes

**New Bicep module: `infra/modules/cosmos-db.bicep`**
- Serverless NoSQL account: `cosmos${cleanName}`
- Database + container with TTL and minimal indexing policy
- `disableLocalAuth: true`, `consistencyPolicy: Session`

**Modify: `infra/main.bicep`**
- Add `module cosmosDb 'modules/cosmos-db.bicep'` at Level 0 (independent)
- Output: `COSMOS_ENDPOINT`

**Modify: `infra/modules/rbac.bicep`**
- Add Cosmos data-plane role assignments (new `sqlRoleAssignments` resource type)

**Modify: `infra/hooks/postprovision.ps1`**
- Write `COSMOS_ENDPOINT` to `.env`

**Code changes:**
- `requirements.txt` — add `azure-cosmos>=4.9.0`
- `api/conversation_state.py` — rewrite: async Cosmos client replaces in-memory dict.
  New async functions: `init_cosmos()`, `create_conversation()`, `get_conversation()`,
  `save_conversation()`, `delete_conversation()`. Remove `_store`, `_cleanup_expired`,
  `is_expired`
- `api/server.py` — init Cosmos client in lifespan startup, close on shutdown
- `agents/orchestrator_agent.py` — make state calls `await`, add
  `await save_conversation(state)` after each mutation (~15 points throughout the file)
- `tests/test_orchestrator.py` — mock Cosmos operations or provide in-memory fallback

Items:
- [x] Create `infra/modules/cosmos-db.bicep` (Serverless account + database + container)
- [x] Modify `infra/main.bicep` — wire Cosmos module + outputs
- [x] Modify `infra/modules/rbac.bicep` — add Cosmos data-plane role assignments
- [x] Modify `infra/hooks/postprovision.ps1` — write COSMOS_ENDPOINT to .env
- [x] Add `azure-cosmos>=4.9.0` to `requirements.txt`
- [x] Rewrite `api/conversation_state.py` — dual-backend (Cosmos + in-memory fallback)
- [x] Update `api/server.py` — Cosmos client lifecycle in lifespan
- [x] Update `agents/orchestrator_agent.py` — async state calls + save after mutations
- [x] Update `.env.example` — add `COSMOS_ENDPOINT`
- [x] Update tests — `init_store()` fixture + async `get_conversation` calls
- [x] All 111 tests passing
- [x] Test: `azd up` provisions Cosmos account + database + container (confirmed 2026-03-29; East US AZ capacity workaround via `COSMOS_LOCATION` override)
- [x] Test: restart server, resume HIL conversation — state persists (confirmed 2026-03-29 via UI; requires `pip install azure-cosmos` — missing package causes silent in-memory fallback)
- [ ] Test: wait 10+ min — expired state auto-deleted by Cosmos TTL

---

### Phase 14. Content Understanding — VA Rate & News Intelligence Pipeline — PLANNED

**Goal:** Add a Content Understanding ingestion pipeline that processes external content
(VA rate changes, policy updates, mortgage industry news) into structured data, pushes it
to Azure AI Search, and makes it queryable by the existing Advisor Agent via Foundry IQ.

**What is Content Understanding:**
Azure Content Understanding is a **GA Foundry Tool** (API `2025-11-01`, Python SDK
`azure-ai-contentunderstanding>=1.0.1`) that uses generative AI to process unstructured
content (documents, HTML, images, audio, video) into **user-defined structured output**.
It runs on the same `Microsoft.CognitiveServices/accounts` (kind: `AIServices`) resource
the project already uses.

Core concept: **Analyzers** — configurable processing units that define a field schema
with three extraction methods per field:
- `extract` — literal values from content (titles, dates, names)
- `generate` — AI-generated values (summaries, relevance assessments)
- `classify` — categorize against an enum (source type, rate direction)

**Why Content Understanding (not just more markdown files):**
- Processes real HTML/web content into consistent structured output with confidence scores
- Custom analyzers enforce schema consistency across diverse sources
- Supports GA Python SDK with async client
- Runs on the existing AI Services resource (no new infrastructure)
- Content Understanding MCP server for direct agent access is "coming soon" (not yet available)

**Architecture:**
```
RSS/Web Feeds → Timer-Triggered Azure Function → Content Understanding (Custom Analyzer)
    → Structured JSON → Azure AI Search Index → Foundry IQ KB → Advisor Agent (existing)
```

**Custom analyzer field schema (VA Mortgage News):**
- `Title` (extract), `PublishDate` (extract)
- `SourceType` (classify: rate_change | policy_update | industry_news | va_circular |
  lender_bulletin)
- `Summary` (generate: 2-3 sentences for veterans/lenders)
- `RateInfo` (generate: object — current_rate, previous_rate, effective_date, direction)
- `PolicyUpdate` (generate: object — affected_area, change_description, effective_date)
- `RelevanceToVeterans` (generate: one sentence)

**Model deployments:**
Content Understanding requires completion + embedding models. Options:
- Add `gpt-4.1-mini` deployment (CU default for field extraction — cheaper than gpt-4.1)
- Configure CU defaults to use existing `gpt-4.1` and `text-embedding-3-small` deployments
  (avoids new deployments but uses more expensive model for extraction)

**New files:**
- `tools/content_ingestion.py` — Content Understanding client wrapper: create/manage
  analyzer, analyze content, push structured output to search index
- `tools/feed_sources.json` — RSS feed URLs and web source configuration
- `mcp-server/ingest_trigger.py` — Timer-triggered Azure Function (every 4 hours):
  fetch RSS feeds → download articles → CU analyze → push to search index

**Files to modify:**
- `infra/modules/ai-services.bicep` — (optional) add `gpt-4.1-mini` model deployment
- `infra/hooks/postprovision.ps1` — create news search index + configure CU analyzer defaults
- `agents/advisor_agent.py` — update `ADVISOR_INSTRUCTIONS` to reference news/rate sources,
  include publish dates in citations for timely content
- `requirements.txt` — add `azure-ai-contentunderstanding>=1.0.1`, `feedparser>=6.0.0`
- `mcp-server/requirements.txt` — add same dependencies for Function App
- `.env.example` — add `CU_ANALYZER_NAME=`, `NEWS_INDEX_NAME=`

**What NOT to do:**
- Do NOT use CU as a real-time agent tool — it is async batch processing (seconds to minutes
  latency), not suitable for synchronous agent calls
- Do NOT bypass Foundry IQ — CU produces data, Foundry IQ provides agentic retrieval with
  citations and permissions. CU is the producer; Foundry IQ is the consumer
- Do NOT use the preview-only Pro mode (`2025-05-01-preview`) — multi-file analysis and
  external KB features are not in the GA API

Items:
- [ ] Create custom CU analyzer via Python SDK or REST API
- [ ] Create `tools/content_ingestion.py` — CU client wrapper + search push
- [ ] Create `tools/feed_sources.json` — RSS/web source configuration
- [ ] Create `mcp-server/ingest_trigger.py` — timer-triggered ingestion function
- [ ] Create news search index in `postprovision.ps1`
- [ ] (Optional) Add `gpt-4.1-mini` model deployment to `ai-services.bicep`
- [ ] Update `agents/advisor_agent.py` instructions for news/rate sources
- [ ] Add dependencies to `requirements.txt` and `mcp-server/requirements.txt`
- [ ] Test: manually ingest sample VA news article → verify structured output
- [ ] Test: ask Advisor "What are current VA loan rates?" → verify news source cited
- [ ] Test: timer trigger fires on schedule and ingests new content

---

### Phase 15. Foundry Memory Stores — Semantic Long-Term Memory — PLANNED

**Goal:** Add cross-conversation memory so the system remembers Veterans across sessions —
prior interactions, preferences, loan history, and communication patterns. This complements
Phase 13's session state (which tracks a single conversation's HIL flow) with a persistent
semantic layer that enriches future conversations automatically.

**What are Foundry Memory Stores:**
Foundry Memory Stores (`client.beta.memory_stores`) are a **preview** feature that gives
agents automatic long-term memory. The LLM extracts salient facts from conversations and
stores them as semantic memories. On future interactions, relevant memories are retrieved
automatically and injected into the agent's context — no explicit code needed for retrieval.

Memory Stores are attached to agent definitions in the Foundry portal (the "Memory" section
visible on each agent's configuration page). They are per-agent but shared across all
calling surfaces — a memory created during a React UI session is available when the same
Veteran uses Teams via the Workflow Agent, and vice versa.

**Expanded use case — Returning Veteran Recognition:**

*First visit (all managed by Phase 13 session state):*
Marcus asks about refinancing. The orchestrator's session state manages the multi-turn HIL
flow: pause for loan details → calculator runs → appointment booked for Thursday → user
confirms → calendar event created. Session state expires after 10 minutes of inactivity.

*Long-term memory captures (Phase 15 — automatic):*
- "Marcus completed IRRRL refinance from 6.8% to 6.1% on existing VA loan"
- "Marcus is funding-fee-exempt (10% disability rating)"
- "Marcus prefers Thursday afternoon appointments"
- "Marcus's loan officer was Sarah Chen (confirmation #LOAN-84921)"
- "Marcus's loan balance was approximately $320,000"

*Three weeks later — Marcus returns:*
Marcus asks: "I'm thinking about a cash-out refi to fund some home improvements."
Long-term memory automatically surfaces his prior context. The Advisor Agent knows he has
an existing VA loan (recently refinanced to 6.1%), is fee-exempt, and was working with
Sarah Chen. The system:
1. Skips basic eligibility questions (already established he has a VA loan)
2. Provides cash-out refi advice contextualized to his 6.1% rate and ~$320K balance
3. Pre-fills calculator with known loan parameters (session state collects only the new
   details — desired cash-out amount, estimated home value)
4. Offers to book with Sarah Chen again on a Thursday afternoon

This demonstrates both memory layers working together:
- **Session state** (Cosmos DB) manages the current conversation's HIL flow from scratch
- **Long-term memory** (Foundry Memory Stores) enriches the conversation with context from
  weeks ago, creating a personalized experience without re-collecting known information

**Architecture:**
```
                        ┌──────────────────────────┐
                        │   Foundry Memory Store    │
                        │  (semantic, cross-session) │
                        │  "Marcus prefers Thurs"   │
                        │  "IRRRL at 6.1%, exempt"  │
                        └─────────┬────────────────┘
                                  │ auto-retrieved at inference
                                  ▼
User ──→ Orchestrator ──→ [Agent + Memory Context] ──→ Response
              │
              ▼
     ┌─────────────────┐
     │  Cosmos DB State  │
     │  (structured,     │
     │   single-session) │
     │  pending_action,  │
     │  retry_count...   │
     └─────────────────┘
```

**Why Foundry Memory Stores (not custom Cosmos collections):**
- Automatic extraction — the LLM decides what is worth remembering, no manual code
- Automatic retrieval — relevant memories are injected at inference time, no query logic
- Portal-native — visible and manageable in the Foundry portal Memory section
- Shared across orchestration paths — React UI and Teams/Workflow Agent use the same store
- Preview feature aligns with Foundry roadmap (expected to GA alongside Responses API maturity)

**Implementation approach:**
- Enable Memory Stores on the Orchestrator agent (primary — sees all conversations)
- Optionally enable on Advisor agent (KB-enriched memories for loan-specific facts)
- Configure memory instructions to focus on: loan details, preferences, prior outcomes,
  communication patterns (NOT PII like SSN, account numbers, or full addresses)
- Update agent instructions to reference and leverage recalled memories
- Add memory-aware greeting logic: if memories exist for the user, acknowledge prior context
- Test: first conversation → verify memories created in portal; second conversation →
  verify relevant memories recalled and used

**Privacy and compliance considerations:**
- Memory Stores inherit the agent's content safety policies (Phase 7 guardrails)
- Must exclude PII from memory extraction (configure via memory instructions)
- Retention policy TBD — may need periodic memory pruning for compliance
- Veteran consent UX: inform user that the system remembers prior interactions
- Memory deletion API needed for "right to be forgotten" requests

**Prerequisite:** Phase 11 (Authentication) — long-term memory is only meaningful when
users are authenticated. Without auth, there's no way to associate memories with a
specific Veteran across sessions.

**Files to modify:**
| File | Change |
|------|--------|
| `agents/orchestrator_agent.py` | Enable Memory Store on agent registration; add memory-aware greeting logic |
| `agents/advisor_agent.py` | (Optional) Enable Memory Store for loan-specific recall |
| `profiles.py` | Update `_profile_context_block` to merge recalled memories with profile data |
| `api/server.py` | Pass authenticated user ID to orchestrator (requires Phase 11) |
| `CLAUDE.md` | Document Phase 15 |

Items:
- [ ] Enable Memory Stores on Orchestrator agent in Foundry portal
- [ ] Configure memory instructions (what to remember, what to exclude)
- [ ] Update agent instructions to reference recalled memories
- [ ] Add memory-aware greeting logic to orchestrator
- [ ] Test: first visit creates memories → second visit recalls them
- [ ] Add privacy controls (PII exclusion, consent UX, deletion API)
- [ ] Verify memories shared across React UI and Workflow Agent paths

---

### Phase Sequencing

Phases 1–8 + 10 + 13 are complete. Phases 9–16 bring production readiness and new capabilities.
Each `azd up` leaves the system fully working.

```
Completed:
  Phase 1 (Foundation) → Phase 2 (Agents + HIL) → Phase 3 (Foundry IQ KB)
  → Phase 4 (MCP Server) → Phase 5 (Workflow Agent) → Phase 6 (IaC)
  → Phase 7 (Guardrails) → Phase 8 (Evaluations) → Phase 10 (Observability)
  → Phase 13 (Cosmos DB State)

Planned (existing, blocked on Phase 9):
  Phase 9 (Web App)       ← DEFERRED (VM quota); demo runs locally
      ├── Phase 11 (Auth)          — requires Phase 9 (App Service for Easy Auth)
      └── Phase 12 (Network)       — requires Phase 9 (VNet integration needs App Service)

Planned (independent — can start immediately):
  Phase 14 (Content Understanding) ← new capability, enriches demo

Planned (requires Phase 11):
  Phase 15 (Foundry Memory Stores) ← cross-session Veteran memory (requires auth)

Validated (not a numbered phase):
  Orchestration patterns confirmed as MAF best practices (2026-03-29).
  See Phase 5 "Why not ConnectedAgentTool / A2APreviewTool" for rationale.

Dependency graph:
  Phase 14 is independent of Phases 9–12.
  Phase 13 complements Phase 9 (Web App MI gets Cosmos RBAC when unblocked).
  Phase 14 extends Phase 3 (Foundry IQ KB gets new content source).
  Phase 15 requires Phase 11 (Auth) — long-term memory needs authenticated user identity.
  Phase 15 complements Phase 13 — session state (structured) + long-term memory (semantic).
```