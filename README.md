# LLMSQL — Agentic AI Database & Visualization Assistant

> Ask questions in plain English → get SQL queries, interactive charts, and AI insights from your database — instantly.

---

## 💡 What LLMSQL Does (Step-by-Step)

**LLMSQL** is an **Agentic AI Database & Visualization Assistant**. It allows non-technical users to query real databases using natural language.

When a user asks a question, LLMSQL executes a 7-step agentic workflow:

```mermaid
flowchart TD
    User([1. User Natural Language Question]) --> Memory[2. ConversationManager Store]
    Memory --> Agent[3. LLMSQL Agent Core]

    subgraph LLMSQL Registered Tool Menu (PS §4.2)
        Agent -->|Schema Inquiry| T1[get_schema]
        Agent -->|Data Query| T2[execute_query]
        Agent -->|Architecture Query| T3[generate_flowchart]
        Agent -->|Data Visualization| T4[generate_chart]
        Agent -->|Executive Summaries| T5[explain_data]
    end

    T1 --> DB[(ecommerce.db SQLite)]
    T2 --> DB
    DB --> Results[4. Structured Results & Guardrails]
    Results --> T4
    Results --> T5
    T3 --> UI
    T4 --> UI([5. Glassmorphic Dashboard])
    T5 --> UI
```

### The 7-Step Process

1. **User Asks Question**: Plain-English query (e.g. *"Top 5 products by revenue"* or *"Show me the ER diagram"*).
2. **Conversation Context**: `ConversationManager` pulls session memory for follow-up support (*"now show monthly trend for these"*).
3. **Schema Discovery (`get_schema`)**: Agent inspects tables, column types, foreign keys, and sample data.
4. **SQL Generation & Guardrails (`execute_query`)**: LLM constructs SQL; `guardrails.py` uses `sqlparse` token validation to enforce read-only `SELECT` execution and block multi-statement injection.
5. **Dynamic Visualization (`generate_chart`)**: Automatically selects the optimal chart (Bar, Line, Pie, Scatter) based on data shape and intent.
6. **System Diagramming (`generate_flowchart`)**: Generates Mermaid.js ER diagrams or process flowcharts for architecture queries.
7. **Executive Insights (`explain_data`)**: Computes summary statistics and formats plain-English executive takeaways, streamed directly to the UI.

---

## Quick Start

### Prerequisites
- Python 3.10+
- An OpenAI or Gemini API key

### 1. Clone & Configure

```bash
cp .env.example .env
# Edit .env and add your API key:
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Seed the Database

```bash
python -m src.database.seed_databases
```

### 4. Launch the Server

```bash
uvicorn src.main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

### 5. Using Docker (Recommended for Demo)

```bash
docker-compose up --build
```

---

## Tool Specification Table (Problem Statement §4.2)

| Tool Name | Class Name | Purpose | Parameters | Return Shape |
|:---|:---|:---|:---|:---|
| `get_schema` | `SchemaDiscoveryTool` | Inspect database tables, columns, keys, and sample rows | `table_name?: str` | `{table: {columns, foreign_keys, sample_rows, row_count}}` |
| `execute_query` | `ExecuteQueryTool` | Execute a validated SQL SELECT query against the database | `sql: str` | `{columns: list, rows: list[dict], row_count: int}` |
| `generate_chart` | `VisualizeDataTool` | Automatically select chart type and generate Plotly spec | `columns: list, rows: list, query_intent?: str` | `{chart_type, plotly_spec: dict}` |
| `generate_flowchart` | `SystemDiagramTool` | Generate Mermaid ER diagrams or process flowcharts | `diagram_type: "er"\|"flowchart"` | `{diagram_type, mermaid_markup: str}` |
| `explain_data` | `ExplainDataTool` | Compute statistics and generate plain-English executive summary | `columns: list, rows: list, query_intent?: str` | `{statistics: dict, explanation: str}` |

