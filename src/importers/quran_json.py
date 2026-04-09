"""Import Quran word-by-word JSON into quran_tokens."""

from __future__ import annotations

import json
from pathlib import Path

from ..db.repositories import insert_quran_token
from ..normalize.arabic import normalize_arabic


def _pick(obj: dict, *keys: str):
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def import_quran_words_json(conn, path: Path) -> int:
    """
    Import JSON array of word objects.

    Supported key aliases per object:
    - surah: surah_no, surah, chapter
    - ayah: ayah_no, ayah, verse
    - word: word_no, word, w
    - text: token_uthmani, text, uthmani, word_uthmani
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of word objects")

    count = 0
    for obj in data:
        if not isinstance(obj, dict):
            continue
        surah = _pick(obj, "surah_no", "surah", "chapter")
        ayah = _pick(obj, "ayah_no", "ayah", "verse")
        word = _pick(obj, "word_no", "word", "w")
        text = _pick(obj, "token_uthmani", "text", "uthmani", "word_uthmani")
        if surah is None or ayah is None or word is None or text is None:
            continue
        surah_no = int(surah)
        ayah_no = int(ayah)
        word_no = int(word)
        token_uthmani = str(text).strip()
        token_plain = normalize_arabic(token_uthmani)
        insert_quran_token(conn, surah_no, ayah_no, word_no, token_uthmani, token_plain)
        count += 1
    return count
