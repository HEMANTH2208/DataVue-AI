"""
LLMSQL — FastAPI Application Server

Main entry point for the LLMSQL web application.
Provides REST API endpoints for natural language database queries,
schema inspection, and SSE streaming responses.

Endpoints:
    POST /api/query          – Submit NL query, get full agent response
    GET  /api/query/stream   – SSE stream for real-time tool lifecycle
    GET  /api/schema         – Get database schema metadata
    GET  /api/health         – Health check
    GET  /                   – Serve the dashboard UI
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uuid
import shutil

from src.config import get_settings
from src.database.db_manager import DatabaseManager
from src.database.seed_databases import seed
from src.agent.agent_controller import AgentController
from src.agent.intelligent_agent import IntelligentAgent
from src.tools.schema_discovery import SchemaDiscoveryTool
from src.tools.query_executor import ExecuteQueryTool
from src.tools.visualizer import VisualizeDataTool
from src.tools.diagrammer import SystemDiagramTool
from src.tools.insight_explainer import ExplainInsightsTool


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DataMind AI",
    description="Agentic AI Database & Visualization Assistant",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend files
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
if PUBLIC_DIR.exists():
    app.mount("/public", StaticFiles(directory=str(PUBLIC_DIR)), name="public")
    vendor_dir = PUBLIC_DIR / "vendor"
    if vendor_dir.exists():
        app.mount("/vendor", StaticFiles(directory=str(vendor_dir)), name="vendor")


# ---------------------------------------------------------------------------
# Startup: initialise database & agent
# ---------------------------------------------------------------------------

_agent: AgentController | None = None
_intelligent_agent: IntelligentAgent | None = None
_db: DatabaseManager | None = None


@app.on_event("startup")
async def startup() -> None:
    global _agent, _intelligent_agent, _db
    settings = get_settings()

    # Seed database if it doesn't exist
    db_path = Path(settings.default_db_path)
    if not db_path.exists():
        print("[Seed] Seeding DataMind AI ecommerce database...")
        seed()

    _db = DatabaseManager(settings.default_db_path)

    # Register all LLMSQL tools
    tools = [
        SchemaDiscoveryTool(_db),
        ExecuteQueryTool(_db),
        VisualizeDataTool(),
        SystemDiagramTool(_db),
        ExplainInsightsTool(),
    ]

    # Initialize both agents
    _agent = AgentController(
        db_manager=_db,
        tools=tools,
        llm_provider=settings.llm_provider,
    )
    
    _intelligent_agent = IntelligentAgent(
        db_manager=_db,
        tools=tools,
        llm_provider=settings.llm_provider,
    )
    
    print(f"[Start] DataMind AI Agent ready | Provider: {settings.llm_provider} | DB: {settings.default_db_path}")
    print("[Start] Intelligent Agent mode available at /api/query/intelligent/stream")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard() -> HTMLResponse:
    """Serve the DataMind AI dashboard UI."""
    index_path = PUBLIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>DataMind AI</h1><p>Dashboard not found.</p>")


@app.post("/api/query")
async def query(request: QueryRequest) -> JSONResponse:
    """Submit a natural language query and get a full agent response."""
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not initialized"})

    try:
        if request.model:
            _agent.set_llm_provider(request.model)

        from src.database.resolver import active_session_id
        token = active_session_id.set(request.session_id)
        try:
            result = _agent.query(
                user_message=request.question,
                session_id=request.session_id,
            )
            return JSONResponse(content=result)
        finally:
            active_session_id.reset(token)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/query/stream")
async def query_stream(
    question: str,
    session_id: str | None = None,
    model: str | None = None,
) -> EventSourceResponse:
    """SSE endpoint for real-time agent tool lifecycle streaming."""
    if not _agent:
        async def error_gen():
            yield {"event": "error", "data": json.dumps({"error": "Agent not initialized"})}
        return EventSourceResponse(error_gen())

    if model:
        _agent.set_llm_provider(model)

    async def event_generator():
        from src.database.resolver import active_session_id
        token = active_session_id.set(session_id)
        try:
            async for event in _agent.query_stream(
                user_message=question,
                session_id=session_id,
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"], default=str),
                }
        finally:
            active_session_id.reset(token)

    return EventSourceResponse(event_generator())


@app.get("/api/query/intelligent/stream")
async def query_intelligent_stream(
    question: str,
    session_id: str | None = None,
    model: str | None = None,
) -> EventSourceResponse:
    """
    Enhanced SSE endpoint with intelligent question analysis, 
    multi-step planning, and result validation.
    
    This endpoint provides production-quality conversational analytics with:
    - Deep question understanding
    - Multi-step analytical reasoning
    - Result validation and correction
    - Data-grounded explanations
    """
    if not _intelligent_agent:
        async def error_gen():
            yield {"event": "error", "data": json.dumps({"error": "Intelligent agent not initialized"})}
        return EventSourceResponse(error_gen())

    async def event_generator():
        from src.database.resolver import active_session_id
        token = active_session_id.set(session_id)
        try:
            async for event in _intelligent_agent.query_stream(
                user_message=question,
                session_id=session_id,
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"], default=str),
                }
        finally:
            active_session_id.reset(token)

    return EventSourceResponse(event_generator())


@app.get("/api/schema")
async def get_schema(session_id: str | None = None) -> JSONResponse:
    """Return the full database schema metadata."""
    if not _db:
        return JSONResponse(status_code=503, content={"error": "Database not initialized"})

    try:
        from src.database.resolver import active_session_id
        token = active_session_id.set(session_id)
        try:
            schema = _db.get_full_schema()
            return JSONResponse(content={"schema": schema, "tables": list(schema.keys())})
        finally:
            active_session_id.reset(token)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Database Upload & Switching Endpoints
# ---------------------------------------------------------------------------

class SelectDBRequest(BaseModel):
    source_type: str


@app.post("/api/database/upload")
async def upload_database(
    file: UploadFile = File(...),
    session_id: str | None = None
) -> JSONResponse:
    """Upload a database ZIP file, validate, extract, and make it active for the session."""
    if not _db:
        return JSONResponse(status_code=503, content={"error": "Database not initialized"})

    if not session_id or session_id == "null" or session_id == "undefined":
        session_id = str(uuid.uuid4())

    temp_dir = Path("data/temporary_databases/uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = temp_dir / f"{uuid.uuid4()}_{file.filename}"

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        print(f"[Upload Error] Failed to write temporary file: {exc}")
        return JSONResponse(status_code=500, content={"error": "Failed to save uploaded file."})

    try:
        from src.database.resolver import process_zip_upload, active_session_id
        sess_db = process_zip_upload(temp_file_path, session_id)
        
        token = active_session_id.set(session_id)
        try:
            schema = _db.get_full_schema()
        finally:
            active_session_id.reset(token)

        return JSONResponse(content={
            "session_id": session_id,
            "database_name": sess_db.database_name,
            "database_type": sess_db.database_type,
            "source_type": sess_db.source_type,
            "table_count": len(schema),
            "status": "Ready",
            "tables": list(schema.keys())
        })
    except ValueError as exc:
        print(f"[Upload Validation Error] {exc}")
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        print(f"[Upload Server Error] Internal error during processing: {exc}")
        return JSONResponse(status_code=500, content={"error": "An internal error occurred while processing the database."})
    finally:
        if temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except Exception:
                pass


@app.get("/api/database/status/{session_id}")
async def get_database_status(session_id: str) -> JSONResponse:
    """Get active database details and status for the session."""
    try:
        from src.database.resolver import get_session_db_info
        info = get_session_db_info(session_id)
        return JSONResponse(content=info)
    except Exception as exc:
        print(f"[Status Error] {exc}")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch database status."})


@app.get("/api/database/schema/{session_id}")
async def get_database_schema(session_id: str) -> JSONResponse:
    """Get discovered schema for the session's active database."""
    if not _db:
        return JSONResponse(status_code=503, content={"error": "Database not initialized"})
    try:
        from src.database.resolver import active_session_id
        token = active_session_id.set(session_id)
        try:
            schema = _db.get_full_schema()
            return JSONResponse(content={"schema": schema, "tables": list(schema.keys())})
        finally:
            active_session_id.reset(token)
    except Exception as exc:
        print(f"[Schema Fetch Error] {exc}")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch database schema."})


