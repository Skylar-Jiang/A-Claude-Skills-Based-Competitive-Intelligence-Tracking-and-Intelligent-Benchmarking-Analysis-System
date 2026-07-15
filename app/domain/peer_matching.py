from __future__ import annotations

import json
import re
from decimal import Decimal
from math import sqrt
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml
from pydantic import BaseModel, Field

from app.schemas.common import DataGap
from app.schemas.product import ProductProfile

TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
GENERIC_TOKENS = {
    "a",
    "an",
    "and",
    "automatic",
    "for",
    "indoor",
    "of",
    "pet",
    "pets",
    "product",
    "supplies",
    "the",
    "with",
}


class CandidateProductSignature(BaseModel):
    product_id: str
    name: str
    category: str
    description: str
    features: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    use_scenarios: list[str] = Field(default_factory=list)
    target_species: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    vision_summary: str = ""
    target_price: Decimal | None = None

    @classmethod
    def from_product(
        cls,
        product: ProductProfile,
        *,
        vision_summary: str = "",
    ) -> CandidateProductSignature:
        attributes = dict(product.attributes)
        details = attributes.pop("details", {})
        parameters = {**attributes, **(details if isinstance(details, dict) else {})}
        species = _target_species(parameters, product.target_audience)
        return cls(
            product_id=product.product_id,
            name=product.name,
            category=product.category,
            description=product.description,
            features=product.features,
            parameters=parameters,
            use_scenarios=product.use_scenarios,
            target_species=species,
            target_audience=product.target_audience,
            vision_summary=vision_summary,
            target_price=product.target_price,
        )

    def matching_text(self) -> str:
        values = [
            self.name,
            self.category,
            self.description,
            *self.features,
            *self.use_scenarios,
            *self.target_species,
            self.vision_summary,
            *(f"{key}: {value}" for key, value in sorted(self.parameters.items())),
        ]
        return "\n".join(str(value) for value in values if value)


class CatalogProduct(BaseModel):
    parent_asin: str
    title: str
    description: str = ""
    features: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    main_category: str = ""
    target_species: list[str] = Field(default_factory=list)
    price: Decimal | None = None
    average_rating: float | None = None
    rating_number: int | None = None
    source_line: int
    image_url: str | None = None

    def matching_text(self) -> str:
        values = [
            self.title,
            self.description,
            *self.features,
            *self.categories,
            *self.target_species,
            *(f"{key}: {value}" for key, value in sorted(self.details.items())),
        ]
        return "\n".join(str(value) for value in values if value)


class PeerMatchConfig(BaseModel):
    matcher_version: str = "peer-matcher-v2"
    accessory_terms: list[str]
    prefilter_limit: int = Field(default=300, ge=100, le=300)
    rerank_limit: int = Field(default=40, ge=20, le=50)
    final_peer_limit: int = Field(default=20, ge=10, le=30)
    minimum_rule_score: float = Field(default=0.2, ge=0, le=1)
    minimum_semantic_score: float = Field(default=0.45, ge=0, le=1)
    minimum_peer_count: int = Field(default=10, ge=1, le=30)


class RuleCandidate(BaseModel):
    product: CatalogProduct
    rule_score: float = Field(ge=0, le=1)
    match_reason: str
    is_accessory: bool = False


class RulePrefilterResult(BaseModel):
    candidates: list[RuleCandidate] = Field(default_factory=list)
    excluded_accessory_count: int = 0


class PeerMatch(BaseModel):
    peer_group_id: str
    peer_product_id: str
    parent_asin: str
    match_score: float = Field(ge=0, le=1)
    match_reason: str
    is_accessory: bool = False
    match_method: str
    product: CatalogProduct


class PeerMatchResult(BaseModel):
    peer_group_id: str
    peers: list[PeerMatch] = Field(default_factory=list)
    prefilter_count: int
    rerank_count: int
    excluded_accessory_count: int
    insufficient_peer_products: bool = False
    data_gaps: list[DataGap] = Field(default_factory=list)
    match_metadata: dict[str, Any] = Field(default_factory=dict)


