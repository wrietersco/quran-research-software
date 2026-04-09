# Project features — UI, workflows, and modules

This document describes the **Quran Lexicon** desktop app and data pipeline **as implemented in this repository**: features, screen-by-screen UI fields, workflows, and Python modules.

---

## 1. Entry points

| Entry | Purpose |
|--------|---------|
| `python server.py` | Tkinter desktop app: **Verse roots**, **Question refiner**, **Database** explorer. |
| `python database.py` | One-shot DB build: schema, lexicon import, Quran import, mapping (see README). |
| `python scripts/init_db.py` | Schema only (`src/db/schema.sql`) — use after pulling schema changes (e.g. new `bot1_analysis_runs`). |

**Default database path:** `data/db/quran_lexicon.db`  
**Override:** environment variable `QURAN_LEXICON_DB` (absolute path).

**Configuration:** `src/config.py` — loads optional project-root **`.env`** via `python-dotenv` (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_MODEL_BOT1`, `OPENAI_BASE_URL`, etc.).

---

## 2. Desktop app (`server.py`) — top-level UI

**Window:** title `Quran Lexicon — Database Explorer`, default size **1280×820**, min **960×600**.

**Header bar**

| Control | Binding / behavior |
|---------|---------------------|
| Label `Database: <path>` | Shows resolved `get_db_path()`. |
| Button **Refresh tables** | Reloads table list in Database tab; refreshes verse surah list if DB exists. |

**Main notebook (3 tabs, order)**

1. **Verse roots** — Quranic verse → words → roots → lexicon (graph, table, tree).  
2. **Question refiner** — OpenAI question refiner + Bot 1 step + diagnostics.  
3. **Database** — SQLite table/column browser and row grid.

**Theming:** `clam` theme; styles **`Verse.Treeview`** (larger Arabic, verse table/list) and **`Browse.Treeview`** (DB browser). Arabic UI fonts loaded from `assets/fonts/` via `src/ui/app_fonts.py` (Amiri, Noto Naskh Arabic) with OS-specific registration.

---

## 3. Tab: Verse roots

### 3.1 Control bar

| Field | Type | Notes |
|-------|------|--------|
| **Surah** | `ttk.Combobox` (readonly) | Values = surahs that have rows in `quran_tokens`. Syncs max ayah when changed. |
| **Ayah** | `ttk.Spinbox` | Range `1 … max_ayah` for selected surah. |
| **Load verse** | Button | Runs DB query and refreshes all sub-views. |
| Status label | `verse_status_var` | e.g. word count or errors. |

### 3.2 Sub-notebook (three panes)

#### A. Graph (interactive)

- **Requires:** `matplotlib`, `networkx` (`src/ui/verse_hierarchy_chart.py`).
- Renders a layered graph: verse → words → roots → headings → definition leaf; click opens definition window.
- If deps missing, a placeholder label explains `pip install matplotlib networkx`.

#### B. Table

- **`ttk.Treeview`** `style="Verse.Treeview"`, `show="tree headings"`.
- **Tree column (#0):** “Word / entry” — parent rows for words with multiple lexicon headings; child rows for each heading (no repeated token/root on children).
- **Data columns:** `word_no`, `token`, `root_id`, `root`, `seq`, `heading`, `definition` (truncated preview).
- **Accordion behavior:** If a word has **≥ 2** headings, one parent row (`open=False` by default) with children; single-heading words stay one flat row.
- **Double-click:** Toggles expand on parent rows with children; on leaf rows with a stored definition, opens **Definition** `Toplevel` (`ScrolledText`, Arabic shaping via `src/ui/arabic_display.py`).
- Heading text uses **`heading_display_label()`** (`src/ui/lexicon_display.py`) to strip Lane-style `1. ⇒` / `⇒` prefixes.

#### C. Hierarchical list

- Tree only (`show="tree"`): Surah/ayah → Word → Root → heading nodes; each heading has a **child** row with definition preview (collapsible).
- Double-click: same as table (definition or toggle expand) per handler logic in `server.py`.

**Data source:** `fetch_verse_word_hierarchy()` in `src/db/verse_hierarchy.py` (override root, then primary `token_root_analysis`, then `lexicon_roots` / `lexicon_entries`).

---

## 4. Tab: Question refiner

Implemented by **`QuestionRefinerTab`** in `src/ui/question_refiner_tab.py`. Uses a **nested notebook** with sub-tabs:

**Sub-tab order:** Question refiner | Step 1 — Bot 1 | Step 2 — Bot 2 | Step 3 — Find Verses | **Step 4 — Kalimat** | **Step 5 — Synthesis**.

**Step 5 (new):** async LLM processing over saved Step 3 verse hits. For each verse hit, the app builds morpheme-root units from Step 4 sources, enumerates Lane-entry combinations, and sends one JSON payload per combination to either OpenAI or DeepSeek (provider selectable). It persists runs/jobs/results with status + retry metadata, stores parsed output (`possibility_score`, `exegesis`, `symbolic_reasoning`), usage tokens, and computed cost in SQLite.

### Failure recovery (Bot 2 & Step 5)

| Situation | Behavior |
|-----------|----------|
| **Bot 2 — network crash or app quit mid-run** | Each connotation is written to `bot2_synonym_runs` / `bot2_synonym_terms` **as soon as** that LLM call succeeds, so completed connotations are not lost. |
| **Bot 2 — Skip already saved** | Optional checkbox **“Skip connotations that already have Bot 2 synonyms (for the current Bot 1 run)”** avoids re-calling the model for connotations that already have a saved synonym run tied to the same Bot 1 `pipeline_run_id`. |
| **Bot 2 — Stop** | **Stop Bot 2** sets a cancel flag; connotations finished before stop remain saved. |
| **Step 5 — crash or lost worker** | Jobs can remain `in_progress` in SQLite with no live orchestrator. Use **Resume last run** (Step 5 tab): confirms, then resets those rows to `waiting_retry` and starts the background worker again on the **latest** non-cancelled run for the session. Provider, model, workers, and system text come from the **current** Step 5 controls (not from the original run row). |
| **Step 5 — CLEAR** | Removes Step 5 synthesis data for the session only; does not remove Find Verses rows or the shortlist. |
| **Step 5 — Stop** | Cancels the orchestrator and marks the run cancelled in the DB (same as before). |

### 4.1 Sub-tab: Question refiner

**Layout:** horizontal `PanedWindow`: **Sessions | Chat | Diagnostics**.

#### Left: Sessions

| Control | Behavior |
|---------|----------|
| **Listbox** | Session titles (from chat store); selecting loads messages into log. |
| **New session** | Creates session, selects it, clears log. |
| **Rename** | `simpledialog` → updates title in `data/chat/question_refiner_sessions.json`. |
| **Delete** | Confirms, removes session and cached token stats / Bot 1 preview cache. |

#### Center: Chat

| Field | Notes |
|-------|--------|
| Intro label | Explains refiner purpose; API key hint if missing. |
| Status label | e.g. Ready / Waiting / errors. |
| **Log** `tk.Text` | User vs Assistant (tags); refined block shown as “Refined question” from JSON or legacy markers. |
| **Input** `ScrolledText` | Multiline compose; **Ctrl+Enter** sends. |
| **Send** | Appends user message, calls `refine_reply()` (`src/chat/refine_engine.py`). |

**Assistant system prompt:** `docs/chatbot-question-refiner.md` (loaded each request).  
**Refined output (preferred):** block `<<<REFINED_JSON>>> … {"question":"…"} … <<<END_REFINED_JSON>>>`.  
**Legacy:** `<<<REFINED_QUESTION>>>` … `<<<END_REFINED_QUESTION>>>`.  
Parsing: `extract_refined_json()`, `refined_display_text()`, `split_assistant_for_display()` in `refine_engine.py`.

**Sessions file:** `data/chat/question_refiner_sessions.json` — `ChatSessionsStore` in `src/chat/sessions_store.py`.

#### Right: LLM diagnostics (dev)

Read-only monospace text: env model, base URL, API key present, temperature, system prompt file size, last response tokens, session/app token totals.

---

### 4.2 Sub-tab: Step 1 — Bot 1

| Area | Content |
|------|---------|
| Intro | Describes Bot 1 (topics & connotations) vs `docs/quran-openai-prompts.md`. |
| Hint line | `BOT1_TEMPERATURE`, `OPENAI_MODEL_BOT1` / `OPENAI_MODEL`. |
| **Status** | Session title + whether refined JSON is ready. |
| **Run Bot 1 & save to DB** | Finds latest `<<<REFINED_JSON>>>` in current session → `run_bot1()` → `insert_bot1_run()` → SQLite `bot1_analysis_runs`. |
| **Preview** `tk.Text` | Shows refined JSON input and last in-memory Bot 1 analysis for this session. |

**Engine:** `src/chat/bot1_engine.py` — system text from `docs/bot1-topics-connotations-system.md`; OpenAI **tool** `save_topics_connotations_analysis` (`analysis_json` string); fallback: parse JSON from assistant message.

**On success:** Caches analysis per session, refreshes preview, selects this sub-tab, shows dialog with row `id`.

---

## 5. Tab: Database

**Layout:** horizontal paned: **navigation tree | grid**.

| Area | UI |
|------|-----|
| Left tree | Root node **Tables**; each user table as node; children = columns with `[PK]`/`[FK]` and FK target text. |
| Right top | **Rows (limit):** spinbox 10–5000 (default 200); **Load table**; **status_var** (row counts / hints). |
| Right grid | `data_tree` `Browse.Treeview` `show="headings"` — columns from selected table; vertical + horizontal scrollbars. |

**Interactions**

- Select table or column → sets internal current table name.
- **Load table** or **double-click** table node → `fetch_table_rows` + `table_row_count` (`src/db/introspection.py`).

---

## 6. Definition popup (shared)

Opened from verse graph pick, verse table double-click, verse tree double-click when a definition exists.

- `Toplevel`, title “Definition”.
- Title label + `ScrolledText` with `shape_arabic_display()` for mixed Arabic/Latin.

---

## 7. Data & analysis workflows (CLI / pipeline)

### 7.1 Build database (`database.py`)

Typical flow: `init_db` → import lexicon JSON → import Quran JSON → heuristic mapping → overrides. Flags documented in `README.md`.

### 7.2 Question refiner → Bot 1 → DB

1. User obtains `<<<REFINED_JSON>>>` with `{"question":"…"}` in chat.  
2. **Step 1 — Bot 1** runs model; response stored in **`bot1_analysis_runs`** (`refined_question_json`, `analysis_json`, tokens, `chat_session_id`, `model`, timestamps).

### 7.3 Verse hierarchy (read-only)

`quran_tokens` + `token_root_overrides` / `token_root_analysis` + `lexicon_roots` + `lexicon_entries` → UI as above.

---

## 8. Database tables (relevant to app features)

| Table | Role |
|-------|------|
| `lexicon_roots`, `lexicon_entries` | Lane-style lexicon. |
| `quran_tokens` | Per-word Quran text. |
| `token_root_analysis`, `token_root_overrides` | Token→root links. |
| `lexicon_entries_fts` | FTS5 on definitions. |
| `bot1_analysis_runs` | Bot 1 JSON outputs linked to optional chat session id. |
| `scraper_state` | Scraper resume pointer. |

Full DDL: `src/db/schema.sql`. Overview: `docs/data-model.md`.

---

## 9. Module map (`src/`)

| Module / package | Role |
|--------------------|------|
| `config.py` | Paths, `get_db_path()`, `.env` via `_load_dotenv()`. |
| `db/connection.py` | `connect()`, `init_db()` from `schema.sql`. |
| `db/schema.sql` | Canonical SQLite DDL. |
| `db/introspection.py` | Table list, columns/FK metadata, paginated row fetch. |
| `db/verse_hierarchy.py` | `VerseWordNode`, `fetch_verse_word_hierarchy`, surah/ayah helpers. |
| `db/repositories.py` | Lexicon/table helpers for scripts. |
| `db/bot1_analysis.py` | `insert_bot1_run()`. |
| `chat/sessions_store.py` | JSON file persistence for refiner sessions/messages. |
| `chat/refine_engine.py` | Question refiner OpenAI call, `RefineResult`, refined JSON/text extraction. |
| `chat/bot1_engine.py` | Bot 1 OpenAI call + tool, `Bot1Result`. |
| `ui/app_fonts.py` | Download/register Arabic fonts; paths under `assets/fonts/`. |
| `ui/arabic_display.py` | Arabic reshaper/bidi for display; matplotlib font helper. |
| `ui/lexicon_display.py` | `heading_display_label`, `entry_dialog_title`. |
| `ui/verse_hierarchy_chart.py` | Matplotlib/networkx graph widget. |
| `ui/question_refiner_tab.py` | Full Question refiner + Step 1 UI. |
| `ui/tree_text.py` | Optional text-wrap helper (legacy/table experiments). |
| `importers/`, `mapping/`, `normalize/`, `scraper/` | CLI pipeline (lexicon, Quran, roots, scrape). |

---

## 10. Documentation index (prompts & specs)

| File | Content |
|------|---------|
| `docs/chatbot-question-refiner.md` | System prompt for question refiner (loaded by API). |
| `docs/bot1-topics-connotations-system.md` | Bot 1 system prompt (fenced block + persistence instructions). |
| `docs/quran-openai-prompts.md` | Bots 1–4 reference (URLs + full text summaries). |
| `docs/architecture.md` | High-level architecture. |
| `docs/data-model.md` | SQLite entity notes. |
| `README.md` | Install, `database.py`, scripts, explorer basics. |

---

## 11. Dependencies (UI + LLM)

See `requirements.txt`: Selenium (scraper), **matplotlib**, **networkx**, **arabic-reshaper**, **python-bidi**, **openai**, **python-dotenv**.

---

*Last updated to match the codebase layout and features described above. For command-line flags and import order, prefer `README.md` and script `--help` where available.*
