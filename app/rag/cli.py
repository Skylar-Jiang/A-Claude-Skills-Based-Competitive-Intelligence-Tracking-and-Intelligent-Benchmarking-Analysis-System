import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from app.core.config import get_settings
from app.core.enums import KnowledgeType
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.embeddings import create_embedding_function
from app.rag.evaluation import evaluate_collection, write_evaluation_report
from app.rag.importers import iter_filtered_documents, validate_source
from app.rag.manifest import IndexManifest, ManifestStats


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = __import__("os").open(str(self.path), __import__("os").O_CREAT | __import__("os").O_EXCL)
        except FileExistsError as exc:
            raise RuntimeError(f"Index lock already exists: {self.path}") from exc
        return self

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if self.handle is not None:
            __import__("os").close(self.handle)
        self.path.unlink(missing_ok=True)


def _store(*, offline: bool = False) -> ChromaKnowledgeStore:
    settings = get_settings()
    persist_dir = settings.chroma_persist_dir or settings.chroma_dir
    return ChromaKnowledgeStore(
        persist_dir,
        create_embedding_function(settings, offline=offline),
        collection_names={
            KnowledgeType.PRODUCT_KNOWLEDGE: settings.chroma_product_collection,
            KnowledgeType.REVIEW_INSIGHT: settings.chroma_review_collection,
        },
        score_threshold=settings.rag_score_threshold,
    )


