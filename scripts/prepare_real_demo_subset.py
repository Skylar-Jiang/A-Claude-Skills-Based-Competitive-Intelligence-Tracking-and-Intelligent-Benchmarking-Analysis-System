import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.demo_subset import prepare_real_demo_subset  # noqa: E402
from app.rag.embeddings import create_embedding_function  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the isolated single-product TradePilot Real demo runtime.")
    parser.add_argument(
        "--metadata-input",
        type=Path,
        default=Path("data/filtered/meta_pet_supplies_prefiltered.jsonl"),
    )
    parser.add_argument(
        "--reviews-input",
        type=Path,
        default=Path("data/filtered/pet_supplies_reviews_prefiltered.jsonl"),
    )
    parser.add_argument("--runtime-dir", type=Path, default=Path("data/demo"))
    parser.add_argument("--query", default="cat water fountain")
    parser.add_argument("--max-reviews", type=int, default=300)
    parser.add_argument(
        "--review-scan-limit",
        type=int,
        default=100_000,
        help="Hard upper bound for review JSONL rows scanned during product selection.",
    )
    parser.add_argument(
        "--offline-embeddings",
        action="store_true",
        help="Use deterministic local embeddings for tests only; Real validation must omit this flag.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    result = prepare_real_demo_subset(
        metadata_path=args.metadata_input,
        reviews_path=args.reviews_input,
        runtime_dir=args.runtime_dir,
        query=args.query,
        max_reviews=args.max_reviews,
        review_scan_limit=args.review_scan_limit,
        embedding_function=create_embedding_function(settings, offline=args.offline_embeddings),
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
