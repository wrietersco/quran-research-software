"""SQLite helpers for Step 5 synthesis runs/jobs/results."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Step5MatchRow:
    find_match_id: int
    bot1_topic_id: int
    bot1_connotation_id: int
    topic_text: str
    connotation_text: str
    query_text: str
    surah_no: int
    ayah_no: int
    verse_text: str


@dataclass(frozen=True)
class ClaimedManifestBatch:
    manifest_id: int
    run_id: int
    find_match_id: int
    bot1_topic_id: int | None
    bot1_connotation_id: int | None
    topic_text: str
    connotation_text: str
    surah_no: int
    ayah_no: int
    verse_text: str
    manifest_json: str
    total_combos: int
    ordinals: tuple[int, ...]


@dataclass(frozen=True)
class Step5Progress:
    total_jobs: int
    dispatched: int
    completed: int
    failed: int
    waiting_retry: int
    cost_usd: float
    is_cancelled: bool


@dataclass(frozen=True)
class Step5RequestStats:
    """Per-row counts from step5_synthesis_jobs for a run (matches bulk-seeded queue)."""

    total_requests: int
    done: int
    failed: int
    in_progress: int
    waiting_retry: int
    cancelled: int


@dataclass(frozen=True)
class Step5ShortlistRow:
    find_match_id: int
    surah_no: int
    ayah_no: int
    relevance_score: float
    threshold_pct: int
    query_text: str
    verse_text: str


@dataclass(frozen=True)
class Step5ResultListRow:
    result_id: int
    job_id: int
    run_id: int
    manifest_id: int
    find_match_id: int
    surah_no: int
    ayah_no: int
    possibility_score: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    provider: str
    model: str
    created_at: str


@dataclass(frozen=True)
class Step5RequestLogRow:
    job_id: int
    result_id: int | None
    surah_no: int
    ayah_no: int
    status_label: str
    progress_label: str
    request_preview: str
    response_preview: str


@dataclass(frozen=True)
class Step5RunAnalytics:
    """Aggregates over ``step5_synthesis_results`` for one run (all rows, not UI-limited)."""

    result_count: int
    distinct_verse_count: int
    sum_prompt_tokens: int
    sum_completion_tokens: int
    sum_total_tokens: int
    total_cost_usd: float
    with_score_count: int
    without_score_count: int
    score_avg: float | None
    score_min: int | None
    score_max: int | None
    score_histogram: tuple[tuple[int, int], ...]
    failed_jobs_by_error: tuple[tuple[str, int], ...]

    def to_json_dict(self) -> dict[str, object]:
        n = self.result_count
        avg_in = (self.sum_prompt_tokens / n) if n else None
        avg_out = (self.sum_completion_tokens / n) if n else None
        avg_tot = (self.sum_total_tokens / n) if n else None
        avg_cost = (self.total_cost_usd / n) if n else None
        return {
            "result_count": self.result_count,
            "distinct_verse_count": self.distinct_verse_count,
            "sum_prompt_tokens": self.sum_prompt_tokens,
            "sum_completion_tokens": self.sum_completion_tokens,
            "sum_total_tokens": self.sum_total_tokens,
            "tokens": {
                "input_prompt_tokens": self.sum_prompt_tokens,
                "output_completion_tokens": self.sum_completion_tokens,
                "total_tokens": self.sum_total_tokens,
                "avg_input_prompt_tokens_per_saved_result": avg_in,
                "avg_output_completion_tokens_per_saved_result": avg_out,
                "avg_total_tokens_per_saved_result": avg_tot,
            },
            "total_cost_usd": self.total_cost_usd,
            "cost_usd": {
                "total": self.total_cost_usd,
                "avg_per_saved_result": avg_cost,
            },
            "with_score_count": self.with_score_count,
            "without_score_count": self.without_score_count,
            "score_avg": self.score_avg,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "score_histogram": [list(x) for x in self.score_histogram],
            "failed_jobs_by_error": [list(x) for x in self.failed_jobs_by_error],
        }


def _step5_one_line_preview(s: str | None, max_len: int = 96) -> str:
    if not s:
        return ""
    t = " ".join(str(s).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _step5_request_log_status(job_status: str, has_result: bool) -> str:
    if has_result:
        return "done"
    js = (job_status or "").strip().lower()
    if js == "in_progress":
        return "in progress"
    if js == "waiting_retry":
        return "waiting retry"
    if js == "failed":
        return "failed"
    if js == "cancelled":
        return "cancelled"
    if js == "done":
        return "done"
    return js or "unknown"


def _step5_request_log_progress(
    job_status: str,
    has_result: bool,
    llm_call_state: str | None,
    has_payload: bool,
) -> str:
    """Human-readable live phase for the request-log table."""
    if has_result:
        return "Done — response saved"
    js = (job_status or "").strip().lower()
    if js == "failed":
        return "Failed"
    if js == "waiting_retry":
        return "Backing off before retry"
    if js == "cancelled":
        return "Cancelled"
    if js == "done":
        return "Done"
    if js == "in_progress":
        ph = (llm_call_state or "").strip().lower()
        if ph == "queued":
            return "Queued — worker has not started yet"
        if ph == "building":
            return "Building JSON payload…"
        if ph == "ready":
            if has_payload:
                return "Payload ready — waiting (queue / rate limit)…"
            return "Queued…"
        if ph == "calling":
            return "LLM request in flight…"
        if ph == "saving":
            return "Writing result to database…"
        if has_payload:
            return "In progress…"
        return "Claimed job — preparing…"
    return js or "Unknown"


def create_step5_run(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    provider: str,
    model: str,
    verse_mode: str,
    verse_n: int | None,
    system_prompt_hash: str | None,
    relevance_threshold_pct: int | None = None,
    cross_encoder_model: str | None = None,
    synthesis_mode: str = "combination",
) -> int:
    sm = (synthesis_mode or "combination").strip().lower()
    if sm not in {"combination", "loaded"}:
        sm = "combination"
    cur = conn.execute(
        """
        INSERT INTO step5_synthesis_runs (
            chat_session_id, provider, model, verse_mode, verse_n, system_prompt_hash,
            relevance_threshold_pct, cross_encoder_model, synthesis_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_session_id,
            provider.strip(),
            model.strip(),
            verse_mode.strip(),
            int(verse_n) if verse_n is not None else None,
            system_prompt_hash,
            int(relevance_threshold_pct) if relevance_threshold_pct is not None else None,
            cross_encoder_model.strip() if cross_encoder_model else None,
            sm,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def cancel_step5_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        "UPDATE step5_synthesis_runs SET cancelled_at = datetime('now') WHERE id = ?",
        (run_id,),
    )
    conn.commit()


