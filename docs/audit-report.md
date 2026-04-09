# Project audit report

**Scope:** Quran Lexicon Pipeline — SQLite importers, Tkinter desktop app (`server.py`), FastAPI surface (`api_server.py`), chat/morphology pipelines under `src/`.  
**Date:** 2026-04-09 (workspace snapshot)  
**Note:** Security and deployment hardening are intentionally out of scope for this report.

This document lists architectural risks, maintainability gaps, and prioritized improvements. It is not a judgment of fitness for personal use; many items trade purity for pragmatism.

---

## Executive summary

The codebase is **feature-rich and reasonably layered** (`src/db`, `src/importers`, `src/chat`, `src/ui`), with clear documentation in `README.md` and `docs/`. The main weaknesses are **very large entrypoint modules**, **schema evolution split across SQL files and Python strings**, **non-packaged layout** (`sys.path` hacks), **heavy binary-ish assets in the tree**, and **uneven failure recovery in the Question refiner pipeline** (see User experience below).

---

## User experience — workflows, errors, and recovery

This section covers what happens when something goes wrong (network drop, API error, user closes the app, etc.) and whether the UI supports **starting over** vs **continuing where things stopped**.

### Example you raised: disconnect mid-step

| Step | Roughly what happens | “Start over” | “Resume where it left off” |
|------|----------------------|--------------|----------------------------|
| **Question refiner** | Failed call shows in the log; session messages remain in the JSON store / DB side. User can send again. | Implicit (new message / new session). | N/A for a single request; user retries manually. |
| **Bot 1** | One LLM run; on success, results are written to the pipeline DB. On **Stop** or failure, **nothing** is saved (`_on_bot1_stopped` / error path). | Re-run Bot 1. | No partial Bot 1 artifact to resume; must run again. |
| **Bot 2** | Loops connotations in a **background thread**, collects successes in memory, then **writes all synonyms to the DB in one batch** at the end (`_apply_bot2_batch`). If the **process exits** (crash, force quit) **before** that callback runs, **even completed API calls can be lost**. Stop mid-run does call the batch saver with whatever finished. | Re-run Bot 2 (may duplicate synonym rows if prior partial batch did save — data model dependent). | No explicit “resume only missing connotations” flow; user must infer from UI/DB. |
| **Find Verses (Step 3)** | DB-oriented; re-running generally re-executes the scan (user should understand replace vs duplicate from docs). | Re-run the action. | No guided “resume interrupted scan” (usually fast enough not to matter). |
| **Step 5** | **Strongest persistence:** jobs and results live in SQLite; orchestrator handles **`waiting_retry`** (e.g. rate limits) by polling the DB. **Stop** cancels the run record via `cancel_step5_run`. | **CLEAR** deletes Step 5 synthesis data for the session (intro text explains it does **not** remove Find Verses / shortlist). | **Gap:** after an **abrupt exit**, jobs can remain **`in_progress`** in the DB while no worker is alive. **“Run Step 5” always creates a new run** (`create_step5_run` + new queue); there is **no first-class “reattach orchestrator to run_id = …”** button in the flow audited here. Progress UIs can show the last run via `latest_step5_run_id_for_session`, but recovery is **not spelled out** for the user. |
| **Step 6 (report)** | Run status is updated in the DB on completion, cancel, or error (`step6_report_tab`). | User can start another run after error/cancel. | Depends on implementation of the agent; no universal “resume half-written report” promise from the UI layer alone. |

**Takeaway:** The product **does not offer a single, obvious control** for “abandon this run and reset only this step” vs “pick up the same run after a disconnect.” Step 5 is closest to resumable at the **data** layer, but the **UX** still leans toward **start a new run** rather than **resume run N**.

### Other UX observations

