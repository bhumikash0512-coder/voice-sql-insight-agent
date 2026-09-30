# Vercel Deployment Guide

## Repository

`https://github.com/luckylucky110507/voice-sql-insight-agent`

## Why This Repo Works On Vercel

- The Flask app exports a top-level `app` instance in `app.py`
- Static assets are available under `public/`
- `.python-version` is included
- `vercel.json` excludes unnecessary files from the Python function bundle

## Deploy Steps

1. Sign in to Vercel.
2. Click `Add New...` -> `Project`.
3. Import the GitHub repository:
   `voice-sql-insight-agent`
4. Keep the detected Python settings.
5. Add environment variables if you want MySQL or LLM mode.
6. Click `Deploy`.

## Environment Variables

### Demo Mode

No variables are required. The app will use the local SQLite sample dataset.

### MySQL Mode

- `DB_BACKEND=mysql`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`
- `DB_SEED_SAMPLE=false`
- `ANALYTICS_TABLE=business_metrics`

### Optional LLM Planner

- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

## Test After Deployment

- `Which region has the highest revenue?`
- `Show the monthly profit trend for Alpha`
- `What are the biggest risk hotspots?`

## Notes

- Browser voice input depends on microphone permission and browser support.
- Chrome or Edge is recommended for speech recognition.
