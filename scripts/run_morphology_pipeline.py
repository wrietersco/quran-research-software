#!/usr/bin/env python3
"""
Run the morphology pipeline: legacy single-token or ensemble (CAMeL top-N + Stanza + scorer + optional LLM).

  pip install -r requirements-camel.txt && camel_data -i light
  pip install -r requirements-stanza.txt   # optional validator
  # Legacy:
  python scripts/run_morphology_pipeline.py --token "بِخَلَٰقِهِمۡ" -v
  # Ensemble (sentence):
  python scripts/run_morphology_pipeline.py --ensemble --sentence "وترهبون به عدو الله"
  python scripts/run_morphology_pipeline.py --ensemble --token "لَهُم" --top-n 5 --no-stanza
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CAMeL morphology: legacy single-token or ensemble sentence pipeline.",
    )
    ap.add_argument("--token", default=None, help="Single Arabic surface token (legacy mode)")
    ap.add_argument(
        "--sentence",
        default=None,
        help="Full sentence for ensemble mode (space/tokenize via CAMeL)",
    )
    ap.add_argument(
        "--ensemble",
        action="store_true",
        help="Use ensemble pipeline (top-N candidates, scorer, sequence pass)",
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="CAMeL MLE top analyses for ensemble (default 5)",
    )
    ap.add_argument(
        "--llm-rerank",
        action="store_true",
        help="Allow OpenAI rerank among candidates when confidence is low (needs OPENAI_API_KEY)",
    )
    ap.add_argument(
        "--context",
        default=None,
        help="(Legacy) Full sentence for Stanza alignment",
    )
    ap.add_argument("--token-id", type=int, default=1)
    ap.add_argument("--no-stanza", action="store_true", help="Skip Stanza validator")
    ap.add_argument(
        "--full-analysis",
        action="store_true",
        help="Include camel.analysis_full (raw CALIMA dict)",
    )
    ap.add_argument(
        "--scheme",
        default="bwtok",
        help="MorphologicalTokenizer scheme (default bwtok)",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging for all pipeline modules",
    )
    args = ap.parse_args()

    from src.morphology_pipeline import (
        EnsembleConfig,
        MorphologyPipeline,
        configure_morphology_logging,
        export_json,
        process_sentence_ensemble,
    )

    configure_morphology_logging(
        logging.DEBUG if args.verbose else logging.INFO,
    )

    try:
        if args.ensemble:
            cfg = EnsembleConfig(camel_top=max(1, args.top_n))
            if args.sentence:
                out = process_sentence_ensemble(
                    args.sentence.strip(),
                    enable_llm=args.llm_rerank,
                    cfg=cfg,
                    morph_scheme=args.scheme,
                    use_stanza=not args.no_stanza,
                    include_full_camel=args.full_analysis,
                )
            elif args.token:
                out = process_sentence_ensemble(
                    [args.token.strip()],
                    enable_llm=args.llm_rerank,
                    cfg=cfg,
                    morph_scheme=args.scheme,
                    use_stanza=not args.no_stanza,
                    include_full_camel=args.full_analysis,
                )
            else:
                ap.error("--ensemble requires --sentence or --token")
                return 2
            print(export_json(out))
            return 0

        if not args.token:
            ap.error("--token is required (or use --ensemble with --sentence/--token)")
            return 2

        pipe = MorphologyPipeline(
            morph_scheme=args.scheme,
            use_stanza=not args.no_stanza,
        )
        record = pipe.process_token(
            args.token,
            token_id=args.token_id,
            context_sentence=args.context,
            include_full_camel_analysis=args.full_analysis,
        )
        print(export_json(record))
        return 0
    except ImportError as e:
        logging.getLogger("run_morphology_pipeline").error("%s", e)
        return 1
    except Exception as e:
        logging.getLogger("run_morphology_pipeline").exception("Pipeline failed: %s", e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
