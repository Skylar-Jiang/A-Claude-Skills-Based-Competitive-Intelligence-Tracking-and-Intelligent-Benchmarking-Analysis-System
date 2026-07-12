from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modules.data_loader import (
    IntelligenceRecord,
    fetch_agri_daily_reports,
    is_public_source_url,
    load_csv,
    parse_agri_daily_html,
)
from modules.source_manager import persist_collected_records
from modules.tools import ingest_csv_tool


FIXTURE = Path(__file__).parent / "fixtures" / "agri_daily.html"
PUBLIC_URL = "https://www.agri.cn/zx/zxfb/202606/t20260618_8845498.htm"


class DataPipelineTests(unittest.TestCase):
    def test_non_public_csv_is_saved_as_sample_and_not_indexed(self):
        with TemporaryDirectory() as temp_dir:
            processed_path = Path(temp_dir) / "processed.csv"
            sample_path = Path(temp_dir) / "samples.csv"

            result = ingest_csv_tool(
                "data/raw/shouguang_cucumber_manual.csv",
                output_path=str(processed_path),
                sample_output_path=str(sample_path),
            )

            self.assertEqual(result["mode"], "sample")
            self.assertFalse(result["indexed"])
            self.assertFalse(processed_path.exists())
            self.assertEqual(len(load_csv(sample_path)), 5)

    def test_agri_daily_batch_fetch_uses_each_public_url(self):
        html = FIXTURE.read_text(encoding="utf-8")
        requested = []

        class Response:
            apparent_encoding = "utf-8"
            encoding = "utf-8"
            text = html

            @staticmethod
            def raise_for_status():
                return None

        def fetcher(url, **kwargs):
            requested.append(url)
            return Response()

        second_url = PUBLIC_URL.replace("8845498", "8845499")
        records = fetch_agri_daily_reports([PUBLIC_URL, second_url], fetcher=fetcher)

        self.assertEqual(requested, [PUBLIC_URL, second_url])
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.source_type == "agri_daily" for record in records))

    def test_agri_daily_batch_records_individual_page_errors(self):
        html = FIXTURE.read_text(encoding="utf-8")
        errors = []

        class Response:
            apparent_encoding = "utf-8"
            encoding = "utf-8"
            text = html

            def __init__(self, fail=False):
                self.fail = fail

            def raise_for_status(self):
                if self.fail:
                    raise ValueError("HTTP 403")

        def fetcher(url, **kwargs):
            return Response(fail="blocked" in url)

        records = fetch_agri_daily_reports(
            [PUBLIC_URL, "https://www.agri.cn/blocked.htm"],
            fetcher=fetcher,
            on_error=errors.append,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(errors[0]["url"], "https://www.agri.cn/blocked.htm")
        self.assertIn("HTTP 403", errors[0]["error"])

    def test_agri_daily_parser_preserves_traceability_fields(self):
        record = parse_agri_daily_html(
            FIXTURE.read_text(encoding="utf-8"),
            PUBLIC_URL,
            collected_at="2026-07-11T12:00:00+00:00",
        )

        self.assertEqual(record.source_name, "农业农村部市场与信息化司")
        self.assertEqual(record.published_at, "2026-06-18")
        self.assertEqual(record.collected_at, "2026-07-11T12:00:00+00:00")
        self.assertEqual(record.competitor, "全国农产品批发市场")
        self.assertEqual(record.dimension, "price")
        self.assertEqual(record.source_url, PUBLIC_URL)
        self.assertIn("黄瓜", record.content)

    def test_public_source_url_rejects_examples_and_local_hosts(self):
        self.assertTrue(is_public_source_url(PUBLIC_URL))
        for url in (
            "https://manual.local/record/1",
            "https://example.com/record/1",
            "https://example.test/record/1",
            "http://localhost:8000/record/1",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_source_url(url))

    def test_equivalent_tracking_urls_share_record_identity(self):
        first = IntelligenceRecord(
            title="同一报告",
            content="黄瓜价格公开信息" * 20,
            source_url="HTTPS://WWW.AGRI.CN/report/?id=1&utm_source=test#top",
            source_name="农业农村部市场与信息化司",
            published_at="2026-06-18",
        )
        second = IntelligenceRecord(
            title="同一报告",
            content="黄瓜价格公开信息" * 20,
            source_url="https://www.agri.cn/report?id=1",
            source_name="农业农村部市场与信息化司",
            published_at="2026-06-18",
        )

        self.assertEqual(first.source_url, second.source_url)
        self.assertEqual(first.record_id, second.record_id)

    def test_repeated_persistence_separates_raw_and_processed_and_is_idempotent(self):
        record = IntelligenceRecord(
            title="公开报告",
            content=(
                "据农业农村部监测，全国农产品批发市场重点监测的蔬菜平均价格出现变化，"
                "其中黄瓜价格较前一日下降3.1%，相关数据来自公开发布的日度市场监测。"
                "本记录用于验证公开报告的清洗、追溯和重复采集。"
            ),
            source_url=PUBLIC_URL,
            source_name="农业农村部市场与信息化司",
            source_type="agri_daily",
            published_at="2026-06-18",
            collected_at="2026-07-11T12:00:00+00:00",
            competitor="全国农产品批发市场",
            dimension="price",
        )
        with TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw" / "records.csv"
            processed_path = Path(temp_dir) / "processed" / "records.csv"

            first = persist_collected_records([record], raw_path, processed_path, keywords=["黄瓜"])
            second = persist_collected_records([record], raw_path, processed_path, keywords=["黄瓜"])

            self.assertEqual(first["new_count"], 1)
            self.assertEqual(second["new_count"], 0)
            self.assertEqual(len(load_csv(raw_path)), 1)
            processed = load_csv(processed_path)
            self.assertEqual(len(processed), 1)
            self.assertEqual(processed[0].source_name, "农业农村部市场与信息化司")
            self.assertNotEqual(raw_path.parent, processed_path.parent)

    def test_processed_persistence_rejects_missing_source_metadata(self):
        record = IntelligenceRecord(
            title="缺少来源字段",
            content="黄瓜公开价格信息" * 20,
            source_url=PUBLIC_URL,
            source_type="webpage",
            competitor="全国农产品批发市场",
            dimension="price",
        )
        with TemporaryDirectory() as temp_dir:
            result = persist_collected_records(
                [record],
                Path(temp_dir) / "raw" / "records.csv",
                Path(temp_dir) / "processed" / "records.csv",
                keywords=["黄瓜"],
            )

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["rejected"][0]["reason"], "missing_traceability_metadata")


if __name__ == "__main__":
    unittest.main()