- **Discoverability:** Recovery behavior (what CLEAR does, what Stop does, what survives a crash) is partly in **long tab intros** and dialogs — easy to miss compared to a short **“If something fails…”** help strip or link to `docs/project-features.md`.
- **Global busy state** (`_busy`): While a step is running, many actions are blocked. That avoids overlapping LLM jobs but can feel **stuck** if status text is easy to overlook.
- **Errors:** “Last Bot 1 / Bot 2 error” panels are helpful; ensuring **every** step surfaces **actionable next steps** (“Retry”, “Clear step data”, “New session”) would reduce support burden.
- **Pipeline summary / metrics:** Good for power users; tying **stale `in_progress` Step 5 jobs** to a visible **“Reset stuck jobs”** or **“Resume this run”** would close the gap between backend capability and user mental model.

### Recommendations (UX-focused)

1. **Bot 2:** Persist **each** successful connotation to the DB **immediately** (or in small batches), so a disconnect never throws away finished API work; optionally add **“Run only connotations without synonyms yet”** to support true resume.
2. **Step 5:** Offer **“Resume last run for this session”** when `latest_step5_run_id_for_session` has incomplete work, and/or a maintenance action to **requeue or fail stale `in_progress`** jobs after crash.
3. **Copy / docs:** One short **failure & recovery** subsection in `docs/project-features.md` (or in-app “?”) listing Stop vs CLEAR vs Delete session vs New session.
4. **Optional:** Per-step **“Reset this step only”** (truncate relevant tables for the session) where safe, so users do not have to delete the whole session to retry one bot.

---

## Strengths

- **Clear separation** between importers, DB helpers, LLM engines, and UI tabs.
- **SQLite usage** enables `PRAGMA foreign_keys`, WAL mode, and incremental `migrate_schema()` for existing databases.
- **Documentation** (`docs/architecture.md`, `docs/data-model.md`, `docs/project-features.md`) matches much of the real behavior.
- **Tests** exist for normalization, morphology pipeline pieces, corpus roots, and step-6 chunking (`tests/`).
- **Pipeline UX primitives** already exist: **Stop** for Bot 1 / Bot 2 / Step 5, **CLEAR** for Step 5 synthesis, **New session** / **Delete**, error summaries, and Step 5 **waiting_retry** handling in the orchestrator.

---

## Critical / high priority

### 1. Large data files in the repository root

- Multiple **`lane_lexicon*.json` files (tens of MB each)** plus `quran.json`, `quran_data.csv`, `quran_pages.xlsx` **bloat clones and backups** and blur the line between “source code” and “datasets.”
- **Recommendation:** Move canonical inputs under `data/raw/` with a **download/import script**, or use **Git LFS** / external artifact storage; keep small **samples** in-repo for tests and docs.

### 2. Monolithic UI entrypoint

- **`server.py` is on the order of ~800+ lines** with a single large `DbExplorerApp` that wires notebook tabs, DB browsing, verse views, and integrations. This **raises merge conflict risk** and makes **testing the UI** difficult.
- **Recommendation:** Split along existing tab boundaries (e.g. one module per notebook tab + a thin `main`), or introduce a small **application shell** class that only composes frames.

---

## Medium priority — architecture and maintainability

### 3. Schema management: two sources of truth

- **Bootstrap:** `src/db/schema.sql` creates the base tables.
- **Evolving DBs:** `src/db/connection.py` holds **large `_MIGRATE_*` string blocks** plus **conditional `ALTER TABLE`** branches.
- **Risk:** New developers can miss updating both paths; **fresh installs vs upgraded DBs** can diverge in subtle ways.
- **Recommendation:** Prefer **versioned migration files** (e.g. numbered `.sql` or a tiny migration registry) and a single “current schema” story; or generate migrations from one declarative source.

### 4. Project layout and imports

- **Many scripts and tests repeat:**

  ```python
  ROOT = Path(...).resolve().parent
  sys.path.insert(0, str(ROOT))
  ```

- This works but **prevents editable installs**, confuses tooling, and duplicates boilerplate.
- **Recommendation:** Add a **`pyproject.toml`** with `[project]` / `packages = [{ include = "src" }]` or rename `src` to the package name `quran_lexicon` and `pip install -e .`; then drop path hacks from tests via `pytest` `pythonpath` or proper package layout.

### 5. Overlapping morphology concepts

