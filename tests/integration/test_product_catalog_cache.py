import json
from pathlib import Path

from app.domain.product_catalog import ProductCatalog


def _metadata_row(parent_asin: str, title: str) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "title": title,
        "description": ["Automatic drinking fountain for household pets."],
        "features": ["Quiet operation", "Visible water level"],
        "details": {"Target Species": "Cat", "Capacity": "2.5 Liters"},
        "categories": ["Pet Supplies", "Cats", "Fountains"],
        "main_category": "Pet Supplies",
        "price": 35.99,
        "average_rating": 4.4,
        "rating_number": 500,
        "images": [{"variant": "MAIN", "large": f"https://example.test/{parent_asin}.jpg"}],
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_catalog_cache_reuses_unchanged_source_and_returns_normalized_products(tmp_path: Path) -> None:
    source = tmp_path / "metadata.jsonl"
    cache_path = tmp_path / "cache" / "product_catalog.sqlite"
    _write_jsonl(source, [_metadata_row("P1", "Ceramic Cat Water Fountain"), _metadata_row("P2", "Dog Bowl")])

    first = ProductCatalog.build(source, cache_path)
    second = ProductCatalog.build(source, cache_path)
    products = list(second.iter_products())

    assert first.rebuilt is True
    assert first.rows_scanned == 2
    assert first.row_count == 2
    assert first.scan_duration_ms >= 0
    assert second.rebuilt is False
    assert second.rows_scanned == 0
    assert second.source_signature == first.source_signature
    assert [item.parent_asin for item in products] == ["P1", "P2"]
    assert products[0].target_species == ["cat"]
    assert products[0].image_url == "https://example.test/P1.jpg"


def test_catalog_cache_rebuilds_when_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "metadata.jsonl"
    cache_path = tmp_path / "product_catalog.sqlite"
    _write_jsonl(source, [_metadata_row("P1", "Ceramic Cat Water Fountain")])
    ProductCatalog.build(source, cache_path)
    _write_jsonl(
        source,
        [
            _metadata_row("P1", "Ceramic Cat Water Fountain"),
            _metadata_row("P2", "Stainless Cat Water Fountain"),
        ],
    )

    rebuilt = ProductCatalog.build(source, cache_path)

    assert rebuilt.rebuilt is True
    assert rebuilt.rows_scanned == 2
    assert rebuilt.row_count == 2
