"""SQLite connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import get_db_path

_MIGRATE_QR_MESSAGES = """
CREATE TABLE IF NOT EXISTS question_refiner_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL,
    session_title TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    bot_name TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    response_id TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_qr_msgs_session ON question_refiner_messages(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_qr_msgs_created ON question_refiner_messages(created_at);
"""

_MIGRATE_CHAT_PIPELINE = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS session_refined_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL UNIQUE REFERENCES chat_sessions(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    source_question_refiner_message_id INTEGER REFERENCES question_refiner_messages(id) ON DELETE SET NULL,
    finalized_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_srq_session ON session_refined_questions(chat_session_id);
CREATE TABLE IF NOT EXISTS pipeline_step_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    refined_question_id INTEGER NOT NULL REFERENCES session_refined_questions(id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    model TEXT,
    openai_response_id TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pipeline_session_step ON pipeline_step_runs(chat_session_id, step_key);
CREATE INDEX IF NOT EXISTS idx_pipeline_refined ON pipeline_step_runs(refined_question_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_created ON pipeline_step_runs(created_at);
CREATE TABLE IF NOT EXISTS bot1_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_step_runs(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    topic_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bot1_topics_run ON bot1_topics(pipeline_run_id);
CREATE TABLE IF NOT EXISTS bot1_connotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot1_topic_id INTEGER NOT NULL REFERENCES bot1_topics(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    slot_key TEXT,
    connotation_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bot1_connotations_topic ON bot1_connotations(bot1_topic_id);
"""

_MIGRATE_BOT2 = """
CREATE TABLE IF NOT EXISTS bot2_synonym_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_run_id INTEGER NOT NULL UNIQUE REFERENCES pipeline_step_runs(id) ON DELETE CASCADE,
    bot1_connotation_id INTEGER NOT NULL REFERENCES bot1_connotations(id) ON DELETE CASCADE,
    connotation_text_snapshot TEXT NOT NULL,
    topic_text_snapshot TEXT,
    model TEXT,
    openai_response_id TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bot2_syn_runs_connotation ON bot2_synonym_runs(bot1_connotation_id);
CREATE INDEX IF NOT EXISTS idx_bot2_syn_runs_pipeline ON bot2_synonym_runs(pipeline_run_id);
CREATE TABLE IF NOT EXISTS bot2_synonym_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot2_synonym_run_id INTEGER NOT NULL REFERENCES bot2_synonym_runs(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    synonym_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bot2_terms_run ON bot2_synonym_terms(bot2_synonym_run_id);
"""

_MIGRATE_FIND_VERSES = """
CREATE TABLE IF NOT EXISTS find_verse_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    refined_question_id INTEGER NOT NULL REFERENCES session_refined_questions(id) ON DELETE CASCADE,
    bot1_connotation_id INTEGER NOT NULL REFERENCES bot1_connotations(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('connotation', 'synonym')),
    bot2_synonym_term_id INTEGER REFERENCES bot2_synonym_terms(id) ON DELETE SET NULL,
    query_text TEXT NOT NULL,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fvm_session ON find_verse_matches(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_fvm_connotation ON find_verse_matches(bot1_connotation_id);
CREATE INDEX IF NOT EXISTS idx_fvm_surah_ayah ON find_verse_matches(surah_no, ayah_no);
"""

_MIGRATE_FIND_MATCH_WORD_ROWS = """
CREATE TABLE IF NOT EXISTS find_match_word_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    find_match_id INTEGER NOT NULL REFERENCES find_verse_matches(id) ON DELETE CASCADE,
    token_id INTEGER NOT NULL REFERENCES quran_tokens(id) ON DELETE CASCADE,
    word_no INTEGER NOT NULL,
    work_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        work_status IN ('pending', 'running', 'done', 'error', 'skipped')
    ),
    work_payload TEXT,
    work_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (find_match_id, token_id)
);
CREATE INDEX IF NOT EXISTS idx_fmw_find_match ON find_match_word_rows(find_match_id);
CREATE INDEX IF NOT EXISTS idx_fmw_token ON find_match_word_rows(token_id);
CREATE INDEX IF NOT EXISTS idx_fmw_status ON find_match_word_rows(work_status);
"""

_MIGRATE_QURAN_VERSES = """
CREATE TABLE IF NOT EXISTS quran_verses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    verse_text TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (surah_no, ayah_no)
);
CREATE INDEX IF NOT EXISTS idx_quran_verses_surah_ayah ON quran_verses(surah_no, ayah_no);
"""

_MIGRATE_QURAN_KALIMAH = """
CREATE TABLE IF NOT EXISTS quran_token_kalimah (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL REFERENCES quran_tokens(id) ON DELETE CASCADE,
    kalimah_seq INTEGER NOT NULL,
    surface TEXT NOT NULL,
    pos TEXT,
    morph_tags TEXT,
    source TEXT NOT NULL DEFAULT 'quran_morphology',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (token_id, kalimah_seq)
);
CREATE INDEX IF NOT EXISTS idx_quran_token_kalimah_token ON quran_token_kalimah(token_id);
"""

_MIGRATE_QURAN_CORPUS_ROOT = """
CREATE TABLE IF NOT EXISTS quran_token_corpus_root (
    token_id INTEGER PRIMARY KEY REFERENCES quran_tokens(id) ON DELETE CASCADE,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    word_no INTEGER NOT NULL,
    root_buckwalter TEXT,
    root_arabic TEXT,
    source TEXT NOT NULL DEFAULT 'corpus_morphology',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quran_token_corpus_root_ref ON quran_token_corpus_root(surah_no, ayah_no, word_no);
CREATE INDEX IF NOT EXISTS idx_quran_token_corpus_root_bw ON quran_token_corpus_root(root_buckwalter);
"""

_MIGRATE_FIND_VERSES_ADHOC = """
CREATE TABLE IF NOT EXISTS find_verse_adhoc_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    query_text TEXT NOT NULL,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fva_session ON find_verse_adhoc_matches(chat_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fva_session_query_ayah ON find_verse_adhoc_matches(chat_session_id, query_text, surah_no, ayah_no);
"""

_MIGRATE_STEP5 = """
CREATE TABLE IF NOT EXISTS step5_synthesis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    verse_mode TEXT NOT NULL CHECK (verse_mode IN ('all', 'first_n')),
    verse_n INTEGER,
    system_prompt_hash TEXT,
    relevance_threshold_pct INTEGER,
    cross_encoder_model TEXT,
    synthesis_mode TEXT NOT NULL DEFAULT 'combination',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    cancelled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_step5_runs_session ON step5_synthesis_runs(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_step5_runs_created ON step5_synthesis_runs(created_at);

CREATE TABLE IF NOT EXISTS step5_verse_manifests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES step5_synthesis_runs(id) ON DELETE CASCADE,
    find_match_id INTEGER NOT NULL REFERENCES find_verse_matches(id) ON DELETE CASCADE,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    bot1_topic_id INTEGER REFERENCES bot1_topics(id) ON DELETE SET NULL,
    bot1_connotation_id INTEGER REFERENCES bot1_connotations(id) ON DELETE SET NULL,
    verse_text TEXT,
    manifest_json TEXT NOT NULL,
    total_combos INTEGER NOT NULL DEFAULT 0,
    next_ordinal INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    cross_encoder_relevance REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (run_id, find_match_id)
);
CREATE INDEX IF NOT EXISTS idx_step5_manifest_run ON step5_verse_manifests(run_id);
CREATE INDEX IF NOT EXISTS idx_step5_manifest_match ON step5_verse_manifests(find_match_id);

CREATE TABLE IF NOT EXISTS step5_synthesis_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manifest_id INTEGER NOT NULL REFERENCES step5_verse_manifests(id) ON DELETE CASCADE,
    combo_ordinal INTEGER NOT NULL,
    entry_combo_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('in_progress', 'done', 'failed', 'waiting_retry', 'cancelled')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    next_attempt_at TEXT,
    error_code TEXT,
    error_message TEXT,
    user_payload_json TEXT,
    llm_call_state TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (manifest_id, combo_ordinal)
);
CREATE INDEX IF NOT EXISTS idx_step5_jobs_manifest ON step5_synthesis_jobs(manifest_id);
CREATE INDEX IF NOT EXISTS idx_step5_jobs_status ON step5_synthesis_jobs(status);
CREATE INDEX IF NOT EXISTS idx_step5_jobs_retry ON step5_synthesis_jobs(next_attempt_at);

CREATE TABLE IF NOT EXISTS step5_synthesis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE REFERENCES step5_synthesis_jobs(id) ON DELETE CASCADE,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES step5_synthesis_runs(id) ON DELETE CASCADE,
    manifest_id INTEGER NOT NULL REFERENCES step5_verse_manifests(id) ON DELETE CASCADE,
    find_match_id INTEGER NOT NULL REFERENCES find_verse_matches(id) ON DELETE CASCADE,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    bot1_topic_id INTEGER REFERENCES bot1_topics(id) ON DELETE SET NULL,
    bot1_connotation_id INTEGER REFERENCES bot1_connotations(id) ON DELETE SET NULL,
    entry_combo_json TEXT NOT NULL,
    verse_text TEXT,
    context_json TEXT,
    user_payload_json TEXT NOT NULL,
    response_json TEXT,
    possibility_score INTEGER,
    exegesis TEXT,
    symbolic_reasoning TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    raw_response_text TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step5_results_run ON step5_synthesis_results(run_id);
CREATE INDEX IF NOT EXISTS idx_step5_results_manifest ON step5_synthesis_results(manifest_id);
CREATE INDEX IF NOT EXISTS idx_step5_results_match ON step5_synthesis_results(find_match_id);
CREATE INDEX IF NOT EXISTS idx_step5_results_session ON step5_synthesis_results(chat_session_id);
"""

_MIGRATE_STEP5_SHORTLIST = """
CREATE TABLE IF NOT EXISTS step5_session_shortlist (
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    find_match_id INTEGER NOT NULL REFERENCES find_verse_matches(id) ON DELETE CASCADE,
    relevance_score REAL NOT NULL,
    threshold_pct INTEGER NOT NULL,
    cross_encoder_model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_session_id, find_match_id)
);
CREATE INDEX IF NOT EXISTS idx_step5_shortlist_session ON step5_session_shortlist(chat_session_id);
"""

_MIGRATE_STEP5_STATS_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS step5_run_stats_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES step5_synthesis_runs(id) ON DELETE CASCADE,
    stats_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step5_stats_snapshots_run ON step5_run_stats_snapshots(run_id);
"""

_MIGRATE_STEP6 = """
CREATE TABLE IF NOT EXISTS step6_knowledge_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    openai_file_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step6_knowledge_session ON step6_knowledge_files(chat_session_id);

CREATE TABLE IF NOT EXISTS step6_report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'done', 'error', 'cancelled')
    ),
    error_message TEXT,
    report_dir TEXT,
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step6_report_session ON step6_report_runs(chat_session_id);
"""

_MIGRATE_STEP6_REPORT_CHAT = """
CREATE TABLE IF NOT EXISTS step6_report_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step6_report_chat_session ON step6_report_chat_messages(chat_session_id);
"""

_MIGRATE_SESSION_ATTACHED_DOCS = """
CREATE TABLE IF NOT EXISTS session_attached_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    openai_file_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    local_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_session_attached_session ON session_attached_documents(chat_session_id);
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cur.fetchall()}


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive schema changes for existing DB files (safe to call repeatedly)."""
    conn.executescript(_MIGRATE_QR_MESSAGES)
    conn.executescript(_MIGRATE_CHAT_PIPELINE)
    conn.executescript(_MIGRATE_BOT2)
    conn.executescript(_MIGRATE_FIND_VERSES)
    conn.executescript(_MIGRATE_FIND_MATCH_WORD_ROWS)
    from src.db.find_match_words import backfill_find_match_word_rows_missing

    backfill_find_match_word_rows_missing(conn)
    conn.executescript(_MIGRATE_FIND_VERSES_ADHOC)
    conn.executescript(_MIGRATE_QURAN_VERSES)
    conn.executescript(_MIGRATE_QURAN_KALIMAH)
    conn.executescript(_MIGRATE_QURAN_CORPUS_ROOT)
    conn.executescript(_MIGRATE_STEP5)
    conn.executescript(_MIGRATE_STEP5_SHORTLIST)
    conn.executescript(_MIGRATE_STEP5_STATS_SNAPSHOT)
    conn.executescript(_MIGRATE_STEP6)
    conn.executescript(_MIGRATE_STEP6_REPORT_CHAT)
    conn.executescript(_MIGRATE_SESSION_ATTACHED_DOCS)
    cols_step6r = _table_columns(conn, "step6_report_runs")
    if cols_step6r and "openai_report_file_id" not in cols_step6r:
        conn.execute(
            "ALTER TABLE step6_report_runs ADD COLUMN openai_report_file_id TEXT"
        )
    cols_chat = _table_columns(conn, "chat_sessions")
    if cols_chat and "openai_vector_store_id" not in cols_chat:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN openai_vector_store_id TEXT"
        )
    cols5 = _table_columns(conn, "step5_synthesis_runs")
    if cols5:
        if "relevance_threshold_pct" not in cols5:
            conn.execute(
                "ALTER TABLE step5_synthesis_runs ADD COLUMN relevance_threshold_pct INTEGER"
            )
        if "cross_encoder_model" not in cols5:
            conn.execute(
                "ALTER TABLE step5_synthesis_runs ADD COLUMN cross_encoder_model TEXT"
            )
        if "synthesis_mode" not in cols5:
            conn.execute(
                "ALTER TABLE step5_synthesis_runs "
                "ADD COLUMN synthesis_mode TEXT NOT NULL DEFAULT 'combination'"
            )
    cols5m = _table_columns(conn, "step5_verse_manifests")
    if cols5m and "cross_encoder_relevance" not in cols5m:
        conn.execute(
            "ALTER TABLE step5_verse_manifests ADD COLUMN cross_encoder_relevance REAL"
        )
    cols5j = _table_columns(conn, "step5_synthesis_jobs")
    if cols5j and "user_payload_json" not in cols5j:
        conn.execute("ALTER TABLE step5_synthesis_jobs ADD COLUMN user_payload_json TEXT")
    if cols5j and "llm_call_state" not in cols5j:
        conn.execute("ALTER TABLE step5_synthesis_jobs ADD COLUMN llm_call_state TEXT")
    cols = _table_columns(conn, "bot1_analysis_runs")
    if cols:
        if "session_title" not in cols:
            conn.execute("ALTER TABLE bot1_analysis_runs ADD COLUMN session_title TEXT")
        if "question_refiner_assistant_message_id" not in cols:
            conn.execute(
                "ALTER TABLE bot1_analysis_runs ADD COLUMN question_refiner_assistant_message_id INTEGER"
            )
    conn.commit()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate_schema(conn)
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create all tables from schema.sql."""
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
