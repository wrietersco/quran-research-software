"""SQLite helpers for Step 6 knowledge uploads and report runs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Step6KnowledgeFileRow:
    id: int
    chat_session_id: str
    openai_file_id: str
    chunk_index: int
    local_path: str


@dataclass(frozen=True)
class Step6ReportRunRow:
    id: int
    chat_session_id: str
    status: str
    error_message: str | None
    report_dir: str | None
    model: str | None


def list_step6_knowledge_files(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[Step6KnowledgeFileRow]:
    rows = conn.execute(
        """
        SELECT id, chat_session_id, openai_file_id, chunk_index, local_path
        FROM step6_knowledge_files
        WHERE chat_session_id = ?
        ORDER BY chunk_index ASC, id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    return [
        Step6KnowledgeFileRow(
            id=int(r["id"]),
            chat_session_id=str(r["chat_session_id"]),
            openai_file_id=str(r["openai_file_id"]),
            chunk_index=int(r["chunk_index"]),
            local_path=str(r["local_path"]),
        )
        for r in rows
    ]


def delete_step6_knowledge_files_for_session(
    conn: sqlite3.Connection, chat_session_id: str, *, commit: bool = True
) -> None:
    conn.execute(
        "DELETE FROM step6_knowledge_files WHERE chat_session_id = ?",
        (chat_session_id,),
    )
    if commit:
        conn.commit()


def insert_step6_knowledge_file(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    openai_file_id: str,
    chunk_index: int,
    local_path: str,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO step6_knowledge_files (
            chat_session_id, openai_file_id, chunk_index, local_path
        )
        VALUES (?, ?, ?, ?)
        """,
        (chat_session_id, openai_file_id, chunk_index, local_path),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def insert_step6_report_run(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    model: str | None = None,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO step6_report_runs (chat_session_id, status, model)
        VALUES (?, 'pending', ?)
        """,
        (chat_session_id, model),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def update_step6_report_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str | None = None,
    error_message: str | None = None,
    report_dir: str | None = None,
    commit: bool = True,
) -> None:
    parts: list[str] = ["updated_at = datetime('now')"]
    args: list[object] = []
    if status is not None:
        parts.append("status = ?")
        args.append(status)
    if error_message is not None:
        parts.append("error_message = ?")
        args.append(error_message)
    if report_dir is not None:
        parts.append("report_dir = ?")
        args.append(report_dir)
    args.append(run_id)
    conn.execute(
        f"UPDATE step6_report_runs SET {', '.join(parts)} WHERE id = ?",
        args,
    )
    if commit:
        conn.commit()


def max_step6_knowledge_chunk_index(
    conn: sqlite3.Connection, chat_session_id: str
) -> int:
    row = conn.execute(
        """
        SELECT MAX(chunk_index) AS m FROM step6_knowledge_files
        WHERE chat_session_id = ?
        """,
        (chat_session_id,),
    ).fetchone()
    if row is None or row["m"] is None:
        return -1
    return int(row["m"])


def latest_step6_report_run(
    conn: sqlite3.Connection, chat_session_id: str
) -> Step6ReportRunRow | None:
    row = conn.execute(
        """
        SELECT id, chat_session_id, status, error_message, report_dir, model
        FROM step6_report_runs
        WHERE chat_session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id,),
    ).fetchone()
    if row is None:
        return None
    return Step6ReportRunRow(
        id=int(row["id"]),
        chat_session_id=str(row["chat_session_id"]),
        status=str(row["status"]),
        error_message=str(row["error_message"]) if row["error_message"] else None,
        report_dir=str(row["report_dir"]) if row["report_dir"] else None,
        model=str(row["model"]) if row["model"] else None,
    )
