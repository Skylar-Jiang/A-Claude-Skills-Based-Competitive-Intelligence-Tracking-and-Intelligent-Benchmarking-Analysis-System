from pathlib import Path

from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin
from app.domain.peer_data import OnlinePeerSelection
from app.domain.peer_matching import PeerMatchResult
from app.schemas.product import ProductCreate, ProductProfile
from app.services.peer_group_service import PeerGroupService


class RecordingStore:
    embedding_function = object()

    def ingest(self, documents):  # type: ignore[no-untyped-def]
        return len(documents)


def test_peer_group_context_records_database_and_rag_ingest_timings(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    selection = OnlinePeerSelection(
        match_result=PeerMatchResult(
            peer_group_id="stable-group",
            peers=[],
            prefilter_count=12,
            rerank_count=8,
            excluded_accessory_count=3,
            match_metadata={"matcher_version": "peer-matcher-v2"},
        ),
        selected_parent_asins=[],
        reviews=[],
        match_duration_ms=5,
        review_read_duration_ms=1,
        total_duration_ms=7,
    )
    monkeypatch.setattr(
        "app.services.peer_group_service.select_peer_group_from_prepared",
        lambda **_kwargs: selection,
    )
    monkeypatch.setattr(
        "app.services.peer_group_service.build_peer_documents",
        lambda **_kwargs: [object(), object()],
    )
    monkeypatch.setattr(PeerGroupService, "_persist", lambda *_args, **_kwargs: None)
    product = ProductProfile(
        product_id="temporary-id",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="New Cat Fountain",
            category="Fountains",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )
    service = PeerGroupService(
        session=object(),  # type: ignore[arg-type]
        knowledge_store=RecordingStore(),  # type: ignore[arg-type]
        settings=Settings(
            _env_file=None,
            peer_metadata_path=tmp_path / "metadata.jsonl",
            peer_reviews_path=tmp_path / "reviews.jsonl",
            peer_cache_dir=tmp_path / "cache",
        ),
    )

    context = service.build_context(product)

    assert context.database_persist_duration_ms >= 0
    assert context.rag_document_build_duration_ms >= 0
    assert context.rag_ingest_duration_ms >= 0
    assert context.peer_group_service_total_duration_ms >= 0
    assert context.documents_ingested == 2


def test_peer_group_service_reports_internal_phase_boundaries(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    selection = OnlinePeerSelection(
        match_result=PeerMatchResult(
            peer_group_id="stable-group",
            peers=[],
            prefilter_count=1,
            rerank_count=1,
            excluded_accessory_count=0,
        ),
        selected_parent_asins=[],
        reviews=[],
        match_duration_ms=1,
        review_read_duration_ms=1,
        total_duration_ms=2,
    )
    monkeypatch.setattr(
        "app.services.peer_group_service.select_peer_group_from_prepared",
        lambda **_kwargs: selection,
    )
    monkeypatch.setattr("app.services.peer_group_service.build_peer_documents", lambda **_kwargs: [])
    monkeypatch.setattr(PeerGroupService, "_persist", lambda *_args, **_kwargs: None)
    product = ProductProfile(
        product_id="temporary-id",
        data_origin=DataOrigin.USER,
        **ProductCreate(name="New Cat Fountain", category="Fountains", data_mode=DataMode.REAL).model_dump(),
    )
    events: list[str] = []
    service = PeerGroupService(
        session=object(),  # type: ignore[arg-type]
        knowledge_store=RecordingStore(),  # type: ignore[arg-type]
        settings=Settings(
            _env_file=None,
            peer_metadata_path=tmp_path / "metadata.jsonl",
            peer_reviews_path=tmp_path / "reviews.jsonl",
            peer_cache_dir=tmp_path / "cache",
        ),
        progress_callback=events.append,
    )

    service.build_context(product)

    assert events == [
        "selection_started",
        "selection_completed",
        "database_persist_started",
        "database_persist_completed",
        "document_build_started",
        "document_build_completed",
        "rag_ingest_started",
        "rag_ingest_completed",
    ]
