"""
Build the SQLite database: schema, lexicon import, Quran import, mapping.

Run from project root:
    python database.py
    python database.py --truncate-lexicon --skip-mapping
    python database.py --only-corpus-roots   # refresh quran_token_corpus_root from kalimah only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import QURAN_ROOT_JSON, RAW_QURAN_DIR, get_db_path  # noqa: E402
from src.importers.quran_morphology import import_quran_morphology_txt  # noqa: E402
from src.db.connection import connect, init_db  # noqa: E402
from src.db.corpus_roots import populate_quran_token_corpus_roots  # noqa: E402
from src.db.repositories import truncate_lexicon_tables  # noqa: E402
from src.importers.lexicon_json import (  # noqa: E402
    discover_lexicon_json_files,
    import_lexicon_json_file,
)
from src.importers.quran_json import import_quran_words_json  # noqa: E402
from src.importers.quran_root_json import import_quran_root_json  # noqa: E402
from src.mapping.root_mapper import apply_overrides, run_heuristic_mapping  # noqa: E402


def discover_quran_json_files() -> list[Path]:
    """All *.json under data/raw/quran/."""
    if not RAW_QURAN_DIR.exists():
        return []
    return sorted(RAW_QURAN_DIR.glob("*.json"))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create/populate quran_lexicon.db (init, imports, mapping)."
    )
    ap.add_argument(
        "--truncate-lexicon",
        action="store_true",
        help="Delete all lexicon rows before importing JSON",
    )
    ap.add_argument(
        "--replace-entries",
        action="store_true",
        help="Replace lexicon entry rows for roots that already exist",
    )
    ap.add_argument(
        "--skip-quran",
        action="store_true",
        help="Skip Quran import (raw/*.json and root quran.json)",
    )
    ap.add_argument(
        "--skip-root-quran-json",
        action="store_true",
        help="Skip importing project-root quran.json into quran_verses + quran_tokens",
    )
    ap.add_argument(
        "--morphology-file",
        action="append",
        default=None,
        metavar="PATH",
        help=(
            "Tab-separated Quran morphology (kalimat segments). Repeatable. "
            "Default: data/raw/quran/quran-morphology.txt if present, else morphology.example.txt"
        ),
    )
    ap.add_argument(
        "--skip-kalimah",
        action="store_true",
        help="Skip Step 3b morphology import into quran_token_kalimah",
    )
    ap.add_argument(
        "--skip-corpus-roots",
        action="store_true",
        help="Skip building quran_token_corpus_root from kalimah ROOT: tags",
    )
    ap.add_argument(
        "--only-corpus-roots",
        action="store_true",
        help="Only run migrate + populate quran_token_corpus_root (skip lexicon/Quran/mapping)",
    )
    ap.add_argument(
        "--morphology-buckwalter",
        choices=("auto", "yes", "no"),
        default="auto",
        help=(
            "Corpus morphology FORM column: auto-detect Buckwalter vs Arabic, "
            "force Buckwalter→Unicode (yes), or never convert (no). Uses pyarabic."
        ),
    )
    ap.add_argument(
        "--skip-mapping",
        action="store_true",
        help="Skip heuristic mapping and overrides",
    )
    ap.add_argument(
        "--quran-file",
        action="append",
        default=None,
        help="Explicit Quran JSON path (repeatable). Default: all *.json in data/raw/quran/",
    )
    ap.add_argument(
        "--mapping-limit",
        type=int,
        default=None,
        help="Max quran_tokens to process in heuristic mapping",
    )
    ap.add_argument(
        "--min-confidence",
        type=float,
        default=0.35,
        help="Minimum heuristic score to keep a candidate",
    )
    ap.add_argument(
        "--no-clear-mapping",
        action="store_true",
        help="Do not delete existing heuristic analyses before re-mapping",
    )
    args = ap.parse_args()

    db_path = get_db_path()
    print(f"Database: {db_path}")

    print("Step 1: Initialize schema...")
    init_db(db_path)

    if args.only_corpus_roots:
        conn = connect(db_path)
        try:
            print("Only corpus roots: populate quran_token_corpus_root from kalimah…")
            st = populate_quran_token_corpus_roots(conn)
            conn.commit()
            print(
                f"  tokens_total={st.tokens_total}, rows_inserted={st.rows_inserted}, "
                f"with_root_buckwalter={st.with_root_bw}, with_root_arabic={st.with_root_ar}"
            )
        finally:
            conn.close()
        return

    conn = connect(db_path)
    try:
        print("Step 2: Import lexicon JSON...")
        paths = discover_lexicon_json_files()
        if not paths:
            print(
                "  Warning: No lane_lexicon*.json found under data/raw/lexicon/ or project root."
            )
        else:
            if args.truncate_lexicon:
                truncate_lexicon_tables(conn)
                conn.commit()
                print("  Truncated lexicon tables.")
            total_roots = 0
            total_entries = 0
            total_skipped = 0
            for path in paths:
                r, e, skipped = import_lexicon_json_file(
                    conn,
                    path,
                    replace_existing_entries=args.replace_entries,
                )
                conn.commit()
                total_roots += r
                total_entries += e
                total_skipped += skipped
                print(
                    f"  {path.name}: roots_written={r}, entries_inserted={e}, "
                    f"roots_skipped_already_in_db={skipped}"
                )
            print(
                f"  Lexicon totals: roots_written={total_roots}, "
                f"entries_inserted={total_entries}, roots_skipped_already_in_db={total_skipped}"
            )

        if not args.skip_quran:
            print("Step 3: Import Quran words JSON...")
            if args.quran_file:
                qpaths = [Path(p) for p in args.quran_file]
            else:
                qpaths = discover_quran_json_files()
            if not qpaths:
                print("  No Quran JSON files found under data/raw/quran/. Skipped.")
            else:
                total_tok = 0
                for qp in qpaths:
                    if not qp.is_file():
                        print(f"  Skip missing file: {qp}")
                        continue
                    n = import_quran_words_json(conn, qp)
                    conn.commit()
                    total_tok += n
                    print(f"  {qp.name}: imported {n} tokens")
                print(f"  Quran total tokens imported: {total_tok}")
        else:
            print("Step 3: Skipped (--skip-quran).")

        if not args.skip_root_quran_json:
            if QURAN_ROOT_JSON.is_file():
                print("Step 3c: Import project-root quran.json (verses + word split → SQLite)…")
                st = import_quran_root_json(conn, QURAN_ROOT_JSON, source_ref=QURAN_ROOT_JSON.name)
                conn.commit()
                print(
                    f"  {QURAN_ROOT_JSON.name}: verses_upserted={st.verses_upserted}, "
                    f"tokens_upserted={st.tokens_upserted}"
                )
            else:
                print(
                    f"Step 3c: No {QURAN_ROOT_JSON.name} at project root — skipped "
                    "(place mushaf JSON there or use --skip-root-quran-json to silence)."
                )
        else:
            print("Step 3c: Skipped (--skip-root-quran-json).")

        if not args.skip_kalimah:
            print("Step 3b: Quran morphology (kalimat)...")
            mpaths: list[Path] = []
            if args.morphology_file:
                mpaths = [Path(p) for p in args.morphology_file]
            else:
                for candidate in (
                    RAW_QURAN_DIR / "quran-morphology.txt",
                    RAW_QURAN_DIR / "morphology.example.txt",
                ):
                    if candidate.is_file():
                        mpaths = [candidate]
                        break
            if not mpaths:
                print(
                    "  No morphology file. Add data/raw/quran/quran-morphology.txt "
                    "or pass --morphology-file (see README). Skipped."
                )
            else:
                for i, mp in enumerate(mpaths):
                    if not mp.is_file():
                        print(f"  Skip missing file: {mp}")
                        continue
                    st = import_quran_morphology_txt(
                        conn,
                        mp,
                        clear_existing=(i == 0),
                        source_label=mp.stem,
                        buckwalter=args.morphology_buckwalter,
                    )
                    conn.commit()
                    extra = (
                        f", buckwalter_to_arabic={st.buckwalter_converted}"
                        if st.buckwalter_converted
                        else ""
                    )
                    print(
                        f"  {mp.name}: lines={st.lines_parsed}, "
                        f"segments_written={st.segments_written}, "
                        f"tokens_matched={st.tokens_matched}, "
                        f"tokens_not_in_db={st.tokens_missing}"
                        f"{extra}"
                    )
        else:
            print("Step 3b: Skipped (--skip-kalimah).")

        if not args.skip_corpus_roots:
            print("Step 3d: Corpus stem roots per word (quran_token_corpus_root)…")
            st = populate_quran_token_corpus_roots(conn)
            conn.commit()
            print(
                f"  tokens_total={st.tokens_total}, rows_inserted={st.rows_inserted}, "
                f"with_root_buckwalter={st.with_root_bw}, with_root_arabic={st.with_root_ar}"
            )
        else:
            print("Step 3d: Skipped (--skip-corpus-roots).")

        if not args.skip_mapping:
            print("Step 4: Token→root mapping...")
            n = run_heuristic_mapping(
                conn,
                clear_existing=not args.no_clear_mapping,
                limit=args.mapping_limit,
                min_confidence=args.min_confidence,
            )
            conn.commit()
            print(f"  Heuristic mapping processed {n} tokens.")
            o = apply_overrides(conn)
            conn.commit()
            print(f"  Manual overrides applied: {o}")
        else:
            print("Step 4: Skipped (--skip-mapping).")

        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
