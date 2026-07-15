from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import DataPreparationRequiredError

REVIEW_LOOKUP_SCHEMA_VERSION = 1


class IndexedReview(BaseModel):
    parent_asin: str
    source_row: int
    record: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class ReviewLookup:
    source_path: Path
    cache_path: Path
    source_signature: str
    rebuilt: bool
    review_count: int
    parent_count: int
    rows_scanned: int
    build_duration_ms: int

    @classmethod
    def build(cls, source_path: Path, cache_path: Path) -> ReviewLookup:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        signature = _source_signature(source_path)
        metadata = _cached_metadata(cache_path, signature)
        if metadata is not None:
            return cls(
                source_path=source_path,
                cache_path=cache_path,
                source_signature=signature,
                rebuilt=False,
                review_count=metadata["review_count"],
                parent_count=metadata["parent_count"],
                rows_scanned=0,
                build_duration_ms=0,
            )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".building")
        temporary_path.unlink(missing_ok=True)
        started = time.perf_counter()
        review_count, parent_count, rows_scanned = _build_cache(source_path, temporary_path, signature)
        temporary_path.replace(cache_path)
        return cls(
            source_path=source_path,
            cache_path=cache_path,
            source_signature=signature,
            rebuilt=True,
            review_count=review_count,
            parent_count=parent_count,
            rows_scanned=rows_scanned,
            build_duration_ms=round((time.perf_counter() - started) * 1000),
        )

    @classmethod
    def open_prepared(cls, source_path: Path, cache_path: Path) -> ReviewLookup:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        signature = _source_signature(source_path)
        if not cache_path.is_file():
            raise DataPreparationRequiredError("review lookup")
        metadata = _cached_metadata(cache_path, signature)
        if metadata is None:
            raise DataPreparationRequiredError("review lookup", stale=True)
        return cls(
            source_path=source_path,
            cache_path=cache_path,
            source_signature=signature,
            rebuilt=False,
            review_count=metadata["review_count"],
            parent_count=metadata["parent_count"],
            rows_scanned=0,
            build_duration_ms=0,
        )

    def read(self, parent_asins: list[str], *, max_total: int = 300) -> list[IndexedReview]:
        selected = list(dict.fromkeys(item for item in parent_asins if item))
        if not selected or max_total < 1:
            return []
        placeholders = ", ".join("?" for _ in selected)
        with closing(sqlite3.connect(self.cache_path)) as connection:
            rows = list(
                connection.execute(
                    f"""
                    SELECT parent_asin, source_row, byte_offset, byte_length
                    FROM review_offsets
                    WHERE parent_asin IN ({placeholders})
                    ORDER BY source_row
                    LIMIT ?
                    """,  # noqa: S608 - placeholders are generated, values remain parameterized
                    [*selected, max_total * 2],
                )
            )
        result: list[IndexedReview] = []
        seen_reviews: set[tuple[object, ...]] = set()
        with self.source_path.open("rb") as source:
            for parent_asin, source_row, byte_offset, byte_length in rows:
                source.seek(byte_offset)
                raw = source.read(byte_length)
                try:
                    value = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(value, dict) or value.get("parent_asin") != parent_asin:
                    continue
                review_key = (
                    parent_asin,
                    value.get("asin") or "",
                    value.get("user_id") or "",
                    value.get("timestamp") or "",
                    value.get("title") or "",
                    value.get("text") or "",
                )
                if review_key in seen_reviews:
                    continue
                seen_reviews.add(review_key)
                result.append(
                    IndexedReview(
                        parent_asin=parent_asin,
                        source_row=source_row,
                        record=value,
                    )
                )
                if len(result) >= max_total:
                    break
        return result


def _source_signature(path: Path) -> str:
    stat = path.stat()
    payload = json.dumps(
        {
            "schema": REVIEW_LOOKUP_SCHEMA_VERSION,
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_metadata(path: Path, signature: str) -> dict[str, int] | None:
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path)) as connection:
            values = dict(connection.execute("SELECT key, value FROM review_lookup_meta"))
    except sqlite3.Error:
        return None
    if values.get("source_signature") != signature:
        return None
    try:
        return {
            "review_count": int(values["review_count"]),
            "parent_count": int(values["parent_count"]),
        }
    except (KeyError, ValueError):
        return None


def _build_cache(source_path: Path, cache_path: Path, signature: str) -> tuple[int, int, int]:
    review_count = 0
    rows_scanned = 0
    with closing(sqlite3.connect(cache_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE review_lookup_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE review_offsets (
                parent_asin TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                byte_offset INTEGER NOT NULL,
                byte_length INTEGER NOT NULL,
                PRIMARY KEY (parent_asin, source_row)
            );
            CREATE INDEX ix_review_offsets_source_row ON review_offsets(source_row);
            """
        )
        with source_path.open("rb") as source:
            source_row = 0
            while True:
                byte_offset = source.tell()
                raw = source.readline()
                if not raw:
                    break
                source_row += 1
                rows_scanned = source_row
                try:
                    value = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                parent_asin = str(value.get("parent_asin") or "").strip()
                if not parent_asin:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO review_offsets
                    (parent_asin, source_row, byte_offset, byte_length)
                    VALUES (?, ?, ?, ?)
                    """,
                    (parent_asin, source_row, byte_offset, len(raw)),
                )
                review_count += 1
                if review_count % 5000 == 0:
                    connection.commit()
        parent_count = int(
            connection.execute("SELECT COUNT(DISTINCT parent_asin) FROM review_offsets").fetchone()[0]
        )
        connection.executemany(
            "INSERT INTO review_lookup_meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", str(REVIEW_LOOKUP_SCHEMA_VERSION)),
                ("source_signature", signature),
                ("review_count", str(review_count)),
                ("parent_count", str(parent_count)),
            ],
        )
        connection.commit()
    return review_count, parent_count, rows_scanned
