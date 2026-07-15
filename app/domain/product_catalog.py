from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.exceptions import DataPreparationRequiredError
from app.domain.peer_matching import (
    GENERIC_TOKENS,
    TOKEN_PATTERN,
    CandidateProductSignature,
    CatalogProduct,
)

CATALOG_SCHEMA_VERSION = 2


@dataclass(slots=True)
class ProductCatalog:
    source_path: Path
    cache_path: Path
    source_signature: str
    rebuilt: bool
    row_count: int
    rows_scanned: int
    scan_duration_ms: int

    @classmethod
    def build(cls, source_path: Path, cache_path: Path) -> ProductCatalog:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        signature = _source_signature(source_path)
        cached_count = _cached_row_count(cache_path, signature)
        if cached_count is not None:
            return cls(
                source_path=source_path,
                cache_path=cache_path,
                source_signature=signature,
                rebuilt=False,
                row_count=cached_count,
                rows_scanned=0,
                scan_duration_ms=0,
            )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".building")
        temporary_path.unlink(missing_ok=True)
        started = time.perf_counter()
        row_count, rows_scanned = _build_cache(source_path, temporary_path, signature)
        temporary_path.replace(cache_path)
        return cls(
            source_path=source_path,
            cache_path=cache_path,
            source_signature=signature,
            rebuilt=True,
            row_count=row_count,
            rows_scanned=rows_scanned,
            scan_duration_ms=round((time.perf_counter() - started) * 1000),
        )

    @classmethod
    def open_prepared(cls, source_path: Path, cache_path: Path) -> ProductCatalog:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        signature = _source_signature(source_path)
        if not cache_path.is_file():
            raise DataPreparationRequiredError("product catalog")
        row_count = _cached_row_count(cache_path, signature)
        if row_count is None:
            raise DataPreparationRequiredError("product catalog", stale=True)
        return cls(
            source_path=source_path,
            cache_path=cache_path,
            source_signature=signature,
            rebuilt=False,
            row_count=row_count,
            rows_scanned=0,
            scan_duration_ms=0,
        )

    def iter_products(self) -> Iterator[CatalogProduct]:
        with closing(sqlite3.connect(self.cache_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT parent_asin, title, description, features_json, details_json,
                       categories_json, main_category, target_species_json, price,
                       average_rating, rating_number, source_line, image_url
                FROM catalog_products
                ORDER BY source_line
                """
            )
            for row in rows:
                yield CatalogProduct(
                    parent_asin=row["parent_asin"],
                    title=row["title"],
                    description=row["description"],
                    features=json.loads(row["features_json"]),
                    details=json.loads(row["details_json"]),
                    categories=json.loads(row["categories_json"]),
                    main_category=row["main_category"],
                    target_species=json.loads(row["target_species_json"]),
                    price=Decimal(row["price"]) if row["price"] is not None else None,
                    average_rating=row["average_rating"],
                    rating_number=row["rating_number"],
                    source_line=row["source_line"],
                    image_url=row["image_url"],
                )

    def iter_candidates(
        self,
        signature: CandidateProductSignature,
        *,
        candidate_limit: int = 1200,
    ) -> Iterator[CatalogProduct]:
        tokens = {
            token.casefold()
            for token in TOKEN_PATTERN.findall(signature.matching_text())
            if token.casefold() not in GENERIC_TOKENS and len(token) > 1
        }
        with closing(sqlite3.connect(self.cache_path)) as connection:
            connection.row_factory = sqlite3.Row
            if tokens:
                query = " OR ".join(f'"{token}"' for token in sorted(tokens))
                rows = connection.execute(
                    """
                    SELECT p.parent_asin, p.title, p.description, p.features_json, p.details_json,
                           p.categories_json, p.main_category, p.target_species_json, p.price,
                           p.average_rating, p.rating_number, p.source_line, p.image_url
                    FROM catalog_fts AS f
                    JOIN catalog_products AS p ON p.parent_asin = f.parent_asin
                    WHERE catalog_fts MATCH ?
                    ORDER BY bm25(catalog_fts), COALESCE(p.rating_number, 0) DESC
                    LIMIT ?
                    """,
                    (query, candidate_limit),
                )
            else:
                rows = connection.execute(
                    """
                    SELECT parent_asin, title, description, features_json, details_json,
                           categories_json, main_category, target_species_json, price,
                           average_rating, rating_number, source_line, image_url
                    FROM catalog_products
                    ORDER BY COALESCE(rating_number, 0) DESC, source_line
                    LIMIT ?
                    """,
                    (candidate_limit,),
                )
            for row in rows:
                yield _row_to_product(row)


def _source_signature(path: Path) -> str:
    stat = path.stat()
    payload = json.dumps(
        {
            "schema": CATALOG_SCHEMA_VERSION,
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_row_count(path: Path, signature: str) -> int | None:
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path)) as connection:
            rows = dict(connection.execute("SELECT key, value FROM catalog_meta"))
    except sqlite3.Error:
        return None
    if rows.get("source_signature") != signature:
        return None
    try:
        return int(rows["row_count"])
    except (KeyError, ValueError):
        return None


def _build_cache(source_path: Path, cache_path: Path, signature: str) -> tuple[int, int]:
    row_count = 0
    rows_scanned = 0
    with closing(sqlite3.connect(cache_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_products (
                parent_asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                features_json TEXT NOT NULL,
                details_json TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                main_category TEXT NOT NULL,
                target_species_json TEXT NOT NULL,
                price TEXT,
                average_rating REAL,
                rating_number INTEGER,
                source_line INTEGER NOT NULL,
                image_url TEXT,
                normalized_text TEXT NOT NULL
            );
            CREATE INDEX ix_catalog_products_source_line ON catalog_products(source_line);
            CREATE VIRTUAL TABLE catalog_fts USING fts5(
                parent_asin UNINDEXED,
                normalized_text,
                tokenize='unicode61'
            );
            """
        )
        with source_path.open("r", encoding="utf-8") as source:
            for source_line, line in enumerate(source, start=1):
                rows_scanned = source_line
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                product = _catalog_product(value, source_line)
                if product is None:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO catalog_products (
                        parent_asin, title, description, features_json, details_json,
                        categories_json, main_category, target_species_json, price,
                        average_rating, rating_number, source_line, image_url, normalized_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product.parent_asin,
                        product.title,
                        product.description,
                        json.dumps(product.features, ensure_ascii=False),
                        json.dumps(product.details, ensure_ascii=False, default=str),
                        json.dumps(product.categories, ensure_ascii=False),
                        product.main_category,
                        json.dumps(product.target_species, ensure_ascii=False),
                        str(product.price) if product.price is not None else None,
                        product.average_rating,
                        product.rating_number,
                        product.source_line,
                        product.image_url,
                        product.matching_text().casefold(),
                    ),
                )
                connection.execute(
                    "INSERT INTO catalog_fts (parent_asin, normalized_text) VALUES (?, ?)",
                    (product.parent_asin, product.matching_text().casefold()),
                )
                row_count += 1
                if row_count % 2000 == 0:
                    connection.commit()
        connection.executemany(
            "INSERT INTO catalog_meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", str(CATALOG_SCHEMA_VERSION)),
                ("source_signature", signature),
                ("row_count", str(row_count)),
            ],
        )
        connection.commit()
    return row_count, rows_scanned


