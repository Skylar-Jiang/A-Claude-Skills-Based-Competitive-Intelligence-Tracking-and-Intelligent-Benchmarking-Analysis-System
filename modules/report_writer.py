"""Persist generated intelligence reports for handoff and demos."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path("data/reports")


def slugify(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip().lower())
    return re.sub(r"-+", "-", text).strip("-") or "report"


def append_items(lines: list[str], value: Any) -> None:
    if isinstance(value, list):
        lines.extend(f"- {item}" for item in value)
    elif value:
        lines.append(str(value))


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('title', '生鲜批发采购区域供应源竞品动态追踪与智能对标分析报告')}",
        "",
        "## 1. 执行摘要",
        report.get("executive_summary", report.get("summary", "")),
        "",
        "## 2. 区域供应源动态汇总",
    ]
    append_items(lines, report.get("platform_updates", report.get("key_findings", report.get("findings", []))))
    sections = [
        ("## 3. 肉蛋奶价格对比", report.get("meat_egg_dairy_price_comparison", "")),
        ("## 4. 基础蔬菜价格对比", report.get("vegetable_price_comparison", "")),
        ("## 5. 水果价格对比", report.get("fruit_price_comparison", "")),
        ("## 6. 新产季与供应动态分析", report.get("promotion_and_seasonal_products", "")),
        ("## 7. 质量监管与供应风险", report.get("sentiment_and_service_risks", "")),
        ("## 8. 时序价格趋势", report.get("time_series_price_trend", "")),
        ("## 9. 机会与威胁研判", report.get("opportunity_threat_judgement", "")),
    ]
    for heading, content in sections:
        lines.extend(["", heading, str(content)])
    lines.extend(["", "## 10. 经营建议"])
    append_items(
        lines,
        report.get("operation_suggestions", report.get("recommendations", report.get("suggestions", []))),
    )
    lines.extend(["", "## 11. 证据来源列表"])
    source_urls = report.get("source_urls", [])
    if source_urls:
        lines.extend(f"- {url}" for url in source_urls)
    else:
        for item in report.get("evidence", []):
            source_name = item.get("source_name", "未知来源")
            published_at = item.get("published_at", "发布时间未知")
            source_url = item.get("source_url", "")
            if source_url:
                lines.append(f"- {source_name} | {published_at} | {source_url}")
    lines.extend(["", "## 12. 生成时间", report.get("generated_at", datetime.now().isoformat())])
    return "\n".join(lines).strip() + "\n"

def save_report(report: dict[str, Any], competitor: str) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{timestamp}-{slugify(competitor)}"
    json_path = REPORT_DIR / f"{base}.json"
    md_path = REPORT_DIR / f"{base}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}

