import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.enums import KnowledgeType
from app.rag.chroma import ChromaKnowledgeStore


@dataclass(slots=True)
class EvaluationMetrics:
    collection: str
    query_count: int
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    mrr: float
    empty_retrieval_rate: float
    duplicate_result_rate: float
    metadata_filter_accuracy: float
    avg_latency_ms: float
    p95_latency_ms: float


def build_sanity_queries(store: ChromaKnowledgeStore, knowledge_type: KnowledgeType, *, limit: int = 20):
    collection = store._collection(knowledge_type)  # type: ignore[attr-defined]
    items = collection.peek(limit=limit)
    queries = []
    for item_id, document, metadata in zip(
        items.get("ids", []),
        items.get("documents", []),
        items.get("metadatas", []),
        strict=False,
    ):
        metadata = metadata or {}
        query = " ".join(str(document or "").split()[:18])
        if query:
            queries.append(
                {
                    "query": query,
                    "expected_id": item_id,
                    "product_id": metadata.get("product_id", ""),
                }
            )
    return queries


def evaluate_collection(
    store: ChromaKnowledgeStore,
    knowledge_type: KnowledgeType,
    *,
    top_k: int = 5,
) -> EvaluationMetrics:
    queries = build_sanity_queries(store, knowledge_type)
    if not queries:
        return EvaluationMetrics(
            collection=store.collection_names[knowledge_type],
            query_count=0,
            hit_at_1=0,
            hit_at_3=0,
            hit_at_5=0,
            mrr=0,
            empty_retrieval_rate=1,
            duplicate_result_rate=0,
            metadata_filter_accuracy=0,
            avg_latency_ms=0,
            p95_latency_ms=0,
        )
    hit1 = hit3 = hit5 = empty = duplicates = filter_ok = 0
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    for query in queries:
        started = time.perf_counter()
        result = store.retrieve(
            query=query["query"],
            product_id=str(query["product_id"]),
            knowledge_type=knowledge_type,
            top_k=top_k,
            fetch_k=max(10, top_k * 3),
        )
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [item.evidence_id for item in result.evidence]
        if not ids:
            empty += 1
        duplicates += len(ids) - len(set(ids))
        if all(item.metadata.get("product_id") == query["product_id"] for item in result.evidence):
            filter_ok += 1
        expected = query["expected_id"]
        if expected in ids[:1]:
            hit1 += 1
        if expected in ids[:3]:
            hit3 += 1
        if expected in ids[:5]:
            hit5 += 1
        reciprocal_ranks.append(1 / (ids.index(expected) + 1) if expected in ids else 0)
    count = len(queries)
    sorted_latencies = sorted(latencies)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
    return EvaluationMetrics(
        collection=store.collection_names[knowledge_type],
        query_count=count,
        hit_at_1=hit1 / count,
        hit_at_3=hit3 / count,
        hit_at_5=hit5 / count,
        mrr=sum(reciprocal_ranks) / count,
        empty_retrieval_rate=empty / count,
        duplicate_result_rate=duplicates / max(1, count * top_k),
        metadata_filter_accuracy=filter_ok / count,
        avg_latency_ms=statistics.fmean(latencies),
        p95_latency_ms=sorted_latencies[p95_index],
    )


def write_evaluation_report(metrics: list[EvaluationMetrics], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(item) for item in metrics]
    (output_dir / "rag_evaluation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# RAG Evaluation", ""]
    for item in metrics:
        lines.extend(
            [
                f"## {item.collection}",
                "",
                f"- query_count: {item.query_count}",
                f"- Hit@1: {item.hit_at_1:.3f}",
                f"- Hit@3: {item.hit_at_3:.3f}",
                f"- Hit@5: {item.hit_at_5:.3f}",
                f"- MRR: {item.mrr:.3f}",
                f"- Empty Retrieval Rate: {item.empty_retrieval_rate:.3f}",
                f"- Duplicate Result Rate: {item.duplicate_result_rate:.3f}",
                f"- Metadata Filter Accuracy: {item.metadata_filter_accuracy:.3f}",
                f"- Avg Latency Ms: {item.avg_latency_ms:.1f}",
                f"- P95 Latency Ms: {item.p95_latency_ms:.1f}",
                "",
            ]
        )
    (output_dir / "rag_evaluation.md").write_text("\n".join(lines), encoding="utf-8")
