from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.enums import KnowledgeType
from app.rag.contracts import KnowledgeDocument
from app.rag.documents import split_product_text, split_review_text
from app.rag.utils import clean_text, content_hash, iter_jsonl, stable_id


@dataclass(slots=True)
class DataFileProfile:
    path: str
    file_type: str
    records: int
    fields: dict[str, int]
    nulls: dict[str, int]
    duplicate_content_hashes: int
    mapped_knowledge_type: str | None


@dataclass(slots=True)
class ImportSummary:
    files: list[DataFileProfile] = field(default_factory=list)
    documents_total: int = 0
    documents_yielded: int = 0
    skipped_empty: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    by_collection: dict[str, int] = field(default_factory=dict)


def discover_data_files(source: Path) -> list[Path]:
    supported = {".jsonl", ".json", ".csv", ".txt", ".md", ".markdown"}
    return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in supported)


def _is_meta_file(path: Path, sample: dict[str, Any] | None = None) -> bool:
    name = path.name.lower()
    return "meta" in name or bool(sample and {"features", "description", "average_rating"} & set(sample))


def _is_review_file(path: Path, sample: dict[str, Any] | None = None) -> bool:
    name = path.name.lower()
    return "review" in name or bool(sample and {"rating", "text", "user_id"} <= set(sample))


def profile_jsonl(path: Path) -> DataFileProfile:
    fields: Counter[str] = Counter()
    nulls: Counter[str] = Counter()
    hashes: Counter[str] = Counter()
    total = 0
    sample: dict[str, Any] | None = None
    for _, obj in iter_jsonl(path):
        if not isinstance(obj, dict):
            continue
        sample = sample or obj
        total += 1
        for key, value in obj.items():
            fields[key] += 1
            if value in (None, "", [], {}):
                nulls[key] += 1
        text = clean_text(" ".join(str(obj.get(key, "")) for key in ("title", "text", "description", "features")))
        if text:
            hashes[content_hash(text)] += 1
    knowledge_type = None
    if _is_meta_file(path, sample):
        knowledge_type = KnowledgeType.PRODUCT_KNOWLEDGE.value
    if _is_review_file(path, sample):
        knowledge_type = KnowledgeType.REVIEW_INSIGHT.value
    return DataFileProfile(
        path=str(path),
        file_type=path.suffix.lower().lstrip("."),
        records=total,
        fields=dict(fields),
        nulls=dict(nulls),
        duplicate_content_hashes=sum(1 for count in hashes.values() if count > 1),
        mapped_knowledge_type=knowledge_type,
    )


def validate_source(source: Path) -> ImportSummary:
    summary = ImportSummary()
    for path in discover_data_files(source):
        if path.suffix.lower() == ".jsonl":
            summary.files.append(profile_jsonl(path))
        else:
            summary.files.append(
                DataFileProfile(
                    path=str(path),
                    file_type=path.suffix.lower().lstrip("."),
                    records=0,
                    fields={},
                    nulls={},
                    duplicate_content_hashes=0,
                    mapped_knowledge_type=None,
                )
            )
    return summary


def _metadata_base(path: Path, line_number: int, record: dict[str, Any]) -> dict[str, Any]:
    categories = record.get("categories") if isinstance(record.get("categories"), list) else []
    details = record.get("details") if isinstance(record.get("details"), dict) else {}
    parent_asin = clean_text(record.get("parent_asin"))
    return {
        "source_file": str(path),
        "source_row": line_number,
        "source_locator": f"{path.name}:{line_number}",
        "source_id": parent_asin,
        "product_id": stable_id("product", parent_asin),
        "parent_asin": parent_asin,
        "asin": clean_text(record.get("asin")),
        "product_name": clean_text(record.get("title")),
        "category": categories[-1] if categories else clean_text(record.get("main_category")),
        "brand": clean_text(details.get("Brand")) or clean_text(record.get("store")),
        "marketplace": "amazon_us",
        "target_market": "amazon_us",
        "language": "en",
        "data_origin": "real",
        "is_demo": False,
    }


