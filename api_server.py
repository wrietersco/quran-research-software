"""
HTTP API exposing the Question refiner pipeline steps.

Run from project root:
    python api_server.py            # default: 127.0.0.1:8000
    python api_server.py --port 9000
    python api_server.py --host 0.0.0.0 --port 8080

Interactive docs at /docs (Swagger) or /redoc.
The desktop Tkinter app (server.py) is unaffected and can run simultaneously.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.bot1_engine import Bot1Error, Bot1Result, run_bot1  # noqa: E402
from src.chat.bot2_engine import Bot2Error, Bot2Result, run_bot2_synonyms  # noqa: E402
from src.chat.refine_engine import (  # noqa: E402
    RefineError,
    RefineResult,
    extract_refined_json,
    refine_reply,
    split_assistant_for_display,
)
from src.chat.openai_health import check_openai_api_health  # noqa: E402
from src.config import get_db_path  # noqa: E402  (also loads .env)
from src.chat.session_cleanup import (  # noqa: E402
    delete_session_database_side,
    delete_session_files_on_disk,
)
from src.db.chat_pipeline import (  # noqa: E402
    fetch_latest_bot1_analysis_dict,
    insert_bot1_step_run,
    refined_question_text_for_session,
    upsert_chat_session,
)
from src.db.bot2_synonyms import (  # noqa: E402
    ConnotationWorkItem,
    insert_bot2_synonym_pipeline,
    list_connotations_for_bot1_run,
    latest_bot1_pipeline_run_id,
)
from src.db.chat_pipeline import refined_question_id_for_session  # noqa: E402
from src.db.connection import connect  # noqa: E402
from src.db.find_verses import (  # noqa: E402
    FindVersesStats,
    run_find_verses_for_session,
    search_arabic_text_in_quran,
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Quran Lexicon — Pipeline API",
    description=(
        "HTTP endpoints for the Question refiner pipeline steps "
        "(refine, Bot 1, Bot 2, Find Verses). "
        "The desktop Tkinter app (`python server.py`) remains the primary UI."
    ),
    version="0.1.0",
)

# Last OpenAI connectivity probe (updated at startup and via GET /api/health)
_openai_health_state: dict[str, object] = {
    "ok": None,
    "summary": "pending",
    "detail": None,
}


def _probe_openai_health_background() -> None:
    def run() -> None:
        try:
            r = check_openai_api_health()
            _openai_health_state["ok"] = r.ok
            _openai_health_state["summary"] = r.summary
            _openai_health_state["detail"] = r.detail
        except Exception as e:
            _openai_health_state["ok"] = False
            _openai_health_state["summary"] = "error"
            _openai_health_state["detail"] = str(e)

    threading.Thread(target=run, daemon=True).start()


@app.on_event("startup")
def _startup_probe_openai() -> None:
    _probe_openai_health_background()

# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------


@contextmanager
def _db_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    with _db_conn() as conn:
        yield conn


# ===================================================================
# Request / response models
# ===================================================================


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


# -- Refine ---------------------------------------------------------

class RefineRequest(BaseModel):
    messages: list[ChatMessage]
    api_key: str | None = None
    model: str | None = None
    instructions_base: str | None = Field(
        None,
        description="Optional full system message; if omitted, uses disk override or built-in doc.",
    )


class RefineResponse(BaseModel):
    text: str
    model: str
    response_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    refined_question: str | None = None
    refined_json: dict | None = None


# -- Bot 1 ----------------------------------------------------------

class Bot1Request(BaseModel):
    refined_question: dict = Field(
        ..., description='Must include a "question" key, e.g. {"question": "..."}',
    )
    api_key: str | None = None
    model: str | None = None
    vector_store_ids: list[str] | None = None
    temperature: float | None = None
    instructions_base: str | None = Field(
        None,
        description="Optional core system block; app still appends tool-persistence instructions.",
    )


class Bot1Response(BaseModel):
    analysis: dict
    model: str
    response_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


# -- Bot 2 ----------------------------------------------------------

class Bot2Request(BaseModel):
    connotation_text: str
    topic_text: str = ""
    refined_question: str = ""
    api_key: str | None = None
    model: str | None = None
    vector_store_ids: list[str] | None = None
    max_synonyms: int = 8
    temperature: float | None = None
    instructions_base: str | None = Field(
        None,
        description="Optional core system block; app appends synonym limit + tool instructions.",
    )


class Bot2Response(BaseModel):
    synonyms: list[str]
    model: str
    response_id: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


# -- Find Verses (ad-hoc search) ------------------------------------

class SearchVersesRequest(BaseModel):
    arabic_text: str


class VerseHit(BaseModel):
    surah_no: int
    ayah_no: int


class SearchVersesResponse(BaseModel):
    hits: list[VerseHit]
    error: str | None = None


# -- Session pipeline ------------------------------------------------

class CreateSessionRequest(BaseModel):
    title: str | None = "New session"


class SessionInfo(BaseModel):
    id: str
    title: str | None = None


class SaveRefinedQuestionRequest(BaseModel):
    question_text: str


class SessionBot1Request(BaseModel):
    refined_question: dict
    api_key: str | None = None
    model: str | None = None
    vector_store_ids: list[str] | None = None
    temperature: float | None = None
    session_title: str | None = None
    instructions_base: str | None = None


class SessionBot1Response(BaseModel):
    pipeline_run_id: int
    analysis: dict
    model: str
    response_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class SessionBot2Request(BaseModel):
    bot1_connotation_id: int
    connotation_text: str
    topic_text: str = ""
    refined_question: str = ""
    api_key: str | None = None
    model: str | None = None
    vector_store_ids: list[str] | None = None
    max_synonyms: int = 8
    temperature: float | None = None
    instructions_base: str | None = None


class SessionBot2Response(BaseModel):
    pipeline_run_id: int
    synonyms: list[str]
    model: str
    response_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class FindVersesResponse(BaseModel):
    rows_inserted: int
    connotations_processed: int
    queries_run: int
    skipped_empty_queries: int
    quran_token_count: int
    ayah_count: int
    corpus_source: str
    not_found_connotations: list[list] = []
    not_found_synonyms: list[list] = []
    match_word_rows_inserted: int = 0


# ===================================================================
# Stateless endpoints — no DB needed, any caller can use directly
# ===================================================================

@app.get("/api/health")
def health(probe_openai: bool = False) -> dict:
    """
    Liveness and DB path. OpenAI status is filled at startup; pass ``probe_openai=true``
    to run a fresh authenticated request (same probe as the desktop “Check API” button).
    """
    if probe_openai:
        try:
            r = check_openai_api_health()
            _openai_health_state["ok"] = r.ok
            _openai_health_state["summary"] = r.summary
            _openai_health_state["detail"] = r.detail
        except Exception as e:
            _openai_health_state["ok"] = False
            _openai_health_state["summary"] = "error"
            _openai_health_state["detail"] = str(e)

    return {
        "status": "ok",
        "db_path": str(get_db_path()),
        "openai": {
            "ok": _openai_health_state.get("ok"),
            "summary": _openai_health_state.get("summary"),
            "detail": _openai_health_state.get("detail"),
        },
    }


@app.post("/api/refine", response_model=RefineResponse)
def api_refine(req: RefineRequest) -> RefineResponse:
    """Question refiner: multi-turn chat that produces a single refined question."""
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        r: RefineResult = refine_reply(
            msgs,
            api_key=req.api_key,
            model=req.model,
            instructions_base=req.instructions_base,
        )
    except RefineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    prose, refined_q = split_assistant_for_display(r.text)
    return RefineResponse(
        text=r.text,
        model=r.model,
        response_id=r.response_id,
        finish_reason=r.finish_reason,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens,
        refined_question=refined_q,
        refined_json=extract_refined_json(r.text),
    )


@app.post("/api/bot1", response_model=Bot1Response)
def api_bot1(req: Bot1Request) -> Bot1Response:
    """Bot 1: generate topics and connotations from a refined question."""
    try:
        r: Bot1Result = run_bot1(
            req.refined_question,
            api_key=req.api_key,
            model=req.model,
            vector_store_ids=req.vector_store_ids,
            temperature=req.temperature,
            instructions_base=req.instructions_base,
        )
    except Bot1Error as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Bot1Response(
        analysis=r.analysis,
        model=r.model,
        response_id=r.response_id,
        finish_reason=r.finish_reason,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens,
    )


@app.post("/api/bot2", response_model=Bot2Response)
def api_bot2(req: Bot2Request) -> Bot2Response:
    """Bot 2: Arabic synonyms for a single connotation."""
    try:
        r: Bot2Result = run_bot2_synonyms(
            connotation_text=req.connotation_text,
            topic_text=req.topic_text,
            refined_question=req.refined_question,
            api_key=req.api_key,
            model=req.model,
            vector_store_ids=req.vector_store_ids,
            max_synonyms=req.max_synonyms,
            temperature=req.temperature,
            instructions_base=req.instructions_base,
        )
    except Bot2Error as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Bot2Response(
        synonyms=r.synonyms,
        model=r.model,
        response_id=r.response_id,
        finish_reason=r.finish_reason,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens,
    )


@app.post("/api/search-verses", response_model=SearchVersesResponse)
def api_search_verses(
    req: SearchVersesRequest, conn: sqlite3.Connection = Depends(get_db)
) -> SearchVersesResponse:
    """Ad-hoc Arabic text search across the Quran corpus (no session required)."""
    hits, err = search_arabic_text_in_quran(conn, req.arabic_text)
    return SearchVersesResponse(
        hits=[VerseHit(surah_no=s, ayah_no=a) for s, a in hits],
        error=err,
    )


# ===================================================================
# Session-based pipeline endpoints — persist results to the project DB
# ===================================================================

@app.post("/api/sessions", response_model=SessionInfo, status_code=201)
def api_create_session(
    req: CreateSessionRequest, conn: sqlite3.Connection = Depends(get_db)
) -> SessionInfo:
    """Create a chat session in the pipeline DB."""
    import uuid

    sid = str(uuid.uuid4())
    upsert_chat_session(conn, sid, req.title)
    conn.commit()
    return SessionInfo(id=sid, title=req.title)


@app.delete("/api/sessions/{session_id}", status_code=204)
def api_delete_session(
    session_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> None:
    delete_session_database_side(conn, session_id)
    delete_session_files_on_disk(session_id)


@app.post("/api/sessions/{session_id}/refined-question")
def api_save_refined_question(
    session_id: str,
    req: SaveRefinedQuestionRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Save or update the refined question for a session (required before Bot 1 pipeline)."""
    from src.db.chat_pipeline import upsert_session_refined_question

    upsert_chat_session(conn, session_id, None)
    rq_id = upsert_session_refined_question(conn, session_id, req.question_text, None)
    conn.commit()
    return {"refined_question_id": rq_id, "question_text": req.question_text}


