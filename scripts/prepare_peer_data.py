import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.peer_data import prepare_peer_data  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly prepare reusable TradePilot product-catalog and review-offset caches.",
    )
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
    parser.add_argument("--cache-dir", type=Path, default=Path("data/demo/cache"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = prepare_peer_data(
        metadata_path=args.metadata_input,
        reviews_path=args.reviews_input,
        cache_dir=args.cache_dir,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