class PeerMatcher:
    def __init__(self, embedding_function: Any, config: PeerMatchConfig) -> None:
        self.embedding_function = embedding_function
        self.config = config

    def match(
        self,
        signature: CandidateProductSignature,
        products: list[CatalogProduct],
        *,
        group_context: str = "",
    ) -> PeerMatchResult:
        prefiltered = rule_prefilter(signature, products, self.config)
        if not prefiltered.candidates:
            raise ValueError("No complete peer products passed deterministic prefiltering")
        texts = [signature.matching_text(), *[item.product.matching_text() for item in prefiltered.candidates]]
        vectors = self._embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("Embedding result count does not match peer candidate count")
        query_vector = vectors[0]
        embedding_model = _embedding_model_name(self.embedding_function)
        scored = []
        for candidate, vector in zip(prefiltered.candidates, vectors[1:], strict=True):
            semantic_score = max(0.0, min(1.0, _cosine(query_vector, vector)))
            if semantic_score < self.config.minimum_semantic_score:
                continue
            match_score = 0.6 * semantic_score + 0.4 * candidate.rule_score
            scored.append((match_score, semantic_score, candidate))
        if not scored:
            raise ValueError("No complete peer products passed the semantic similarity threshold")
        scored.sort(key=lambda item: (-item[0], item[2].product.parent_asin))
        reranked = scored[: self.config.rerank_limit]
        selected = reranked[: self.config.final_peer_limit]
        peer_group_id = _peer_group_id(
            signature,
            self.config,
            selected,
            embedding_model=embedding_model,
            group_context=group_context,
        )
        peers = [
            PeerMatch(
                peer_group_id=peer_group_id,
                peer_product_id=str(uuid5(NAMESPACE_URL, f"tradepilot:peer-product:{candidate.product.parent_asin}")),
                parent_asin=candidate.product.parent_asin,
                match_score=round(match_score, 6),
                match_reason=f"{candidate.match_reason}; semantic similarity={semantic_score:.3f}",
                is_accessory=False,
                match_method="rules+embedding",
                product=candidate.product,
            )
            for match_score, semantic_score, candidate in selected
        ]
        insufficient_peer_products = len(peers) < self.config.minimum_peer_count
        data_gaps = (
            [
                DataGap(
                    code="insufficient_peer_products",
                    field="peer_group",
                    reason=(
                        f"Only {len(peers)} peer products met the configured rule and semantic thresholds; "
                        "lower-quality products were not added to reach the preferred sample size."
                    ),
                    required_for="broader peer-market coverage",
                )
            ]
            if insufficient_peer_products
            else []
        )
        return PeerMatchResult(
            peer_group_id=peer_group_id,
            peers=peers,
            prefilter_count=len(prefiltered.candidates),
            rerank_count=len(reranked),
            excluded_accessory_count=prefiltered.excluded_accessory_count,
            insufficient_peer_products=insufficient_peer_products,
            data_gaps=data_gaps,
            match_metadata={
                "matcher_version": self.config.matcher_version,
                "embedding_model": embedding_model,
                "minimum_rule_score": self.config.minimum_rule_score,
                "minimum_semantic_score": self.config.minimum_semantic_score,
                "minimum_peer_count": self.config.minimum_peer_count,
                "acceptance_rule": (
                    f"rule_score>={self.config.minimum_rule_score:g} and "
                    f"semantic_score>={self.config.minimum_semantic_score:g}"
                ),
            },
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if hasattr(self.embedding_function, "embed_documents"):
            return self.embedding_function.embed_documents(texts)
        return self.embedding_function(texts)


def load_peer_match_config(path: Path) -> PeerMatchConfig:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Peer matching config must be a mapping: {path}")
    return PeerMatchConfig.model_validate(value)


def rule_prefilter(
    signature: CandidateProductSignature,
    products: list[CatalogProduct],
    config: PeerMatchConfig,
) -> RulePrefilterResult:
    signature_tokens = _tokens(signature.matching_text())
    signature_title_tokens = _tokens(signature.name)
    signature_feature_tokens = _tokens(" ".join(signature.features + signature.use_scenarios))
    signature_category_tokens = _tokens(signature.category)
    signature_species = {item.casefold() for item in signature.target_species}
    candidates: list[RuleCandidate] = []
    excluded_accessory_count = 0
    for product in products:
        if _is_accessory(product, config.accessory_terms):
            excluded_accessory_count += 1
            continue
        product_tokens = _tokens(product.matching_text())
        title_overlap = signature_title_tokens & _tokens(product.title)
        feature_overlap = signature_feature_tokens & _tokens(" ".join(product.features) + " " + product.description)
        category_overlap = signature_category_tokens & _tokens(" ".join(product.categories))
        all_overlap = signature_tokens & product_tokens
        species_match = bool(signature_species & {item.casefold() for item in product.target_species})
        score = min(
            1.0,
            0.38 * _overlap_ratio(title_overlap, signature_title_tokens)
            + 0.22 * _overlap_ratio(feature_overlap, signature_feature_tokens)
            + 0.12 * _overlap_ratio(category_overlap, signature_category_tokens)
            + 0.13 * _overlap_ratio(all_overlap, signature_tokens)
            + (0.10 if species_match else 0.0)
            + 0.05 * _price_similarity(signature.target_price, product.price),
        )
        if score < config.minimum_rule_score or not (title_overlap or feature_overlap):
            continue
        matched = sorted(title_overlap | feature_overlap | category_overlap)
        reason = "product keywords: " + ", ".join(matched[:8])
        if species_match:
            reason += "; target species matched"
        candidates.append(
            RuleCandidate(
                product=product,
                rule_score=round(score, 6),
                match_reason=reason,
            )
        )
    candidates.sort(
        key=lambda item: (-item.rule_score, -int(item.product.rating_number or 0), item.product.parent_asin)
    )
    return RulePrefilterResult(
        candidates=candidates[: config.prefilter_limit],
        excluded_accessory_count=excluded_accessory_count,
    )


def _target_species(parameters: dict[str, Any], target_audience: list[str]) -> list[str]:
    raw = parameters.get("Target Species") or parameters.get("target_species") or ""
    values = re.split(r"[,;/]", str(raw)) if raw else []
    values.extend(item for item in target_audience if any(token in item.casefold() for token in ("cat", "dog")))
    return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_PATTERN.findall(text) if token.casefold() not in GENERIC_TOKENS}