@app.post(
    "/api/sessions/{session_id}/bot1",
    response_model=SessionBot1Response,
)
def api_session_bot1(
    session_id: str,
    req: SessionBot1Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> SessionBot1Response:
    """Run Bot 1 AND persist topics/connotations to the session pipeline."""
    try:
        br: Bot1Result = run_bot1(
            req.refined_question,
            api_key=req.api_key,
            model=req.model,
            vector_store_ids=req.vector_store_ids,
            temperature=req.temperature,
            instructions_base=req.instructions_base,
        )
    except Bot1Error as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run_id = insert_bot1_step_run(
        conn,
        chat_session_id=session_id,
        session_title=req.session_title,
        refined=req.refined_question,
        br=br,
    )
    return SessionBot1Response(
        pipeline_run_id=run_id,
        analysis=br.analysis,
        model=br.model,
        response_id=br.response_id,
        prompt_tokens=br.prompt_tokens,
        completion_tokens=br.completion_tokens,
        total_tokens=br.total_tokens,
    )


@app.post(
    "/api/sessions/{session_id}/bot2",
    response_model=SessionBot2Response,
)
def api_session_bot2(
    session_id: str,
    req: SessionBot2Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> SessionBot2Response:
    """Run Bot 2 for one connotation AND persist synonyms to the session pipeline."""
    try:
        br: Bot2Result = run_bot2_synonyms(
            connotation_text=req.connotation_text,
            topic_text=req.topic_text,
            refined_question=req.refined_question,
            api_key=req.api_key,
            model=req.model,
            vector_store_ids=req.vector_store_ids,
            max_synonyms=req.max_synonyms,
            temperature=req.temperature,
            instructions_base=req.instructions_base,
        )
    except Bot2Error as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    rq_id = refined_question_id_for_session(conn, session_id)
    if rq_id is None:
        raise HTTPException(
            status_code=409,
            detail="No refined question saved for this session. POST to /refined-question first.",
        )
    item = ConnotationWorkItem(
        bot1_connotation_id=req.bot1_connotation_id,
        connotation_text=req.connotation_text,
        topic_text=req.topic_text,
    )
    pr_id = insert_bot2_synonym_pipeline(
        conn,
        chat_session_id=session_id,
        refined_question_id=rq_id,
        item=item,
        br=br,
    )
    return SessionBot2Response(
        pipeline_run_id=pr_id,
        synonyms=br.synonyms,
        model=br.model,
        response_id=br.response_id,
        prompt_tokens=br.prompt_tokens,
        completion_tokens=br.completion_tokens,
        total_tokens=br.total_tokens,
    )


@app.post(
    "/api/sessions/{session_id}/find-verses",
    response_model=FindVersesResponse,
)
def api_session_find_verses(
    session_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> FindVersesResponse:
    """Step 3 — scan Quran corpus for all connotations/synonyms in the latest Bot 1 run."""
    try:
        stats: FindVersesStats = run_find_verses_for_session(conn, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return FindVersesResponse(
        rows_inserted=stats.rows_inserted,
        connotations_processed=stats.connotations_processed,
        queries_run=stats.queries_run,
        skipped_empty_queries=stats.skipped_empty_queries,
        quran_token_count=stats.quran_token_count,
        ayah_count=stats.ayah_count,
        corpus_source=stats.corpus_source,
        not_found_connotations=[list(t) for t in stats.not_found_connotations],
        not_found_synonyms=[list(t) for t in stats.not_found_synonyms],
        match_word_rows_inserted=stats.match_word_rows_inserted,
    )


@app.get("/api/sessions/{session_id}/bot1-analysis")
def api_get_bot1_analysis(
    session_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    """Retrieve the latest persisted Bot 1 analysis for a session."""
    result = fetch_latest_bot1_analysis_dict(conn, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No Bot 1 analysis found for this session.")
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Quran Lexicon pipeline API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