def latest_step5_run_id_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM step5_synthesis_runs
        WHERE chat_session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def list_step5_matches_for_session(
    conn: sqlite3.Connection,
    chat_session_id: str,
    *,
    max_rows: int | None = None,
    only_find_match_ids: frozenset[int] | None = None,
) -> list[Step5MatchRow]:
    sql = """
        SELECT
            f.id AS find_match_id,
            t.id AS bot1_topic_id,
            c.id AS bot1_connotation_id,
            t.topic_text AS topic_text,
            c.connotation_text AS connotation_text,
            f.query_text AS query_text,
            f.surah_no AS surah_no,
            f.ayah_no AS ayah_no,
            COALESCE(v.verse_text, '') AS verse_text
        FROM find_verse_matches f
        JOIN bot1_connotations c ON c.id = f.bot1_connotation_id
        JOIN bot1_topics t ON t.id = c.bot1_topic_id
        LEFT JOIN quran_verses v ON v.surah_no = f.surah_no AND v.ayah_no = f.ayah_no
        WHERE f.chat_session_id = ?
    """
    params: list[object] = [chat_session_id]
    if only_find_match_ids:
        ids = tuple(sorted(int(x) for x in only_find_match_ids))
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql += f" AND f.id IN ({placeholders})"
        params.extend(ids)
    sql += """
        ORDER BY t.sort_order ASC, c.sort_order ASC, f.source_kind ASC, f.query_text ASC,
                 f.surah_no ASC, f.ayah_no ASC, f.id ASC
    """
    if max_rows is not None and not only_find_match_ids:
        sql += " LIMIT ?"
        params.append(max(1, int(max_rows)))
    rows = conn.execute(sql, params).fetchall()
    out: list[Step5MatchRow] = []
    for r in rows:
        out.append(
            Step5MatchRow(
                find_match_id=int(r["find_match_id"]),
                bot1_topic_id=int(r["bot1_topic_id"]),
                bot1_connotation_id=int(r["bot1_connotation_id"]),
                topic_text=str(r["topic_text"] or ""),
                connotation_text=str(r["connotation_text"] or ""),
                query_text=str(r["query_text"] or ""),
                surah_no=int(r["surah_no"]),
                ayah_no=int(r["ayah_no"]),
                verse_text=str(r["verse_text"] or ""),
            )
        )
    return out