def _row_to_product(row: sqlite3.Row) -> CatalogProduct:
    return CatalogProduct(
        parent_asin=row["parent_asin"],
        title=row["title"],
        description=row["description"],
        features=json.loads(row["features_json"]),
        details=json.loads(row["details_json"]),
        categories=json.loads(row["categories_json"]),
        main_category=row["main_category"],
        target_species=json.loads(row["target_species_json"]),
        price=Decimal(row["price"]) if row["price"] is not None else None,
        average_rating=row["average_rating"],
        rating_number=row["rating_number"],
        source_line=row["source_line"],
        image_url=row["image_url"],
    )


def _catalog_product(value: dict[str, Any], source_line: int) -> CatalogProduct | None:
    parent_asin = _text(value.get("parent_asin"))
    title = _text(value.get("title"))
    if not parent_asin or not title:
        return None
    details = value.get("details") if isinstance(value.get("details"), dict) else {}
    features = _string_list(value.get("features"))
    categories = _string_list(value.get("categories"))
    target_species = _string_list(details.get("Target Species"))
    if not target_species and details.get("Target Species"):
        target_species = [
            item.strip().casefold()
            for item in str(details["Target Species"]).replace("/", ",").split(",")
            if item.strip()
        ]
    return CatalogProduct(
        parent_asin=parent_asin,
        title=title,
        description=_description(value.get("description")),
        features=features,
        details=details,
        categories=categories,
        main_category=_text(value.get("main_category")),
        target_species=target_species,
        price=_decimal(value.get("price")),
        average_rating=_float(value.get("average_rating")),
        rating_number=_int(value.get("rating_number")),
        source_line=source_line,
        image_url=_image_url(value.get("images")),
    )


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _description(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(item for item in (_text(part) for part in value) if item)
    return _text(value)


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_text(part) for part in value) if item]
    if isinstance(value, str):
        return [item.strip().casefold() for item in value.split(",") if item.strip()]
    return []


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _image_url(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for image in value:
        if not isinstance(image, dict):
            continue
        for key in ("hi_res", "large"):
            candidate = image.get(key)
            if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
                return candidate
    return None
