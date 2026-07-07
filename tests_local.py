import os
import tempfile
from pathlib import Path

import modules.rag_chain as rag_module
from modules.agent_core import registry_snapshot
from modules.dashboard import comparison_data, competitor_summary, risk_tags_view
from modules.data_loader import load_csv
from modules.llm_client import ModelConfig, parse_json_object
from modules.memory_store import ConversationMemory
from modules.rag_chain import (
    DEFAULT_EMBEDDING_MODEL,
    HuggingFaceEmbeddingFunction,
    collection_name_for,
    get_embedding_settings,
    SimpleRAGIndex,
    build_project_index,
)
from modules.skill_core import list_skills, run_skill
from modules.source_manager import load_sources, run_collection_job
from modules.tools import ingest_csv_tool, retrieve_evidence_tool


class TestEmbeddingFunction:
    @staticmethod
    def name():
        return "test_embedding"

    def embed_query(self, input):
        texts = input if isinstance(input, list) else [input]
        return self(texts)

    def __call__(self, input):
        vectors = []
        for text in input:
            base = float((sum(ord(char) for char in text) % 17) + 1)
            vectors.append([base, base / 2, base / 3, base / 5])
        return vectors


def with_test_rag_embedding(func):
    old_create = rag_module.create_embedding_function
    old_chroma_dir = rag_module.CHROMA_DIR
    old_index_path = rag_module.INDEX_PATH
    temp_dir = Path(tempfile.mkdtemp(prefix="rag-test-"))
    try:
        rag_module.create_embedding_function = lambda: TestEmbeddingFunction()
        rag_module.CHROMA_DIR = temp_dir / "chroma"
        rag_module.INDEX_PATH = temp_dir / "rag_index.json"
        return func()
    finally:
        rag_module.create_embedding_function = old_create
        rag_module.CHROMA_DIR = old_chroma_dir
        rag_module.INDEX_PATH = old_index_path


def test_data_and_rag():
    def run():
        records = load_csv("data/raw/hema_price_manual.csv")
        assert len(records) >= 3
        assert all(record.source_url for record in records)

        result = ingest_csv_tool("data/raw/hema_price_manual.csv")
        assert result["count"] >= 3

        index = build_project_index()
        assert len(index.chunks) >= 6

        evidence = retrieve_evidence_tool("盒马 鸡蛋 牛奶 番茄 价格", competitor="盒马", top_k=3)
        assert evidence
        assert evidence[0]["source_url"]

    with_test_rag_embedding(run)


def test_rag_uses_huggingface_embedding_defaults():
    settings = get_embedding_settings({})
    assert settings["provider"] == "huggingface"
    assert settings["model_name"] == DEFAULT_EMBEDDING_MODEL
    assert settings["device"] == "cpu"
    assert settings["normalize_embeddings"] is True
    assert collection_name_for(settings) == "competitor_intelligence_baai_bge_m3"
    assert callable(HuggingFaceEmbeddingFunction.embed_query)
    assert HuggingFaceEmbeddingFunction.name() == "huggingface"


def test_deepseek_env_fallback_is_openai_compatible():
    keys = [
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "MODEL_FAST",
        "MODEL_ANALYSIS",
        "MODEL_REPORT",
    ]
    old = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["OPENAI_API_KEY"] = ""
        os.environ["OPENAI_BASE_URL"] = ""
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com/v1"
        os.environ["MODEL_FAST"] = "deepseek-v4-flash"
        os.environ["MODEL_ANALYSIS"] = "deepseek-v4-pro"
        os.environ["MODEL_REPORT"] = "deepseek-v4-pro"
        config = ModelConfig.from_env()
        assert config.api_key == "sk-test"
        assert config.base_url == "https://api.deepseek.com/v1"
        assert config.model_fast == "deepseek-v4-flash"
        assert config.model_analysis == "deepseek-v4-pro"
        assert config.model_report == "deepseek-v4-pro"
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_conversation_memory_records_turns():
    memory = ConversationMemory()
    memory.add_user_message("分析盒马价格变化")
    memory.add_ai_message("已记录价格分析结果")
    messages = memory.get_all_messages()
    assert messages == [
        {"role": "user", "content": "分析盒马价格变化"},
        {"role": "assistant", "content": "已记录价格分析结果"},
    ]


def test_collection_and_dashboard():
    sources = load_sources()
    assert sources
    job = run_collection_job(force=True, use_llm_filter=False)
    assert job["source_count"] >= 1
    assert competitor_summary()
    assert comparison_data()["dimensions"] == ["price", "new_product", "sentiment"]
    assert isinstance(risk_tags_view(), list)


def test_agents_registered():
    names = {item["name"] for item in registry_snapshot()}
    assert {"price_monitor", "new_product", "sentiment"} <= names


def test_json_parser():
    parsed = parse_json_object('```json\n{"ok": true, "items": [1]}\n```')
    assert parsed["ok"] is True


def test_skills_mock_provider():
    def run():
        skill_names = {item["name"] for item in list_skills()}
        assert {
            "price_monitor_skill",
            "product_update_skill",
            "sentiment_risk_skill",
            "trend_compare_skill",
            "report_generation_skill",
            "orchestrator_skill",
        } <= skill_names
        result = run_skill(
            "orchestrator_skill",
            {
                "competitor": "盒马",
                "query": "分析盒马近期肉蛋奶和基础蔬菜的价格变化、促销活动和负面舆情",
                "top_k": 2,
                "provider": "mock",
            },
        )
        assert result["competitor"] == "盒马"
        assert "analysis_result" in result
        assert "insufficient_evidence" in result

    with_test_rag_embedding(run)


if __name__ == "__main__":
    test_data_and_rag()
    test_rag_uses_huggingface_embedding_defaults()
    test_deepseek_env_fallback_is_openai_compatible()
    test_conversation_memory_records_turns()
    test_collection_and_dashboard()
    test_agents_registered()
    test_json_parser()
    test_skills_mock_provider()
    print("local tests passed")
