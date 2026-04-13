-- Quran Lexicon SQLite schema (utf8)
-- Enable foreign keys at connection time: PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lexicon_roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_word TEXT NOT NULL,
    root_word_normalized TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (root_word_normalized)
);

CREATE TABLE IF NOT EXISTS lexicon_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL REFERENCES lexicon_roots(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    heading_raw TEXT NOT NULL,
    heading_normalized TEXT,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (root_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_lexicon_entries_root_id ON lexicon_entries(root_id);

CREATE TABLE IF NOT EXISTS quran_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surah_no INTEGER NOT NULL,
    ayah_no INTEGER NOT NULL,
    word_no INTEGER NOT NULL,
    token_uthmani TEXT NOT NULL,
    token_plain TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (surah_no, ayah_no, word_no)
);

CREATE INDEX IF NOT EXISTS idx_quran_tokens_plain ON quran_tokens(token_plain);

-- Full verse text from project-root quran.json (or other verse-JSON import)
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

-- Step 4 — Grammatical kalimāt per orthographic word (from Quranic morphology resource, e.g. quran-morphology.txt)
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

-- Corpus morphology stem root per orthographic word (from kalimah FEATURES ROOT:…)
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

CREATE TABLE IF NOT EXISTS token_root_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL REFERENCES quran_tokens(id) ON DELETE CASCADE,
    root_id INTEGER NOT NULL REFERENCES lexicon_roots(id) ON DELETE CASCADE,
    lemma TEXT,
    pattern TEXT,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tra_token ON token_root_analysis(token_id);
CREATE INDEX IF NOT EXISTS idx_tra_root_primary ON token_root_analysis(root_id, is_primary);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tra_token_root ON token_root_analysis(token_id, root_id);

CREATE TABLE IF NOT EXISTS token_root_overrides (
    token_id INTEGER PRIMARY KEY REFERENCES quran_tokens(id) ON DELETE CASCADE,
    root_id INTEGER NOT NULL REFERENCES lexicon_roots(id),
    reason TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Question refiner chat mirror: each user/assistant turn, keyed by JSON session id
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

-- Chat pipeline: one finalized refined question per session; step runs (Bot 1, future bots)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    openai_vector_store_id TEXT,
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

-- Bot 2: one Responses API call per connotation; synonyms in separate rows
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

-- Step 3 — Find Verses: exact token-sequence hits in quran_tokens per connotation / Bot 2 synonym
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

-- Words in DB linked to each saved Find Verses hit (for per-word / iterative jobs)
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

-- Step 3 — optional manual verse search (user preview, then explicit save)
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

-- Step 5 — LLM synthesis over Lane-entry combinations per saved verse hit
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

-- Step 5 — CrossEncoder shortlist per session (separate from synthesis runs)
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

-- Step 5 — optional JSON snapshots of run analytics (scorecard + chart inputs)
CREATE TABLE IF NOT EXISTS step5_run_stats_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES step5_synthesis_runs(id) ON DELETE CASCADE,
    stats_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_step5_stats_snapshots_run ON step5_run_stats_snapshots(run_id);

-- Legacy: older Bot 1 writes (JSON blobs). New runs use pipeline_step_runs + bot1_topics + bot1_connotations.
CREATE TABLE IF NOT EXISTS bot1_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT,
    session_title TEXT,
    question_refiner_assistant_message_id INTEGER REFERENCES question_refiner_messages(id) ON DELETE SET NULL,
    refined_question_json TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bot1_runs_session ON bot1_analysis_runs(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_bot1_runs_created ON bot1_analysis_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_bot1_runs_qr_msg ON bot1_analysis_runs(question_refiner_assistant_message_id);

CREATE TABLE IF NOT EXISTS scraper_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_root_word_normalized TEXT,
    last_url TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- FTS5: external content table for lexicon entry definitions
CREATE VIRTUAL TABLE IF NOT EXISTS lexicon_entries_fts USING fts5(
    definition,
    content='lexicon_entries',
    content_rowid='id',
    tokenize='unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS lexicon_entries_ai AFTER INSERT ON lexicon_entries BEGIN
    INSERT INTO lexicon_entries_fts(rowid, definition) VALUES (new.id, new.definition);
END;

CREATE TRIGGER IF NOT EXISTS lexicon_entries_ad AFTER DELETE ON lexicon_entries BEGIN
    INSERT INTO lexicon_entries_fts(lexicon_entries_fts, rowid) VALUES('delete', old.id);
END;

CREATE TRIGGER IF NOT EXISTS lexicon_entries_au AFTER UPDATE ON lexicon_entries BEGIN
    INSERT INTO lexicon_entries_fts(lexicon_entries_fts, rowid, definition) VALUES('delete', old.id, old.definition);
    INSERT INTO lexicon_entries_fts(rowid, definition) VALUES (new.id, new.definition);
END;

-- Step 6 — Report: per-session knowledge files on OpenAI + report run metadata
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
    openai_report_file_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step6_report_session ON step6_report_runs(chat_session_id);

CREATE TABLE IF NOT EXISTS step6_report_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_step6_report_chat_session ON step6_report_chat_messages(chat_session_id);
