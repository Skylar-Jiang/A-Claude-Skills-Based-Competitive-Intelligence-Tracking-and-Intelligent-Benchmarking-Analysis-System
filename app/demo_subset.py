from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import KnowledgeType
from app.db.migrations import upgrade_database
from app.db.models.core import CompetitorOffer, KnowledgeSource, Product, Review
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.importers import iter_filtered_documents
from scripts.domain_imports.import_pet_supplies import deterministic_id, import_pet_supplies

MANIFEST_VERSION = 2


@dataclass(slots=True)
class SelectedRow:
    source_line: int
    record: dict[str, object]


@dataclass(slots=True)
class DemoSubsetResult:
    product_id: str
    parent_asin: str
    product_name: str
    image_url: str | None
    product_count: int
    review_count: int
    collection_counts: dict[str, int]
    database_duration_ms: int
    index_duration_ms: int
    database_rebuilt: bool
    index_rebuilt: bool
    fingerprint: str
    metadata_rows_scanned: int
    review_rows_scanned: int


def prepare_real_demo_subset(
    *,
    metadata_path: Path,
    reviews_path: Path,
    runtime_dir: Path,
    query: str,
    max_reviews: int,
    review_scan_limit: int = 100_000,
    embedding_function: Any,
) -> DemoSubsetResult:
    if max_reviews < 1:
        raise ValueError("max_reviews must be at least 1")
    if not metadata_path.is_file() or not reviews_path.is_file():
        raise FileNotFoundError("Real pet-supplies metadata and review JSONL files are required")

    runtime_dir.mkdir(parents=True, exist_ok=True)
    source_dir = runtime_dir / "subset_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    database_path = runtime_dir / "tradepilot_demo.db"
    chroma_dir = runtime_dir / "chroma"
    manifest_path = runtime_dir / "subset_manifest.json"
    if review_scan_limit < max_reviews:
        raise ValueError("review_scan_limit must be greater than or equal to max_reviews")
    input_signature = _input_signature(metadata_path, reviews_path, query, max_reviews, review_scan_limit)
    manifest = _load_manifest(manifest_path)
    warm = _load_warm_result(
        manifest=manifest,
        input_signature=input_signature,
        database_path=database_path,
        chroma_dir=chroma_dir,
        embedding_function=embedding_function,
    )
    if warm is not None:
        return warm

    reviews_by_parent, review_rows_scanned = _scan_review_window(
        reviews_path,
        max_reviews=max_reviews,
        review_scan_limit=review_scan_limit,
    )
    selected, reviews, metadata_rows_scanned = _select_metadata(
        metadata_path,
        query,
        reviews_by_parent,
    )
    parent_asin = str(selected.record["parent_asin"])
    if not reviews:
        raise ValueError(f"Selected product {parent_asin} has no traceable reviews")

    metadata_record = {
        **selected.record,
        "_tradepilot_source_file": str(metadata_path),
        "_tradepilot_source_line": selected.source_line,
    }
    review_records = [
        {
            **item.record,
            "_tradepilot_source_file": str(reviews_path),
            "_tradepilot_source_line": item.source_line,
        }
        for item in reviews
    ]
    fingerprint = _fingerprint(metadata_record, review_records)
    metadata_subset_path = source_dir / "meta_pet_supplies_prefiltered.jsonl"
    review_subset_path = source_dir / "pet_supplies_reviews_prefiltered.jsonl"
    _write_jsonl(metadata_subset_path, [metadata_record])
    _write_jsonl(review_subset_path, review_records)

    unchanged = manifest.get("fingerprint") == fingerprint
    database_started = time.perf_counter()
    database_rebuilt = not (unchanged and database_path.is_file())
    if database_rebuilt:
        database_path.unlink(missing_ok=True)
        _build_database(
            database_path=database_path,
            metadata_subset_path=metadata_subset_path,
            review_subset_path=review_subset_path,
            metadata_source=selected,
            metadata_source_path=metadata_path,
            review_sources=reviews,
            review_source_path=reviews_path,
        )
    database_duration_ms = round((time.perf_counter() - database_started) * 1000)

    store = ChromaKnowledgeStore(chroma_dir, embedding_function)
    current_counts = _collection_counts(store)
    expected_counts = manifest.get("collection_counts", {})
    index_rebuilt = not (
        unchanged
        and expected_counts
        and current_counts == {str(key): int(value) for key, value in expected_counts.items()}
    )
    index_started = time.perf_counter()
    if index_rebuilt:
        store.clear()
        documents, _ = iter_filtered_documents(source_dir)
        traced_documents = _trace_documents(
            list(documents),
            metadata_path=metadata_path,
            metadata_source=selected,
            reviews_path=reviews_path,
            review_sources=reviews,
        )
        store.ingest(traced_documents)
    collection_counts = _collection_counts(store)
    index_duration_ms = round((time.perf_counter() - index_started) * 1000)

    product_id = deterministic_id("product", parent_asin)
    product_count, review_count = _database_counts(database_path)
    result = DemoSubsetResult(
        product_id=product_id,
        parent_asin=parent_asin,
        product_name=str(selected.record["title"]),
        image_url=_image_url(selected.record),
        product_count=product_count,
        review_count=review_count,
        collection_counts=collection_counts,
        database_duration_ms=database_duration_ms,
        index_duration_ms=index_duration_ms,
        database_rebuilt=database_rebuilt,
        index_rebuilt=index_rebuilt,
        fingerprint=fingerprint,
        metadata_rows_scanned=metadata_rows_scanned,
        review_rows_scanned=review_rows_scanned,
    )
    payload = {
        **asdict(result),
        "version": MANIFEST_VERSION,
        "input_signature": input_signature,
        "database_rebuilt": False,
        "index_rebuilt": False,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _input_signature(
    metadata_path: Path,
    reviews_path: Path,
    query: str,
    max_reviews: int,
    review_scan_limit: int,
) -> dict[str, object]:
    return {
        "version": MANIFEST_VERSION,
        "metadata": _file_signature(metadata_path),
        "reviews": _file_signature(reviews_path),
        "query": " ".join(query.casefold().split()),
        "max_reviews": max_reviews,
        "review_scan_limit": review_scan_limit,
    }


def _file_signature(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_warm_result(
    *,
    manifest: dict[str, Any],
    input_signature: dict[str, object],
    database_path: Path,
    chroma_dir: Path,
    embedding_function: Any,
) -> DemoSubsetResult | None:
    if manifest.get("input_signature") != input_signature or not database_path.is_file():
        return None
    required = {field.name for field in DemoSubsetResult.__dataclass_fields__.values()}
    if not required.issubset(manifest):
        return None
    store = ChromaKnowledgeStore(chroma_dir, embedding_function)
    counts = _collection_counts(store)
    expected = {str(key): int(value) for key, value in manifest.get("collection_counts", {}).items()}
    if not expected or counts != expected:
        return None
    values = {key: manifest[key] for key in required}
    values.update(
        collection_counts=counts,
        database_duration_ms=0,
        index_duration_ms=0,
        database_rebuilt=False,
        index_rebuilt=False,
    )
    return DemoSubsetResult(**values)


def _select_metadata(
    path: Path,
    query: str,
    reviews_by_parent: dict[str, list[SelectedRow]],
) -> tuple[SelectedRow, list[SelectedRow], int]:
    if not reviews_by_parent:
        raise ValueError("No valid reviews were found inside the bounded review scan window")
    fallback: SelectedRow | None = None
    fallback_reviews: list[SelectedRow] = []
    query_match: SelectedRow | None = None
    query_reviews: list[SelectedRow] = []
    target_review_count = max(len(items) for items in reviews_by_parent.values())
    query_tokens = {token for token in query.casefold().split() if token}
    rows_scanned = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            rows_scanned = line_number
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict) or not _eligible_metadata(value):
                continue
            parent_asin = str(value.get("parent_asin") or "")
            candidate_reviews = reviews_by_parent.get(parent_asin, [])
            if not candidate_reviews:
                continue
            row = SelectedRow(source_line=line_number, record=value)
            haystack = json.dumps(
                {
                    "title": value.get("title"),
                    "categories": value.get("categories"),
                    "description": value.get("description"),
                    "features": value.get("features"),
                },
                ensure_ascii=False,
            ).casefold()
            if query_tokens and all(token in haystack for token in query_tokens):
                if len(candidate_reviews) > len(query_reviews):
                    query_match = row
                    query_reviews = candidate_reviews
                if len(query_reviews) >= target_review_count:
                    return query_match, query_reviews, rows_scanned
            if len(candidate_reviews) > len(fallback_reviews):
                fallback = row
                fallback_reviews = candidate_reviews
    if query_match is not None:
        return query_match, query_reviews, rows_scanned
    if fallback is None:
        raise ValueError("No eligible real pet-supplies product was found")
    return fallback, fallback_reviews, rows_scanned


def _eligible_metadata(value: dict[str, object]) -> bool:
    title = str(value.get("title") or "").strip()
    parent_asin = str(value.get("parent_asin") or "").strip()
    categories = value.get("categories") or value.get("main_category")
    descriptive = value.get("description") or value.get("features")
    numeric = value.get("price") is not None or value.get("average_rating") is not None
    return bool(title and parent_asin and categories and descriptive and numeric and _rating_count(value) > 0)


def _rating_count(value: dict[str, object]) -> int:
    try:
        return int(value.get("rating_number") or 0)
    except (TypeError, ValueError):
        return 0


def _scan_review_window(
    path: Path,
    *,
    max_reviews: int,
    review_scan_limit: int,
) -> tuple[dict[str, list[SelectedRow]], int]:
    selected: dict[str, list[SelectedRow]] = {}
    rows_scanned = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if line_number > review_scan_limit:
                break
            rows_scanned = line_number
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            if not str(value.get("text") or value.get("title") or "").strip():
                continue
            parent_asin = str(value.get("parent_asin") or "").strip()
            if not parent_asin:
                continue
            bucket = selected.setdefault(parent_asin, [])
            if len(bucket) < max_reviews:
                bucket.append(SelectedRow(source_line=line_number, record=value))
    return selected, rows_scanned


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _fingerprint(metadata: dict[str, object], reviews: list[dict[str, object]]) -> str:
    payload = json.dumps({"metadata": metadata, "reviews": reviews}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_database(
    *,
    database_path: Path,
    metadata_subset_path: Path,
    review_subset_path: Path,
    metadata_source: SelectedRow,
    metadata_source_path: Path,
    review_sources: list[SelectedRow],
    review_source_path: Path,
) -> None:
    database_url = f"sqlite:///{database_path.resolve().as_posix()}"
    upgrade_database(database_url)
    engine = create_engine(database_url)
    product_id = deterministic_id("product", metadata_source.record["parent_asin"])
    with Session(engine) as session:
        import_pet_supplies(session, metadata_subset_path, review_subset_path)
        product = session.get(Product, product_id)
        if product is None:
            raise RuntimeError("Subset product import did not create the selected product")
        product.attributes_json = {**product.attributes_json, "image_url": _image_url(metadata_source.record)}
        product.metadata_json = {
            "source_file": str(metadata_source_path),
            "source_line": metadata_source.source_line,
            "parent_asin": metadata_source.record["parent_asin"],
        }
        knowledge = session.scalar(select(KnowledgeSource).where(KnowledgeSource.product_id == product_id))
        if knowledge is not None:
            knowledge.metadata_json = {
                **knowledge.metadata_json,
                "source_file": str(metadata_source_path),
                "source_line": metadata_source.source_line,
            }
        for item in review_sources:
            record = item.record
            review_id = deterministic_id(
                "review",
                record.get("parent_asin"),
                record.get("asin") or "",
                record.get("user_id") or "",
                record.get("timestamp"),
                " ".join(str(record.get("title") or "").split()),
                " ".join(str(record.get("text") or "").split()),
            )
            review = session.get(Review, review_id)
            if review is not None:
                review.metadata_json = {
                    **review.metadata_json,
                    "source_file": str(review_source_path),
                    "source_line": item.source_line,
                }
        session.commit()
    engine.dispose()


def _trace_documents(
    documents: list[Any],
    *,
    metadata_path: Path,
    metadata_source: SelectedRow,
    reviews_path: Path,
    review_sources: list[SelectedRow],
) -> list[Any]:
    traced = []
    for document in documents:
        metadata = dict(document.metadata)
        if document.knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE:
            source_path = metadata_path
            source_line = metadata_source.source_line
        else:
            subset_line = int(metadata.get("source_row") or 1)
            source = review_sources[min(max(subset_line - 1, 0), len(review_sources) - 1)]
            source_path = reviews_path
            source_line = source.source_line
        metadata.update(
            source_file=str(source_path),
            source_row=source_line,
            source_locator=f"{source_path}#L{source_line}",
        )
        traced.append(
            document.model_copy(
                update={
                    "source_uri": f"{source_path}#L{source_line}",
                    "metadata": metadata,
                }
            )
        )
    return traced


def _collection_counts(store: ChromaKnowledgeStore) -> dict[str, int]:
    return {name: int(item["count"]) for name, item in store.status().items()}


def _database_counts(path: Path) -> tuple[int, int]:
    engine = create_engine(f"sqlite:///{path.resolve().as_posix()}")
    with Session(engine) as session:
        product_count = int(session.scalar(select(func.count()).select_from(Product)) or 0)
        review_count = int(session.scalar(select(func.count()).select_from(Review)) or 0)
        if session.scalar(select(func.count()).select_from(CompetitorOffer)) != product_count:
            raise RuntimeError("Subset offer count does not match product count")
    engine.dispose()
    return product_count, review_count


def _image_url(record: dict[str, object]) -> str | None:
    images = record.get("images")
    if not isinstance(images, list):
        return None
    for image in images:
        if not isinstance(image, dict):
            continue
        for key in ("hi_res", "large"):
            value = image.get(key)
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                return value
    return None