def replace_step5_session_shortlist(
    conn: sqlite3.Connection,
    chat_session_id: str,
    entries: list[tuple[int, float]],
    *,
    threshold_pct: int,
    cross_encoder_model: str | None,
) -> None:
    conn.execute(
        "DELETE FROM step5_session_shortlist WHERE chat_session_id = ?",
        (chat_session_id,),
    )
    model = cross_encoder_model.strip() if cross_encoder_model else None
    for fid, score in entries:
        conn.execute(
            """
            INSERT INTO step5_session_shortlist (
                chat_session_id, find_match_id, relevance_score,
                threshold_pct, cross_encoder_model
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_session_id, int(fid), float(score), int(threshold_pct), model),
        )
    conn.commit()


def fetch_step5_shortlist_rows(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[Step5ShortlistRow]:
    rows = conn.execute(
        """
        SELECT
            s.find_match_id AS find_match_id,
            s.relevance_score AS relevance_score,
            s.threshold_pct AS threshold_pct,
            f.surah_no AS surah_no,
            f.ayah_no AS ayah_no,
            f.query_text AS query_text,
            COALESCE(v.verse_text, '') AS verse_text
        FROM step5_session_shortlist s
        JOIN find_verse_matches f
            ON f.id = s.find_match_id AND f.chat_session_id = s.chat_session_id
        LEFT JOIN quran_verses v ON v.surah_no = f.surah_no AND v.ayah_no = f.ayah_no
        WHERE s.chat_session_id = ?
        ORDER BY s.relevance_score DESC, f.surah_no ASC, f.ayah_no ASC, s.find_match_id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    out: list[Step5ShortlistRow] = []
    for r in rows:
        out.append(
            Step5ShortlistRow(
                find_match_id=int(r["find_match_id"]),
                surah_no=int(r["surah_no"]),
                ayah_no=int(r["ayah_no"]),
                relevance_score=float(r["relevance_score"]),
                threshold_pct=int(r["threshold_pct"]),
                query_text=str(r["query_text"] or ""),
                verse_text=str(r["verse_text"] or ""),
            )
        )
    return out


def fetch_step5_shortlist_find_match_ids(
    conn: sqlite3.Connection, chat_session_id: str
) -> frozenset[int]:
    rows = conn.execute(
        """
        SELECT find_match_id
        FROM step5_session_shortlist
        WHERE chat_session_id = ?
        """,
        (chat_session_id,),
    ).fetchall()
    return frozenset(int(r["find_match_id"]) for r in rows)


def fetch_step5_shortlist_scores_map(
    conn: sqlite3.Connection, chat_session_id: str
) -> dict[int, float]:
    rows = conn.execute(
        """
        SELECT find_match_id, relevance_score
        FROM step5_session_shortlist
        WHERE chat_session_id = ?
        """,
        (chat_session_id,),
    ).fetchall()
    return {int(r["find_match_id"]): float(r["relevance_score"]) for r in rows}


def fetch_step5_shortlist_run_meta(
    conn: sqlite3.Connection, chat_session_id: str
) -> tuple[int | None, str | None]:
    row = conn.execute(
        """
        SELECT threshold_pct, cross_encoder_model
        FROM step5_session_shortlist
        WHERE chat_session_id = ?
        LIMIT 1
        """,
        (chat_session_id,),
    ).fetchone()
    if row is None:
        return (None, None)
    tp = int(row["threshold_pct"]) if row["threshold_pct"] is not None else None
    m = str(row["cross_encoder_model"]) if row["cross_encoder_model"] else None
    return (tp, m)


def delete_step5_synthesis_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> int:
    cur = conn.execute(
        "DELETE FROM step5_synthesis_runs WHERE chat_session_id = ?",
        (chat_session_id,),
    )
    conn.commit()
    return cur.rowcount


def insert_step5_manifest(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    find_match_id: int,
    bot1_topic_id: int | None,
    bot1_connotation_id: int | None,
    surah_no: int,
    ayah_no: int,
    verse_text: str,
    manifest_json: str,
    total_combos: int,
    cross_encoder_relevance: float | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO step5_verse_manifests (
            run_id, find_match_id, surah_no, ayah_no, bot1_topic_id, bot1_connotation_id,
            verse_text, manifest_json, total_combos, cross_encoder_relevance
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, find_match_id) DO UPDATE SET
            bot1_topic_id = excluded.bot1_topic_id,
            bot1_connotation_id = excluded.bot1_connotation_id,
            verse_text = excluded.verse_text,
            manifest_json = excluded.manifest_json,
            total_combos = excluded.total_combos,
            cross_encoder_relevance = excluded.cross_encoder_relevance
        """,
        (
            run_id,
            find_match_id,
            surah_no,
            ayah_no,
            bot1_topic_id,
            bot1_connotation_id,
            verse_text,
            manifest_json,
            int(total_combos),
            float(cross_encoder_relevance) if cross_encoder_relevance is not None else None,
        ),
    )
    if cur.lastrowid:
        mid = int(cur.lastrowid)
    else:
        row = conn.execute(
            """
            SELECT id
            FROM step5_verse_manifests
            WHERE run_id = ? AND find_match_id = ?
            """,
            (run_id, find_match_id),
        ).fetchone()
        if row is None:
            raise ValueError("Failed to upsert step5_verse_manifests row.")
        mid = int(row["id"])
    conn.commit()
    return mid


def bulk_seed_step5_jobs_for_run(conn: sqlite3.Connection, run_id: int) -> int:
    """Insert one queued job row per combo for every manifest in the run (before workers start).

    Workers use INSERT ... ON CONFLICT DO UPDATE, so pre-seeded rows become visible immediately
    in the request log while status is still ``queued``.
    """
    from src.chat.step5_engine import combo_to_json, manifest_from_json, ordinal_to_combo

    mrows = conn.execute(
        """
        SELECT id AS manifest_id, manifest_json, total_combos
        FROM step5_verse_manifests
        WHERE run_id = ?
        ORDER BY id
        """,
        (int(run_id),),
    ).fetchall()
    batch: list[tuple[int, int, str]] = []
    for r in mrows:
        mid = int(r["manifest_id"])
        total = int(r["total_combos"])
        if total <= 0:
            continue
        manifest = manifest_from_json(str(r["manifest_json"] or "[]"))
        if not manifest.units:
            continue
        counts = [len(u.entries) for u in manifest.units]
        for ord_no in range(1, total + 1):
            combo = ordinal_to_combo(ord_no, counts)
            ecj = combo_to_json(manifest, combo)
            batch.append((mid, ord_no, ecj))
    if batch:
        chunk = 400
        for i in range(0, len(batch), chunk):
            conn.executemany(
                """
                INSERT INTO step5_synthesis_jobs (
                    manifest_id, combo_ordinal, entry_combo_json, status, attempt_count, llm_call_state
                )
                VALUES (?, ?, ?, 'in_progress', 1, 'queued')
                ON CONFLICT(manifest_id, combo_ordinal) DO NOTHING
                """,
                batch[i : i + chunk],
            )
        conn.commit()
    return len(batch)


def claim_next_manifest_batch(
    conn: sqlite3.Connection, run_id: int, *, batch_size: int
) -> ClaimedManifestBatch | None:
    n = max(1, int(batch_size))
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """
            SELECT
                m.id AS manifest_id,
                m.run_id AS run_id,
                m.find_match_id AS find_match_id,
                m.bot1_topic_id AS bot1_topic_id,
                m.bot1_connotation_id AS bot1_connotation_id,
                m.surah_no AS surah_no,
                m.ayah_no AS ayah_no,
                m.verse_text AS verse_text,
                m.manifest_json AS manifest_json,
                m.total_combos AS total_combos,
                m.next_ordinal AS next_ordinal,
                t.topic_text AS topic_text,
                c.connotation_text AS connotation_text
            FROM step5_verse_manifests m
            LEFT JOIN bot1_topics t ON t.id = m.bot1_topic_id
            LEFT JOIN bot1_connotations c ON c.id = m.bot1_connotation_id
            WHERE m.run_id = ? AND m.next_ordinal < m.total_combos
            ORDER BY m.id ASC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        start = int(row["next_ordinal"])
        total = int(row["total_combos"])
        end = min(total, start + n)
        conn.execute(
            """
            UPDATE step5_verse_manifests
            SET next_ordinal = ?
            WHERE id = ?
            """,
            (end, int(row["manifest_id"])),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Ordinals are 1..total to match bulk_seed_step5_jobs_for_run and ordinal_to_combo.
    ordinals = tuple(range(start + 1, end + 1)) if end > start else ()
    return ClaimedManifestBatch(
        manifest_id=int(row["manifest_id"]),
        run_id=int(row["run_id"]),
        find_match_id=int(row["find_match_id"]),
        bot1_topic_id=int(row["bot1_topic_id"]) if row["bot1_topic_id"] is not None else None,
        bot1_connotation_id=(
            int(row["bot1_connotation_id"])
            if row["bot1_connotation_id"] is not None
            else None
        ),
        topic_text=str(row["topic_text"] or ""),
        connotation_text=str(row["connotation_text"] or ""),
        surah_no=int(row["surah_no"]),
        ayah_no=int(row["ayah_no"]),
        verse_text=str(row["verse_text"] or ""),
        manifest_json=str(row["manifest_json"] or "[]"),
        total_combos=total,
        ordinals=ordinals,
    )


def list_retry_jobs_ready(
    conn: sqlite3.Connection, run_id: int, *, max_rows: int = 20
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            j.id AS job_id,
            j.manifest_id AS manifest_id,
            j.combo_ordinal AS combo_ordinal,
            j.entry_combo_json AS entry_combo_json,
            j.attempt_count AS attempt_count,
            m.run_id AS run_id,
            m.find_match_id AS find_match_id,
            m.bot1_topic_id AS bot1_topic_id,
            m.bot1_connotation_id AS bot1_connotation_id,
            m.surah_no AS surah_no,
            m.ayah_no AS ayah_no,
            m.verse_text AS verse_text,
            m.manifest_json AS manifest_json,
            t.topic_text AS topic_text,
            c.connotation_text AS connotation_text
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        LEFT JOIN bot1_topics t ON t.id = m.bot1_topic_id
        LEFT JOIN bot1_connotations c ON c.id = m.bot1_connotation_id
        WHERE m.run_id = ?
          AND j.status = 'waiting_retry'
          AND COALESCE(j.next_attempt_at, datetime('now')) <= datetime('now')
        ORDER BY j.next_attempt_at ASC, j.id ASC
        LIMIT ?
        """,
        (run_id, max(1, int(max_rows))),
    ).fetchall()


def insert_or_mark_job_in_progress(
    conn: sqlite3.Connection,
    *,
    manifest_id: int,
    combo_ordinal: int,
    entry_combo_json: str,
    increment_attempt: bool = False,
) -> tuple[int, int]:
    conn.execute(
        """
        INSERT INTO step5_synthesis_jobs (
            manifest_id, combo_ordinal, entry_combo_json, status, attempt_count
        )
        VALUES (?, ?, ?, 'in_progress', 1)
        ON CONFLICT(manifest_id, combo_ordinal) DO UPDATE SET
            entry_combo_json = excluded.entry_combo_json,
            status = 'in_progress',
            user_payload_json = NULL,
            llm_call_state = 'building',
            attempt_count = CASE
                WHEN ? THEN step5_synthesis_jobs.attempt_count + 1
                ELSE step5_synthesis_jobs.attempt_count
            END,
            next_attempt_at = NULL,
            error_code = NULL,
            error_message = NULL,
            updated_at = datetime('now')
        """,
        (manifest_id, combo_ordinal, entry_combo_json, 1 if increment_attempt else 0),
    )
    row = conn.execute(
        """
        SELECT id, attempt_count
        FROM step5_synthesis_jobs
        WHERE manifest_id = ? AND combo_ordinal = ?
        """,
        (manifest_id, combo_ordinal),
    ).fetchone()
    if row is None:
        raise ValueError("Unable to resolve step5_synthesis_jobs row id.")
    conn.commit()
    return int(row["id"]), int(row["attempt_count"])


def set_step5_job_user_payload(
    conn: sqlite3.Connection, job_id: int, user_payload_json: str
) -> None:
    conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET user_payload_json = ?,
            llm_call_state = 'ready',
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (user_payload_json, int(job_id)),
    )
    conn.commit()


def set_step5_job_llm_call_state(
    conn: sqlite3.Connection, job_id: int, state: str | None
) -> None:
    conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET llm_call_state = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (state, int(job_id)),
    )
    conn.commit()


def mark_job_waiting_retry(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    error_code: str,
    error_message: str,
    wait_minutes: int = 5,
) -> None:
    conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET status = 'waiting_retry',
            next_attempt_at = datetime('now', ?),
            error_code = ?,
            error_message = ?,
            llm_call_state = NULL,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (f"+{max(1, int(wait_minutes))} minutes", error_code, error_message, job_id),
    )
    conn.commit()


def mark_job_failed(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    manifest_id: int,
    error_code: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET status = 'failed',
            error_code = ?,
            error_message = ?,
            llm_call_state = NULL,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (error_code, error_message, job_id),
    )
    conn.execute(
        """
        UPDATE step5_verse_manifests
        SET failed_count = failed_count + 1
        WHERE id = ?
        """,
        (manifest_id,),
    )
    conn.commit()


def mark_job_done(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    manifest_id: int,
) -> None:
    conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET status = 'done',
            llm_call_state = NULL,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (job_id,),
    )
    conn.execute(
        """
        UPDATE step5_verse_manifests
        SET completed_count = completed_count + 1
        WHERE id = ?
        """,
        (manifest_id,),
    )
    conn.commit()


def insert_step5_result(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    chat_session_id: str,
    run_id: int,
    manifest_id: int,
    find_match_id: int,
    surah_no: int,
    ayah_no: int,
    bot1_topic_id: int | None,
    bot1_connotation_id: int | None,
    entry_combo_json: str,
    verse_text: str,
    context_json: str,
    user_payload_json: str,
    response_obj: dict[str, object] | None,
    possibility_score: int | None,
    exegesis: str | None,
    symbolic_reasoning: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    cost_usd: float | None,
    raw_response_text: str | None,
    provider: str,
    model: str,
) -> None:
    conn.execute(
        """
        INSERT INTO step5_synthesis_results (
            job_id, chat_session_id, run_id, manifest_id, find_match_id,
            surah_no, ayah_no, bot1_topic_id, bot1_connotation_id,
            entry_combo_json, verse_text, context_json, user_payload_json, response_json,
            possibility_score, exegesis, symbolic_reasoning,
            prompt_tokens, completion_tokens, total_tokens, cost_usd,
            raw_response_text, provider, model
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            response_json = excluded.response_json,
            possibility_score = excluded.possibility_score,
            exegesis = excluded.exegesis,
            symbolic_reasoning = excluded.symbolic_reasoning,
            prompt_tokens = excluded.prompt_tokens,
            completion_tokens = excluded.completion_tokens,
            total_tokens = excluded.total_tokens,
            cost_usd = excluded.cost_usd,
            raw_response_text = excluded.raw_response_text,
            provider = excluded.provider,
            model = excluded.model
        """,
        (
            job_id,
            chat_session_id,
            run_id,
            manifest_id,
            find_match_id,
            surah_no,
            ayah_no,
            bot1_topic_id,
            bot1_connotation_id,
            entry_combo_json,
            verse_text,
            context_json,
            user_payload_json,
            json.dumps(response_obj, ensure_ascii=False) if response_obj is not None else None,
            possibility_score,
            exegesis,
            symbolic_reasoning,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost_usd,
            raw_response_text,
            provider,
            model,
        ),
    )
    conn.commit()


def reset_stale_step5_in_progress_jobs(conn: sqlite3.Connection, run_id: int) -> int:
    """
    Mark Step 5 jobs stuck in ``in_progress`` (e.g. after app crash) as ``waiting_retry``
    so the orchestrator can pick them up again.
    """
    cur = conn.execute(
        """
        UPDATE step5_synthesis_jobs
        SET status = 'waiting_retry',
            next_attempt_at = datetime('now'),
            error_code = 'recovered_after_interrupt',
            error_message = 'Reset from in_progress (resume or reconnect).',
            user_payload_json = NULL,
            llm_call_state = NULL,
            updated_at = datetime('now')
        WHERE status = 'in_progress'
          AND manifest_id IN (
              SELECT id FROM step5_verse_manifests WHERE run_id = ?
          )
        """,
        (int(run_id),),
    )
    conn.commit()
    return int(cur.rowcount or 0)


def step5_run_is_resumable(conn: sqlite3.Connection, run_id: int) -> bool:
    """True if this run was not cancelled and the job queue still has unfinished work."""
    row = conn.execute(
        "SELECT cancelled_at FROM step5_synthesis_runs WHERE id = ?",
        (int(run_id),),
    ).fetchone()
    if row is None or row["cancelled_at"]:
        return False
    stats = fetch_step5_request_stats(conn, run_id)
    if stats.total_requests <= 0:
        return False
    if stats.in_progress > 0:
        return True
    if stats.waiting_retry > 0:
        return True
    finished = stats.done + stats.failed + stats.cancelled
    return finished < stats.total_requests


def fetch_step5_progress(conn: sqlite3.Connection, run_id: int) -> Step5Progress:
    m = conn.execute(
        """
        SELECT
            COALESCE(SUM(total_combos), 0) AS total_jobs,
            COALESCE(SUM(next_ordinal), 0) AS dispatched,
            COALESCE(SUM(completed_count), 0) AS completed,
            COALESCE(SUM(failed_count), 0) AS failed
        FROM step5_verse_manifests
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    j = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'waiting_retry' THEN 1 ELSE 0 END), 0) AS waiting_retry
        FROM step5_synthesis_jobs
        WHERE manifest_id IN (
            SELECT id FROM step5_verse_manifests WHERE run_id = ?
        )
        """,
        (run_id,),
    ).fetchone()
    c = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0.0) AS cost_sum
        FROM step5_synthesis_results
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    r = conn.execute(
        "SELECT cancelled_at FROM step5_synthesis_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return Step5Progress(
        total_jobs=int(m["total_jobs"] if m else 0),
        dispatched=int(m["dispatched"] if m else 0),
        completed=int(m["completed"] if m else 0),
        failed=int(m["failed"] if m else 0),
        waiting_retry=int(j["waiting_retry"] if j else 0),
        cost_usd=float(c["cost_sum"] if c else 0.0),
        is_cancelled=bool(r and r["cancelled_at"]),
    )


def fetch_step5_request_stats(conn: sqlite3.Connection, run_id: int) -> Step5RequestStats:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END), 0) AS done_n,
            COALESCE(SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_n,
            COALESCE(SUM(CASE WHEN j.status = 'in_progress' THEN 1 ELSE 0 END), 0) AS inprog_n,
            COALESCE(SUM(CASE WHEN j.status = 'waiting_retry' THEN 1 ELSE 0 END), 0) AS retry_n,
            COALESCE(SUM(CASE WHEN j.status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_n
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        WHERE m.run_id = ?
        """,
        (int(run_id),),
    ).fetchone()
    if row is None:
        return Step5RequestStats(0, 0, 0, 0, 0, 0)
    return Step5RequestStats(
        total_requests=int(row["total"] or 0),
        done=int(row["done_n"] or 0),
        failed=int(row["failed_n"] or 0),
        in_progress=int(row["inprog_n"] or 0),
        waiting_retry=int(row["retry_n"] or 0),
        cancelled=int(row["cancelled_n"] or 0),
    )


def fetch_step5_run_analytics(conn: sqlite3.Connection, run_id: int) -> Step5RunAnalytics:
    """Full-run aggregates from saved synthesis results plus failed-job error breakdown."""
    rid = int(run_id)
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS n,
            COUNT(DISTINCT printf('%d:%d', surah_no, ayah_no)) AS n_verse,
            COALESCE(SUM(COALESCE(prompt_tokens, 0)), 0) AS sp,
            COALESCE(SUM(COALESCE(completion_tokens, 0)), 0) AS sc,
            COALESCE(SUM(COALESCE(total_tokens, 0)), 0) AS st,
            COALESCE(SUM(COALESCE(cost_usd, 0.0)), 0.0) AS cost,
            COALESCE(SUM(CASE WHEN possibility_score IS NOT NULL THEN 1 ELSE 0 END), 0) AS wsc,
            COALESCE(SUM(CASE WHEN possibility_score IS NULL THEN 1 ELSE 0 END), 0) AS wosc
        FROM step5_synthesis_results
        WHERE run_id = ?
        """,
        (rid,),
    ).fetchone()
    n = int(row["n"] or 0) if row else 0
    n_verse = int(row["n_verse"] or 0) if row else 0
    sp = int(row["sp"] or 0) if row else 0
    sc = int(row["sc"] or 0) if row else 0
    st = int(row["st"] or 0) if row else 0
    cost = float(row["cost"] or 0.0) if row else 0.0
    wsc = int(row["wsc"] or 0) if row else 0
    wosc = int(row["wosc"] or 0) if row else 0

    score_avg: float | None = None
    score_min: int | None = None
    score_max: int | None = None
    if wsc > 0:
        r2 = conn.execute(
            """
            SELECT
                AVG(possibility_score) AS av,
                MIN(possibility_score) AS mi,
                MAX(possibility_score) AS ma
            FROM step5_synthesis_results
            WHERE run_id = ? AND possibility_score IS NOT NULL
            """,
            (rid,),
        ).fetchone()
        if r2 is not None:
            if r2["av"] is not None:
                score_avg = float(r2["av"])
            if r2["mi"] is not None:
                score_min = int(r2["mi"])
            if r2["ma"] is not None:
                score_max = int(r2["ma"])

    hrows = conn.execute(
        """
        SELECT possibility_score AS sc, COUNT(*) AS c
        FROM step5_synthesis_results
        WHERE run_id = ? AND possibility_score IS NOT NULL
        GROUP BY possibility_score
        ORDER BY sc
        """,
        (rid,),
    ).fetchall()
    score_histogram = tuple((int(r["sc"]), int(r["c"])) for r in hrows)

    erows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(j.error_code), ''), '(none)') AS ec, COUNT(*) AS c
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        WHERE m.run_id = ? AND j.status = 'failed'
        GROUP BY ec
        ORDER BY c DESC, ec ASC
        """,
        (rid,),
    ).fetchall()
    failed_jobs_by_error = tuple((str(r["ec"]), int(r["c"])) for r in erows)

    return Step5RunAnalytics(
        result_count=n,
        distinct_verse_count=n_verse,
        sum_prompt_tokens=sp,
        sum_completion_tokens=sc,
        sum_total_tokens=st,
        total_cost_usd=cost,
        with_score_count=wsc,
        without_score_count=wosc,
        score_avg=score_avg,
        score_min=score_min,
        score_max=score_max,
        score_histogram=score_histogram,
        failed_jobs_by_error=failed_jobs_by_error,
    )


def fetch_step5_run_models_and_split_cost(
    conn: sqlite3.Connection, run_id: int
) -> tuple[float, float, str]:
    """Approximate input/output USD from token counts × list prices; models as distinct provider/model."""
    from src.chat.llm_pricing import split_cost_usd

    rid = int(run_id)
    mrows = conn.execute(
        """
        SELECT DISTINCT TRIM(COALESCE(provider, '')) AS p, TRIM(COALESCE(model, '')) AS m
        FROM step5_synthesis_results
        WHERE run_id = ? AND TRIM(COALESCE(model, '')) != ''
        ORDER BY p, m
        """,
        (rid,),
    ).fetchall()
    models_l = [f"{r['p']}/{r['m']}" for r in mrows if r["m"]]
    models_label = ", ".join(models_l) if models_l else "(see Step 5 results)"

    drows = conn.execute(
        """
        SELECT provider, model, prompt_tokens, completion_tokens
        FROM step5_synthesis_results
        WHERE run_id = ?
        """,
        (rid,),
    ).fetchall()
    cin = 0.0
    cout = 0.0
    for r in drows:
        a, b, _ = split_cost_usd(
            str(r["provider"] or ""),
            str(r["model"] or ""),
            prompt_tokens=int(r["prompt_tokens"] or 0),
            completion_tokens=int(r["completion_tokens"] or 0),
        )
        cin += a
        cout += b
    return cin, cout, models_label


def insert_step5_run_stats_snapshot(
    conn: sqlite3.Connection, *, run_id: int, stats_json: str
) -> int:
    cur = conn.execute(
        """
        INSERT INTO step5_run_stats_snapshots (run_id, stats_json)
        VALUES (?, ?)
        """,
        (int(run_id), stats_json),
    )
    conn.commit()
    return int(cur.lastrowid)


def fetch_step5_results_for_run(
    conn: sqlite3.Connection, run_id: int, *, limit: int = 250
) -> list[Step5ResultListRow]:
    rows = conn.execute(
        """
        SELECT
            r.id AS result_id,
            r.job_id AS job_id,
            r.run_id AS run_id,
            r.manifest_id AS manifest_id,
            r.find_match_id AS find_match_id,
            r.surah_no AS surah_no,
            r.ayah_no AS ayah_no,
            r.possibility_score AS possibility_score,
            r.prompt_tokens AS prompt_tokens,
            r.completion_tokens AS completion_tokens,
            r.total_tokens AS total_tokens,
            r.cost_usd AS cost_usd,
            r.provider AS provider,
            r.model AS model,
            r.created_at AS created_at
        FROM step5_synthesis_results r
        WHERE r.run_id = ?
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (run_id, max(1, int(limit))),
    ).fetchall()
    return [
        Step5ResultListRow(
            result_id=int(r["result_id"]),
            job_id=int(r["job_id"]),
            run_id=int(r["run_id"]),
            manifest_id=int(r["manifest_id"]),
            find_match_id=int(r["find_match_id"]),
            surah_no=int(r["surah_no"]),
            ayah_no=int(r["ayah_no"]),
            possibility_score=(
                int(r["possibility_score"]) if r["possibility_score"] is not None else None
            ),
            prompt_tokens=int(r["prompt_tokens"]) if r["prompt_tokens"] is not None else None,
            completion_tokens=(
                int(r["completion_tokens"]) if r["completion_tokens"] is not None else None
            ),
            total_tokens=int(r["total_tokens"]) if r["total_tokens"] is not None else None,
            cost_usd=float(r["cost_usd"]) if r["cost_usd"] is not None else None,
            provider=str(r["provider"] or ""),
            model=str(r["model"] or ""),
            created_at=str(r["created_at"] or ""),
        )
        for r in rows
    ]


def fetch_step5_request_log_for_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    limit: int = 500,
    heavy_text_max_chars: int | None = 512,
    recent_tail: bool = False,
) -> list[Step5RequestLogRow]:
    """Load rows for the Step 5 «LLM API calls» tree.

    ``heavy_text_max_chars`` caps payload/response columns in SQL so refreshes do not
    pull multi-megabyte strings for every row (full text loads on row select via
    ``fetch_step5_job_llm_detail``). Set to ``None`` only when callers need complete
    strings in-memory for every job.

    When ``recent_tail`` is True, returns the last ``limit`` jobs (by id) in ascending
    order for display — useful while a large run is in progress.
    """
    cap = int(heavy_text_max_chars) if heavy_text_max_chars is not None else 0
    lim = max(1, int(limit))
    if cap > 0:
        sel_payload = (
            "SUBSTR(COALESCE(NULLIF(r.user_payload_json, ''), j.user_payload_json), 1, ?) "
            "AS user_payload_json"
        )
        sel_raw = "SUBSTR(COALESCE(r.raw_response_text, ''), 1, ?) AS raw_response_text"
        sel_rj = "SUBSTR(COALESCE(r.response_json, ''), 1, ?) AS response_json"
        order_clause = "ORDER BY j.id DESC LIMIT ?" if recent_tail else "ORDER BY j.id ASC LIMIT ?"
        sql = f"""
        SELECT
            j.id AS job_id,
            j.status AS job_status,
            j.error_code AS error_code,
            j.error_message AS error_message,
            j.llm_call_state AS llm_call_state,
            r.id AS result_id,
            {sel_payload},
            {sel_raw},
            {sel_rj},
            m.surah_no AS surah_no,
            m.ayah_no AS ayah_no
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        LEFT JOIN step5_synthesis_results r ON r.job_id = j.id
        WHERE m.run_id = ?
        {order_clause}
        """
        params: tuple[int, ...] = (cap, cap, cap, int(run_id), lim)
        rows = conn.execute(sql, params).fetchall()
        if recent_tail:
            rows = list(reversed(rows))
    else:
        order_clause = "ORDER BY j.id DESC LIMIT ?" if recent_tail else "ORDER BY j.id ASC LIMIT ?"
        sql = f"""
        SELECT
            j.id AS job_id,
            j.status AS job_status,
            j.error_code AS error_code,
            j.error_message AS error_message,
            j.llm_call_state AS llm_call_state,
            r.id AS result_id,
            COALESCE(NULLIF(r.user_payload_json, ''), j.user_payload_json) AS user_payload_json,
            r.raw_response_text AS raw_response_text,
            r.response_json AS response_json,
            m.surah_no AS surah_no,
            m.ayah_no AS ayah_no
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        LEFT JOIN step5_synthesis_results r ON r.job_id = j.id
        WHERE m.run_id = ?
        {order_clause}
        """
        rows = conn.execute(sql, (int(run_id), lim)).fetchall()
        if recent_tail:
            rows = list(reversed(rows))
    out: list[Step5RequestLogRow] = []
    for r in rows:
        rid = int(r["result_id"]) if r["result_id"] is not None else None
        has_res = rid is not None
        status_label = _step5_request_log_status(str(r["job_status"] or ""), has_res)
        payload = str(r["user_payload_json"] or "") if r["user_payload_json"] else ""
        has_payload = bool(payload.strip())
        lc_raw = r["llm_call_state"]
        llm_state = str(lc_raw).strip() if lc_raw is not None and str(lc_raw).strip() else None
        progress_label = _step5_request_log_progress(
            str(r["job_status"] or ""),
            has_res,
            llm_state,
            has_payload,
        )
        raw = str(r["raw_response_text"] or "") if r["raw_response_text"] else ""
        rj = str(r["response_json"] or "") if r["response_json"] else ""
        err = str(r["error_message"] or "") if r["error_message"] else ""
        code = str(r["error_code"] or "") if r["error_code"] else ""
        if raw:
            resp_prev = _step5_one_line_preview(raw)
        elif rj:
            resp_prev = _step5_one_line_preview(rj)
        elif err or code:
            resp_prev = _step5_one_line_preview(
                f"{code}: {err}".strip(": ").strip() or err or code or "error"
            )
        else:
            resp_prev = "—"
        req_prev = _step5_one_line_preview(payload) if payload else "—"
        out.append(
            Step5RequestLogRow(
                job_id=int(r["job_id"]),
                result_id=rid,
                surah_no=int(r["surah_no"]),
                ayah_no=int(r["ayah_no"]),
                status_label=status_label,
                progress_label=progress_label,
                request_preview=req_prev,
                response_preview=resp_prev,
            )
        )
    return out


def fetch_step5_job_llm_detail(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            j.id AS job_id,
            j.status AS job_status,
            j.error_code AS error_code,
            j.error_message AS error_message,
            j.attempt_count AS attempt_count,
            j.llm_call_state AS llm_call_state,
            r.id AS result_id,
            COALESCE(NULLIF(r.user_payload_json, ''), j.user_payload_json) AS user_payload_json,
            r.raw_response_text AS raw_response_text,
            r.response_json AS response_json,
            m.surah_no AS surah_no,
            m.ayah_no AS ayah_no
        FROM step5_synthesis_jobs j
        JOIN step5_verse_manifests m ON m.id = j.manifest_id
        LEFT JOIN step5_synthesis_results r ON r.job_id = j.id
        WHERE j.id = ?
        """,
        (int(job_id),),
    ).fetchone()


def fetch_step5_result_detail(
    conn: sqlite3.Connection, result_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            r.*,
            m.bot1_topic_id AS manifest_topic_id,
            m.bot1_connotation_id AS manifest_connotation_id,
            m.cross_encoder_relevance AS cross_encoder_relevance,
            t.topic_text AS topic_text,
            c.connotation_text AS connotation_text
        FROM step5_synthesis_results r
        LEFT JOIN step5_verse_manifests m ON m.id = r.manifest_id
        LEFT JOIN bot1_topics t ON t.id = m.bot1_topic_id
        LEFT JOIN bot1_connotations c ON c.id = m.bot1_connotation_id
        WHERE r.id = ?
        """,
        (result_id,),
    ).fetchone()
