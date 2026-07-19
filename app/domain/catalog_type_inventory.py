from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

UNRESOLVED_TYPE_KEY = "__unresolved__"
GENERIC_LEAF_LABELS = {
    "accessories",
    "food",
    "grooming",
    "health supplies",
    "other",
    "supplies",
    "toys",
}


@dataclass(frozen=True)
class CatalogTypeRow:
    parent_asin: str
    title: str
    categories: list[str]


@dataclass
class CatalogTypeBucket:
    type_key: str
    type_label: str
    product_count: int = 0
    unresolved: bool = False
    category_paths: dict[str, int] = field(default_factory=dict)
    example_products: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CatalogTypeAssignment:
    type_key: str
    type_label: str
    source_category_path: str
    classification_method: str
    confidence: float
    unresolved: bool


@dataclass(frozen=True)
class CatalogTypeInventory:
    total_product_count: int
    assigned_product_count: int
    type_count: int
    unresolved_product_count: int
    types: list[CatalogTypeBucket]


def build_catalog_type_inventory(
    rows: Iterable[CatalogTypeRow],
    *,
    example_limit: int = 3,
) -> CatalogTypeInventory:
    buckets: dict[str, CatalogTypeBucket] = {}
    path_counts: dict[str, Counter[str]] = {}
    total = 0
    unresolved_count = 0
    for row in rows:
        total += 1
        assignment = classify_catalog_type(row.categories)
        bucket = buckets.setdefault(
            assignment.type_key,
            CatalogTypeBucket(
                type_key=assignment.type_key,
                type_label=assignment.type_label,
                unresolved=assignment.unresolved,
            ),
        )
        bucket.product_count += 1
        path_counts.setdefault(assignment.type_key, Counter())[assignment.source_category_path] += 1
        if len(bucket.example_products) < example_limit:
            bucket.example_products.append({"parent_asin": row.parent_asin, "title": row.title})
        if assignment.unresolved:
            unresolved_count += 1

    result = sorted(buckets.values(), key=lambda item: (-item.product_count, item.type_key))
    for bucket in result:
        bucket.category_paths = dict(sorted(path_counts[bucket.type_key].items()))
    return CatalogTypeInventory(
        total_product_count=total,
        assigned_product_count=sum(item.product_count for item in result),
        type_count=len(result),
        unresolved_product_count=unresolved_count,
        types=result,
    )


def classify_catalog_type(categories: list[str]) -> CatalogTypeAssignment:
    clean = [" ".join(value.split()) for value in categories if value.strip()]
    if not clean:
        return CatalogTypeAssignment(
            type_key=UNRESOLVED_TYPE_KEY,
            type_label="Unresolved: missing categories",
            source_category_path="(missing categories)",
            classification_method="missing_source_category",
            confidence=0.0,
            unresolved=True,
        )
    leaf = clean[-1]
    leaf_key = _normalize(leaf)
    if leaf_key not in GENERIC_LEAF_LABELS or len(clean) == 1:
        type_key, type_label = leaf_key, leaf
    else:
        parent = clean[-2]
        type_key, type_label = f"{_normalize(parent)} / {leaf_key}", f"{parent} / {leaf}"
    return CatalogTypeAssignment(
        type_key=type_key,
        type_label=type_label,
        source_category_path=" > ".join(clean),
        classification_method="source_category",
        confidence=1.0,
        unresolved=False,
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
