"""Step 5 resume helpers: stale in_progress reset and resumable-run detection."""

from __future__ import annotations

import sqlite3

from src.db.step5_synthesis import reset_stale_step5_in_progress_jobs, step5_run_is_resumable


def _minimal_step5_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE step5_synthesis_runs (
            id INTEGER PRIMARY KEY,
            cancelled_at TEXT
        );
        CREATE TABLE step5_verse_manifests (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL
        );
        CREATE TABLE step5_synthesis_jobs (
            id INTEGER PRIMARY KEY,
            manifest_id INTEGER NOT NULL,
            combo_ordinal INTEGER NOT NULL,
            entry_combo_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            next_attempt_at TEXT,
            error_code TEXT,
            error_message TEXT,
            user_payload_json TEXT,
            llm_call_state TEXT,
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    return c


def test_reset_stale_step5_in_progress_jobs_marks_waiting_retry() -> None:
    c = _minimal_step5_conn()
    try:
        c.execute(
            "INSERT INTO step5_synthesis_runs (id, cancelled_at) VALUES (1, NULL)"
        )
        c.execute("INSERT INTO step5_verse_manifests (id, run_id) VALUES (10, 1)")
        c.execute(
            """
            INSERT INTO step5_synthesis_jobs (id, manifest_id, combo_ordinal, status)
            VALUES (100, 10, 1, 'in_progress')
            """
        )
        c.commit()
        n = reset_stale_step5_in_progress_jobs(c, 1)
        assert n == 1
        row = c.execute(
            "SELECT status, error_code FROM step5_synthesis_jobs WHERE id = 100"
        ).fetchone()
        assert row is not None
        assert row["status"] == "waiting_retry"
        assert row["error_code"] == "recovered_after_interrupt"
    finally:
        c.close()


def test_step5_run_is_resumable_true_when_in_progress() -> None:
    c = _minimal_step5_conn()
    try:
        c.execute(
            "INSERT INTO step5_synthesis_runs (id, cancelled_at) VALUES (1, NULL)"
        )
        c.execute("INSERT INTO step5_verse_manifests (id, run_id) VALUES (10, 1)")
        c.execute(
            """
            INSERT INTO step5_synthesis_jobs (id, manifest_id, combo_ordinal, status)
            VALUES (1, 10, 1, 'in_progress')
            """
        )
        c.commit()
        assert step5_run_is_resumable(c, 1) is True
    finally:
        c.close()


def test_step5_run_is_resumable_false_when_cancelled() -> None:
    c = _minimal_step5_conn()
    try:
        c.execute(
            "INSERT INTO step5_synthesis_runs (id, cancelled_at) VALUES (1, '2020-01-01')"
        )
        c.execute("INSERT INTO step5_verse_manifests (id, run_id) VALUES (10, 1)")
        c.execute(
            """
            INSERT INTO step5_synthesis_jobs (id, manifest_id, combo_ordinal, status)
            VALUES (1, 10, 1, 'in_progress')
            """
        )
        c.commit()
        assert step5_run_is_resumable(c, 1) is False
    finally:
        c.close()


def test_step5_run_is_resumable_false_when_all_done() -> None:
    c = _minimal_step5_conn()
    try:
        c.execute(
            "INSERT INTO step5_synthesis_runs (id, cancelled_at) VALUES (1, NULL)"
        )
        c.execute("INSERT INTO step5_verse_manifests (id, run_id) VALUES (10, 1)")
        c.execute(
            """
            INSERT INTO step5_synthesis_jobs (id, manifest_id, combo_ordinal, status)
            VALUES (1, 10, 1, 'done')
            """
        )
        c.commit()
        assert step5_run_is_resumable(c, 1) is False
    finally:
        c.close()
