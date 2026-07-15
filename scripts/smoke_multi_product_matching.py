import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.enums import DataMode, DataOrigin  # noqa: E402
from app.domain.peer_matching import (  # noqa: E402
    CandidateProductSignature,
    PeerMatcher,
    load_peer_match_config,
)
from app.domain.product_catalog import ProductCatalog  # noqa: E402
from app.domain.review_lookup import ReviewLookup  # noqa: E402
from app.rag.embeddings import create_embedding_function  # noqa: E402
from app.schemas.product import ProductCreate, ProductProfile  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run limited-candidate peer matching for ten concrete real-data product queries.",
    )
    parser.add_argument("--manifest", type=Path, default=Path("config/real_product_smoke_manifest.yaml"))
    parser.add_argument("--metadata", type=Path, default=Path("data/filtered/meta_pet_supplies_prefiltered.jsonl"))
    parser.add_argument("--reviews", type=Path, default=Path("data/filtered/pet_supplies_reviews_prefiltered.jsonl"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/demo/cache"))
    parser.add_argument("--match-config", type=Path, default=Path("config/peer_matching.yaml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/demo/validation/multi_product_matching.json"),
    )
    parser.add_argument("--offline", action="store_true", help="Use deterministic HashEmbedding for local tests.")
    parser.add_argument("--case-id", action="append", default=[], help="Run only selected manifest case IDs.")
    return parser


def _profile(case: dict[str, object]) -> ProductProfile:
    create = ProductCreate(
        name=str(case["name"]),
        category=str(case["category"]),
        description=str(case["description"]),
        features=list(case.get("features") or []),
        use_scenarios=list(case.get("use_scenarios") or []),
        target_audience=list(case.get("target_audience") or []),
        attributes=dict(case.get("attributes") or {}),
        target_price=case.get("target_price"),
        target_currency="USD",
        data_mode=DataMode.REAL,
    )
    return ProductProfile(
        product_id=f"validation-{case['case_id']}",
        data_origin=DataOrigin.USER,
        **create.model_dump(),
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    started = perf_counter()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    catalog = ProductCatalog.open_prepared(args.metadata, args.cache_dir / "product_catalog.sqlite")
    review_lookup = ReviewLookup.open_prepared(args.reviews, args.cache_dir / "review_lookup.sqlite")
    embedding = create_embedding_function(Settings(), offline=args.offline)
    match_config = load_peer_match_config(args.match_config)
    cases = []
    selected_case_ids = set(args.case_id)
    selected_cases = [
        case
        for case in manifest["products"]
        if not selected_case_ids or case["case_id"] in selected_case_ids
    ]
    for case in selected_cases:
        case_started = perf_counter()
        profile = _profile(case)
        signature = CandidateProductSignature.from_product(profile)
        result = PeerMatcher(embedding, match_config).match(
            signature,
            catalog.iter_candidates(signature),  # type: ignore[arg-type]
            group_context=catalog.source_signature,
        )
        parent_asins = [peer.parent_asin for peer in result.peers]
        reviews = review_lookup.read(parent_asins, max_total=300)
        selected = set(parent_asins)
        orphan_reviews = [item.source_row for item in reviews if item.parent_asin not in selected]
        cases.append(
            {
                "case_id": case["case_id"],
                "query": profile.model_dump(mode="json"),
                "peer_group_id": result.peer_group_id,
                "prefilter_count": result.prefilter_count,
                "rerank_count": result.rerank_count,
                "peer_product_count": len(result.peers),
                "insufficient_peer_products": result.insufficient_peer_products,
                "excluded_accessory_count": result.excluded_accessory_count,
                "review_count": len(reviews),
                "orphan_review_count": len(orphan_reviews),
                "selected_parent_asins": parent_asins,
                "peers": [
                    {
                        "parent_asin": peer.parent_asin,
                        "title": peer.product.title,
                        "match_score": peer.match_score,
                        "match_reason": peer.match_reason,
                        "is_accessory": peer.is_accessory,
                    }
                    for peer in result.peers
                ],
                "match_metadata": result.match_metadata,
                "data_gaps": [item.model_dump(mode="json") for item in result.data_gaps],
                "duration_ms": round((perf_counter() - case_started) * 1000),
            }
        )
    output = {
        "manifest_version": manifest["version"],
        "purpose": manifest["purpose"],
        "catalog_signature": catalog.source_signature,
        "review_signature": review_lookup.source_signature,
        "catalog_rebuilt": catalog.rebuilt,
        "review_lookup_rebuilt": review_lookup.rebuilt,
        "embedding_model": getattr(embedding, "name", lambda: type(embedding).__name__)(),
        "case_count": len(cases),
        "cases": cases,
        "total_duration_ms": round((perf_counter() - started) * 1000),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    args = _parser().parse_args()
    result = run(args)
    summary = {
        "case_count": result["case_count"],
        "embedding_model": result["embedding_model"],
        "catalog_rebuilt": result["catalog_rebuilt"],
        "review_lookup_rebuilt": result["review_lookup_rebuilt"],
        "total_duration_ms": result["total_duration_ms"],
        "cases": [
            {
                "case_id": item["case_id"],
                "peer_product_count": item["peer_product_count"],
                "review_count": item["review_count"],
                "insufficient_peer_products": item["insufficient_peer_products"],
            }
            for item in result["cases"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
