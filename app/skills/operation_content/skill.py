from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.schemas.product import ProductProfile

TITLE_PREFIX = "CONTENT_TITLE: "
BULLET_PREFIX = "CONTENT_BULLET: "
DESCRIPTION_PREFIX = "CONTENT_DESCRIPTION: "
KEYWORDS_PREFIX = "CONTENT_KEYWORDS: "
CUSTOMER_SERVICE_PREFIX = "CUSTOMER_SERVICE_"


class TitleRules(BaseModel):
    max_chars: int = Field(ge=40, le=250)


class BulletRules(BaseModel):
    count: int = Field(ge=3, le=8)
    max_chars: int = Field(ge=80, le=500)


class DescriptionRules(BaseModel):
    max_chars: int = Field(ge=200, le=3000)
    template: str


class KeywordRules(BaseModel):
    max_items: int = Field(ge=3, le=30)


class ContentRules(BaseModel):
    title: TitleRules
    bullets: BulletRules
    description: DescriptionRules
    keywords: KeywordRules
    forbidden_claims: list[str] = Field(default_factory=list)
    customer_service_templates: dict[str, str] = Field(default_factory=dict)


class SkillConfig(BaseModel):
    name: str
    version: str
    owner: str
    enabled: bool
    description: str
    rules: ContentRules


@dataclass(frozen=True)
class ContentPolicyIssue:
    code: str
    message: str
    blocking: bool = False


@dataclass(frozen=True)
class OperationContent:
    title: str
    bullets: tuple[str, ...]
    description: str
    keywords: tuple[str, ...]
    customer_service: dict[str, str]

    def as_next_steps(self) -> list[str]:
        steps = [f"{TITLE_PREFIX}{self.title}"]
        steps.extend(f"{BULLET_PREFIX}{bullet}" for bullet in self.bullets)
        steps.append(f"{DESCRIPTION_PREFIX}{self.description}")
        steps.append(f"{KEYWORDS_PREFIX}{', '.join(self.keywords)}")
        steps.extend(
            f"{CUSTOMER_SERVICE_PREFIX}{name.upper()}: {text}"
            for name, text in sorted(self.customer_service.items())
        )
        return steps

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "bullets": list(self.bullets),
            "description": self.description,
            "keywords": list(self.keywords),
            "customer_service": dict(self.customer_service),
        }


