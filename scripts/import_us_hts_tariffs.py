from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.background.tariff_data import (  # noqa: E402
    DEFAULT_SOURCE_NAME,
    DEFAULT_SOURCE_URL,
    build_tariff_database,
    parse_us_hts_table,
    write_normalized_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a local U.S. HTS export into normalized JSONL and a lightweight serving SQLite database."
    )
    parser.add_argument("--input", type=Path, required=True, help="Local HTS export file (CSV/TSV/pipe-delimited).")
    parser.add_argument(
        "--normalized-output",
        type=Path,
        default=Path("data/external/normalized/us_tariff_rules/us_hts_tariffs.jsonl"),
    )
    parser.add_argument(
        "--database-output",
        type=Path,
        default=Path("data/external/serving/tariff_rules.sqlite"),
    )
    parser.add_argument("--source-name", default=DEFAULT_SOURCE_NAME)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--market", default="United States")
    parser.add_argument("--jurisdiction", default="US")
    parser.add_argument("--default-effective-date", default=None)
    parser.add_argument("--default-hs-version", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = parse_us_hts_table(
        args.input,
        source_name=args.source_name,
        source_url=args.source_url,
        market=args.market,
        jurisdiction=args.jurisdiction,
        default_effective_date=(
            None
            if args.default_effective_date is None
            else _parse_cli_date(args.default_effective_date)
        ),
        default_hs_version=args.default_hs_version,
    )
    write_normalized_jsonl(records, args.normalized_output)
    build_tariff_database(
        records,
        args.database_output,
        metadata={
            "input_path": str(args.input),
            "normalized_output_path": str(args.normalized_output),
            "source_name": args.source_name,
            "source_url": args.source_url,
        },
    )
    print(
        f"Imported {len(records)} tariff rows into {args.database_output} and {args.normalized_output}",
    )


def _parse_cli_date(value: str):
    from app.background.tariff_data import parse_optional_date

    parsed = parse_optional_date(value)
    if parsed is None:
        raise ValueError("default-effective-date must not be empty")
    return parsed


if __name__ == "__main__":
    main()