def _print(payload: object, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(payload)


def validate(args: argparse.Namespace) -> int:
    summary = validate_source(args.source)
    _print({"files": [asdict(file) for file in summary.files]}, as_json=args.json)
    return 0 if summary.files else 2


def index(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = _store(offline=args.offline_embeddings)
    embedding_model = getattr(store.embedding_function, "name", lambda: "configured")()
    collections = [KnowledgeType(args.collection)] if args.collection else list(KnowledgeType)
    started = time.perf_counter()
    with FileLock((settings.chroma_persist_dir or settings.chroma_dir) / ".index.lock"):
        manifest = IndexManifest(settings.rag_manifest_path)
        if args.rebuild:
            if args.collection:
                store.clear_collection(KnowledgeType(args.collection))
            else:
                store.clear()
            for knowledge_type in collections:
                manifest.clear_collection(store.collection_names[knowledge_type])
        documents, summary = iter_filtered_documents(
            args.source,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            limit=args.limit,
            knowledge_types={KnowledgeType(args.collection)} if args.collection else None,
        )
        batch = []
        batch_actions: list[str] = []
        stats_by_collection: dict[str, ManifestStats] = {}
        processed = 0
        for document in documents:
            collection = store.collection_names[document.knowledge_type]
            stats = stats_by_collection.setdefault(collection, ManifestStats())
            decision = manifest.decide(collection=collection, document=document, embedding_model=embedding_model)
            if decision.action == "skip":
                stats.skipped += 1
                processed += 1
                if processed % args.progress_every == 0:
                    _progress(processed, stats_by_collection)
                continue
            batch.append(document)
            batch_actions.append(decision.action)
            if len(batch) >= args.batch_size:
                _flush_batch(store, manifest, batch, batch_actions, stats_by_collection, embedding_model)
                processed += len(batch)
                if processed % args.progress_every == 0:
                    _progress(processed, stats_by_collection)
                batch.clear()
                batch_actions.clear()
        if batch:
            _flush_batch(store, manifest, batch, batch_actions, stats_by_collection, embedding_model)
            processed += len(batch)
            batch.clear()
            batch_actions.clear()
        manifest.commit()
        payload = {
            "source": str(args.source),
            "summary": asdict(summary),
            "ingest": {collection: asdict(stats) for collection, stats in stats_by_collection.items()},
            "manifest": manifest.status_counts(),
            "status": store.status(),
            "embedding_model": embedding_model,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        manifest.close()
        _print(payload, as_json=args.json)
        failed = summary.failed + sum(stats.failed for stats in stats_by_collection.values())
        return 1 if failed else 0


def _flush_batch(
    store: ChromaKnowledgeStore,
    manifest: IndexManifest,
    batch: list,
    actions: list[str],
    stats_by_collection: dict[str, ManifestStats],
    embedding_model: str,
) -> None:
    try:
        store.ingest_with_report(batch)
        for document, action in zip(batch, actions, strict=True):
            collection = store.collection_names[document.knowledge_type]
            stats = stats_by_collection.setdefault(collection, ManifestStats())
            if action == "insert":
                stats.inserted += 1
            else:
                stats.updated += 1
            manifest.mark_success(collection=collection, document=document, embedding_model=embedding_model)
        manifest.commit()
    except Exception as exc:
        for document in batch:
            collection = store.collection_names[document.knowledge_type]
            stats = stats_by_collection.setdefault(collection, ManifestStats())
            stats.failed += 1
            manifest.mark_failed(
                collection=collection,
                document=document,
                embedding_model=embedding_model,
                error=str(exc),
            )
        manifest.commit()
        raise


def _progress(processed: int, stats_by_collection: dict[str, ManifestStats]) -> None:
    payload = {"processed": processed, "ingest": {key: asdict(value) for key, value in stats_by_collection.items()}}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def status(args: argparse.Namespace) -> int:
    _print(_store(offline=args.offline_embeddings).status(), as_json=args.json)
    return 0


def query(args: argparse.Namespace) -> int:
    knowledge_type = KnowledgeType(args.collection)
    result = _store(offline=args.offline_embeddings).retrieve(
        query=args.query,
        product_id=args.product_id,
        knowledge_type=knowledge_type,
        top_k=args.top_k,
        fetch_k=args.fetch_k,
    )
    payload = {
        "status": result.status.value,
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "data_gaps": [item.model_dump(mode="json") for item in result.data_gaps],
    }
    _print(payload, as_json=args.json)
    return 0 if result.evidence else 3


def evaluate(args: argparse.Namespace) -> int:
    store = _store(offline=args.offline_embeddings)
    metrics = [
        evaluate_collection(store, KnowledgeType.PRODUCT_KNOWLEDGE),
        evaluate_collection(store, KnowledgeType.REVIEW_INSIGHT),
    ]
    write_evaluation_report(metrics, args.output_dir)
    _print([asdict(item) for item in metrics], as_json=args.json)
    return 0 if all(item.query_count and item.hit_at_5 >= 0.5 for item in metrics) else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradePilot RAG operations")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--offline-embeddings", action="store_true", help="Use deterministic local embeddings.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="Validate data/filtered files.")
    validate_parser.add_argument("--source", type=Path, default=Path("data/filtered"))
    validate_parser.set_defaults(func=validate)

    index_parser = sub.add_parser("index", help="Build or incrementally update Chroma.")
    index_parser.add_argument("--source", type=Path, default=Path("data/filtered"))
    index_parser.add_argument("--rebuild", action="store_true")
    index_parser.add_argument("--limit", type=int, default=None)
    index_parser.add_argument("--collection", choices=[item.value for item in KnowledgeType], default=None)
    index_parser.add_argument("--batch-size", type=int, default=get_settings().rag_index_batch_size)
    index_parser.add_argument("--progress-every", type=int, default=1000)
    index_parser.set_defaults(func=index)

    status_parser = sub.add_parser("status", help="Show Chroma collection status.")
    status_parser.set_defaults(func=status)

    query_parser = sub.add_parser("query", help="Run a retrieval query.")
    query_parser.add_argument("--collection", choices=[item.value for item in KnowledgeType], required=True)
    query_parser.add_argument("--query", required=True)
    query_parser.add_argument("--product-id", required=True)
    query_parser.add_argument("--top-k", type=int, default=get_settings().rag_top_k)
    query_parser.add_argument("--fetch-k", type=int, default=get_settings().rag_fetch_k)
    query_parser.set_defaults(func=query)

    eval_parser = sub.add_parser("evaluate", help="Run deterministic retrieval evaluation.")
    eval_parser.add_argument("--source", type=Path, default=Path("data/filtered"))
    eval_parser.add_argument("--output-dir", type=Path, default=Path("data/reports/rag_eval"))
    eval_parser.set_defaults(func=evaluate)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
