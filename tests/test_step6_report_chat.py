"""Tests for Step 6 report chat, DB list helpers, and context angle helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.chat.step6_report_agent import append_step6_extra_angle_to_context_blob
from src.chat.step6_report_chat_agent import (
    _extract_json_object,
    classify_intent_json_only,
    user_explicitly_requests_pari_regeneration,
)
from src.db.step6_report import (
    insert_step6_report_run,
    list_step6_report_runs,
    update_step6_report_run,
)


def test_append_step6_extra_angle_to_context_blob() -> None:
    base = "## Refined question\nq\n"
    assert append_step6_extra_angle_to_context_blob(base, None) == base
    assert append_step6_extra_angle_to_context_blob(base, "  ") == base
    out = append_step6_extra_angle_to_context_blob(base, "focus X")
    assert "One-off report angle" in out
    assert "focus X" in out


def test_user_explicitly_requests_pari_regeneration() -> None:
    assert user_explicitly_requests_pari_regeneration("Please write a new report on ethics")
    assert user_explicitly_requests_pari_regeneration("Rewrite the report with a legal angle")
    assert user_explicitly_requests_pari_regeneration("Run PARI again")
    assert not user_explicitly_requests_pari_regeneration(
        "so do you mean Nafs is consciousness?"
    )
    assert not user_explicitly_requests_pari_regeneration(
        "What does the report say about nafs?"
    )


def test_extract_json_object_and_classify() -> None:
    assert _extract_json_object('{"action":"answer","angle":null}') == {
        "action": "answer",
        "angle": None,
    }
    assert _extract_json_object('Here:\n{"action":"regenerate","angle":"more legal"}\n') == {
        "action": "regenerate",
        "angle": "more legal",
    }
    assert classify_intent_json_only({"action": "answer"}) == ("answer", None)
    assert classify_intent_json_only({"action": "regenerate", "angle": "z"}) == (
        "regenerate",
        "z",
    )


def test_list_step6_report_runs_order(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            openai_vector_store_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE step6_report_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            report_dir TEXT,
            model TEXT,
            openai_report_file_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO chat_sessions (id, title) VALUES ('sess1', 't')")
    conn.commit()
    a = insert_step6_report_run(conn, chat_session_id="sess1", model="m1")
    b = insert_step6_report_run(conn, chat_session_id="sess1", model="m2")
    update_step6_report_run(conn, a, status="done", report_dir="/tmp/a", commit=True)
    newest = list_step6_report_runs(conn, "sess1", newest_first=True)
    assert [r.id for r in newest] == [b, a]
    oldest = list_step6_report_runs(conn, "sess1", newest_first=False)
    assert [r.id for r in oldest] == [a, b]
    assert newest[0].openai_report_file_id is None
    conn.close()
