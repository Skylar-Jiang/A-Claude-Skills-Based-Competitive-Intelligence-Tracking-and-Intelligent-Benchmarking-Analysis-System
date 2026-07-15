from pathlib import Path

import yaml


def test_real_product_smoke_manifest_is_concrete_test_preparation_not_a_classifier() -> None:
    path = Path("config/real_product_smoke_manifest.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    products = payload["products"]

    assert payload["purpose"] == "lightweight_real_peer_matching_validation_only"
    assert 8 <= len(products) <= 12
    assert len({item["case_id"] for item in products}) == len(products)
    assert len({item["category"] for item in products}) == len(products)
    for product in products:
        assert product["name"]
        assert product["description"]
        assert len(product["features"]) >= 3
        assert product["attributes"]["Target Species"]
        assert not ({"test_peer_pool", "global_category", "category_label"} & set(product))


def test_multi_product_smoke_script_does_not_create_global_groups_or_full_indexes() -> None:
    script = Path("scripts/smoke_multi_product_matching.py").read_text(encoding="utf-8")

    assert "ProductCatalog.open_prepared" in script
    assert "ReviewLookup.open_prepared" in script
    assert "iter_candidates" in script
    assert "iter_products" not in script
    assert "test_peer_pool" not in script
    assert "ChromaKnowledgeStore" not in script
    assert "prepare_peer_data(" not in script
