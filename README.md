# CivicAI

CivicAI is a runnable local MVP for an autonomous smart-city grievance resolution platform. It is built to demonstrate true agentic AI system thinking: each complaint moves through independent agents for understanding, image verification, classification, duplicate detection, priority scoring, routing, citizen communication, monitoring, escalation, risk prediction, resource allocation, sentiment analysis, and transparency reporting.

The MVP is intentionally self-contained. It uses Python's standard-library web server plus SQLite, so it runs on this machine without installing FastAPI, Streamlit, LangGraph, or PostgreSQL. The database schema and agent boundaries are shaped so the project can later move to FastAPI, LangGraph, PostgreSQL, ChromaDB, and Gemini with minimal redesign.

## What Works

- Citizen complaint submission with optional evidence image upload.
- Persistent SQLite database with citizens, complaints, departments, assignments, status history, escalations, agent runs, and SOP procedures.
- Autonomous multi-agent workflow:
  - Complaint Understanding Agent
  - Vision Verification Agent
  - Classification Agent
  - Duplicate Detection Agent
  - Priority Scoring Agent
  - Routing Agent
  - Citizen Communication Agent
  - Resolution Monitoring Agent
  - Escalation Agent
  - Transparency Report Agent
  - Predictive Risk Agent
  - Resource Allocation Agent
  - Citizen Sentiment Agent
- Duplicate complaint linking using local similarity scoring.
- Priority score from severity, affected citizens, location criticality, issue risk, and image evidence.
- Officer dashboard with status updates.
- Resolution Monitoring Agent that checks elapsed time against SLA for every open ticket.
- Escalation Agent that autonomously escalates SLA-breaching complaints through municipal levels.
- Predictive Risk Agent that detects ward-level complaint clusters and forecasts operational risk.
- Resource Allocation Agent that recommends staff deployment from active complaint load.
- Citizen Sentiment Agent that classifies post-resolution feedback and powers satisfaction metrics.
- Transparency dashboard with KPIs, map view, department load, status mix, rankings, predictive risk, staffing, and satisfaction.
- Optional Gemini REST integration through `GEMINI_API_KEY`.

## Run

From this folder:

```powershell
.\run.ps1
```

Then open:

```text
http://127.0.0.1:8080
```

If Python is available on PATH, this also works:

```powershell
python -m app.server --host 127.0.0.1 --port 8080
```

In this Codex workspace, the bundled Python runtime is detected automatically by `run.ps1`.

## Test

```powershell
.\run_tests.ps1
```

## Optional Gemini

Set an API key before running the server:

```powershell
$env:GEMINI_API_KEY="your-key"
$env:GEMINI_MODEL="gemini-2.5-flash"
.\run.ps1
```

Without a key, CivicAI still runs using deterministic local agents.

## API

```text
GET    /api/health
POST   /api/complaints
GET    /api/complaints
GET    /api/complaints/{id}
PATCH  /api/complaints/{id}/status
POST   /api/complaints/{id}/feedback
POST   /api/monitor/run
GET    /api/dashboard
```

## Data

Runtime data is stored under:

```text
data/civicai.db
data/uploads/
```

For a PostgreSQL migration, map the existing SQLite tables directly:

```text
citizens
complaints
departments
assignments
status_history
escalations
agent_runs
feedback
procedures
```

## Demo Script

1. File a complaint: "There is a huge water leak near ABC Road Government School affecting students."
2. Show the agent trace: understanding, vision check, classification, duplicate detection, priority score, route, citizen message.
3. File a similar second complaint at the same location to show duplicate linking.
4. Open the officer dashboard and run the Monitoring Agent to show autonomous SLA checks and escalation decisions.
5. Mark a complaint resolved, then submit negative feedback to trigger the Citizen Sentiment Agent.
6. Open the transparency dashboard to show department load, priority, map, rankings, predictive risk, resource allocation, and citizen satisfaction.