def _product_text(record: dict[str, Any]) -> str:
    details = record.get("details") if isinstance(record.get("details"), dict) else {}
    features = record.get("features") if isinstance(record.get("features"), list) else []
    descriptions = record.get("description") if isinstance(record.get("description"), list) else []
    categories = record.get("categories") if isinstance(record.get("categories"), list) else []
    sections = [
        f"Product title: {clean_text(record.get('title'))}",
        f"Category path: {' > '.join(clean_text(item) for item in categories if clean_text(item))}",
        f"Brand/store: {clean_text(details.get('Brand')) or clean_text(record.get('store'))}",
        f"Price: {record.get('price')} USD",
        f"Average rating: {record.get('average_rating')} from {record.get('rating_number')} ratings",
    ]
    if features:
        sections.append("Feature bullets:\n- " + "\n- ".join(clean_text(item) for item in features if clean_text(item)))
    if descriptions:
        sections.append("Description:\n" + "\n".join(clean_text(item) for item in descriptions if clean_text(item)))
    if details:
        detail_lines = [
            f"{clean_text(key)}: {clean_text(value)}"
            for key, value in details.items()
            if clean_text(value)
        ]
        sections.append("Product parameters:\n- " + "\n- ".join(detail_lines))
    return "\n\n".join(section for section in sections if clean_text(section))


def _review_text(record: dict[str, Any]) -> str:
    title = clean_text(record.get("title"))
    text = clean_text(record.get("text"))
    rating = record.get("rating")
    prefix = f"Rating: {rating}" if rating is not None else ""
    return "\n\n".join(part for part in (prefix, title, text) if part)


def iter_filtered_documents(
    source: Path,
    *,
    chunk_size: int = 2800,
    chunk_overlap: int = 300,
    limit: int | None = None,
    knowledge_types: set[KnowledgeType] | None = None,
) -> tuple[Iterable[KnowledgeDocument], ImportSummary]:
    summary = validate_source(source)
    seen_hashes: set[str] = set()

    def generator() -> Iterable[KnowledgeDocument]:
        nonlocal summary
        yielded = 0
        for path in discover_data_files(source):
            if path.suffix.lower() != ".jsonl":
                continue
            for line_number, record in iter_jsonl(path):
                if not isinstance(record, dict):
                    summary.failed += 1
                    continue
                try:
                    metadata = _metadata_base(path, line_number, record)
                    if _is_meta_file(path, record):
                        if knowledge_types is not None and KnowledgeType.PRODUCT_KNOWLEDGE not in knowledge_types:
                            continue
                        parent_id = clean_text(record.get("parent_asin"))
                        text = _product_text(record)
                        chunks = split_product_text(
                            parent_id=parent_id,
                            product_id=str(metadata["product_id"]),
                            source_name=clean_text(record.get("title")) or parent_id,
                            source_file=path,
                            source_locator=f"{path.name}:{line_number}",
                            text=text,
                            metadata={
                                **metadata,
                                "knowledge_type": KnowledgeType.PRODUCT_KNOWLEDGE.value,
                                "listed_price": record.get("price"),
                                "currency": "USD" if record.get("price") is not None else "",
                                "rating": record.get("average_rating"),
                                "rating_number": record.get("rating_number"),
                                "document_type": "product_metadata",
                            },
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                        )
                    elif _is_review_file(path, record):
                        if knowledge_types is not None and KnowledgeType.REVIEW_INSIGHT not in knowledge_types:
                            continue
                        parent_id = stable_id(
                            "review",
                            record.get("parent_asin"),
                            record.get("asin"),
                            record.get("user_id"),
                            record.get("timestamp"),
                            record.get("title"),
                            record.get("text"),
                        )
                        text = _review_text(record)
                        chunks = split_review_text(
                            parent_id=parent_id,
                            product_id=str(metadata["product_id"]),
                            source_name=clean_text(record.get("title")) or parent_id,
                            source_file=path,
                            source_locator=f"{path.name}:{line_number}",
                            text=text,
                            metadata={
                                **metadata,
                                "knowledge_type": KnowledgeType.REVIEW_INSIGHT.value,
                                "review_id": parent_id,
                                "review_title": clean_text(record.get("title")),
                                "rating": record.get("rating"),
                                "review_date": record.get("timestamp") or "",
                                "verified_purchase": bool(record.get("verified_purchase")),
                                "helpful_vote": record.get("helpful_vote") or 0,
                                "document_type": "review",
                            },
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                        )
                    else:
                        continue
                    if not chunks:
                        summary.skipped_empty += 1
                        continue
                    for chunk in chunks:
                        summary.documents_total += 1
                        if chunk.hash in seen_hashes:
                            summary.skipped_duplicate += 1
                            continue
                        seen_hashes.add(chunk.hash)
                        document = chunk.to_document()
                        summary.documents_yielded += 1
                        summary.by_collection[document.knowledge_type.value] = (
                            summary.by_collection.get(document.knowledge_type.value, 0) + 1
                        )
                        yielded += 1
                        yield document
                        if limit is not None and yielded >= limit:
                            return
                except Exception:
                    summary.failed += 1
                    continue

    return generator(), summary
