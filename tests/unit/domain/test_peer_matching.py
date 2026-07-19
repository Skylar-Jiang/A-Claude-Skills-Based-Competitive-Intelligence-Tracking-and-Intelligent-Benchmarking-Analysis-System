from decimal import Decimal
from pathlib import Path

from app.core.enums import DataMode, DataOrigin
from app.domain.peer_matching import (
    CandidateProductSignature,
    CatalogProduct,
    PeerMatchConfig,
    PeerMatcher,
    load_peer_match_config,
    rule_prefilter,
)
from app.schemas.product import ProductCreate, ProductProfile


def _new_product() -> ProductProfile:
    return ProductProfile(
        product_id="new-product-1",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="Quiet Cat Water Fountain",
            category="Pet Supplies > Cats > Fountains",
            description="Automatic circulating drinking fountain for indoor cats.",
            attributes={"details": {"Target Species": "Cat"}, "capacity": "2.5 L"},
            features=["quiet pump", "visible water level", "easy-clean reservoir"],
            use_scenarios=["indoor daily hydration"],
            target_audience=["cat owners"],
            target_price=Decimal("39.99"),
            target_currency="USD",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )


def _catalog_product(
    parent_asin: str,
    title: str,
    *,
    price: Decimal = Decimal("35.99"),
    features: list[str] | None = None,
) -> CatalogProduct:
    return CatalogProduct(
        parent_asin=parent_asin,
        title=title,
        description="Automatic drinking fountain for cats.",
        features=features or ["quiet operation", "water level window"],
        details={"Target Species": "Cat", "Capacity": "2.5 Liters"},
        categories=["Pet Supplies", "Cats", "Fountains"],
        main_category="Pet Supplies",
        target_species=["cat"],
        price=price,
        average_rating=4.4,
        rating_number=500,
        source_line=12,
        image_url="https://example.test/product.jpg",
    )


def test_candidate_signature_contains_all_new_product_matching_inputs() -> None:
    signature = CandidateProductSignature.from_product(
        _new_product(),
        vision_summary="White reservoir with a raised drinking tray.",
    )

    assert signature.name == "Quiet Cat Water Fountain"
    assert signature.description.startswith("Automatic circulating")
    assert signature.features == ["quiet pump", "visible water level", "easy-clean reservoir"]
    assert signature.parameters["capacity"] == "2.5 L"
    assert signature.use_scenarios == ["indoor daily hydration"]
    assert "cat" in signature.target_species
    assert signature.target_audience == ["cat owners"]
    assert signature.vision_summary.startswith("White reservoir")
    assert signature.target_price == Decimal("39.99")


def test_default_config_keeps_accessory_terms_out_of_python_source() -> None:
    config = load_peer_match_config(Path("config/peer_matching.yaml"))

    assert {"replacement filter", "pump", "mat", "cleaning brush", "power adapter"}.issubset(
        set(config.accessory_terms)
    )
    assert 100 <= config.prefilter_limit <= 300
    assert 20 <= config.rerank_limit <= 50
    assert 10 <= config.final_peer_limit <= 30


def test_default_config_excludes_real_fountain_accessory_title_variants() -> None:
    signature = CandidateProductSignature.from_product(_new_product())
    config = load_peer_match_config(Path("config/peer_matching.yaml"))
    complete = _catalog_product(
        "FOUNTAIN",
        "3L Cat Water Fountain with 3 Filters and Quiet Circulation",
    )
    accessories = [
        _catalog_product("FILTERS", "NautyPaws Cat Fountain Filters, 16 Pack"),
        _catalog_product("FILTER", "Cat Water Fountain Filter, 16 Pack"),
        _catalog_product("SPONGE", "Cat Fountain Filter Replacement Sponge Foam"),
        _catalog_product("KIT", "PETKIT Cat Water Fountain Cleaning Kit"),
    ]

    result = rule_prefilter(signature, [complete, *accessories], config)

    assert [item.product.parent_asin for item in result.candidates] == ["FOUNTAIN"]
    assert result.excluded_accessory_count == len(accessories)


def test_rule_prefilter_excludes_accessories_and_does_not_use_price_as_the_only_signal() -> None:
    signature = CandidateProductSignature.from_product(_new_product())
    config = PeerMatchConfig(
        accessory_terms=["replacement filter", "pump", "mat", "cleaning brush", "power adapter"],
        prefilter_limit=100,
        rerank_limit=20,
        final_peer_limit=10,
        minimum_rule_score=0.2,
    )
    complete = _catalog_product("FOUNTAIN", "Ceramic Cat Water Fountain")
    accessory = _catalog_product("FILTER", "Replacement Filter for Cat Water Fountain")
    unrelated_same_price = _catalog_product(
        "HARNESS",
        "Reflective Dog Walking Harness",
        price=Decimal("39.99"),
        features=["reflective trim", "adjustable chest strap"],
    ).model_copy(
        update={
            "description": "Walking harness for dogs.",
            "categories": ["Pet Supplies", "Dogs", "Harnesses"],
            "target_species": ["dog"],
        }
    )

    result = rule_prefilter(signature, [complete, accessory, unrelated_same_price], config)

    assert [item.product.parent_asin for item in result.candidates] == ["FOUNTAIN"]
    assert result.excluded_accessory_count == 1
    assert result.candidates[0].is_accessory is False
    assert "product keywords" in result.candidates[0].match_reason


class RecordingEmbedding:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [
            [
                1.0 if "fountain" in text.casefold() else 0.0,
                1.0 if "cat" in text.casefold() else 0.0,
                float(len(text) % 17) / 17,
            ]
            for text in texts
        ]


def test_peer_matcher_embeds_only_prefiltered_candidates_and_returns_stable_peers() -> None:
    signature = CandidateProductSignature.from_product(_new_product())
    products = [
        _catalog_product(
            f"FOUNTAIN-{index:03d}",
            f"Ceramic Cat Water Fountain Model {index}",
            price=Decimal("29.99") + index % 10,
        )
        for index in range(120)
    ]
    products.extend(
        _catalog_product(f"FILTER-{index:03d}", "Replacement Filter for Cat Water Fountain")
        for index in range(10)
    )
    embedding = RecordingEmbedding()
    config = PeerMatchConfig(
        accessory_terms=["replacement filter"],
        prefilter_limit=100,
        rerank_limit=20,
        final_peer_limit=10,
        minimum_rule_score=0.2,
    )

    first = PeerMatcher(embedding, config).match(signature, products)
    second = PeerMatcher(RecordingEmbedding(), config).match(signature, products)

    assert first.prefilter_count == 100
    assert first.rerank_count == 20
    assert first.excluded_accessory_count == 10
    assert len(embedding.inputs) == first.prefilter_count + 1
    assert len(first.peers) == 10
    assert all(not item.is_accessory for item in first.peers)
    assert all(item.match_method == "rules+embedding" for item in first.peers)
    assert len({item.peer_group_id for item in first.peers}) == 1
    assert first.peer_group_id == second.peer_group_id
    assert [item.parent_asin for item in first.peers] == [item.parent_asin for item in second.peers]
