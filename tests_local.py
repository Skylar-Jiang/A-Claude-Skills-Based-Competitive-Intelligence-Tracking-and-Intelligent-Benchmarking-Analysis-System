import csv
import os
import tempfile
from pathlib import Path

import modules.rag_chain as rag_module
import modules.agent_core as agent_module
import modules.tools as tools_module
from modules.data_loader import load_csv
from modules.agent_core import registry_snapshot
from modules.dashboard import comparison_data, competitor_summary, risk_tags_view
from modules.llm_client import ModelConfig, parse_json_object
from modules.memory_store import ConversationMemory
from modules.rag_chain import (
    DEFAULT_EMBEDDING_MODEL,
    EvidenceChunk,
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
    old_index_meta_path = rag_module.INDEX_META_PATH
    old_cache = tools_module._PROJECT_INDEX_CACHE
    temp_dir = Path(tempfile.mkdtemp(prefix="rag-test-"))
    try:
        rag_module.create_embedding_function = lambda: TestEmbeddingFunction()
        rag_module.CHROMA_DIR = temp_dir / "chroma"
        rag_module.INDEX_PATH = temp_dir / "rag_index.json"
        rag_module.INDEX_META_PATH = temp_dir / "rag_index_meta.json"
        tools_module._PROJECT_INDEX_CACHE = None
        return func()
    finally:
        rag_module.create_embedding_function = old_create
        rag_module.CHROMA_DIR = old_chroma_dir
        rag_module.INDEX_PATH = old_index_path
        rag_module.INDEX_META_PATH = old_index_meta_path
        tools_module._PROJECT_INDEX_CACHE = old_cache


def test_data_and_rag():
    def run():
        records = load_csv("data/processed/intelligence_records.csv")
        real_records = [record for record in records if record.source_name and record.published_at]
        assert len(real_records) >= 5
        assert all(record.source_url.startswith("https://www.agri.cn/") for record in real_records)

        result = ingest_csv_tool("data/raw/shouguang_cucumber_manual.csv")
        assert result["count"] >= 3
        assert result["mode"] == "sample"
        assert result["indexed"] is False

        index = build_project_index()
        assert len(index.chunks) >= 5

        evidence = retrieve_evidence_tool("黄瓜 农产品批发价格200指数 涨跌", top_k=3)
        assert evidence
        assert evidence[0]["source_name"] == "农业农村部市场与信息化司"
        assert evidence[0]["published_at"]

    with_test_rag_embedding(run)


def test_table_csv_comparison_retrieves_cross_competitor_evidence():
    def run():
        temp_dir = Path(tempfile.mkdtemp(prefix="table-rag-test-"))
        csv_path = temp_dir / "national_veg_prices.csv"
        rows = [
            {
                "quote_date": "2026-07-05",
                "province": "山东",
                "market": "寿光批发市场",
                "vegetable_name": "黄瓜",
                "commodity_id": "cucumber-sg-001",
                "current_price": "3.70",
                "previous_price": "3.90",
                "change_rate": "-5.13",
                "unit": "元/kg",
                "source_url": "https://price.example.local/shouguang-cucumber-20260705",
            },
            {
                "quote_date": "2026-07-05",
                "province": "河北",
                "market": "石家庄批发市场",
                "vegetable_name": "黄瓜",
                "commodity_id": "cucumber-hb-001",
                "current_price": "3.20",
                "previous_price": "3.10",
                "change_rate": "3.23",
                "unit": "元/kg",
                "source_url": "https://price.example.local/hebei-cucumber-20260705",
            },
            {
                "quote_date": "2026-07-05",
                "province": "辽宁",
                "market": "沈阳批发市场",
                "vegetable_name": "黄瓜",
                "commodity_id": "cucumber-ln-001",
                "current_price": "2.80",
                "previous_price": "3.00",
                "change_rate": "-6.67",
                "unit": "元/kg",
                "source_url": "https://price.example.local/liaoning-cucumber-20260705",
            },
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        records = load_csv(csv_path)
        assert {record.competitor for record in records} == {"山东黄瓜", "河北黄瓜", "辽宁黄瓜"}
        assert {record.dimension for record in records} == {"price"}

        old_loader = rag_module.load_project_records
        try:
            rag_module.load_project_records = lambda: records
            build_project_index()
            result = run_skill(
                "orchestrator_skill",
                {
                    "competitor": "山东黄瓜",
                    "query": "对比山东黄瓜、河北黄瓜和辽宁黄瓜的当前价格、涨跌幅和区域价差",
                    "top_k": 3,
                    "provider": "mock",
                },
            )
        finally:
            rag_module.load_project_records = old_loader

        competitors = {item.get("competitor") for item in result["evidence"]}
        assert {"山东黄瓜", "河北黄瓜", "辽宁黄瓜"} <= competitors

    with_test_rag_embedding(run)


def test_rag_uses_huggingface_embedding_defaults():
    settings = get_embedding_settings({})
    assert settings["provider"] == "huggingface"
    assert settings["model_name"] == DEFAULT_EMBEDDING_MODEL
    assert settings["device"] == "cpu"
    assert settings["normalize_embeddings"] is True
    assert collection_name_for(settings) == "competitor_intelligence_baai_bge_small_zh_v1_5"
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
    memory.add_user_message("分析山东寿光黄瓜价格变化")
    memory.add_ai_message("已记录价格分析结果")
    messages = memory.get_all_messages()
    assert messages == [
        {"role": "user", "content": "分析山东寿光黄瓜价格变化"},
        {"role": "assistant", "content": "已记录价格分析结果"},
    ]


def test_collection_and_dashboard():
    def run():
        sources = load_sources()
        assert sources
        job = run_collection_job(force=True, use_llm_filter=False)
        assert job["source_count"] >= 1
        assert competitor_summary()
        assert comparison_data()["dimensions"] == ["price", "new_product", "sentiment"]
        assert isinstance(risk_tags_view(), list)

    with_test_rag_embedding(run)


def test_agents_registered():
    names = {item["name"] for item in registry_snapshot()}
    assert {"price_monitor", "new_product", "sentiment"} <= names


def test_json_parser():
    parsed = parse_json_object('```json\n{"ok": true, "items": [1]}\n```')
    assert parsed["ok"] is True


def test_retrieve_evidence_reuses_loaded_index():
    load_calls = 0

    class FakeIndex:
        def search(self, query, top_k=5, dimension=None, competitor=None):
            return [
                EvidenceChunk(
                    chunk_id="chunk-1",
                    record_id="record-1",
                    title="山东黄瓜价格",
                    text="山东黄瓜价格高于辽宁黄瓜。",
                    source_url="https://example.test/source",
                    competitor="山东黄瓜",
                    dimension="price",
                    collected_at="2026-07-09T00:00:00Z",
                )
            ]

    def fake_load():
        nonlocal load_calls
        load_calls += 1
        return FakeIndex()

    old_load = tools_module.SimpleRAGIndex.load
    old_cache = tools_module._PROJECT_INDEX_CACHE
    try:
        tools_module._PROJECT_INDEX_CACHE = None
        tools_module.SimpleRAGIndex.load = fake_load
        retrieve_evidence_tool("山东黄瓜 价格", dimension="price", top_k=1)
        retrieve_evidence_tool("河北黄瓜 价格", dimension="price", top_k=1)
    finally:
        tools_module.SimpleRAGIndex.load = old_load
        tools_module._PROJECT_INDEX_CACHE = old_cache

    assert load_calls == 1


def test_rag_search_uses_keyword_fallback_when_collection_empty():
    class EmptyCollection:
        def count(self):
            return 0

        def query(self, **kwargs):
            raise AssertionError("empty collection should not run vector query")

    index = SimpleRAGIndex.__new__(SimpleRAGIndex)
    index.collection = EmptyCollection()
    index.chunks = [
        EvidenceChunk(
            chunk_id="chunk-1",
            record_id="record-1",
            title="山东寿光黄瓜精品货采购窗口收窄",
            text="山东寿光黄瓜精品货报价继续上行，和河北黄瓜价差扩大。",
            source_url="https://example.test/shouguang",
            competitor="山东寿光黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        )
    ]

    evidence = index.search("山东寿光黄瓜 河北黄瓜 价差", top_k=1, dimension="price", competitor="山东寿光黄瓜")

    assert evidence
    assert evidence[0].chunk_id == "chunk-1"


def test_rag_load_without_persisted_index_uses_keyword_mode():
    temp_dir = Path(tempfile.mkdtemp(prefix="rag-keyword-mode-"))
    record = load_csv("data/raw/shouguang_cucumber_manual.csv")[0]

    old_index_path = rag_module.INDEX_PATH
    old_load_records = rag_module.load_project_records
    old_create = rag_module.create_embedding_function
    try:
        rag_module.INDEX_PATH = temp_dir / "missing_index.json"
        rag_module.load_project_records = lambda: [record]
        rag_module.create_embedding_function = lambda: (_ for _ in ()).throw(
            AssertionError("missing persisted index should not initialize embedding")
        )

        index = SimpleRAGIndex.load()
        evidence = index.search("山东寿光黄瓜 批发价", top_k=1, dimension="price", competitor="山东寿光黄瓜")
    finally:
        rag_module.INDEX_PATH = old_index_path
        rag_module.load_project_records = old_load_records
        rag_module.create_embedding_function = old_create

    assert evidence
    assert evidence[0].competitor == "山东寿光黄瓜"


def test_price_agent_merges_focused_and_broad_evidence():
    calls = []

    class FakeLLM:
        def chat_json(self, prompt, payload, role="analysis", max_tokens=1200):
            return {
                "dimension": "price",
                "summary": "已完成跨区域价格对比",
                "competitors": [item["competitor"] for item in payload["evidence"]],
                "price_signals": [],
                "risk_level": "medium",
                "opportunities": [],
                "recommendations": [],
                "source_urls": [item["source_url"] for item in payload["evidence"]],
            }

    def fake_retrieve(query, dimension=None, top_k=5, competitor=None):
        calls.append(competitor)
        if competitor:
            return [
                {
                    "chunk_id": "sg-1",
                    "title": "寿光黄瓜精品货采购窗口收窄",
                    "text": "寿光黄瓜精品货报价继续上行。",
                    "source_url": "https://example.test/shouguang",
                    "competitor": "山东寿光黄瓜",
                    "dimension": "price",
                }
            ]
        return [
            {
                "chunk_id": "sg-1",
                "title": "寿光黄瓜精品货采购窗口收窄",
                "text": "寿光黄瓜精品货报价继续上行。",
                "source_url": "https://example.test/shouguang",
                "competitor": "山东寿光黄瓜",
                "dimension": "price",
            },
            {
                "chunk_id": "sg-2",
                "title": "寿光黄瓜统货供应充足",
                "text": "寿光黄瓜统货价格维持低位。",
                "source_url": "https://example.test/shouguang-2",
                "competitor": "山东寿光黄瓜",
                "dimension": "price",
            },
            {
                "chunk_id": "sg-3",
                "title": "寿光黄瓜到货价回升",
                "text": "寿光黄瓜到货价回升。",
                "source_url": "https://example.test/shouguang-3",
                "competitor": "山东寿光黄瓜",
                "dimension": "price",
            },
            {
                "chunk_id": "hb-1",
                "title": "河北黄瓜价差优势收窄",
                "text": "河北黄瓜到货价上行。",
                "source_url": "https://example.test/hebei",
                "competitor": "河北黄瓜",
                "dimension": "price",
            },
            {
                "chunk_id": "ln-1",
                "title": "辽宁黄瓜受物流成本影响上调",
                "text": "辽宁批发市场黄瓜到货价上调。",
                "source_url": "https://example.test/liaoning",
                "competitor": "辽宁批发市场黄瓜",
                "dimension": "price",
            },
        ]

    old_retrieve = agent_module.retrieve_evidence_tool
    old_get_cached = agent_module.get_cached_result
    old_set_cached = agent_module.set_cached_result
    try:
        agent_module.get_cached_result = lambda key: None
        agent_module.set_cached_result = lambda key, value: None
        agent_module.retrieve_evidence_tool = fake_retrieve
        result = agent_module.PriceMonitorAgent(FakeLLM()).analyze(
            "山东寿光黄瓜",
            "对比山东寿光黄瓜、河北黄瓜和辽宁批发市场黄瓜",
            top_k=3,
        )
    finally:
        agent_module.retrieve_evidence_tool = old_retrieve
        agent_module.get_cached_result = old_get_cached
        agent_module.set_cached_result = old_set_cached

    assert calls == ["山东寿光黄瓜", None]
    assert {item["competitor"] for item in result["evidence"]} == {
        "山东寿光黄瓜",
        "河北黄瓜",
        "辽宁批发市场黄瓜",
    }


def test_keyword_fallback_matches_chinese_competitors_in_natural_query():
    class EmptyCollection:
        def count(self):
            return 0

    index = SimpleRAGIndex.__new__(SimpleRAGIndex)
    index.collection = EmptyCollection()
    index.chunks = [
        EvidenceChunk(
            chunk_id="sg",
            record_id="sg",
            title="寿光黄瓜精品货采购窗口收窄",
            text="山东寿光黄瓜精品货报价继续上行。",
            source_url="https://example.test/sg",
            competitor="山东寿光黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        ),
        EvidenceChunk(
            chunk_id="sg-2",
            record_id="sg-2",
            title="寿光黄瓜统货供应充足",
            text="山东寿光黄瓜统货价格维持低位。",
            source_url="https://example.test/sg-2",
            competitor="山东寿光黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        ),
        EvidenceChunk(
            chunk_id="sg-3",
            record_id="sg-3",
            title="寿光黄瓜到货价回升",
            text="山东寿光黄瓜到货价回升。",
            source_url="https://example.test/sg-3",
            competitor="山东寿光黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        ),
        EvidenceChunk(
            chunk_id="hb",
            record_id="hb",
            title="河北黄瓜价差优势收窄",
            text="河北黄瓜到货价上行。",
            source_url="https://example.test/hb",
            competitor="河北黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        ),
        EvidenceChunk(
            chunk_id="ln",
            record_id="ln",
            title="辽宁黄瓜受物流成本影响上调",
            text="辽宁批发市场黄瓜到货价上调。",
            source_url="https://example.test/ln",
            competitor="辽宁批发市场黄瓜",
            dimension="price",
            collected_at="2026-07-09T00:00:00Z",
        ),
    ]

    evidence = index.search(
        "对比山东寿光黄瓜、河北黄瓜和辽宁批发市场黄瓜的当前价格、区域价差和采购风险",
        top_k=3,
        dimension="price",
        competitor=None,
    )

    assert {item.competitor for item in evidence} == {"山东寿光黄瓜", "河北黄瓜", "辽宁批发市场黄瓜"}


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
                "competitor": "山东寿光黄瓜",
                "query": "分析山东寿光黄瓜相对河北黄瓜和辽宁批发市场黄瓜的批发价波动、异常价差、新批次供应和质量风险",
                "top_k": 2,
                "provider": "mock",
            },
        )
        assert result["competitor"] == "山东寿光黄瓜"
        assert "analysis_result" in result
        assert "insufficient_evidence" in result

    with_test_rag_embedding(run)


if __name__ == "__main__":
    test_data_and_rag()
    test_table_csv_comparison_retrieves_cross_competitor_evidence()
    test_rag_uses_huggingface_embedding_defaults()
    test_deepseek_env_fallback_is_openai_compatible()
    test_conversation_memory_records_turns()
    test_collection_and_dashboard()
    test_agents_registered()
    test_json_parser()
    test_retrieve_evidence_reuses_loaded_index()
    test_rag_search_uses_keyword_fallback_when_collection_empty()
    test_rag_load_without_persisted_index_uses_keyword_mode()
    test_price_agent_merges_focused_and_broad_evidence()
    test_keyword_fallback_matches_chinese_competitors_in_natural_query()
    test_skills_mock_provider()
    print("local tests passed")
