from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import KnowledgeType
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile


@dataclass(slots=True)
class SufficiencyResult:
    sufficient: bool
    reasons: list[str] = field(default_factory=list)
    missing_evidence_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def assess_evidence_sufficiency(
    *,
    profile: ProductProfile,
    knowledge_type: KnowledgeType,
    evidence: list[EvidenceReference],
    min_evidence: int,
) -> SufficiencyResult:
    reasons: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []
    if len(evidence) < min_evidence:
        reasons.append(f"accepted_evidence_below_minimum:{len(evidence)}<{min_evidence}")
    if not evidence:
        missing.append(knowledge_type.value)
        return SufficiencyResult(False, reasons or ["no_evidence"], missing, warnings)
    product_matches = [item for item in evidence if item.metadata.get("product_id") == profile.product_id]
    if not product_matches:
        reasons.append("product_id_not_matched")
    if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE:
        text = " ".join(item.excerpt.lower() for item in evidence)
        if not any(token in text for token in ("feature", "parameter", "material", "size", "product title")):
            missing.append("product_function_or_parameter")
        if not any(token in text for token in ("risk", "warning", "safe", "durable", "limitation")):
            warnings.append("risk_or_limitation_evidence_limited")
    else:
        ratings = [float(item.metadata.get("rating", 0) or 0) for item in evidence]
        if not any(rating >= 4 for rating in ratings):
            warnings.append("positive_review_coverage_limited")
        if not any(0 < rating <= 2 for rating in ratings):
            warnings.append("negative_review_coverage_limited")
        review_ids = {str(item.metadata.get("review_id") or item.evidence_id) for item in evidence}
        if len(review_ids) < min(3, min_evidence):
            reasons.append("independent_review_coverage_limited")
    return SufficiencyResult(not reasons and not missing, reasons, missing, warnings)
