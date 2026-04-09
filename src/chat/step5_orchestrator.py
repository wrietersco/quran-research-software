"""Background Step 5 job orchestrator."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.chat.llm_provider import (
    LlmProviderConfig,
    call_chat_completion,
)
from src.chat.step5_engine import (
    LOADED_ALL_ENTRIES_COMBO_JSON,
    Step5Manifest,
    build_payload,
    build_payload_all_entries,
    combo_to_json,
    is_loaded_all_entries_combo_json,
    manifest_from_json,
    ordinal_to_combo,
    parse_step5_response_json,
    truncate_payload_for_tokens,
)
from src.db.connection import connect
from src.db.step5_synthesis import (
    Step5Progress,
    claim_next_manifest_batch,
    fetch_step5_progress,
    insert_or_mark_job_in_progress,
    insert_step5_result,
    list_retry_jobs_ready,
    mark_job_done,
    mark_job_failed,
    mark_job_waiting_retry,
    set_step5_job_llm_call_state,
    set_step5_job_user_payload,
)


@dataclass(frozen=True)
class Step5Task:
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
    manifest: Step5Manifest
    combo_ordinal: int
    combo: tuple[int, ...]
    is_retry: bool
    all_entries: bool = False


class Step5Orchestrator:
    def __init__(
        self,
        *,
        db_path: Path,
        run_id: int,
        chat_session_id: str,
        question_text: str,
        provider_cfg: LlmProviderConfig,
        system_prompt: str,
        max_workers: int = 2,
        batch_size: int = 20,
        cancel_event: threading.Event | None = None,
        on_status: Callable[[str], None] | None = None,
        on_after_job_db_write: Callable[[], None] | None = None,
        synthesis_mode: str = "combination",
    ) -> None:
        self._db_path = db_path
        self._run_id = int(run_id)
        self._chat_session_id = chat_session_id
        self._question_text = question_text
        self._provider_cfg = provider_cfg
        self._system_prompt = system_prompt
        sm = (synthesis_mode or "combination").strip().lower()
        self._synthesis_mode = sm if sm in {"combination", "loaded"} else "combination"
        self._max_workers = max(1, int(max_workers))
        self._batch_size = max(1, int(batch_size))
        self._cancel = cancel_event or threading.Event()
        self._on_status = on_status
        self._on_after_job_db_write = on_after_job_db_write
        self._thread: threading.Thread | None = None
        self._rpm_lock = threading.Lock()
        self._recent_calls: deque[float] = deque(maxlen=max(1, provider_cfg.rpm_limit))
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def get_progress(self) -> Step5Progress:
        conn = connect(self._db_path)
        try:
            return fetch_step5_progress(conn, self._run_id)
        finally:
            conn.close()

    def _emit(self, msg: str) -> None:
        cb = self._on_status
        if cb:
            cb(msg)

    def _bounded_process_task(self, sem: threading.Semaphore, task: Step5Task) -> None:
        """Run one task; release semaphore slot always (daemon thread)."""
        try:
            self._process_task(task)
        finally:
            sem.release()

    def _run(self) -> None:
        # Daemon workers + semaphore (not ThreadPoolExecutor): the stdlib executor
        # registers non-daemon threads and atexit joins that fight Ctrl+C / Tk exit.
        sem = threading.Semaphore(self._max_workers)
        try:
            while not self._cancel.is_set():
                tasks = self._next_tasks()
                if not tasks:
                    p = self.get_progress()
                    if p.total_jobs > 0 and p.completed + p.failed >= p.total_jobs:
                        break
                    if p.waiting_retry > 0:
                        time.sleep(1.0)
                        continue
                    if p.dispatched >= p.total_jobs:
                        break
                    time.sleep(0.2)
                    continue
                threads: list[threading.Thread] = []
                for t in tasks:
                    sem.acquire()
                    th = threading.Thread(
                        target=self._bounded_process_task,
                        args=(sem, t),
                        daemon=True,
                        name="step5-worker",
                    )
                    th.start()
                    threads.append(th)
                for th in threads:
                    th.join()
                if self._cancel.is_set():
                    break
        finally:
            self._running = False

    def _next_tasks(self) -> list[Step5Task]:
        conn = connect(self._db_path)
        try:
            retry_rows = list_retry_jobs_ready(conn, self._run_id, max_rows=self._batch_size)
            if retry_rows:
                out: list[Step5Task] = []
                for r in retry_rows:
                    manifest = manifest_from_json(str(r["manifest_json"] or "[]"))
                    if not manifest.units:
                        continue
                    ecj = str(r["entry_combo_json"] or "[]")
                    if is_loaded_all_entries_combo_json(ecj):
                        combo = tuple(1 for _ in manifest.units)
                        all_entries = True
                    else:
                        combo = self._combo_from_entry_combo_json(ecj)
                        if not combo:
                            continue
                        all_entries = False
                    out.append(
                        Step5Task(
                            manifest_id=int(r["manifest_id"]),
                            run_id=int(r["run_id"]),
                            find_match_id=int(r["find_match_id"]),
                            bot1_topic_id=(
                                int(r["bot1_topic_id"])
                                if r["bot1_topic_id"] is not None
                                else None
                            ),
                            bot1_connotation_id=(
                                int(r["bot1_connotation_id"])
                                if r["bot1_connotation_id"] is not None
                                else None
                            ),
                            topic_text=str(r["topic_text"] or ""),
                            connotation_text=str(r["connotation_text"] or ""),
                            surah_no=int(r["surah_no"]),
                            ayah_no=int(r["ayah_no"]),
                            verse_text=str(r["verse_text"] or ""),
                            manifest=manifest,
                            combo_ordinal=int(r["combo_ordinal"]),
                            combo=combo,
                            is_retry=True,
                            all_entries=all_entries,
                        )
                    )
                if out:
                    return out

            batch = claim_next_manifest_batch(conn, self._run_id, batch_size=self._batch_size)
            if batch is None or not batch.ordinals:
                return []
            manifest = manifest_from_json(batch.manifest_json)
            if not manifest.units:
                return []
            counts = [len(u.entries) for u in manifest.units]
            all_entries = self._synthesis_mode == "loaded"
            out2: list[Step5Task] = []
            for ord_no in batch.ordinals:
                combo = ordinal_to_combo(ord_no, counts)
                out2.append(
                    Step5Task(
                        manifest_id=batch.manifest_id,
                        run_id=batch.run_id,
                        find_match_id=batch.find_match_id,
                        bot1_topic_id=batch.bot1_topic_id,
                        bot1_connotation_id=batch.bot1_connotation_id,
                        topic_text=batch.topic_text,
                        connotation_text=batch.connotation_text,
                        surah_no=batch.surah_no,
                        ayah_no=batch.ayah_no,
                        verse_text=batch.verse_text,
                        manifest=manifest,
                        combo_ordinal=int(ord_no),
                        combo=combo,
                        is_retry=False,
                        all_entries=all_entries,
                    )
                )
            return out2
        finally:
            conn.close()

    @staticmethod
    def _combo_from_entry_combo_json(raw: str) -> tuple[int, ...]:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        if not isinstance(obj, list):
            return ()
        out: list[int] = []
        for x in obj:
            if not isinstance(x, dict):
                continue
            try:
                out.append(max(1, int(x.get("entry_pick", 1))))
            except (TypeError, ValueError):
                out.append(1)
        return tuple(out)

    def _set_job_llm_phase(self, job_id: int, phase: str | None) -> None:
        c = connect(self._db_path)
        try:
            set_step5_job_llm_call_state(c, job_id, phase)
        finally:
            c.close()
        self._notify_db()

    def _notify_db(self) -> None:
        cb = self._on_after_job_db_write
        if cb:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def _wait_rpm_slot(self) -> None:
        with self._rpm_lock:
            max_calls = max(1, int(self._provider_cfg.rpm_limit))
            now = time.time()
            if len(self._recent_calls) >= max_calls:
                head = self._recent_calls[0]
                delta = now - head
                if delta < 60.0:
                    time.sleep(60.0 - delta)
            self._recent_calls.append(time.time())

    def _process_task(self, task: Step5Task) -> None:
        conn = connect(self._db_path)
        try:
            entry_combo_json = (
                LOADED_ALL_ENTRIES_COMBO_JSON
                if task.all_entries
                else combo_to_json(task.manifest, task.combo)
            )
            job_id, _attempt = insert_or_mark_job_in_progress(
                conn,
                manifest_id=task.manifest_id,
                combo_ordinal=task.combo_ordinal,
                entry_combo_json=entry_combo_json,
                increment_attempt=task.is_retry,
            )
        finally:
            conn.close()

        self._set_job_llm_phase(job_id, "building")

        if task.all_entries:
            payload, context_rows = build_payload_all_entries(
                question=self._question_text,
                topic=task.topic_text,
                connotation=task.connotation_text,
                verse_arabic=task.verse_text,
                manifest=task.manifest,
            )
        else:
            payload, context_rows = build_payload(
                question=self._question_text,
                topic=task.topic_text,
                connotation=task.connotation_text,
                verse_arabic=task.verse_text,
                manifest=task.manifest,
                combo=task.combo,
            )
        payload = truncate_payload_for_tokens(payload, self._provider_cfg.max_input_tokens)
        payload_json = json.dumps(payload, ensure_ascii=False)

        c_payload = connect(self._db_path)
        try:
            set_step5_job_user_payload(c_payload, job_id, payload_json)
        finally:
            c_payload.close()
        self._notify_db()

        try:
            self._wait_rpm_slot()
            self._set_job_llm_phase(job_id, "calling")
            llm = call_chat_completion(
                self._provider_cfg,
                system_prompt=self._system_prompt,
                user_json_payload=payload_json,
            )
            parsed = parse_step5_response_json(llm.text)
            if parsed is None:
                # one immediate retry for parse-noise
                self._set_job_llm_phase(job_id, "ready")
                self._wait_rpm_slot()
                self._set_job_llm_phase(job_id, "calling")
                llm = call_chat_completion(
                    self._provider_cfg,
                    system_prompt=self._system_prompt,
                    user_json_payload=payload_json,
                )
                parsed = parse_step5_response_json(llm.text)
            if parsed is None:
                c2 = connect(self._db_path)
                try:
                    mark_job_failed(
                        c2,
                        job_id=job_id,
                        manifest_id=task.manifest_id,
                        error_code="parse_error",
                        error_message="Model output was not valid JSON after one retry.",
                    )
                finally:
                    c2.close()
                self._notify_db()
                return

            score_raw = parsed.get("possibility_score")
            score_val: int | None
            try:
                score_val = int(score_raw) if score_raw is not None else None
            except (TypeError, ValueError):
                score_val = None
            exeg = parsed.get("exegesis")
            sym = parsed.get("symbolic_reasoning")

            self._set_job_llm_phase(job_id, "saving")

            c3 = connect(self._db_path)
            try:
                insert_step5_result(
                    c3,
                    job_id=job_id,
                    chat_session_id=self._chat_session_id,
                    run_id=task.run_id,
                    manifest_id=task.manifest_id,
                    find_match_id=task.find_match_id,
                    surah_no=task.surah_no,
                    ayah_no=task.ayah_no,
                    bot1_topic_id=task.bot1_topic_id,
                    bot1_connotation_id=task.bot1_connotation_id,
                    entry_combo_json=entry_combo_json,
                    verse_text=task.verse_text,
                    context_json=json.dumps(context_rows, ensure_ascii=False),
                    user_payload_json=payload_json,
                    response_obj=parsed,
                    possibility_score=score_val,
                    exegesis=str(exeg) if exeg is not None else None,
                    symbolic_reasoning=str(sym) if sym is not None else None,
                    prompt_tokens=llm.prompt_tokens,
                    completion_tokens=llm.completion_tokens,
                    total_tokens=llm.total_tokens,
                    cost_usd=llm.cost_usd,
                    raw_response_text=llm.text,
                    provider=self._provider_cfg.provider,
                    model=llm.model,
                )
                mark_job_done(c3, job_id=job_id, manifest_id=task.manifest_id)
            finally:
                c3.close()
            self._notify_db()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            low = msg.lower()
            c4 = connect(self._db_path)
            try:
                if "rate" in low and ("429" in low or "limit" in low):
                    mark_job_waiting_retry(
                        c4,
                        job_id=job_id,
                        error_code="rate_limit",
                        error_message=msg,
                        wait_minutes=5,
                    )
                elif "context" in low and ("length" in low or "token" in low):
                    mark_job_failed(
                        c4,
                        job_id=job_id,
                        manifest_id=task.manifest_id,
                        error_code="context_overflow",
                        error_message=msg,
                    )
                else:
                    mark_job_failed(
                        c4,
                        job_id=job_id,
                        manifest_id=task.manifest_id,
                        error_code="request_error",
                        error_message=msg,
                    )
            finally:
                c4.close()
            self._notify_db()
