"""Formal evidence-grounded analysis chain built with LangChain runnables."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableLambda, RunnableSequence


def insufficient_evidence_result(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "competitor": payload.get("competitor", ""),
        "summary": "现有知识库没有检索到足够证据，无法形成可靠结论。",
        "findings": [],
        "suggestions": ["先采集或更新与问题相关的公开数据，再重新分析。"],
        "evidence": [],
        "insufficient_evidence": True,
        "mode": mode,
        "mock": mode == "mock",
        "reasoning_trace": {
            "framework": "langchain",
            "chain_type": "evidence_guard",
            "steps": ["validate_evidence", "stop_without_model_call"],
        },
    }


def mock_analysis_result(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = payload["evidence"]
    return {
        "competitor": payload.get("competitor", ""),
        "summary": "Mock 模式仅验证结构；未调用真实模型，不代表正式分析结论。",
        "findings": [],
        "suggestions": ["使用 mode=real 并配置有效模型凭据以生成正式分析。"],
        "evidence": evidence,
        "insufficient_evidence": False,
        "mode": "mock",
        "mock": True,
        "reasoning_trace": {
            "framework": "langchain",
            "chain_type": "mock_shortcut",
            "steps": ["validate_evidence", "explicit_mock_response"],
        },
    }


def run_evidence_analysis(
    llm: Any,
    system_prompt: str,
    payload: dict[str, Any],
    mode: str = "real",
    role: str = "analysis",
    max_tokens: int = 2200,
) -> dict[str, Any]:
    """Run the formal LangChain analysis path without silent mode fallback."""
    if mode not in {"real", "mock"}:
        raise ValueError("mode must be real or mock")
    evidence = payload.get("evidence") or []
    if not evidence:
        return insufficient_evidence_result(payload, mode)
    if mode == "mock":
        return mock_analysis_result({**payload, "evidence": evidence})

    def call_model(chain_payload: dict[str, Any]) -> dict[str, Any]:
        return llm.chat_json(system_prompt, chain_payload, role=role, max_tokens=max_tokens)

    def attach_contract(model_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(model_result, dict):
            raise ValueError("Model analysis result must be a JSON object")
        return {
            **model_result,
            "competitor": payload.get("competitor", ""),
            "evidence": evidence,
            "insufficient_evidence": False,
            "mode": "real",
            "mock": False,
            "reasoning_trace": {
                "framework": "langchain",
                "chain_type": "RunnableSequence",
                "steps": ["validate_evidence", "structured_llm_analysis", "attach_evidence_contract"],
                "evidence_chunk_ids": [item.get("chunk_id", "") for item in evidence],
            },
        }

    chain = RunnableLambda(lambda value: value) | RunnableLambda(call_model) | RunnableLambda(attach_contract)
    if not isinstance(chain, RunnableSequence):
        raise RuntimeError("Formal analysis chain was not composed as a LangChain RunnableSequence")
    return chain.invoke({**payload, "evidence": evidence})