### Chart Selection Logic (`select_chart_type`)

> ⚠️ Implementation note: `visualizer.py::select_chart_type()` must implement these exact thresholds before demo day — this table is the source of truth the code should be tested against.

| Data Shape | Intent Keywords | Chart Type |
|:---|:---|:---|
| Categorical + Numeric (≤15 rows) | top, best, compare, ranking | **Bar** |
| Categorical + Numeric (>15 rows) | — | **Horizontal Bar** |
| Date/Time + Numeric | trend, over time, monthly, growth | **Line** |
| Categorical + Numeric (≤8 rows) | distribution, proportion, % | **Pie** |
| Two Numeric columns | correlation, vs, scatter | **Scatter** |

---

## Project Structure

```
LLMSQL/
├── public/                       # Frontend assets (CDN-independent)
│   ├── index.html                # Dashboard UI
│   ├── style.css                 # Glassmorphic design system
│   ├── app.js                    # SSE streaming, Plotly/Mermaid client
│   └── vendor/
│       ├── plotly.min.js         # Bundled Plotly JS (offline-safe)
│       └── mermaid.min.js        # Bundled Mermaid JS (offline-safe)
├── src/
│   ├── main.py                   # FastAPI server (REST + SSE endpoints)
│   ├── config.py                 # pydantic-settings env config
│   ├── tools/
│   │   ├── base.py               # Abstract Tool + ToolResult
│   │   ├── schema_discovery.py   # SchemaDiscoveryTool (get_schema)
│   │   ├── query_executor.py     # ExecuteQueryTool (execute_query)
│   │   ├── visualizer.py         # VisualizeDataTool (generate_chart)
│   │   ├── diagrammer.py         # SystemDiagramTool (generate_flowchart)
│   │   └── insight_explainer.py  # ExplainDataTool (explain_data)
│   ├── database/
│   │   ├── guardrails.py         # sqlparse token-based SQL validation
│   │   ├── db_manager.py         # SQLite connection & schema manager
│   │   └── seed_databases.py     # Ecommerce DB seed script
│   ├── agent/
│   │   ├── agent_controller.py   # Agentic tool-calling loop + SSE
│   │   └── conversation.py       # Multi-turn conversation memory
│   └── services/
│       └── llm_service.py        # OpenAI / Gemini / Mock providers
├── tests/
│   ├── test_guardrails.py        # SQL guardrail unit tests
│   └── test_visualizer.py        # Chart selection unit tests
├── data/                          # SQLite databases (auto-created)
├── .env.example                   # Environment variable template
├── Dockerfile                     # Docker build spec
├── docker-compose.yml              # One-command container launch
└── requirements.txt                # Python dependencies
```

---

## Example Queries

- *"What are the top 5 best-selling products by total revenue?"*
- *"Show monthly order count trend throughout 2025"*
- *"Which product categories have the highest average order value?"*
- *"Show me the ER diagram of the ecommerce database"*
- *"What is the distribution of orders by payment method?"*
- *"Show the LLMSQL agent workflow diagram"*

---

## Day 7 Demo Video Script (3–5 min)

1. **Introduction** (30s) — Show the UI, briefly explain LLMSQL and the agentic tool-calling pattern.
2. **Use Case 1: Sales Analytics** (60s) — Ask "Top 5 best-selling products by revenue" → show SQL transparency panel + bar chart + executive summary.
3. **Use Case 2: ER Diagram** (45s) — Ask "Show me the ER diagram of the database" → show Mermaid ER diagram rendering.
4. **Use Case 3: Process Flowchart** (45s) — Ask "Show me the LLMSQL agent workflow" → show Mermaid flowchart.
5. **Multi-Turn Follow-up** (45s) — "Now show the trend for these categories" → demonstrate conversation context retention.
6. **Architecture Close** (30s) — Expand the tool trace drawer, walk through the tool execution sequence.

---

## License

MIT
