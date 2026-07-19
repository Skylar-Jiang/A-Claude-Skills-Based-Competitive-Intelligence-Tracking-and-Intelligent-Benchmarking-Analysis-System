import json
import sqlite3
from pathlib import Path

from app.domain.catalog_type_inventory import CatalogTypeRow, build_catalog_type_inventory
from scripts import audit_catalog_product_types
from scripts.audit_catalog_product_types import (
    audit_catalog,
    build_type_flag_cache,
    render_inventory_markdown,
)


def _row(parent_asin: str, title: str, categories: list[str]) -> CatalogTypeRow:
    return CatalogTypeRow(parent_asin=parent_asin, title=title, categories=categories)


def test_same_concrete_leaf_under_different_paths_is_one_type() -> None:
    inventory = build_catalog_type_inventory(
        [
            _row("A", "3L Cat Water Fountain", ["Pet Supplies", "Cats", "Fountains"]),
            _row("B", "Circulating Cat Dispenser", ["Cat Accessories", "Fountains"]),
        ]
    )

    assert inventory.type_count == 1
    assert inventory.types[0].type_key == "fountains"
    assert inventory.types[0].product_count == 2
    assert inventory.types[0].category_paths == {
        "Cat Accessories > Fountains": 1,
        "Pet Supplies > Cats > Fountains": 1,
    }


def test_generic_leaf_is_qualified_by_parent_instead_of_becoming_one_global_bucket() -> None:
    inventory = build_catalog_type_inventory(
        [
            _row("A", "Cat Accessory", ["Pet Supplies", "Cats", "Accessories"]),
            _row("B", "Pump Accessory", ["Pet Supplies", "Aquariums", "Air Pumps", "Accessories"]),
        ]
    )

    assert {item.type_key for item in inventory.types} == {
        "air pumps / accessories",
        "cats / accessories",
    }


def test_missing_categories_are_explicit_and_every_product_is_counted_once() -> None:
    rows = [
        _row("A", "Cat Water Fountain", ["Pet Supplies", "Cats", "Fountains"]),
        _row("B", "Unknown Product", []),
        _row("C", "Blank Category Product", ["", "  "]),
    ]

    inventory = build_catalog_type_inventory(rows, example_limit=1)

    assert inventory.total_product_count == 3
    assert inventory.assigned_product_count == 3
    assert sum(item.product_count for item in inventory.types) == 3
    assert inventory.unresolved_product_count == 2
    unresolved = next(item for item in inventory.types if item.type_key == "__unresolved__")
    assert unresolved.example_products == [{"parent_asin": "B", "title": "Unknown Product"}]


def test_catalog_audit_reads_catalog_metadata_and_accounts_for_every_row(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_products (
                parent_asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                categories_json TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO catalog_meta VALUES ('source_signature', 'catalog-v1')")
        connection.executemany(
            "INSERT INTO catalog_products VALUES (?, ?, ?)",
            [
                ("A", "Cat Fountain", json.dumps(["Pet Supplies", "Cats", "Fountains"])),
                ("B", "Unknown Product", "[]"),
            ],
        )

    result = audit_catalog(catalog_path)

    assert result["catalog_signature"] == "catalog-v1"
    assert result["taxonomy_basis"] == "source_leaf_with_generic_parent_disambiguation"
    assert result["inventory"]["total_product_count"] == 2
    assert result["inventory"]["assigned_product_count"] == 2


def test_type_flag_cache_contains_every_product_and_is_idempotent(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    cache_path = tmp_path / "product_type_flags.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_products (
                parent_asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                categories_json TEXT NOT NULL
            );
            INSERT INTO catalog_meta VALUES ('schema_version', '2');
            INSERT INTO catalog_meta VALUES ('source_signature', 'catalog-v1');
            """
        )
        connection.executemany(
            "INSERT INTO catalog_products VALUES (?, ?, ?)",
            [
                ("A", "Cat Fountain", json.dumps(["Pet Supplies", "Cats", "Fountains"])),
                ("B", "Unknown Product", "[]"),
            ],
        )

    first = build_type_flag_cache(catalog_path, cache_path)
    second = build_type_flag_cache(catalog_path, cache_path)

    assert first == {"rebuilt": True, "row_count": 2, "unresolved_count": 1, "type_count": 2}
    assert second == {"rebuilt": False, "row_count": 2, "unresolved_count": 1, "type_count": 2}
    with sqlite3.connect(cache_path) as connection:
        flags = connection.execute(
            "SELECT parent_asin, type_key, classification_method, unresolved "
            "FROM product_type_flags ORDER BY parent_asin"
        ).fetchall()
    assert flags == [
        ("A", "fountains", "source_category", 0),
        ("B", "__unresolved__", "missing_source_category", 1),
    ]


def test_type_flag_cache_rebuilds_when_classifier_version_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    cache_path = tmp_path / "product_type_flags.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_products (
                parent_asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                categories_json TEXT NOT NULL
            );
            INSERT INTO catalog_meta VALUES ('schema_version', '2');
            INSERT INTO catalog_meta VALUES ('source_signature', 'catalog-v1');
            INSERT INTO catalog_products VALUES ('A', 'Cat Fountain', '["Pet Supplies", "Fountains"]');
            """
        )

    first = build_type_flag_cache(catalog_path, cache_path)
    monkeypatch.setattr(audit_catalog_product_types, "TYPE_CLASSIFIER_VERSION", "source-leaf-v2")
    second = build_type_flag_cache(catalog_path, cache_path)

    assert first["rebuilt"] is True
    assert second["rebuilt"] is True
    with sqlite3.connect(cache_path) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM type_flag_meta"))
    assert metadata["classifier_version"] == "source-leaf-v2"


def test_inventory_markdown_lists_every_type_with_scope_caveat(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_products (
                parent_asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                categories_json TEXT NOT NULL
            );
            INSERT INTO catalog_meta VALUES ('schema_version', '2');
            INSERT INTO catalog_meta VALUES ('source_signature', 'catalog-v1');
            """
        )
        connection.execute(
            "INSERT INTO catalog_products VALUES (?, ?, ?)",
            ("A", "Cat Fountain", json.dumps(["Pet Supplies", "Cats", "Fountains"])),
        )

    markdown = render_inventory_markdown(audit_catalog(catalog_path))

    assert "# 商品目录终端类型盘点" in markdown
    assert "来源推导的类型候选，不是线上硬分类" in markdown
    assert "| Fountains | `fountains` | 1 |" in markdown
