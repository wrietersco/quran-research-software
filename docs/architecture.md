# Architecture

## Pipeline

- **One-shot build** — `python database.py` at the project root runs schema init, lexicon import, Quran JSON import (`data/raw/quran/*.json`), and mapping (see `database.py` flags).
- **Desktop explorer** — `python server.py` opens a Tkinter UI to browse tables, columns (PK/FK), and row samples.

1. **Schema** — `scripts/init_db.py` applies `src/db/schema.sql` to `data/db/quran_lexicon.db`.
2. **Lexicon import** — `scripts/import_lexicon.py` reads `data/raw/lexicon/lane_lexicon*.json` into `lexicon_roots` / `lexicon_entries`. FTS5 (`lexicon_entries_fts`) stays in sync via triggers.
3. **Live scrape** — `python -m src.scraper.lexicon_scraper` (or `src/scraper/lexicon_scraper.py`) appends pages from the web UI into the same tables.
4. **Quran tokens** — `scripts/import_quran.py` loads word JSON into `quran_tokens`.
5. **Mapping** — `scripts/map_roots.py` runs heuristic token→root candidates (`token_root_analysis`) and applies `token_root_overrides`.

## Layout

- `src/` — library code (db, importers, normalize, mapping, scraper).
- `scripts/` — CLI entrypoints.
- `data/raw/` — inputs; `data/db/` — SQLite file.
- `tests/` — unit tests.

## Environment

- `QURAN_LEXICON_DB` — optional absolute path to override the default DB location.
