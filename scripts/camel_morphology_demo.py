#!/usr/bin/env python3
"""
Demo: CAMeL MLE disambiguation + morphological tokenization (MSA).

  pip install -r requirements-camel.txt
  camel_data -i light
  python scripts/camel_morphology_demo.py
  python scripts/camel_morphology_demo.py --text "وترهبون به عدو الله"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TEXT = "وترهبون به عدو الله وعدوكم"  # CAMeL docs–style example sentence


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CAMeL Tools: tokenize → MLE disambiguate → morphological tokenizer.",
    )
    ap.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Arabic sentence (default: example similar to the CAMeL docs recipe).",
    )
    ap.add_argument(
        "--model",
        default="calima-msa-r13",
        help="MLE pretrained model name (default: calima-msa-r13).",
    )
    ap.add_argument(
        "--scheme",
        default="bwtok",
        help="MorphologicalTokenizer scheme (default: bwtok).",
    )
    ap.add_argument(
        "--no-split",
        action="store_true",
        help="Keep morphemes joined with underscore instead of splitting.",
    )
    ap.add_argument(
        "--diac",
        action="store_true",
        help="Keep diacritics on tokenizer output.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of a human-readable report.",
    )
    args = ap.parse_args()

    try:
        from src.morphology.camel_pipeline import analyze_sentence
    except ImportError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        result = analyze_sentence(
            args.text,
            model_name=args.model,
            scheme=args.scheme,
            split_morphs=not args.no_split,
            diac=args.diac,
        )
    except Exception as e:
        print(
            "CAMeL pipeline failed (missing data, wrong Python version, or install issue):\n"
            f"  {e}\n\n"
            "Install: pip install -r requirements-camel.txt\n"
            "Then:    camel_data -i light",
            file=sys.stderr,
        )
        return 2

    if args.json:
        payload = {
            "model": result.model,
            "scheme": result.scheme,
            "tokens": result.tokens,
            "morph_flat": result.morph_flat,
            "words": [
                {
                    "word": w.word,
                    "analysis": w.analysis,
                    "morph_segments": w.morph_segments,
                }
                for w in result.words
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"model={result.model}  scheme={result.scheme}\n")
    print("--- tokens (simple_word_tokenize) ---")
    print(result.tokens)
    print("\n--- best MLE analysis per token ---")
    for w in result.words:
        print(w.word, w.analysis if w.analysis else "(no analysis)")
    print("\n--- morph segments per word ---")
    for w in result.words:
        print(f"  {w.word!r} -> {w.morph_segments}")
    print("\n--- MorphologicalTokenizer (whole sentence) ---")
    print(result.morph_flat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