@app.post("/api/database/select/{session_id}")
async def select_session_database(session_id: str, request: SelectDBRequest) -> JSONResponse:
    """Switch active database between 'default' and 'uploaded'."""
    try:
        from src.database.resolver import select_database, get_session_db_info
        select_database(session_id, request.source_type)
        info = get_session_db_info(session_id)
        return JSONResponse(content=info)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        print(f"[Select DB Error] {exc}")
        return JSONResponse(status_code=500, content={"error": "Failed to switch database."})


@app.delete("/api/database/session/{session_id}")
async def delete_database_session(session_id: str) -> JSONResponse:
    """Purge temporary database files and session details manually."""
    try:
        from src.database.resolver import cleanup_session
        cleanup_session(session_id)
        return JSONResponse(content={"status": "success", "message": f"Session {session_id} resources cleaned up."})
    except Exception as exc:
        print(f"[Delete Session Error] {exc}")
        return JSONResponse(status_code=500, content={"error": "Failed to delete session resources."})


@app.get("/api/health")
async def health(model: str | None = None) -> JSONResponse:
    """Health check endpoint."""
    settings = get_settings()
    if model and _agent:
        try:
            _agent.set_llm_provider(model)
        except Exception as exc:
            print(f"[Health Switch Error] Failed to switch LLM provider to '{model}': {exc}")

    active_provider = settings.llm_provider
    if _agent and _agent._llm:
        provider_class_name = _agent._llm.__class__.__name__
        if "Gemini" in provider_class_name:
            active_provider = "gemini"
        elif "OpenAI" in provider_class_name:
            active_provider = "openai"
        elif "Groq" in provider_class_name:
            active_provider = "groq"
        elif "Mock" in provider_class_name:
            active_provider = "mock"

    return JSONResponse(content={
        "status": "healthy",
        "app": "DataMind AI",
        "version": "1.0.0",
        "llm_provider": active_provider,
        "database": settings.default_db_path,
    })
