import unittest

from modules.report_writer import render_markdown_report


class ReportTests(unittest.TestCase):
    def test_formal_analysis_fields_render_with_source_links(self):
        report = {
            "summary": "黄瓜价格在多个监测日出现涨跌。",
            "findings": ["6月18日下降3.1%。"],
            "suggestions": ["继续观察公开日度报告。"],
            "evidence": [{
                "source_name": "农业农村部市场与信息化司",
                "source_url": "https://www.agri.cn/report.htm",
                "published_at": "2026-06-18",
            }],
        }

        markdown = render_markdown_report(report)

        self.assertIn("黄瓜价格在多个监测日出现涨跌。", markdown)
        self.assertIn("6月18日下降3.1%。", markdown)
        self.assertIn("继续观察公开日度报告。", markdown)
        self.assertIn("https://www.agri.cn/report.htm", markdown)
        self.assertIn("2026-06-18", markdown)


if __name__ == "__main__":
    unittest.main()