def _is_accessory(product: CatalogProduct, terms: list[str]) -> bool:
    accessory_text = " ".join([product.title, *product.categories])
    haystack = " ".join(TOKEN_PATTERN.findall(accessory_text.casefold()))
    padded = f" {haystack} "
    return any(
        f" {' '.join(TOKEN_PATTERN.findall(term.casefold()))} " in padded
        for term in terms
        if TOKEN_PATTERN.findall(term.casefold())
    )


def _overlap_ratio(overlap: set[str], reference: set[str]) -> float:
    return len(overlap) / max(1, min(len(reference), 8))


def _price_similarity(target: Decimal | None, candidate: Decimal | None) -> float:
    if target is None or candidate is None or target <= 0 or candidate <= 0:
        return 0.0
    difference = abs(float(target - candidate)) / float(target)
    return max(0.0, 1.0 - min(difference, 1.0))


def _peer_group_id(
    signature: CandidateProductSignature,
    config: PeerMatchConfig,
    selected: list[tuple[float, float, RuleCandidate]],
    *,
    embedding_model: str,
    group_context: str,
) -> str:
    payload = {
        "candidate_signature": _stable_value(
            signature.model_dump(mode="json", exclude={"product_id"})
        ),
        "match_config": config.model_dump(mode="json"),
        "embedding_model": embedding_model,
        "catalog_context": group_context,
        "selected_parent_asins": sorted(candidate.product.parent_asin for _, _, candidate in selected),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, f"tradepilot:peer-analysis-group:{canonical}"))


def _embedding_model_name(embedding_function: Any) -> str:
    name = getattr(embedding_function, "name", None)
    if callable(name):
        value = name()
        if value:
            return str(value)
    return type(embedding_function).__name__


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).casefold(): _stable_value(item) for key, item in value.items()}
    if isinstance(value, list):
        normalized = [_stable_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    limit = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(limit))
    left_norm = sqrt(sum(value * value for value in left[:limit]))
    right_norm = sqrt(sum(value * value for value in right[:limit]))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
