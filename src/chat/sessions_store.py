"""Persistent chat sessions for the question refiner (JSON on disk)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ChatSession:
    id: str
    title: str
    created: str
    updated: str
    messages: list[ChatMessage] = field(default_factory=list)


class ChatSessionsStore:
    """Single JSON file: version, order (session ids), sessions dict."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._order: list[str] = []
        self._sessions: dict[str, ChatSession] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if raw.get("version") != 1:
            return
        self._order = list(raw.get("order") or [])
        for sid, blob in (raw.get("sessions") or {}).items():
            msgs = [
                ChatMessage(role=m["role"], content=m["content"])
                for m in blob.get("messages") or []
                if m.get("role") in ("user", "assistant") and "content" in m
            ]
            self._sessions[sid] = ChatSession(
                id=sid,
                title=str(blob.get("title") or "Session"),
                created=str(blob.get("created") or _utc_now_iso()),
                updated=str(blob.get("updated") or _utc_now_iso()),
                messages=msgs,
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": 1,
            "order": list(self._order),
            "sessions": {},
        }
        for sid in self._order:
            s = self._sessions.get(sid)
            if not s:
                continue
            payload["sessions"][sid] = {
                "title": s.title,
                "created": s.created,
                "updated": s.updated,
                "messages": [asdict(m) for m in s.messages],
            }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list_session_ids(self) -> list[str]:
        return list(self._order)

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def new_session(self, title: str | None = None) -> ChatSession:
        sid = str(uuid.uuid4())
        now = _utc_now_iso()
        s = ChatSession(
            id=sid,
            title=title or "New session",
            created=now,
            updated=now,
            messages=[],
        )
        self._sessions[sid] = s
        self._order.insert(0, sid)
        self.save()
        return s

    def delete_session(self, session_id: str) -> None:
        self._order = [x for x in self._order if x != session_id]
        self._sessions.pop(session_id, None)
        self.save()

    def append_message(self, session_id: str, role: str, content: str) -> None:
        s = self._sessions.get(session_id)
        if not s:
            return
        s.messages.append(ChatMessage(role=role, content=content))
        s.updated = _utc_now_iso()
        if s.title == "New session" and role == "user":
            line = content.strip().replace("\n", " ")
            s.title = (line[:48] + "…") if len(line) > 48 else line or "Session"
        self.save()

    def update_title(self, session_id: str, title: str) -> None:
        s = self._sessions.get(session_id)
        if not s:
            return
        s.title = title.strip() or "Session"
        s.updated = _utc_now_iso()
        self.save()
