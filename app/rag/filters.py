from __future__ import annotations

from typing import Any

from app.core.enums import KnowledgeType
from app.schemas.product import ProductProfile


def build_metadata_filter(
    profile: ProductProfile,
    knowledge_type: KnowledgeType,
    constraints: dict[str, Any] | None = None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    constraints = constraints or {}
    clauses: list[dict[str, Any]] = [{"data_origin": "real"}, {"is_demo": False}]
    product_id = constraints.get("product_id") or profile.product_id
    parent_asin = constraints.get("parent_asin") or profile.attributes.get("parent_asin")
    if product_id:
        clauses.append({"product_id": str(product_id)})
    elif parent_asin:
        clauses.append({"parent_asin": str(parent_asin)})
    if strict:
        _add_optional(clauses, "category", constraints.get("category") or profile.category)
        _add_optional(clauses, "target_market", constraints.get("target_market") or profile.target_market)
    _add_optional(clauses, "marketplace", constraints.get("marketplace"))
    _add_optional(clauses, "language", constraints.get("language"))
    _add_optional(clauses, "asin", constraints.get("asin"))
    if knowledge_type is KnowledgeType.REVIEW_INSIGHT:
        if constraints.get("verified_purchase") is not None:
            clauses.append({"verified_purchase": bool(constraints["verified_purchase"])})
        rating_filter = _rating_filter(constraints)
        if rating_filter:
            clauses.extend(rating_filter)
    return _and(clauses)


def relaxed_filters(where: dict[str, Any]) -> list[dict[str, Any]]:
    filters = [where]
    clauses = list(where.get("$and", [where]))
    keep_core = [
        clause
        for clause in clauses
        if any(key in clause for key in ("data_origin", "is_demo", "product_id", "parent_asin"))
    ]
    if keep_core and keep_core != clauses:
        filters.append(_and(keep_core))
    real_only = [clause for clause in clauses if any(key in clause for key in ("data_origin", "is_demo"))]
    if real_only and real_only != keep_core:
        filters.append(_and(real_only))
    return filters


def _add_optional(clauses: list[dict[str, Any]], key: str, value: Any) -> None:
    if value not in (None, "", [], {}):
        clauses.append({key: value})


def _rating_filter(constraints: dict[str, Any]) -> list[dict[str, Any]]:
    if "rating_min" in constraints or "rating_max" in constraints:
        result = []
        if constraints.get("rating_min") is not None:
            result.append({"rating": {"$gte": float(constraints["rating_min"])}})
        if constraints.get("rating_max") is not None:
            result.append({"rating": {"$lte": float(constraints["rating_max"])}})
        return result
    if constraints.get("rating") is not None:
        rating = float(constraints["rating"])
        return [{"rating": {"$gte": max(1.0, rating - 0.5)}}, {"rating": {"$lte": min(5.0, rating + 0.5)}}]
    return []


def _and(clauses: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned = [{key: value for key, value in clause.items() if value not in (None, "", [], {})} for clause in clauses]
    cleaned = [clause for clause in cleaned if clause]
    if len(cleaned) == 1:
        return cleaned[0]
    return {"$and": cleaned}
