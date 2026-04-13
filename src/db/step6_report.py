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
    openai_report_file_id: str | None
    created_at: str


@dataclass(frozen=True)
class Step6ReportChatMessageRow:
    id: int
    chat_session_id: str
    role: str
    content: str
    meta_json: str | None
    created_at: str


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
    openai_report_file_id: str | None = None,
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
    if openai_report_file_id is not None:
        parts.append("openai_report_file_id = ?")
        args.append(openai_report_file_id)
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


def _row_to_report_run(r: sqlite3.Row) -> Step6ReportRunRow:
    return Step6ReportRunRow(
        id=int(r["id"]),
        chat_session_id=str(r["chat_session_id"]),
        status=str(r["status"]),
        error_message=str(r["error_message"]) if r["error_message"] else None,
        report_dir=str(r["report_dir"]) if r["report_dir"] else None,
        model=str(r["model"]) if r["model"] else None,
        openai_report_file_id=str(r["openai_report_file_id"])
        if r["openai_report_file_id"]
        else None,
        created_at=str(r["created_at"]),
    )


def list_step6_report_runs(
    conn: sqlite3.Connection, chat_session_id: str, *, newest_first: bool = True
) -> list[Step6ReportRunRow]:
    order = "DESC" if newest_first else "ASC"
    rows = conn.execute(
        f"""
        SELECT id, chat_session_id, status, error_message, report_dir, model,
               openai_report_file_id, created_at
        FROM step6_report_runs
        WHERE chat_session_id = ?
        ORDER BY id {order}
        """,
        (chat_session_id,),
    ).fetchall()
    return [_row_to_report_run(r) for r in rows]


def list_openai_report_file_ids_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[str]:
    rows = conn.execute(
        """
        SELECT openai_report_file_id FROM step6_report_runs
        WHERE chat_session_id = ? AND openai_report_file_id IS NOT NULL
           AND TRIM(openai_report_file_id) != ''
        """,
        (chat_session_id,),
    ).fetchall()
    return [str(r["openai_report_file_id"]) for r in rows if r["openai_report_file_id"]]


def null_all_step6_report_openai_file_ids(
    conn: sqlite3.Connection, chat_session_id: str, *, commit: bool = True
) -> None:
    conn.execute(
        """
        UPDATE step6_report_runs
        SET openai_report_file_id = NULL, updated_at = datetime('now')
        WHERE chat_session_id = ?
        """,
        (chat_session_id,),
    )
    if commit:
        conn.commit()


def latest_step6_report_run(
    conn: sqlite3.Connection, chat_session_id: str
) -> Step6ReportRunRow | None:
    row = conn.execute(
        """
        SELECT id, chat_session_id, status, error_message, report_dir, model,
               openai_report_file_id, created_at
        FROM step6_report_runs
        WHERE chat_session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_report_run(row)


def insert_step6_report_chat_message(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    role: str,
    content: str,
    meta_json: str | None = None,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO step6_report_chat_messages (
            chat_session_id, role, content, meta_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (chat_session_id, role, content, meta_json),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def list_step6_report_chat_messages(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[Step6ReportChatMessageRow]:
    rows = conn.execute(
        """
        SELECT id, chat_session_id, role, content, meta_json, created_at
        FROM step6_report_chat_messages
        WHERE chat_session_id = ?
        ORDER BY id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    return [
        Step6ReportChatMessageRow(
            id=int(r["id"]),
            chat_session_id=str(r["chat_session_id"]),
            role=str(r["role"]),
            content=str(r["content"]),
            meta_json=str(r["meta_json"]) if r["meta_json"] else None,
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]
