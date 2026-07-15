import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.rag.contracts import KnowledgeDocument
from app.rag.utils import CHUNK_CONFIG_VERSION


@dataclass(slots=True)
class ManifestDecision:
    action: str
    reason: str


@dataclass(slots=True)
class ManifestStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


class IndexManifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def close(self) -> None:
        self.connection.close()

    def _ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_index_manifest (
                collection TEXT NOT NULL,
                document_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_row INTEGER,
                content_hash TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                chunk_config_version TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (collection, chunk_id)
            )
            """
        )
        self.connection.commit()

    def clear_collection(self, collection: str) -> None:
        self.connection.execute("DELETE FROM rag_index_manifest WHERE collection = ?", (collection,))
        self.connection.commit()

    def decide(self, *, collection: str, document: KnowledgeDocument, embedding_model: str) -> ManifestDecision:
        metadata = document.metadata
        row = self.connection.execute(
            """
            SELECT content_hash, embedding_model, chunk_config_version, status
            FROM rag_index_manifest
            WHERE collection = ? AND chunk_id = ?
            """,
            (collection, document.document_id),
        ).fetchone()
        if row is None:
            return ManifestDecision("insert", "new_chunk")
        content_hash, indexed_model, chunk_config_version, status = row
        if (
            status == "success"
            and content_hash == metadata.get("content_hash")
            and indexed_model == embedding_model
            and chunk_config_version == metadata.get("chunk_config_version", CHUNK_CONFIG_VERSION)
        ):
            return ManifestDecision("skip", "unchanged")
        return ManifestDecision("update", "changed")

    def mark_success(self, *, collection: str, document: KnowledgeDocument, embedding_model: str) -> None:
        metadata = document.metadata
        self.connection.execute(
            """
            INSERT INTO rag_index_manifest (
                collection, document_id, chunk_id, source_file, source_row, content_hash,
                embedding_model, chunk_config_version, status, error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', NULL, ?)
            ON CONFLICT(collection, chunk_id) DO UPDATE SET
                document_id=excluded.document_id,
                source_file=excluded.source_file,
                source_row=excluded.source_row,
                content_hash=excluded.content_hash,
                embedding_model=excluded.embedding_model,
                chunk_config_version=excluded.chunk_config_version,
                status='success',
                error=NULL,
                updated_at=excluded.updated_at
            """,
            (
                collection,
                str(metadata.get("document_id") or document.document_id),
                document.document_id,
                str(metadata.get("source_file") or ""),
                _to_int(metadata.get("source_row")),
                str(metadata.get("content_hash") or ""),
                embedding_model,
                str(metadata.get("chunk_config_version") or CHUNK_CONFIG_VERSION),
                _now(),
            ),
        )

    def mark_failed(
        self,
        *,
        collection: str,
        document: KnowledgeDocument,
        embedding_model: str,
        error: str,
    ) -> None:
        metadata = document.metadata
        self.connection.execute(
            """
            INSERT INTO rag_index_manifest (
                collection, document_id, chunk_id, source_file, source_row, content_hash,
                embedding_model, chunk_config_version, status, error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'failed', ?, ?)
            ON CONFLICT(collection, chunk_id) DO UPDATE SET
                status='failed',
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (
                collection,
                str(metadata.get("document_id") or document.document_id),
                document.document_id,
                str(metadata.get("source_file") or ""),
                _to_int(metadata.get("source_row")),
                str(metadata.get("content_hash") or ""),
                embedding_model,
                str(metadata.get("chunk_config_version") or CHUNK_CONFIG_VERSION),
                error[:500],
                _now(),
            ),
        )

    def commit(self) -> None:
        self.connection.commit()

    def status_counts(self) -> dict[str, dict[str, int]]:
        rows = self.connection.execute(
            """
            SELECT collection, status, COUNT(*)
            FROM rag_index_manifest
            GROUP BY collection, status
            """
        ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for collection, status, count in rows:
            counts.setdefault(collection, {})[status] = int(count)
        return counts


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
