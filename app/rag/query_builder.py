from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas.product import ProductProfile


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    original_query: str
    sub_queries: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


def build_product_queries(profile: ProductProfile, constraints: dict[str, Any] | None = None) -> BuiltQuery:
    constraints = constraints or {}
    base = _parts(
        profile.category,
        profile.description,
        " ".join(profile.features[:8]),
        " ".join(profile.materials[:4]),
        " ".join(profile.use_scenarios[:5]),
        " ".join(profile.target_audience[:5]),
        profile.target_market,
        _decimal(profile.target_price),
        _constraint_text(constraints),
    )
    if not base:
        base = _parts(profile.name, profile.category, profile.target_market) or "product functions parameters risks"
    topics = [
        "product functions and parameters",
        "target usage scenarios",
        "material safety cleaning maintenance",
        "durability risks limitations",
        "price positioning market compatibility",
        "competitor differentiation",
    ]
    sub_queries = [_trim(f"{topic}: {base}") for topic in topics]
    return BuiltQuery(
        original_query=_trim(f"product market analysis evidence: {base}"),
        sub_queries=sub_queries,
        topics=topics,
    )


def build_review_queries(profile: ProductProfile, constraints: dict[str, Any] | None = None) -> BuiltQuery:
    constraints = constraints or {}
    base = _parts(
        profile.category,
        profile.target_market,
        " ".join(profile.target_audience[:5]),
        " ".join(profile.use_scenarios[:5]),
        _constraint_text(constraints),
    )
    if not base:
        base = _parts(profile.name, profile.category, profile.target_market) or "customer review feedback"
    topics = [
        "positive usage experience",
        "durability complaints",
        "size or fit problems",
        "cleaning difficulty",
        "odor issues",
        "installation problems",
        "pet acceptance",
        "value for money",
        "safety concerns",
        "customer expectations",
    ]
    sub_queries = [_trim(f"{topic}: {base}") for topic in topics]
    return BuiltQuery(original_query=_trim(f"review insight evidence: {base}"), sub_queries=sub_queries, topics=topics)


def _parts(*items: object) -> str:
    values = []
    for item in items:
        text = str(item or "").strip()
        if text and text.lower() not in {"none", "[]", "{}"}:
            values.append(text)
    return _trim(" ".join(values))


def _constraint_text(constraints: dict[str, Any]) -> str:
    allowed = ("rating", "verified_purchase", "marketplace", "target_market", "language", "category")
    values = [f"{key}={constraints[key]}" for key in allowed if constraints.get(key) not in (None, "", [], {})]
    return " ".join(values)


def _decimal(value: Decimal | None) -> str:
    return f"target price {value}" if value is not None else ""


def _trim(value: str, limit: int = 900) -> str:
    return " ".join(value.split())[:limit].strip()
