from typing import Any

from app.core.config import Settings
from app.core.enums import DataMode
from app.schemas.analysis import AgentOutputRead, AnalysisRunRead

WORKFLOW_NODES = [
    ("input_validator", "输入校验", "校验任务模式与新商品输入。", 1, None),
    ("product_normalizer", "商品与 RAG 准备", "标准化商品并读取当前同行组证据。", 2, None),
    ("statistics_provider", "同类组统计", "计算同类商品组的结构化 SQL 指标。", 3, None),
    ("product_market_agent", "商品市场分析", "分析同类商品、价格、结构与差异化机会。", 4, "market_and_user"),
    ("user_insight_agent", "同类用户洞察", "仅分析选中同行商品的真实评论样本。", 4, "market_and_user"),
    ("operations_decision_agent", "运营决策", "综合并行分析生成证据约束的上市方案。", 5, None),
    ("evidence_audit_agent", "证据审校", "检查范围、数值、证据引用与假设标签。", 6, None),
    ("persist_and_export", "报告持久化", "保存状态、证据、耗时及 Markdown/JSON 报告。", 7, None),
]

WORKFLOW_EDGES = [
    ["input_validator", "product_normalizer"],
    ["product_normalizer", "statistics_provider"],
    ["statistics_provider", "product_market_agent"],
    ["statistics_provider", "user_insight_agent"],
    ["product_market_agent", "operations_decision_agent"],
    ["user_insight_agent", "operations_decision_agent"],
    ["operations_decision_agent", "evidence_audit_agent"],
    ["evidence_audit_agent", "operations_decision_agent"],
    ["evidence_audit_agent", "persist_and_export"],
]

AGENTS = {
    "ProductMarketAgent": (
        "商品市场分析",
        "分析同类商品多维基线与上市前验证项。",
        "deepseek",
        "model_analysis",
        "market_and_user",
    ),
    "UserInsightAgent": (
        "同类用户洞察",
        "分析同行商品评论中的需求、痛点与样本限制。",
        "deepseek",
        "model_analysis",
        "market_and_user",
    ),
    "OperationsDecisionAgent": (
        "运营决策",
        "综合并行结果形成证据约束的上市方案。",
        "qwen",
        "model_report",
        None,
    ),
    "EvidenceAuditAgent": ("证据审校", "审校同行范围、事实、数值、证据和假设。", "qwen", "model_fast", None),
}
NODE_AGENTS = {
    "product_market_agent": "ProductMarketAgent",
    "user_insight_agent": "UserInsightAgent",
    "operations_decision_agent": "OperationsDecisionAgent",
    "evidence_audit_agent": "EvidenceAuditAgent",
}


def workflow_metadata(settings: Settings) -> dict[str, Any]:
    nodes = []
    for name, display_name, responsibility, order, parallel_group in WORKFLOW_NODES:
        agent_name = NODE_AGENTS.get(name)
        agent = AGENTS.get(agent_name) if agent_name else None
        nodes.append(
            {
                "node_name": name,
                "display_name": display_name,
                "responsibility": responsibility,
                "execution_order": order,
                "parallel_group": parallel_group,
                "provider": agent[2] if agent else None,
                "model_name": getattr(settings, agent[3]) if agent else None,
            }
        )
    return {"nodes": nodes, "edges": WORKFLOW_EDGES, "audit_retry_limit": 1}


def agent_frontend_view(
    item: AgentOutputRead,
    *,
    run: AnalysisRunRead,
    settings: Settings,
) -> dict[str, Any]:
    display_name, responsibility, provider, model_field, parallel_group = AGENTS[item.agent_name]
    evidence_ids = item.output.get("evidence_ids", [])
    summary = next(
        (
            str(item.output[key])
            for key in ("product_summary", "insight_summary", "positioning", "status")
            if item.output.get(key)
        ),
        "",
    )
    return {
        **item.model_dump(mode="json"),
        "display_name": display_name,
        "responsibility": responsibility,
        "provider": provider,
        "model_name": getattr(settings, model_field),
        "real_model_called": (
            run.data_mode is DataMode.REAL and item.output.get("implementation_status") == "production"
        ),
        "parallel_group": parallel_group,
        "retry_count": run.retry_count,
        "token_usage": item.output.get("token_usage"),
        "evidence_ids": evidence_ids if isinstance(evidence_ids, list) else [],
        "output_summary": summary[:500],
    }
