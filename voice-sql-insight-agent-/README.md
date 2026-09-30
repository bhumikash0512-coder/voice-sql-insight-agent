# Voice-Based AI SQL Insight Agent

A voice-enabled analytics assistant that turns spoken business questions into secure SQL queries and replies with clear spoken insights, trend analysis, and risk signals through a lightweight browser interface.

## Highlights

- Voice input with browser speech-to-text
- Voice output with text-to-speech responses
- Natural language to SQL conversion with safety controls
- Context memory for follow-up questions
- Trend, anomaly, and risk-focused analytics
- Transparent SQL and returned-row visibility
- Optional LLM-backed planning (Ollama/Llama) with strict validation and safe fallback
- Auto-detects Hindi / English / mixed-language questions and responds accordingly

## Why This Project

Most analytics tools still expect users to click through dashboards or write SQL manually. This project makes analytics conversational: users can ask a question out loud, see the generated query path, and receive a direct business-focused answer instead of raw data alone.

## What It Does

- Uses browser speech recognition for hands-free questions
- Converts natural-language analytics requests into read-only SQL
- Queries a local SQLite database seeded from `data/business_metrics.csv`
- Returns insight-focused answers about trends, leaders, laggards, and risk hotspots
- Supports follow-up questions by reusing conversational context
- Reads answers aloud with browser text-to-speech
- Shows the generated SQL and returned rows for transparency
- Supports an optional LLM-based query planner (Ollama) with strict validation and safe fallback rules

## Tech Stack

- Backend: Python, Flask, SQLite, pandas
- Frontend: HTML, CSS, vanilla JavaScript
- Voice: Web Speech API for speech-to-text and speech synthesis
- Query layer: Ollama-backed LLM planner or deterministic rule-based planner
- Database: SQLite for demo mode, MySQL/PostgreSQL for client-ready deployments

## Project Structure

```text
voice-sql-insight-agent/
├── app.py                  # Flask entrypoint & API routes
├── src/
│   ├── __init__.py
│   ├── agent.py             # VoiceSQLAgent — core query logic
│   ├── data_setup.py        # Database initialization & helpers
│   └── llm_planner.py       # Ollama / LLM query planner
├── templates/
│   └── index.html           # Web UI
├── public/                  # Frontend assets (served to browser, required by Vercel)
│   ├── app.js
│   └── styles.css
├── data/
│   └── business_metrics.csv
├── .env                      # Local environment config (not committed)
├── .gitignore
├── .python-version
├── requirements.txt
├── vercel.json                # Vercel deployment config
├── VERCEL_DEPLOY.md           # Deployment notes
└── LICENSE
```

> **Note:** All frontend edits should be made in `public/` only — that's the directory the app serves from and the one Vercel expects.

## Run Locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the app:

```bash
python app.py
```

3. Open:

```text
http://127.0.0.1:5000
```

4. Allow microphone access in the browser to use voice mode.

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model name | `llama3.3` |
| `OLLAMA_API_KEY` | API key (only if using a hosted/remote Ollama) | *(optional)* |
| `DB_BACKEND` | `sqlite` or `mysql` | `sqlite` |
| `SQLITE_PATH` | Local SQLite file path | `business_metrics.db` |
| `PORT` | Server port | `5000` |

## MySQL Configuration

For a client-ready MySQL setup, set these environment variables before starting the app:

```powershell
$env:DB_BACKEND="mysql"
$env:MYSQL_HOST="your-host"
$env:MYSQL_PORT="3306"
$env:MYSQL_USER="your-user"
$env:MYSQL_PASSWORD="your-password"
$env:MYSQL_DATABASE="your-database"
$env:DB_SEED_SAMPLE="false"
$env:ANALYTICS_TABLE="business_metrics"
python app.py
```

If `DB_BACKEND` is not set to `mysql`, the app falls back to the local SQLite demo database generated from `data/business_metrics.csv`.
If you want MySQL demo data loaded automatically into an empty table, set `DB_SEED_SAMPLE=true`.

## Example Questions

- `Which region has the highest revenue?`
- `Show the monthly profit trend for Alpha`
- `What are the biggest risk hotspots?`
- `What about the South region?`
- `North region ka revenue kitna hai?`
- `Which product has the lowest customer satisfaction in April?`

## Security Model

- The app does not execute arbitrary user SQL
- SQL is generated only from a constrained internal schema
- LLM output is limited to a validated JSON plan, not raw SQL
- Requests are routed through whitelisted query patterns after validation
- The implementation is scoped to one analytics table: `business_metrics`
- MySQL access is configured through environment variables instead of hardcoded credentials

## Database Schema

The sample table includes:

```text
month, region, product_line, revenue, cost, units_sold, customer_churn, csat, incident_count
```

At startup the app creates a local SQLite database from the CSV file.
On Vercel, the demo SQLite file is created in the temporary runtime directory (note: this does **not** persist between requests — see `VERCEL_DEPLOY.md` for production-database guidance).
When `DB_BACKEND=mysql`, the app connects to the configured MySQL database. It seeds sample data only when `DB_SEED_SAMPLE=true`.

## How Follow-Up Context Works

Each browser session gets its own lightweight conversation memory. If the user asks a follow-up like:

- `Show the profit trend for Alpha`
- `What about North?`

the agent reuses earlier context where that makes sense.

## API Reference

### `POST /api/query`
```json
{
  "question": "Which region has highest revenue?",
  "sessionId": "user-123"
}
```

### `POST /api/batch-query`
```json
{
  "questions": ["Top region?", "What about last month?"],
  "sessionId": "user-123"
}
```

### `GET /api/health`
Returns database + LLM connection status.

### `GET /api/examples`
Returns sample questions.

### `GET /api/session/<sessionId>/context`
Returns current conversation context for a session.

### `POST /api/session/<sessionId>/reset`
Clears a session's conversation context.

## Deployment

### Vercel

This repo is prepared for Vercel with:

- a top-level `app` object in `app.py`
- frontend assets in `public/`
- `.python-version`
- `vercel.json`

Import the GitHub repository into Vercel and deploy. For client MySQL mode, add the same database environment variables used locally.

> ⚠️ Vercel is serverless — `localhost` Ollama and local SQLite will **not** work as-is in production. See `VERCEL_DEPLOY.md` for the required changes (hosted Ollama endpoint + external database).

## User Guide

1. Open the application in a modern browser such as Chrome or Edge.
2. Click `Start listening` or type a question manually.
3. Review the insight summary, generated SQL, and result rows.
4. Ask a follow-up question to continue the same conversation.
5. Toggle `Voice reply` if you want silent mode.

## Customizing for a Real Client Database

To adapt this project for a production client:

1. Replace the sample CSV or point the app to the client MySQL/PostgreSQL database.
2. Extend the schema map and query templates in `src/agent.py`.
3. Configure the Ollama endpoint in `src/llm_planner.py` via `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY` (or an OpenAI-compatible endpoint via `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).
4. Add authentication, audit logging, and stricter role-based access controls.

## Delivery Scope Alignment

This project matches the scope for freelance delivery:

- Voice input and voice output
- Natural language to SQL conversion with safe controls
- Context memory for follow-up questions
- Real-time trend, risk, and anomaly-oriented analysis
- Secure internal database connection pattern
- Browser-based interface
- Source code, deployment guide, and user instructions
- Python backend with an optional controlled LLM query layer

## Notes

- Browser speech recognition depends on Web Speech API support.
- The included dataset is a sample analytics dataset designed to demonstrate trends and risks.

## License

See [`LICENSE`](./LICENSE).