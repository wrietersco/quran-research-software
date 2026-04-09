# Quran Lexicon Pipeline (SQLite)

SQLite-first pipeline for Lane-style lexicon JSON, optional live scraping from [lexicon.quranic-research.net](https://lexicon.quranic-research.net), Quran word lists, and heuristic token→root mapping.

## Quick start

```powershell
cd D:\hassan_backup\quran\selenium
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install the `src` package in editable mode (recommended for development and for `pytest` without `sys.path` hacks):

```powershell
pip install -e .
pip install -e ".[dev]"   # adds pytest; optional
```

### Build database (one command)

From the project root, this initializes the schema, imports `lane_lexicon*.json`, imports every `*.json` under `data/raw/quran/`, imports **`quran.json` at the project root** (if present) into `quran_verses` + `quran_tokens`, then runs heuristic mapping and manual overrides:

```powershell
python database.py
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--truncate-lexicon` | Delete all lexicon rows before importing JSON |
| `--replace-entries` | Replace entries for roots that already exist |
| `--skip-quran` | Skip `data/raw/quran/*.json` word import only |
| `--skip-root-quran-json` | Skip importing project-root `quran.json` (Step 3c) |
| `--skip-kalimah` | Skip Step 3b morphology import (`quran_token_kalimah`) |
| `--morphology-file PATH` | Tab-separated morphology file (repeatable); default file below |
| `--skip-mapping` | Skip token→root mapping |
| `--quran-file PATH` | Import only this Quran JSON (repeatable) |
| `--mapping-limit N` | Limit heuristic mapping to N tokens |
| `--min-confidence X` | Minimum score for a candidate (default `0.35`) |
| `--no-clear-mapping` | Keep existing heuristic rows when re-mapping |

Default database: `data/db/quran_lexicon.db`. Override with env var `QURAN_LEXICON_DB`.

**Step 3c — root `quran.json`:** If `quran.json` exists at the project root (mushaf shape: surah keys → arrays of `{ "chapter", "verse", "text" }`), it is loaded into **`quran_verses`** (full verse text) and **`quran_tokens`** (words split on whitespace, `word_no` 1…n per ayah). This runs **after** `data/raw/quran/` imports so the root file can refresh the full corpus. Use **`--skip-root-quran-json`** to disable. Standalone: `python scripts/import_quran_root_json.py [path-to.json]`.

**Step 3b — kalimāt (morphology):** After Quran words are imported, `database.py` loads morphological segments into `quran_token_kalimah` if a file is available:

- `data/raw/quran/quran-morphology.txt` (full Quran), or else
- `data/raw/quran/morphology.example.txt` (demo: only al-Fātiḥah 1:1).

Format per line: `sura:ayah:word:segment<TAB>surface<TAB>POS<TAB>tags` (UTF-8). The same layout is used by [mustafa0x/quran-morphology](https://github.com/mustafa0x/quran-morphology) (`quran-morphology.txt`). Download the full file from that repository or from [Quranic Arabic Corpus](https://corpus.quran.com/download/) (v0.4 uses Buckwalter in the `surface` column — convert to Arabic before import if you use the raw corpus file).

The **Verse roots** tab shows kalimāt in the table column **Kalimāt (morph.)**, in the hierarchy tree, and in the graph labels when present.

### Desktop database explorer (Tkinter)

After the database file exists:

```powershell
python server.py
```

- **Left:** tree of tables; expand a table to see columns labeled `[PK]`, `[FK]`, and FK targets (e.g. `other_table(id)`).
- **Right:** select a table (or column), set **Rows (limit)**, then **Load table** or double-click the table name to show rows in a grid.

Uses Tkinter (included with standard Python on Windows). No extra UI package is required.

Tabs include **Question refiner** (chat + Bot 1 via the OpenAI **Responses** API) and **OpenAI admin** (vector stores and platform files using the same APIs as the OpenAI dashboard, plus Bot 1 `file_search` attachments). Set `OPENAI_API_KEY` in `.env`.

*(Optional: add a screenshot of the explorer window here.)*

---

### Alternative: step-by-step scripts

### 1. Create database (schema only)

```powershell
python scripts/init_db.py
```

### 2. Import lexicon JSON

Place `lane_lexicon*.json` under `data/raw/lexicon/` (or project root if that folder is empty), then:

```powershell
python scripts/import_lexicon.py
```

- `--truncate` — wipe lexicon tables before import.
- `--replace-entries` — re-insert entries for roots that already exist (use with care).

If both `data/raw/lexicon` and the project root contain the same filenames, only `data/raw/lexicon` is used to avoid duplicate imports.

### 3. Import Quran words

JSON array of objects with `surah` / `ayah` / `word` (or `surah_no`, `ayah_no`, `word_no`) and `text` (Uthmani). Example: [data/raw/quran/words.example.json](data/raw/quran/words.example.json).

```powershell
python scripts/import_quran.py data/raw/quran/words.example.json
```

**Mushaf JSON** (`quran.json` at repo root — verse list per surah):

```powershell
python scripts/import_quran_root_json.py
```

### 4. Map tokens to roots (heuristic)

```powershell
python scripts/map_roots.py
```

Uses substring/prefix heuristics (v1); not full Arabic morphology. Tune `--min-confidence`, `--limit`, and use `token_root_overrides` in SQL for manual corrections.

### 5. Live lexicon scrape (optional)

Requires Chrome + Selenium:

```powershell
python -m src.scraper.lexicon_scraper --url https://lexicon.quranic-research.net/data/01_A/000_A.html
```

### 6. Verify

```powershell
python scripts/verify_db.py
```

### Other utilities

- `python scripts/split_json.py lane_lexicon_3.json 3` — split a large JSON array into numbered parts.

## Tests

With dev extras installed (`pip install -e ".[dev]"`):

```powershell
pytest
```

Or, without pytest:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Documentation

- [docs/project-features.md](docs/project-features.md) — App UI (field-level), workflows, modules
- [docs/architecture.md](docs/architecture.md)
- [docs/data-model.md](docs/data-model.md)
- [docs/quran-openai-prompts.md](docs/quran-openai-prompts.md) — OpenAI Chat prompts (Quran analysis bots 1–4)

## Legacy scripts

Older root-level scripts (`lexicon selenium.py`, `lexicon csv.py`, `json_breaker.py`) are superseded by `src/scraper/lexicon_scraper.py`, DB export workflows, and `scripts/split_json.py`. Prefer the paths above.
