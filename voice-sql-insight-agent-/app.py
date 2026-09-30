from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables from .env FIRST, before anything else
# reads OLLAMA_BASE_URL / OLLAMA_MODEL / OLLAMA_API_KEY etc.
load_dotenv()

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import HTTPException

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

from src.agent import VoiceSQLAgent
from src.data_setup import describe_database, initialize_database

# ==========================================================
# Basic Configuration
# ==========================================================

BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

if CORS:
    CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("VoiceSQLAgent")

PUBLIC_DIR = BASE_DIR / "public"

# ==========================================================
# Initialize Agent
# ==========================================================

database = initialize_database()
agent = VoiceSQLAgent(database)

# ==========================================================
# Helper Functions
# ==========================================================

def success(data):
    return jsonify(
        {
            "success": True,
            "data": data,
        }
    )


def failure(message, status=400):
    return jsonify(
        {
            "success": False,
            "error": message,
        }
    ), status

# ==========================================================
# Static Routes
# ==========================================================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/styles.css")
def styles():
    asset_dir = PUBLIC_DIR if (PUBLIC_DIR / "styles.css").exists() else BASE_DIR / "static"
    return send_from_directory(asset_dir, "styles.css")


@app.get("/app.js")
def app_js():
    asset_dir = PUBLIC_DIR if (PUBLIC_DIR / "app.js").exists() else BASE_DIR / "static"
    return send_from_directory(asset_dir, "app.js")

# ==========================================================
# Health API
# ==========================================================

@app.get("/api/health")
def health():
    """Returns project health status."""
    return success(
        {
            "status": "online",
            "database": describe_database(agent.db_config),
            "backend": agent.db_config.get("backend"),
            "llm_enabled": getattr(agent.llm_planner, "enabled", False),
            "ollama_base_url": getattr(agent.llm_planner, "ollama_base_url", None),
            "ollama_model": getattr(agent.llm_planner, "ollama_model", None),
        }
    )

# ==========================================================
# Query API
# ==========================================================

@app.post("/api/query")
def query():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    session_id = str(payload.get("sessionId", "default-session")).strip() or "default-session"

    if not question:
        return failure("Please enter a business question.")

    logger.info("Question : %s", question)

    try:
        result = agent.handle_query(session_id=session_id, question=question)
        return success(result)
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Batch Query API (multiple questions, same session/context)
# ==========================================================

@app.post("/api/batch-query")
def batch_query():
    """
    Process multiple questions in one call, maintaining context across them.

    Request body:
    {
        "questions": ["...", "..."],
        "sessionId": "user-123"
    }
    """
    payload = request.get_json(silent=True) or {}
    questions = payload.get("questions", [])
    session_id = str(payload.get("sessionId", "default-session")).strip() or "default-session"

    if not isinstance(questions, list) or not questions:
        return failure("Provide 'questions' as a non-empty list.")

    try:
        results = []
        for raw_question in questions:
            question = str(raw_question).strip()
            if question:
                result = agent.handle_query(session_id=session_id, question=question)
                results.append(result)

        return success(
            {
                "session_id": session_id,
                "queries_processed": len(results),
                "results": results,
            }
        )
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Query Examples
# ==========================================================

@app.get("/api/examples")
def examples():
    return success(
        {
            "examples": [
                "Which region has highest revenue?",
                "Show revenue trend",
                "Which product has lowest profit?",
                "North region ka revenue kitna hai?",
                "Customer churn kya hota hai?",
                "What is EBITDA?",
                "SWOT Analysis explain",
                "Marketing strategy kya hoti hai?",
                "Show risk hotspots",
                "Top performing region",
            ]
        }
    )

# ==========================================================
# Session Context (introspection)
# ==========================================================

@app.get("/api/session/<session_id>/context")
def get_session_context(session_id: str):
    """Get current conversation context (metric/dimension/filters/language) for a session."""
    try:
        context = agent.sessions.get(session_id)
        if context is None:
            return failure("Session not found.", status=404)

        return success(
            {
                "session_id": session_id,
                "metric": context.metric,
                "dimension": context.dimension,
                "filters": context.filters,
                "language": context.language,
                "last_title": context.last_title,
            }
        )
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)


@app.post("/api/session/<session_id>/reset")
def reset_session(session_id: str):
    """Reset conversation context for a session."""
    try:
        if session_id in agent.sessions:
            del agent.sessions[session_id]
            return success({"message": f"Session '{session_id}' reset."})
        return success({"message": f"Session '{session_id}' not found (nothing to reset)."})
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Conversation History (kept for compatibility; agent currently
# does not persist a separate history log beyond context)
# ==========================================================

@app.get("/api/history")
def history():
    session_id = request.args.get("sessionId", "default-session")
    try:
        history_data = agent.get_history(session_id) if hasattr(agent, "get_history") else []
        return success(history_data)
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)


@app.post("/api/clear-history")
def clear_history():
    payload = request.get_json(silent=True) or {}
    session_id = payload.get("sessionId", "default-session")
    try:
        if hasattr(agent, "clear_history"):
            agent.clear_history(session_id)
        elif session_id in agent.sessions:
            del agent.sessions[session_id]
        return success({"message": "History cleared."})
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Voice Endpoint
# ==========================================================

@app.post("/api/voice")
def voice():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    session_id = str(payload.get("sessionId", "default-session")).strip() or "default-session"

    if not question:
        return failure("Voice input is empty.")

    try:
        result = agent.handle_query(session_id=session_id, question=question)
        return success(result)
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Chart Data
# ==========================================================

@app.get("/api/chart-data")
def chart_data():
    session_id = request.args.get("sessionId", "default-session")
    try:
        if hasattr(agent, "get_chart_data"):
            chart = agent.get_chart_data(session_id)
        else:
            chart = {"labels": [], "values": [], "type": "bar"}
        return success(chart)
    except Exception as e:
        logger.exception(e)
        return failure(str(e), status=500)

# ==========================================================
# Global Error Handler
# ==========================================================

@app.errorhandler(Exception)
def global_error(error):
    # Let Flask/Werkzeug handle normal HTTP errors (404, 405, etc.) as-is
    if isinstance(error, HTTPException):
        return error

    logger.exception(error)
    return (
        jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ),
        500,
    )

# ==========================================================
# Run Application
# ==========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    logger.info("=" * 60)
    logger.info("Voice SQL Insight Agent Started")
    logger.info("Open : http://127.0.0.1:%s", port)
    logger.info("LLM enabled : %s", getattr(agent.llm_planner, "enabled", False))
    logger.info("=" * 60)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )