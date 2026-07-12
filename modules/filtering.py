"""Automatic filtering, enrichment, and lightweight classification for raw intelligence."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from modules.data_loader import IntelligenceRecord, normalize_source_url

MIN_CONTENT_LENGTH = 80

NOISE_KEYWORDS = {
    "cookie",
    "cookies",
    "subscribe",
    "newsletter",
    "sign in",
    "sign up",
    "all rights reserved",
    "privacy policy",
    "terms of service",
    "advertisement",
    "enable javascript",
}

DIMENSION_KEYWORDS = {
    "price": [
        "price",
        "discount",
        "价格",
        "单价",
        "批发价",
        "到货价",
        "产地价",
        "市场价",
        "价差",
        "行情",
        "涨价",
        "降价",
        "猪肉",
        "牛肉",
        "鸡蛋",
        "黄瓜",
        "白菜",
        "番茄",
        "苹果",
    ],
    "new_product": [
        "新产季",
        "新品种",
        "新产区",
        "新规格",
        "新批次",
        "上市",
        "到货",
        "供应",
        "产地",
        "规格",
    ],
    "sentiment": [
        "complaint",
        "issue",
        "risk",
        "不新鲜",
        "缺斤少两",
        "抽检",
        "不合格",
        "农残",
        "兽残",
        "腐损",
        "供应短缺",
        "物流",
        "天气",
        "监管",
        "变质",
        "投诉",
        "风险",
        "风险",
    ],
}


def normalize_url(url: str) -> str:
    return normalize_source_url(url)


def infer_dimension(text: str, fallback: str = "general") -> str:
    lowered = text.lower()
    scores = {
        dimension: sum(1 for keyword in keywords if keyword.lower() in lowered)
        for dimension, keywords in DIMENSION_KEYWORDS.items()
    }
    best_dimension, score = max(scores.items(), key=lambda item: item[1])
    return best_dimension if score > 0 else fallback


def is_noise_record(record: IntelligenceRecord, keywords: list[str]) -> tuple[bool, str]:
    text = f"{record.title} {record.content}".lower()
    if record.source_type == "csv" and len(text.strip()) >= 20:
        pass
    elif len(record.content) < MIN_CONTENT_LENGTH:
        return True, "content_too_short"
    if not record.source_url:
        return True, "missing_source_url"
    if keywords and not any(keyword.lower() in text for keyword in keywords):
        return True, "keyword_not_matched"
    noise_hits = sum(1 for keyword in NOISE_KEYWORDS if keyword in text)
    if noise_hits >= 4 and record.source_type not in {"webpage", "forum"}:
        return True, "too_many_boilerplate_terms"
    return False, ""


def filter_and_enrich_records(
    records: Iterable[IntelligenceRecord],
    keywords: list[str] | None = None,
    fallback_dimension: str = "general",
) -> tuple[list[IntelligenceRecord], list[dict[str, str]]]:
    keywords = keywords or []
    accepted: list[IntelligenceRecord] = []
    rejected: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for record in records:
        normalized = normalize_url(record.source_url)
        if normalized in seen_urls:
            rejected.append({"source_url": record.source_url, "reason": "duplicate_url"})
            continue
        is_noise, reason = is_noise_record(record, keywords)
        if is_noise:
            rejected.append({"source_url": record.source_url, "reason": reason})
            continue
        seen_urls.add(normalized)
        inferred_dimension = infer_dimension(
            f"{record.title} {record.content}",
            fallback=record.dimension if record.dimension != "general" else fallback_dimension,
        )
        accepted.append(replace(record, source_url=normalized, dimension=inferred_dimension))

    return accepted, rejected
