"""Data source configuration and automated collection jobs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from modules.data_loader import (
    IntelligenceRecord,
    MultiSourceDocumentLoader,
    is_public_source_url,
    load_csv,
    save_records_csv,
)
from modules.filtering import filter_and_enrich_records
from modules.rag_chain import build_project_index
from modules.semantic_filter import semantic_filter_records

CONFIG_DIR = Path("data/config")
SCENARIO_SOURCE_YAML = Path("config/sources.yaml")
SOURCE_CONFIG_PATH = CONFIG_DIR / "data_sources.runtime.json"
COLLECTION_LOG_PATH = Path("logs/collection_jobs.jsonl")
AUTO_COLLECTION_PATH = Path("data/raw/auto_collected_records.csv")
PROCESSED_COLLECTION_PATH = Path("data/processed/intelligence_records.csv")


def persist_collected_records(
    raw_records: list[IntelligenceRecord],
    raw_path: Path,
    processed_path: Path = PROCESSED_COLLECTION_PATH,
    keywords: list[str] | None = None,
    processed_records: list[IntelligenceRecord] | None = None,
) -> dict[str, Any]:
    """Persist raw extraction and merge traceable cleaned records idempotently."""
    existing_raw = load_csv(raw_path) if raw_path.exists() else []
    raw_by_id = {record.record_id: record for record in existing_raw}
    for record in raw_records:
        raw_by_id.setdefault(record.record_id, record)
    save_records_csv(raw_by_id.values(), raw_path)

    if processed_records is None:
        accepted, rejected = filter_and_enrich_records(raw_records, keywords=keywords or [])
    else:
        accepted, rejected = processed_records, []
    traceable = []
    for record in accepted:
        if not is_public_source_url(record.source_url):
            rejected.append({"source_url": record.source_url, "reason": "non_public_source_url"})
        elif not record.source_name or not record.published_at:
            rejected.append({"source_url": record.source_url, "reason": "missing_traceability_metadata"})
        else:
            traceable.append(record)
    existing = load_csv(processed_path) if processed_path.exists() else []
    existing_ids = {record.record_id for record in existing}
    existing_urls = {record.source_url for record in existing}
    new_records = [
        record for record in traceable
        if record.record_id not in existing_ids and record.source_url not in existing_urls
    ]
    save_records_csv(existing + new_records, processed_path)
    return {
        "raw_count": len(raw_records),
        "new_count": len(new_records),
        "duplicate_count": len(traceable) - len(new_records),
        "rejected": rejected,
        "raw_path": str(raw_path),
        "processed_path": str(processed_path),
    }


@dataclass
class DataSourceConfig:
    source_id: str
    source_type: str
    url: str = ""
    urls: list[str] = field(default_factory=list)
    path: str = ""
    competitor: str = ""
    dimension: str = "general"
    priority: int = 5
    frequency_minutes: int = 1440
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)
    llm_filter_enabled: bool = True
    last_run_at: str = ""
    next_run_at: str = ""
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def due(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        now = now or datetime.now(timezone.utc)
        if not self.last_run_at:
            return True
        next_run = parse_datetime(self.next_run_at)
        return not next_run or now >= next_run

    def mark_run(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.last_run_at = now.isoformat()
        self.next_run_at = (now + timedelta(minutes=self.frequency_minutes)).isoformat()


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_sources() -> list[DataSourceConfig]:
    if SOURCE_CONFIG_PATH.exists():
        data = json.loads(SOURCE_CONFIG_PATH.read_text(encoding="utf-8"))
        return [DataSourceConfig(**item) for item in data]
    if SCENARIO_SOURCE_YAML.exists():
        return load_sources_from_yaml(SCENARIO_SOURCE_YAML)
    sources = default_sources()
    save_sources(sources)
    return sources


def load_sources_from_yaml(path: Path) -> list[DataSourceConfig]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    competitors = data.get("competitors", [])
    scenario_keywords = [
        keyword
        for competitor in competitors
        for keyword in competitor.get("keywords", [])
    ]
    category_keywords = [
        keyword
        for category in (data.get("product_categories") or {}).values()
        for keyword in category.get("keywords", [])
    ]
    sources = []
    for idx, item in enumerate(data.get("sources", []), start=1):
        source_type = item.get("type", "html")
        mapped_type = {
            "html": "webpage",
            "manual_csv": "csv",
        }.get(source_type, source_type)
        keywords = item.get("keywords") or scenario_keywords + category_keywords
        sources.append(
            DataSourceConfig(
                source_id=item.get("id", f"source_{idx}"),
                source_type=mapped_type,
                url=item.get("url", ""),
                urls=item.get("urls", []),
                path=item.get("file", item.get("path", "")),
                competitor=item.get("competitor", ""),
                dimension=item.get("dimension", "general"),
                priority=item.get("priority", idx),
                frequency_minutes=item.get("frequency_minutes", 1440),
                enabled=item.get("enabled", True),
                keywords=keywords,
                llm_filter_enabled=item.get("llm_filter_enabled", False if mapped_type == "csv" else True),
                notes=item.get("name", item.get("notes", "")),
            )
        )
    return sources


def save_sources(sources: list[DataSourceConfig]) -> Path:
    SOURCE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_CONFIG_PATH.write_text(
        json.dumps([asdict(source) for source in sources], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return SOURCE_CONFIG_PATH


def default_sources() -> list[DataSourceConfig]:
    return [
        DataSourceConfig(
            source_id="agri_price_public",
            source_type="webpage",
            url="https://pfsc.agri.cn/",
            competitor="",
            dimension="price",
            priority=1,
            frequency_minutes=1440,
            keywords=["猪肉", "牛肉", "鸡蛋", "蔬菜", "水果", "批发价格"],
            notes="全国农产品批发市场价格信息。",
        ),
        DataSourceConfig(
            source_id="mofcom_food_price",
            source_type="webpage",
            url="https://cif.mofcom.gov.cn/",
            competitor="",
            dimension="price",
            priority=2,
            frequency_minutes=1440,
            keywords=["食用农产品", "价格", "肉类", "蛋类", "蔬菜", "水果"],
            notes="商务部食用农产品价格信息。",
        ),
        DataSourceConfig(
            source_id="shouguang_cucumber_manual",
            source_type="csv",
            path="data/raw/shouguang_cucumber_manual.csv",
            competitor="山东寿光黄瓜",
            dimension="price",
            priority=3,
            frequency_minutes=1440,
            keywords=["山东寿光黄瓜", "寿光黄瓜", "批发价", "到货价", "价差"],
            notes="山东寿光黄瓜批发价手工样例。",
        ),
        DataSourceConfig(
            source_id="hebei_cucumber_manual",
            source_type="csv",
            path="data/raw/hebei_cucumber_manual.csv",
            competitor="河北黄瓜",
            dimension="price",
            priority=4,
            frequency_minutes=1440,
            keywords=["河北黄瓜", "河北产区", "黄瓜行情", "价差", "到货"],
            notes="河北黄瓜批发价手工样例。",
        ),
        DataSourceConfig(
            source_id="liaoning_market_cucumber_manual",
            source_type="csv",
            path="data/raw/liaoning_market_cucumber_manual.csv",
            competitor="辽宁批发市场黄瓜",
            dimension="price",
            priority=5,
            frequency_minutes=1440,
            keywords=["辽宁批发市场黄瓜", "辽宁黄瓜", "东北黄瓜", "批发市场", "低价"],
            notes="辽宁批发市场黄瓜手工样例。",
        ),
        DataSourceConfig(
            source_id="wholesale_supply_update_manual",
            source_type="csv",
            path="data/raw/wholesale_supply_update_manual.csv",
            competitor="",
            dimension="market",
            priority=6,
            frequency_minutes=1440,
            keywords=["新产季", "新品种", "新产区", "新规格", "新批次", "上市", "到货"],
            notes="新产季与供应动态手工样例。",
        ),
        DataSourceConfig(
            source_id="wholesale_risk_manual",
            source_type="csv",
            path="data/raw/wholesale_risk_manual.csv",
            competitor="",
            dimension="sentiment",
            priority=7,
            frequency_minutes=1440,
            keywords=["抽检", "不合格", "农残", "腐损", "缺斤少两", "监管通报", "供应短缺"],
            notes="质量监管与供应风险手工样例。",
        ),
        DataSourceConfig(
            source_id="wholesale_logistics_weather_manual",
            source_type="csv",
            path="data/raw/wholesale_logistics_weather_manual.csv",
            competitor="",
            dimension="market",
            priority=8,
            frequency_minutes=1440,
            keywords=["天气", "降雨", "冷链", "物流", "到货延迟", "供应短缺"],
            notes="天气物流影响手工样例。",
        ),
    ]


def upsert_source(source: DataSourceConfig) -> DataSourceConfig:
    sources = load_sources()
    replaced = False
    for idx, existing in enumerate(sources):
        if existing.source_id == source.source_id:
            sources[idx] = source
            replaced = True
            break
    if not replaced:
        sources.append(source)
    save_sources(sources)
    return source


def delete_source(source_id: str) -> bool:
    sources = load_sources()
    kept = [source for source in sources if source.source_id != source_id]
    save_sources(kept)
    return len(kept) != len(sources)


def collect_source(source: DataSourceConfig, use_llm_filter: bool = True) -> dict[str, Any]:
    loader = MultiSourceDocumentLoader(
        source_type=source.source_type,
        url=source.url,
        urls=source.urls,
        path=source.path,
        competitor=source.competitor,
        dimension=source.dimension,
    )
    raw_records: list[IntelligenceRecord] = loader.load_records()
    rule_records, rejected = filter_and_enrich_records(
        raw_records,
        keywords=source.keywords,
        fallback_dimension=source.dimension,
    )
    records = rule_records
    llm_rejected: list[dict[str, Any]] = []
    llm_meta: dict[str, Any] = {"enabled": False}
    if use_llm_filter and source.llm_filter_enabled:
        records, llm_rejected, llm_meta = semantic_filter_records(records)

    raw_is_traceable = all(
        is_public_source_url(record.source_url) and record.source_name and record.published_at
        for record in raw_records
    )
    raw_root = Path("data/raw/real") if raw_is_traceable else Path("data/samples/collected")
    raw_path = raw_root / f"{source.source_id}.csv"
    persistence = persist_collected_records(
        raw_records,
        raw_path=raw_path,
        processed_path=PROCESSED_COLLECTION_PATH,
        keywords=source.keywords,
        processed_records=records,
    )
    source.mark_run()
    persistence_rejected = persistence["rejected"]
    log_entry = {
        "source_id": source.source_id,
        "source_type": source.source_type,
        "raw_count": len(raw_records),
        "rule_pass_count": len(rule_records),
        "count": persistence["new_count"],
        "duplicate_count": persistence["duplicate_count"],
        "rejected_count": len(rejected) + len(llm_rejected) + len(persistence_rejected),
        "rejected": (rejected + llm_rejected + persistence_rejected)[:20],
        "fetch_errors": loader.errors,
        "llm_filter": llm_meta,
        "collected_at": source.last_run_at,
        "raw_output_path": persistence["raw_path"],
        "output_path": persistence["processed_path"],
    }
    append_collection_log(log_entry)
    return log_entry


def run_collection_job(force: bool = False, use_llm_filter: bool = True) -> dict[str, Any]:
    sources = sorted(load_sources(), key=lambda item: item.priority)
    results = []
    errors = []
    for source in sources:
        if not source.enabled:
            continue
        if not force and not source.due():
            continue
        try:
            results.append(collect_source(source, use_llm_filter=use_llm_filter))
        except Exception as exc:  # Keep scheduled jobs from failing the whole system.
            errors.append({"source_id": source.source_id, "error": str(exc)})
    save_sources(sources)
    if any(item.get("count", 0) > 0 for item in results):
        index = build_project_index()
        from modules.tools import set_project_index

        set_project_index(index)
        index_meta = {"rebuilt": True, "chunks": len(index.chunks)}
    else:
        index_meta = {"rebuilt": False, "chunks": 0}
    return {"collected": results, "errors": errors, "source_count": len(sources), "index": index_meta}


def append_collection_log(entry: dict[str, Any]) -> None:
    COLLECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COLLECTION_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_collection_logs(limit: int = 50) -> list[dict[str, Any]]:
    if not COLLECTION_LOG_PATH.exists():
        return []
    lines = COLLECTION_LOG_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]]