class OperationContentSkill:
    """Versioned deterministic copy rules for the operations workflow."""

    def __init__(self, config: SkillConfig) -> None:
        if not config.enabled:
            raise ValueError("operation content skill is disabled")
        self.config = config

    @classmethod
    def from_default(cls) -> OperationContentSkill:
        return cls.from_yaml(Path(__file__).with_name("skill.yaml"))

    @classmethod
    def from_yaml(cls, path: Path) -> OperationContentSkill:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(SkillConfig.model_validate(payload))

    def build(self, *, product: ProductProfile, positioning: str) -> OperationContent:
        rules = self.config.rules
        product_name = self._clean(product.name) or self._clean(product.category) or "Product"
        market = self._clean(product.target_market) or "the selected market"
        audience = self._clean(product.target_audience[0]) if product.target_audience else "intended buyers"
        feature = self._first_clean(product.features) or "the supplied product features"
        scenario = self._first_clean(product.use_scenarios) or "the intended use scenario"

        title_parts = self._unique(
            [product_name, feature, f"For {audience}", f"{market} Market"]
        )
        title = self._truncate(" | ".join(title_parts), rules.title.max_chars)

        bullet_candidates = [
            f"PRODUCT FOCUS: {self._clean(positioning)}",
            f"KEY FEATURE: {feature}.",
            f"USE SCENARIO: Designed around {scenario}.",
            "BUYER GUIDANCE: Confirm listed specifications, compatibility, and use limits before purchase.",
            "SUPPORT: Contact customer service with the order details for product-specific assistance.",
        ]
        bullets = tuple(
            self._truncate(self._clean(item), rules.bullets.max_chars)
            for item in bullet_candidates[: rules.bullets.count]
        )

        feature_sentence = f"The supplied profile identifies {feature} as a feature."
        scenario_sentence = f"The intended use context is {scenario}."
        description = rules.description.template.format(
            product_name=product_name,
            audience=audience,
            market=market,
            feature_sentence=feature_sentence,
            scenario_sentence=scenario_sentence,
        )
        description = self._truncate(self._clean(description), rules.description.max_chars)

        keyword_sources = [
            product.name,
            product.category,
            *product.features,
            *product.use_scenarios,
            *product.target_audience,
            product.target_market,
        ]
        keywords = self._keywords(keyword_sources, rules.keywords.max_items)
        if not keywords:
            keywords = (product_name.casefold(),)

        format_values = {"product_name": product_name, "market": market}
        customer_service = {
            name: self._clean(template.format(**format_values))
            for name, template in rules.customer_service_templates.items()
        }
        return OperationContent(
            title=title,
            bullets=bullets,
            description=description,
            keywords=keywords,
            customer_service=customer_service,
        )

    def extract(self, steps: list[str]) -> OperationContent | None:
        title = ""
        bullets: list[str] = []
        description = ""
        keywords: tuple[str, ...] = ()
        customer_service: dict[str, str] = {}
        for step in steps:
            if step.startswith(TITLE_PREFIX):
                title = step.removeprefix(TITLE_PREFIX).strip()
            elif step.startswith(BULLET_PREFIX):
                bullets.append(step.removeprefix(BULLET_PREFIX).strip())
            elif step.startswith(DESCRIPTION_PREFIX):
                description = step.removeprefix(DESCRIPTION_PREFIX).strip()
            elif step.startswith(KEYWORDS_PREFIX):
                keywords = tuple(
                    item.strip() for item in step.removeprefix(KEYWORDS_PREFIX).split(",") if item.strip()
                )
            elif step.startswith(CUSTOMER_SERVICE_PREFIX) and ":" in step:
                label, text = step.split(":", 1)
                name = label.removeprefix(CUSTOMER_SERVICE_PREFIX).strip().casefold()
                customer_service[name] = text.strip()
        if not any((title, bullets, description, keywords, customer_service)):
            return None
        return OperationContent(
            title=title,
            bullets=tuple(bullets),
            description=description,
            keywords=keywords,
            customer_service=customer_service,
        )

    def audit(self, content: OperationContent | None) -> list[ContentPolicyIssue]:
        if content is None:
            return [
                ContentPolicyIssue(
                    code="content_bundle_missing",
                    message="Generate the title, bullets, description, keywords, and customer-service drafts.",
                )
            ]

        rules = self.config.rules
        issues: list[ContentPolicyIssue] = []
        if not content.title:
            issues.append(ContentPolicyIssue("content_title_missing", "Generate a product title."))
        elif len(content.title) > rules.title.max_chars:
            issues.append(
                ContentPolicyIssue(
                    "content_title_too_long",
                    f"Shorten the title to at most {rules.title.max_chars} characters.",
                )
            )
        if len(content.bullets) != rules.bullets.count:
            issues.append(
                ContentPolicyIssue(
                    "content_bullet_count",
                    f"Generate exactly {rules.bullets.count} product bullets.",
                )
            )
        for index, bullet in enumerate(content.bullets):
            if len(bullet) > rules.bullets.max_chars:
                issues.append(
                    ContentPolicyIssue(
                        "content_bullet_too_long",
                        f"Shorten content bullet {index + 1} to at most {rules.bullets.max_chars} characters.",
                    )
                )
        if not content.description:
            issues.append(ContentPolicyIssue("content_description_missing", "Generate a product description."))
        if not content.keywords:
            issues.append(ContentPolicyIssue("content_keywords_missing", "Generate advertising keywords."))
        elif len(content.keywords) > rules.keywords.max_items:
            issues.append(
                ContentPolicyIssue(
                    "content_keyword_count",
                    f"Limit advertising keywords to {rules.keywords.max_items} items.",
                )
            )

        missing_templates = sorted(
            set(rules.customer_service_templates).difference(content.customer_service)
        )
        if missing_templates:
            issues.append(
                ContentPolicyIssue(
                    "customer_service_template_missing",
                    f"Generate customer-service templates for: {', '.join(missing_templates)}.",
                )
            )

        combined = "\n".join(
            [
                content.title,
                *content.bullets,
                content.description,
                *content.keywords,
                *content.customer_service.values(),
            ]
        ).casefold()
        for claim in rules.forbidden_claims:
            if claim.casefold() in combined:
                issues.append(
                    ContentPolicyIssue(
                        "forbidden_marketing_claim",
                        f"Remove the unsupported or prohibited expression: {claim!r}.",
                        blocking=True,
                    )
                )
        return issues

    def _clean(self, value: str) -> str:
        text = " ".join(value.split())
        for claim in self.config.rules.forbidden_claims:
            text = re.sub(re.escape(claim), "", text, flags=re.IGNORECASE)
        return " ".join(text.replace("||", "|").split()).strip(" |,;-")

    def _first_clean(self, values: list[str]) -> str:
        return next((cleaned for value in values if (cleaned := self._clean(value))), "")

    @staticmethod
    def _truncate(value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return f"{value[: max_chars - 3].rstrip()}..."

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _keywords(self, sources: list[str], max_items: int) -> tuple[str, ...]:
        stopwords = {"and", "for", "the", "with", "from", "this", "that", "demo"}
        values: list[str] = []
        for source in sources:
            cleaned = self._clean(source)
            values.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]+|[\u4e00-\u9fff]{2,}", cleaned))
        unique = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized in stopwords or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
            if len(unique) == max_items:
                break
        return tuple(unique)


def content_values(content: OperationContent) -> list[Any]:
    """Return all content values for consumers that need a compact policy scan."""

    return [
        content.title,
        *content.bullets,
        content.description,
        *content.keywords,
        *content.customer_service.values(),
    ]
