"""Reusable tools for competitor intelligence agents."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from modules.data_loader import IntelligenceRecord, is_public_source_url, load_csv, save_records_csv
from modules.rag_chain import SimpleRAGIndex, build_project_index

_PROJECT_INDEX_CACHE: SimpleRAGIndex | None = None


def get_project_index() -> SimpleRAGIndex:
    global _PROJECT_INDEX_CACHE
    if _PROJECT_INDEX_CACHE is None:
        _PROJECT_INDEX_CACHE = SimpleRAGIndex.load()
    return _PROJECT_INDEX_CACHE


def set_project_index(index: SimpleRAGIndex) -> None:
    """Replace the in-process search cache after a successful rebuild."""
    global _PROJECT_INDEX_CACHE
    _PROJECT_INDEX_CACHE = index


def ingest_csv_tool(
    path: str,
    output_path: str = "data/processed/intelligence_records.csv",
    sample_output_path: str = "data/samples/imported_records.csv",
) -> dict[str, Any]:
    global _PROJECT_INDEX_CACHE
    records = load_csv(path)
    traceable = [
        record for record in records
        if is_public_source_url(record.source_url) and record.source_name and record.published_at
    ]
    if len(traceable) != len(records) or not records:
        saved_path = save_records_csv(records, sample_output_path)
        return {
            "count": len(records),
            "output_path": str(saved_path),
            "mode": "sample",
            "indexed": False,
            "message": "CSV contains sample or non-traceable records and was not added to the formal knowledge base.",
        }
    existing = load_csv(output_path) if Path(output_path).exists() else []
    by_url = {record.source_url: record for record in existing}
    for record in traceable:
        by_url[record.source_url] = record
    saved_path = save_records_csv(by_url.values(), output_path)
    _PROJECT_INDEX_CACHE = build_project_index()
    return {"count": len(records), "output_path": str(saved_path), "mode": "real", "indexed": True}


def add_manual_record_tool(
    title: str,
    content: str,
    source_url: str,
    competitor: str = "",
    dimension: str = "general",
    output_path: str = "data/samples/manual_records.csv",
) -> dict[str, Any]:
    global _PROJECT_INDEX_CACHE
    record = IntelligenceRecord(
        title=title,
        content=content,
        source_url=source_url,
        source_type="manual",
        competitor=competitor,
        dimension=dimension,
    )
    existing = []
    if Path(output_path).exists():
        existing = load_csv(output_path)
    records = existing + [record]
    saved_path = save_records_csv(records, output_path)
    return {"record": asdict(record), "output_path": str(saved_path), "mode": "sample", "indexed": False}


def retrieve_evidence_tool(
    query: str,
    dimension: str | None = None,
    top_k: int = 5,
    competitor: str | None = None,
) -> list[dict[str, Any]]:
    index = get_project_index()
    return [
        asdict(chunk)
        for chunk in index.search(query=query, top_k=top_k, dimension=dimension, competitor=competitor)
    ]
