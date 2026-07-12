"""Plugin-style competitor intelligence agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from modules.analysis_chain import run_evidence_analysis
from modules.llm_client import OpenAICompatibleLLM
from modules.memory_store import append_trace, get_cached_result, make_cache_key, set_cached_result
from modules.prompts import (
    NEW_PRODUCT_PROMPT,
    PRICE_MONITOR_PROMPT,
    REPORT_GENERATION_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT,
)
from modules.tools import retrieve_evidence_tool

AGENT_REGISTRY: dict[str, type["BaseAgent"]] = {}


def merge_evidence(focused: list[dict[str, Any]], broad: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in focused[:1] + broad + focused[1:]:
        key = item.get("chunk_id") or item.get("source_url") or item.get("title")
        if key:
            merged[key] = item
    candidates = list(merged.values())
    selected: list[dict[str, Any]] = []
    seen_competitors = set()
    selected_keys = set()

    for item in candidates:
        competitor = item.get("competitor") or item.get("source_url") or item.get("title")
        key = item.get("chunk_id") or item.get("source_url") or item.get("title")
        if competitor in seen_competitors or not key:
            continue
        selected.append(item)
        seen_competitors.add(competitor)
        selected_keys.add(key)
        if len(selected) >= top_k:
            return selected

    for item in candidates:
        key = item.get("chunk_id") or item.get("source_url") or item.get("title")
        if key and key not in selected_keys:
            selected.append(item)
            selected_keys.add(key)
        if len(selected) >= top_k:
            break
    return selected


def register_agent(agent_cls: type["BaseAgent"]) -> type["BaseAgent"]:
    AGENT_REGISTRY[agent_cls.name] = agent_cls
    return agent_cls


class BaseAgent(ABC):
    name: str
    dimension: str
    prompt: str
    model_role = "analysis"

    def __init__(self, llm: OpenAICompatibleLLM | None = None):
        self.llm = llm or OpenAICompatibleLLM()

    @abstractmethod
    def build_query(self, competitor: str, question: str) -> str:
        """Build the retrieval query for this agent."""

    def analyze(self, competitor: str, question: str, top_k: int = 6) -> dict[str, Any]:
        cache_key = make_cache_key(self.name, competitor, question, top_k)
        cached = get_cached_result(cache_key)
        if cached:
            result = dict(cached["value"])
            result["cache_hit"] = True
            append_trace(
                {
                    "agent": self.name,
                    "competitor": competitor,
                    "question": question,
                    "cache_key": cache_key,
                    "cache_hit": True,
                    "steps": ["memory_cache_lookup"],
                }
            )
            return result

        query = self.build_query(competitor, question)
        focused_evidence = retrieve_evidence_tool(
            query=query,
            dimension=self.dimension,
            top_k=top_k,
            competitor=competitor,
        )
        broad_evidence = retrieve_evidence_tool(
            query=query,
            dimension=self.dimension,
            top_k=max(top_k * 3, top_k),
            competitor=None,
        )
        evidence = merge_evidence(focused_evidence, broad_evidence, top_k)
        payload = {
            "competitor": competitor,
            "question": question,
            "evidence": evidence,
        }
        result = run_evidence_analysis(self.llm, self.prompt, payload, mode="real", role=self.model_role)
        result["agent"] = self.name
        result["evidence"] = evidence
        result["cache_hit"] = False
        result["reasoning_trace"].update(
            {
                "agent_steps": ["build_agent_query", "retrieve_evidence_tool"],
                "tools": ["retrieve_evidence_tool"],
                "model_role": self.model_role,
            }
        )
        set_cached_result(cache_key, result)
        append_trace(
            {
                "agent": self.name,
                "competitor": competitor,
                "question": question,
                "cache_key": cache_key,
                "cache_hit": False,
                "steps": result["reasoning_trace"]["steps"],
                "tools": result["reasoning_trace"]["tools"],
                "model_role": self.model_role,
                "evidence_chunk_ids": result["reasoning_trace"]["evidence_chunk_ids"],
            }
        )
        return result


@register_agent
class PriceMonitorAgent(BaseAgent):
    name = "price_monitor"
    dimension = "price"
    prompt = PRICE_MONITOR_PROMPT

    def build_query(self, competitor: str, question: str) -> str:
        return f"{competitor} 批发价 到货价 产地价 市场价 价差 波动 异常价差 采购优势 {question}"


@register_agent
class NewProductAgent(BaseAgent):
    name = "new_product"
    dimension = "new_product"
    prompt = NEW_PRODUCT_PROMPT

    def build_query(self, competitor: str, question: str) -> str:
        return f"{competitor} 新产季 新品种 新产区 新规格 新批次 上市 到货 供应 {question}"


@register_agent
class SentimentAgent(BaseAgent):
    name = "sentiment"
    dimension = "sentiment"
    prompt = SENTIMENT_ANALYSIS_PROMPT

    def build_query(self, competitor: str, question: str) -> str:
        return f"{competitor} 抽检 食品安全 质量风险 供应短缺 天气 物流 监管通报 舆情 风险 {question}"


class AgentOrchestrator:
    def __init__(self, llm: OpenAICompatibleLLM | None = None):
        self.llm = llm or OpenAICompatibleLLM()

    def list_agents(self) -> list[str]:
        return sorted(AGENT_REGISTRY)

    def run_agent(self, agent_name: str, competitor: str, question: str, top_k: int = 6) -> dict[str, Any]:
        if agent_name not in AGENT_REGISTRY:
            raise ValueError(f"Unknown agent: {agent_name}")
        return AGENT_REGISTRY[agent_name](self.llm).analyze(competitor, question, top_k=top_k)

    def run_all(self, competitor: str, question: str, top_k: int = 6) -> dict[str, Any]:
        results = [
            agent_cls(self.llm).analyze(competitor, question, top_k=top_k)
            for agent_cls in AGENT_REGISTRY.values()
        ]
        return {"competitor": competitor, "question": question, "results": results}

    def generate_report(self, competitor: str, analyses: list[dict[str, Any]]) -> dict[str, Any]:
        cache_key = make_cache_key("report", competitor, json_dumps_for_cache(analyses), len(analyses))
        cached = get_cached_result(cache_key)
        if cached:
            report = dict(cached["value"])
            report["cache_hit"] = True
            append_trace(
                {
                    "agent": "report",
                    "competitor": competitor,
                    "cache_key": cache_key,
                    "cache_hit": True,
                    "steps": ["memory_cache_lookup"],
                }
            )
            return report

        evidence_by_id = {}
        for analysis in analyses:
            for item in analysis.get("evidence", []):
                evidence_by_id[item.get("chunk_id")] = item
        payload = {
            "competitor": competitor,
            "analyses": analyses,
            "evidence": list(evidence_by_id.values()),
        }
        report = run_evidence_analysis(
            self.llm,
            REPORT_GENERATION_PROMPT,
            payload,
            mode="real",
            role="report",
            max_tokens=1800,
        )
        report["evidence"] = payload["evidence"]
        report["cache_hit"] = False
        report["reasoning_trace"].update(
            {
                "report_steps": ["merge_agent_outputs", "dedupe_evidence"],
                "tools": ["report_generation_tool"],
                "model_role": "report",
            }
        )
        set_cached_result(cache_key, report)
        append_trace(
            {
                "agent": "report",
                "competitor": competitor,
                "cache_key": cache_key,
                "cache_hit": False,
                "steps": report["reasoning_trace"]["steps"],
                "tools": report["reasoning_trace"]["tools"],
                "model_role": "report",
                "evidence_chunk_ids": report["reasoning_trace"]["evidence_chunk_ids"],
            }
        )
        return report


def registry_snapshot() -> list[dict[str, str]]:
    return [
        {"name": agent_cls.name, "dimension": agent_cls.dimension, "model_role": agent_cls.model_role}
        for agent_cls in AGENT_REGISTRY.values()
    ]


def json_dumps_for_cache(value: Any) -> str:
    return __import__("json").dumps(value, ensure_ascii=False, sort_keys=True)
