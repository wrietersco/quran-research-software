"""SQLite schema introspection for tools and UI (PK/FK, columns, sample rows)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnInfo:
    cid: int
    name: str
    type: str
    notnull: bool
    default_value: Any
    pk: bool
    is_fk: bool
    fk_refs: str | None  # e.g. "other_table(id)"


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    """Table names excluding sqlite internal tables."""
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(r[0]) for r in rows]


def _pragma_table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f'PRAGMA table_info("{_quote_ident(table)}")').fetchall())


def _pragma_foreign_keys(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f'PRAGMA foreign_key_list("{_quote_ident(table)}")').fetchall())


def _quote_ident(name: str) -> str:
    return name.replace('"', '""')


def get_columns_with_keys(conn: sqlite3.Connection, table: str) -> list[ColumnInfo]:
    """Column metadata with PK flag and FK target summary."""
    infos = _pragma_table_info(conn, table)
    fk_rows = _pragma_foreign_keys(conn, table)
    fk_by_from: dict[str, list[str]] = {}
    for fr in fk_rows:
        col_from = str(fr["from"])
        ref = f'{fr["table"]}({fr["to"]})'
        fk_by_from.setdefault(col_from, []).append(ref)

    out: list[ColumnInfo] = []
    for row in infos:
        name = str(row["name"])
        refs = fk_by_from.get(name)
        is_fk = bool(refs)
        fk_s = "; ".join(refs) if refs else None
        out.append(
            ColumnInfo(
                cid=int(row["cid"]),
                name=name,
                type=str(row["type"] or ""),
                notnull=bool(row["notnull"]),
                default_value=row["dflt_value"],
                pk=bool(row["pk"]),
                is_fk=is_fk,
                fk_refs=fk_s,
            )
        )
    return out


def fetch_table_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """
    Return (column_names, rows) for SELECT * with limit/offset.
    """
    lim = max(1, min(int(limit), 10_000))
    off = max(0, int(offset))
    q = f'SELECT * FROM "{_quote_ident(table)}" LIMIT ? OFFSET ?'
    cur = conn.execute(q, (lim, off))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = [tuple(r) for r in cur.fetchall()]
    return cols, rows


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    q = f'SELECT COUNT(*) AS c FROM "{_quote_ident(table)}"'
    row = conn.execute(q).fetchone()
    return int(row[0]) if row else 0