- **`src/morphology/`** (e.g. Camel pipeline) and **`src/morphology_pipeline/`** (ensemble, Stanza, etc.) **sound like the same concern** to a new reader.
- **Recommendation:** Document the distinction in `docs/architecture.md` (or merge namespaces with subpackages like `morphology.camel` / `morphology.ensemble`) so import paths reflect roles.

### 6. Dependency weight vs optional features

- **`requirements.txt` includes `sentence-transformers`** (and thus **PyTorch**), which is heavy for users who only want DB build + Tkinter explorer.
- **Recommendation:** Split into **`requirements.txt`** (core) and **`requirements-ml.txt`** or extras in `pyproject.toml` (`pip install .[step5]`).

### 7. Testing toolchain drift

- **README** suggests `python -m unittest discover`; **some tests are clearly run with pytest** (pytest-style discovery and `__pycache__` artifacts in the tree).
- **`pytest` is commented out** in `requirements.txt`.
- **Recommendation:** Pick **one** primary runner, document it, and add **`pytest` (or `unittest`) to dev dependencies**; add a **`conftest.py`** or `pyproject.toml` `[tool.pytest.ini_options]` with `pythonpath` so tests do not need `sys.path.insert`.

---

## Lower priority / hygiene

### 8. Scratch and legacy artifacts

- **`_t.py` at repo root** appears to be a **one-off assertion script** (checks a substring in `question_refiner_tab.py`). It clutters the root and is easy to confuse with real tooling.
- **`legacy/`** is acknowledged in the README; consider a **single “deprecated” doc** with dates and replacements, or archive outside the main branch.

### 9. Generated / cache directories

- **`.gitignore` excludes `__pycache__`**; if any cache dirs were ever committed, clean them once. Prefer **not** relying on IDE-only ignores.

### 10. `docs/architecture.md` vs actual system

- The architecture doc describes the **pipeline and layout** well but **understates** the **Question refiner / Bot 1–2 / Step 5–6 / OpenAI admin** subsystems now present in `src/chat` and `src/ui`.
- **Recommendation:** A short **“Runtime surfaces”** section: `server.py` (desktop), `api_server.py` (HTTP), `database.py` (batch build).

### 11. Concurrency and SQLite

- **FastAPI + SQLite:** multiple concurrent writers can **contend or lock** under load. For local single-user use this is usually fine; under heavier concurrent use, document **single-worker** expectations or consider **queueing writes**.

---

## Positive patterns worth keeping

- **Dataclasses and small DB modules** (`bot2_synonyms.py`, `find_verses.py`, etc.) keep SQL near domain names.
- **Explicit `conn.commit()`** in several pipeline writers avoids silent rollback surprises for API callers.
- **Config centralization** in `src/config.py` with `get_db_path()` and `QURAN_LEXICON_DB` override.

---

## Suggested remediation order

1. **Relocate large JSON/CSV** out of the default clone or into LFS + documented fetch steps.  
2. **Introduce `pyproject.toml` + editable install**; remove repeated `sys.path.insert` where possible.  
3. **Refactor `server.py`** into tab-sized modules (incremental extractions).  
4. **Unify migration story** for SQLite (numbered migrations or one generator).  
5. **Split optional ML dependencies** from core `requirements.txt`.  
6. **Align test runner** and dev dependencies with README.  
7. **UX / recovery:** Bot 2 incremental persistence; Step 5 resume + stale-job handling; short user-facing failure guide.

---

## Files referenced for this audit

| Area | Primary locations |
|------|-------------------|
| Desktop app | `server.py` |
| Question refiner pipeline UI | `src/ui/question_refiner_tab.py` |
| Step 5 background worker | `src/chat/step5_orchestrator.py` |
| HTTP API | `api_server.py` |
| DB connection & migrations | `src/db/connection.py`, `src/db/schema.sql` |
| Config | `src/config.py` |
| Batch pipeline | `database.py`, `scripts/*.py` |
| Library code | `src/` |
| Tests | `tests/` |

---

*End of report.*
