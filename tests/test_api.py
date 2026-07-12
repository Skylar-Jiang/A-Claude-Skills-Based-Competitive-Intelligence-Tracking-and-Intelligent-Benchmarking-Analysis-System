import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from modules.api_server import app
from modules.api_server import rebuild_rag
from modules.llm_client import LLMConfigurationError
import modules.api_server as api_module
import modules.tools as tools_module


class APITests(unittest.TestCase):
    def test_rag_rebuild_refreshes_in_process_search_cache(self):
        class Collection:
            name = "test_collection"

        class Index:
            chunks = [object()]
            collection = Collection()
            embedding_settings = {"provider": "test"}

        old_cache = tools_module._PROJECT_INDEX_CACHE
        old_build = api_module.build_project_index
        try:
            tools_module._PROJECT_INDEX_CACHE = object()
            api_module.build_project_index = lambda: Index()

            rebuild_rag(None)

            self.assertIsInstance(tools_module._PROJECT_INDEX_CACHE, Index)
        finally:
            tools_module._PROJECT_INDEX_CACHE = old_cache
            api_module.build_project_index = old_build

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_records_returns_traceable_real_records(self):
        response = self.client.get("/records")

        self.assertEqual(response.status_code, 200)
        records = response.json()
        self.assertGreaterEqual(len(records), 5)
        self.assertTrue(all(item["source_name"] and item["source_url"] for item in records))
        self.assertTrue(all(item["published_at"] and item["collected_at"] for item in records))

    @patch("modules.api_server.retrieve_evidence_tool")
    def test_analysis_mock_mode_is_explicit(self, retrieve):
        retrieve.return_value = [{
            "chunk_id": "1",
            "text": "黄瓜价格下降3.1%",
            "source_name": "农业农村部市场与信息化司",
            "source_url": "https://www.agri.cn/zx/zxfb/202606/t20260618_8845498.htm",
            "published_at": "2026-06-18",
        }]

        response = self.client.post(
            "/analysis/run",
            json={"competitor": "全国农产品批发市场", "question": "分析黄瓜价格", "mode": "mock"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "mock")
        self.assertTrue(response.json()["mock"])

    @patch("modules.api_server.retrieve_evidence_tool")
    @patch("modules.api_server.OpenAICompatibleLLM")
    def test_real_model_configuration_error_has_stable_503_error(self, llm_class, retrieve):
        retrieve.return_value = [{
            "chunk_id": "1",
            "text": "黄瓜价格下降3.1%",
            "source_url": "https://www.agri.cn/zx/zxfb/202606/t20260618_8845498.htm",
        }]
        llm_class.side_effect = LLMConfigurationError("model key missing")

        response = self.client.post(
            "/analysis/run",
            json={"competitor": "全国农产品批发市场", "question": "分析黄瓜价格", "mode": "real"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "llm_not_configured")
        self.assertIn("model key missing", response.json()["error"]["message"])

    def test_http_errors_use_stable_error_envelope(self):
        response = self.client.get("/skills/not-a-skill")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["success"], False)
        self.assertEqual(response.json()["error"]["code"], "http_404")

    @patch("modules.api_server.retrieve_evidence_tool", side_effect=RuntimeError("rag unavailable"))
    def test_analysis_rag_failure_has_stable_502_error(self, _retrieve):
        response = self.client.post(
            "/analysis/run",
            json={"competitor": "全国农产品批发市场", "question": "分析黄瓜价格", "mode": "mock"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "analysis_failed")
        self.assertIn("rag unavailable", response.json()["error"]["message"])

    @patch("modules.api_server.OpenAICompatibleLLM")
    @patch("modules.api_server.retrieve_evidence_tool", return_value=[])
    def test_no_evidence_route_does_not_initialize_real_model(self, _retrieve, llm_class):
        response = self.client.post(
            "/analysis/run",
            json={"competitor": "未知对象", "question": "分析价格", "mode": "real"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["insufficient_evidence"])
        llm_class.assert_not_called()

    @patch("modules.api_server.run_skill", side_effect=ValueError("invalid model JSON"))
    def test_known_skill_execution_value_error_is_not_mapped_to_404(self, _run):
        response = self.client.post(
            "/skills/price_monitor_skill/run",
            json={"competitor": "全国农产品批发市场", "provider": "openai"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "skill_execution_failed")

    @patch("modules.api_server.run_skill", side_effect=RuntimeError("model upstream failed"))
    def test_multi_agent_runtime_error_has_stable_502(self, _run):
        response = self.client.post(
            "/analyze/multi-agent",
            json={"competitor": "全国农产品批发市场", "provider": "openai"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "analysis_failed")

    @patch("modules.api_server.AgentOrchestrator", side_effect=LLMConfigurationError("key missing"))
    def test_legacy_analyze_missing_model_maps_to_503(self, _orchestrator):
        response = self.client.post(
            "/analyze",
            json={"competitor": "全国农产品批发市场", "question": "分析"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "llm_not_configured")


if __name__ == "__main__":
    unittest.main()
