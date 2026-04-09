"""Step 6 knowledge chunking and small helpers."""

from __future__ import annotations

from pathlib import Path

from src.chat.step6_knowledge_export import (
    MAX_KNOWLEDGE_CHUNK_BYTES,
    _ChunkWriter,
    _append_text_chunked,
    extract_surah_ayah_refs,
)
from src.chat.step6_report_agent import parse_toc_headings


def test_extract_surah_ayah_refs() -> None:
    s = extract_surah_ayah_refs("Citation 2:255 and 114:1 plus bad 999:9999")
    assert (2, 255) in s
    assert (114, 1) in s


def test_parse_toc_headings() -> None:
    md = "# Intro\n## Part A\n# Conclusion\n"
    h = parse_toc_headings(md)
    assert h == [(1, "Intro"), (2, "Part A"), (1, "Conclusion")]


def test_parse_toc_empty_fallback() -> None:
    h = parse_toc_headings("just prose\n")
    assert len(h) == 1 and h[0][1] == "Theological analysis"


def test_chunk_writer_max_utf8(tmp_path: Path) -> None:
    small = 2048
    w = _ChunkWriter(tmp_path, max_bytes=small)
    try:
        # Multi-byte UTF-8 (2 bytes per char)
        _append_text_chunked(w, "é" * 5000)
    finally:
        w.close()
    assert len(w.paths) >= 2
    for p in w.paths:
        assert p.stat().st_size <= small + 16  # slack for line-boundary overshoot splits


def test_single_piece_under_limit(tmp_path: Path) -> None:
    w = _ChunkWriter(tmp_path, max_bytes=MAX_KNOWLEDGE_CHUNK_BYTES)
    try:
        _append_text_chunked(w, "hello\n")
    finally:
        w.close()
    assert len(w.paths) == 1
    assert w.paths[0].read_text(encoding="utf-8") == "hello\n"
