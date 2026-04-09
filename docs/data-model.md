# Data model (SQLite)

## lexicon_roots

| Column | Description |
|--------|-------------|
| id | PK |
| root_word | Arabic root as in source |
| root_word_normalized | `normalize_arabic(root_word)` for joins |
| source_ref | File path or URL |

Unique: `root_word_normalized`.

## lexicon_entries

| Column | Description |
|--------|-------------|
| id | PK |
| root_id | FK → lexicon_roots |
| seq | 1-based order within root (replaces repeated `1. ⇒` headings) |
| heading_raw | Original `h3` text |
| heading_normalized | `canonical_heading(seq, heading_raw)` |
| definition | Full entry body |

Unique: `(root_id, seq)`.

## quran_verses

Full Arabic **verse line** as in project-root `quran.json` (or other verse-JSON import). One row per ayah.

| Column | Description |
|--------|-------------|
| id | PK |
| surah_no | Surah number |
| ayah_no | Ayah number |
| verse_text | Full `text` field from JSON |
| source_ref | e.g. `quran.json` |

Unique: `(surah_no, ayah_no)`.

## quran_tokens

Positional word: `(surah_no, ayah_no, word_no)` unique. `token_plain` is `normalize_arabic` of the imported Uthmani token. Step 3 — Find Verses re-normalizes stored tokens with `unify_ta_marbuta=True` when matching so Bot output and corpus align on ة/ه.

## quran_token_kalimah

Grammatical **kalimāt** (morphological segments) inside one orthographic Quran word. Filled by **Step 3b** in `database.py` from a tab-separated morphology file whose `word` index matches `quran_tokens.word_no` (Tanzil / Quran.com style).

| Column | Description |
|--------|-------------|
| id | PK |
| token_id | FK → `quran_tokens` |
| kalimah_seq | 1-based order within the word |
| surface | Arabic segment text |
| pos | Part-of-speech label from source (optional) |
| morph_tags | Full tag string from source (optional) |
| source | Provenance label (e.g. file stem) |

Unique: `(token_id, kalimah_seq)`.

## find_verse_matches

Question refiner Step 3: verse hits for a chat session. FK `chat_session_id` → `chat_sessions`, `refined_question_id` → `session_refined_questions`, `bot1_connotation_id` → `bot1_connotations`, optional `bot2_synonym_term_id` → `bot2_synonym_terms`. Columns `source_kind` (`connotation` | `synonym`), `query_text`, `surah_no`, `ayah_no`, `created_at`.

## token_root_analysis

Candidate or confirmed links from Quran tokens to lexicon roots. Multiple rows per token allowed; at most one `is_primary = 1` per token (heuristic + overrides).

## token_root_overrides

Manual primary root for a token (`token_id` PK).

## lexicon_entries_fts

FTS5 external table over `lexicon_entries.definition`.
