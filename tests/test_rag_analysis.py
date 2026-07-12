import unittest

from modules.data_loader import IntelligenceRecord, is_public_source_url, load_project_records
from modules.rag_chain import records_to_chunks
from modules.analysis_chain import run_evidence_analysis


class RAGMetadataTests(unittest.TestCase):
    def test_chunks_preserve_source_name_and_publication_time(self):
        record = IntelligenceRecord(
            title="农业农村部日度报告",
            content="农业农村部公开报告显示黄瓜价格变化，" * 20,
            source_url="https://www.agri.cn/zx/zxfb/202606/t20260618_8845498.htm",
            source_name="农业农村部市场与信息化司",
            source_type="agri_daily",
            published_at="2026-06-18",
            collected_at="2026-07-11T12:00:00+00:00",
            competitor="全国农产品批发市场",
            dimension="price",
        )

        chunks = records_to_chunks([record])

        self.assertGreater(len(chunks), 0)
        self.assertEqual(chunks[0].source_name, "农业农村部市场与信息化司")
        self.assertEqual(chunks[0].published_at, "2026-06-18")

    def test_formal_project_records_only_include_traceable_processed_data(self):
        records = load_project_records()

        self.assertGreaterEqual(len(records), 5)
        self.assertTrue(all(is_public_source_url(record.source_url) for record in records))
        self.assertTrue(all(record.source_name and record.published_at for record in records))


class EvidenceAnalysisTests(unittest.TestCase):
    class FakeLLM:
        def __init__(self, error=None):
            self.calls = 0
            self.error = error
            self.max_tokens = None

        def chat_json(self, system_prompt, payload, role="analysis", max_tokens=1200):
            self.calls += 1
            self.max_tokens = max_tokens
            if self.error:
                raise self.error
            return {
                "summary": "黄瓜价格出现公开可追溯的日度变化。",
                "findings": ["报告记录黄瓜位于价格降幅前列。"],
                "suggestions": ["继续观察后续日度报告。"],
            }

    def test_no_evidence_returns_insufficient_without_model_call(self):
        llm = self.FakeLLM()

        result = run_evidence_analysis(llm, "system", {"competitor": "黄瓜", "evidence": []}, mode="real")

        self.assertEqual(llm.calls, 0)
        self.assertTrue(result["insufficient_evidence"])
        self.assertEqual(result["mode"], "real")
        self.assertEqual(result["evidence"], [])

    def test_real_analysis_uses_langchain_and_attaches_evidence(self):
        llm = self.FakeLLM()
        evidence = [{
            "chunk_id": "record-1-0",
            "text": "黄瓜价格下降3.1%",
            "source_name": "农业农村部市场与信息化司",
            "source_url": "https://www.agri.cn/zx/zxfb/202606/t20260618_8845498.htm",
            "published_at": "2026-06-18",
        }]

        result = run_evidence_analysis(
            llm,
            "system",
            {"competitor": "黄瓜", "question": "分析价格", "evidence": evidence},
            mode="real",
        )

        self.assertEqual(llm.calls, 1)
        self.assertEqual(llm.max_tokens, 2200)
        self.assertFalse(result["insufficient_evidence"])
        self.assertEqual(result["evidence"], evidence)
        self.assertEqual(result["reasoning_trace"]["framework"], "langchain")
        self.assertEqual(result["reasoning_trace"]["chain_type"], "RunnableSequence")

    def test_real_model_failure_is_not_converted_to_mock(self):
        llm = self.FakeLLM(RuntimeError("model unavailable"))
        evidence = [{"chunk_id": "1", "text": "evidence", "source_url": "https://www.agri.cn/a"}]

        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            run_evidence_analysis(llm, "system", {"competitor": "黄瓜", "evidence": evidence}, mode="real")

        self.assertEqual(llm.calls, 1)

    def test_mock_mode_is_explicit_and_does_not_call_real_model(self):
        llm = self.FakeLLM()
        evidence = [{"chunk_id": "1", "text": "evidence", "source_url": "https://www.agri.cn/a"}]

        result = run_evidence_analysis(llm, "system", {"competitor": "黄瓜", "evidence": evidence}, mode="mock")

        self.assertEqual(llm.calls, 0)
        self.assertEqual(result["mode"], "mock")
        self.assertTrue(result["mock"])


if __name__ == "__main__":
    unittest.main()
