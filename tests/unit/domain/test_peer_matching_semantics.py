import json
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
from app.domain.product_catalog import ProductCatalog
from app.schemas.product import ProductCreate, ProductProfile


class TerminalProductEmbedding:
    """Tiny semantic fixture: fountain/dispenser are peers; feeder is another terminal product."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            normalized = text.casefold()
            if any(token in normalized for token in ("feeder", "feeding food", "food dispenser")):
                vectors.append([0.0, 1.0])
            elif any(token in normalized for token in ("fountain", "circulating drinking", "water dispenser")):
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.2, 0.2])
        return vectors

    @staticmethod
    def name() -> str:
        return "terminal-product-embedding-v1"


class CrossLingualHarnessEmbedding:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0]
            if "harness" in text.casefold() or "胸背带" in text
            else [0.0, 1.0]
            for text in texts
        ]

    @staticmethod
    def name() -> str:
        return "cross-lingual-harness-test-v1"


def _candidate(product_id: str = "candidate-a") -> ProductProfile:
    return ProductProfile(
        product_id=product_id,
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="3L Stainless Steel Cat Water Fountain",
            category="Pet Supplies > Feeding & Watering",
            description="A circulating drinking water dispenser for indoor cats.",
            attributes={"Target Species": "Cat", "capacity": "3L"},
            features=["circulating drinking water", "stainless steel tray", "easy cleaning"],
            use_scenarios=["indoor cat hydration"],
            target_audience=["cat owners"],
            target_price=Decimal("39.99"),
            data_mode=DataMode.REAL,
        ).model_dump(),
    )


def _chinese_harness_candidate() -> ProductProfile:
    return ProductProfile(
        product_id="candidate-zh-harness",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="轻量反光防挣脱犬用胸背带",
            category="犬用胸背带",
            description="适合城市遛犬和夜间出行。",
            features=["反光织带", "四点调节", "前后双牵引环", "透气网布"],
            use_scenarios=["日常遛犬", "夜间出行"],
            target_audience=["中小型犬主人"],
            target_price=Decimal("29.99"),
            data_mode=DataMode.REAL,
        ).model_dump(),
    )


def _product(
    parent_asin: str,
    title: str,
    *,
    description: str,
    features: list[str],
    categories: list[str] | None,
    main_category: str = "Pet Supplies",
    price: Decimal = Decimal("39.99"),
) -> CatalogProduct:
    return CatalogProduct(
        parent_asin=parent_asin,
        title=title,
        description=description,
        features=features,
        details={"Target Species": "Cat"},
        categories=categories or [],
        main_category=main_category,
        target_species=["cat"],
        price=price,
        average_rating=4.3,
        rating_number=100,
        source_line=1,
    )


def _config(*, matcher_version: str = "peer-matcher-v2") -> PeerMatchConfig:
    return PeerMatchConfig(
        accessory_terms=["replacement water pump", "replacement filter", "feeding mat", "accessory"],
        prefilter_limit=100,
        rerank_limit=20,
        final_peer_limit=10,
        minimum_rule_score=0.2,
        minimum_semantic_score=0.5,
        matcher_version=matcher_version,
    )


def _write_catalog(path: Path, products: list[CatalogProduct]) -> None:
    rows = []
    for product in products:
        rows.append(
            {
                "parent_asin": product.parent_asin,
                "title": product.title,
                "description": [product.description],
                "features": product.features,
                "details": product.details,
                "categories": product.categories,
                "main_category": product.main_category,
                "price": float(product.price) if product.price is not None else None,
                "average_rating": product.average_rating,
                "rating_number": product.rating_number,
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_config_excludes_realistic_filter_replacement_pole_and_receiver_only_titles() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    config = load_peer_match_config(Path("config/peer_matching.yaml"))
    complete = _product(
        "COMPLETE",
        "3L Stainless Steel Cat Water Fountain with 3 Filters",
        description="Complete circulating drinking fountain.",
        features=["stainless basin", "circulating water"],
        categories=["Pet Supplies", "Feeding & Watering"],
    )
    accessories = [
        _product(
            "FILTERS",
            "Cat Water Fountain Filters 12 Pack for Stainless Steel Pet Fountain",
            description="Carbon filter replacements.",
            features=["filter media"],
            categories=["Pet Supplies", "Fountain Supplies"],
        ),
        _product(
            "POLE",
            "Natural Sisal Spare Cat Scratching Post Replacement Pole",
            description="Replacement pole for a cat tree.",
            features=["sisal replacement"],
            categories=["Pet Supplies", "Cat Furniture Parts"],
        ),
        _product(
            "RECEIVER",
            "Replacement Dog Training Collar Receiver Only Without Remote",
            description="Single replacement receiver.",
            features=["receiver only"],
            categories=["Pet Supplies", "Training Collar Parts"],
        ),
        _product(
            "COVER",
            "Replacement Outer Cover (Cover ONLY - NO Bed) for Orthopedic Dog Bed",
            description="Washable replacement cover.",
            features=["fabric cover"],
            categories=["Pet Supplies", "Dog Bed Covers"],
        ),
    ]

    result = rule_prefilter(signature, [complete, *accessories], config)

    assert [item.product.parent_asin for item in result.candidates] == ["COMPLETE"]
    assert result.excluded_accessory_count == 4


def test_different_category_text_can_recall_and_match_same_terminal_product(tmp_path: Path) -> None:
    peer = _product(
        "PEER-DISPENSER",
        "Automatic Circulating Drinking Dispenser for Cats",
        description="A stainless steel circulating drinking water dispenser for cats.",
        features=["circulating drinking water", "3L reservoir"],
        categories=["Cat Accessories"],
    )
    source = tmp_path / "metadata.jsonl"
    _write_catalog(source, [peer])
    catalog = ProductCatalog.build(source, tmp_path / "catalog.sqlite")
    signature = CandidateProductSignature.from_product(_candidate())

    recalled = list(catalog.iter_candidates(signature))
    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(signature, recalled)

    assert [item.parent_asin for item in recalled] == ["PEER-DISPENSER"]
    assert [item.parent_asin for item in result.peers] == ["PEER-DISPENSER"]


def test_chinese_harness_input_recalls_and_matches_english_harness_catalog(tmp_path: Path) -> None:
    peers = [
        CatalogProduct(
            parent_asin=f"HARNESS-{index:02d}",
            title=f"Reflective No Pull Dog Harness Model {index}",
            description="Adjustable escape proof walking harness for dogs.",
            features=["reflective webbing", "front leash clip", "breathable mesh"],
            details={"Target Species": "Dog"},
            categories=["Pet Supplies", "Dogs", "Harnesses"],
            main_category="Pet Supplies",
            target_species=["dog"],
            price=Decimal("29.99"),
            average_rating=4.4,
            rating_number=500 + index,
            source_line=index + 1,
        )
        for index in range(12)
    ]
    source = tmp_path / "metadata.jsonl"
    _write_catalog(source, peers)
    catalog = ProductCatalog.build(source, tmp_path / "catalog.sqlite")
    signature = CandidateProductSignature.from_product(_chinese_harness_candidate())

    recalled = list(catalog.iter_candidates(signature))
    result = PeerMatcher(CrossLingualHarnessEmbedding(), _config()).match(signature, recalled)

    assert signature.target_species == ["dog"]
    assert len(recalled) == 12
    assert result.prefilter_count == 12
    assert len(result.peers) == 10


def test_same_main_category_does_not_define_peer_relationship() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    fountain = _product(
        "FOUNTAIN",
        "Stainless Steel Cat Water Fountain",
        description="Circulating drinking water fountain for cats.",
        features=["circulating drinking water"],
        categories=["Pet Supplies", "Feeding & Watering"],
    )
    feeder = _product(
        "FEEDER",
        "Automatic Cat Feeder",
        description="Timed feeding food dispenser for cats.",
        features=["scheduled dry food portions"],
        categories=["Pet Supplies", "Feeders"],
    )

    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(signature, [fountain, feeder])

    assert [item.parent_asin for item in result.peers] == ["FOUNTAIN"]


def test_missing_categories_does_not_block_fts_recall_or_matching(tmp_path: Path) -> None:
    peer = _product(
        "NO-CATEGORY",
        "Quiet Stainless Cat Water Fountain",
        description="A circulating drinking fountain with an easy-clean reservoir.",
        features=["circulating drinking water", "stainless steel tray"],
        categories=None,
    )
    source = tmp_path / "metadata.jsonl"
    _write_catalog(source, [peer])
    catalog = ProductCatalog.build(source, tmp_path / "catalog.sqlite")
    signature = CandidateProductSignature.from_product(_candidate())

    recalled = list(catalog.iter_candidates(signature))
    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(signature, recalled)

    assert recalled[0].categories == []
    assert [item.parent_asin for item in result.peers] == ["NO-CATEGORY"]


def test_complete_product_can_mention_pump_while_replacement_accessories_are_excluded() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    complete = _product(
        "COMPLETE",
        "Complete Stainless Steel Cat Water Fountain",
        description="Complete fountain with a built-in water pump and reservoir.",
        features=["circulating drinking water", "built-in water pump"],
        categories=["Pet Supplies", "Fountains"],
    )
    accessories = [
        _product(
            "PUMP",
            "Replacement Water Pump for Cat Fountain",
            description="Replacement part.",
            features=["pump"],
            categories=["Pet Supplies", "Accessories"],
        ),
        _product(
            "FILTER",
            "Replacement Filter for Cat Water Fountain",
            description="Replacement filter pack.",
            features=["filter"],
            categories=["Pet Supplies", "Accessories"],
        ),
        _product(
            "MAT",
            "Feeding Mat for Cat Fountain",
            description="Silicone feeding mat.",
            features=["mat"],
            categories=["Pet Supplies", "Accessories"],
        ),
    ]

    result = rule_prefilter(signature, [complete, *accessories], _config())

    assert [item.product.parent_asin for item in result.candidates] == ["COMPLETE"]
    assert result.excluded_accessory_count == 3


def test_same_categories_and_price_cannot_select_a_different_terminal_product() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    fountain = _product(
        "FOUNTAIN",
        "Stainless Steel Cat Water Fountain",
        description="Circulating drinking water fountain for cats.",
        features=["circulating drinking water"],
        categories=["Pet Supplies", "Feeding & Watering"],
    )
    mislabeled_feeder = _product(
        "FEEDER-SAME-CATEGORY",
        "Automatic Cat Feeder",
        description="Timed feeding food dispenser for cats.",
        features=["scheduled dry food portions"],
        categories=["Pet Supplies", "Feeding & Watering"],
    )

    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(
        signature, [fountain, mislabeled_feeder]
    )

    assert [item.parent_asin for item in result.peers] == ["FOUNTAIN"]


def test_full_match_does_not_require_a_global_classification_label() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    peers = [
        _product(
            f"PEER-{index}",
            f"Circulating Drinking Dispenser for Cats Model {index}",
            description="Complete circulating drinking water dispenser.",
            features=["circulating drinking water", "easy-clean reservoir"],
            categories=None,
        )
        for index in range(12)
    ]

    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(signature, peers)

    assert result.prefilter_count == 12
    assert len(result.peers) == 10
    assert all(item.product.categories == [] for item in result.peers)


def test_peer_group_id_binds_stable_product_input_data_config_and_selected_peers() -> None:
    peer = _product(
        "FOUNTAIN",
        "Stainless Steel Cat Water Fountain",
        description="Circulating drinking water fountain for cats.",
        features=["circulating drinking water"],
        categories=["Pet Supplies", "Fountains"],
    )
    first_signature = CandidateProductSignature.from_product(_candidate("candidate-a"))
    second_signature = CandidateProductSignature.from_product(_candidate("candidate-b"))
    matcher = PeerMatcher(TerminalProductEmbedding(), _config())

    first = matcher.match(first_signature, [peer], group_context="catalog-source-a")
    repeated = matcher.match(first_signature, [peer], group_context="catalog-source-a")
    same_input_new_temporary_id = matcher.match(
        second_signature, [peer], group_context="catalog-source-a"
    )
    another_config = PeerMatcher(
        TerminalProductEmbedding(), _config(matcher_version="peer-matcher-v3")
    ).match(first_signature, [peer], group_context="catalog-source-a")
    another_data_version = matcher.match(first_signature, [peer], group_context="catalog-source-b")
    another_peer = peer.model_copy(update={"parent_asin": "FOUNTAIN-2"})
    another_selected_set = matcher.match(
        first_signature, [peer, another_peer], group_context="catalog-source-a"
    )

    assert first.peer_group_id == repeated.peer_group_id
    assert first.peer_group_id == same_input_new_temporary_id.peer_group_id
    assert first.peer_group_id != another_config.peer_group_id
    assert first.peer_group_id != another_data_version.peer_group_id
    assert first.peer_group_id != another_selected_set.peer_group_id
    assert first.peer_group_id not in {
        peer.main_category,
        "|".join(peer.categories),
        "pet water fountain",
    }


def test_fewer_than_ten_qualified_peers_are_not_filled_with_low_quality_products() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    qualified = [
        _product(
            f"FOUNTAIN-{index}",
            f"Stainless Steel Cat Water Fountain {index}",
            description="Circulating drinking water fountain for cats.",
            features=["circulating drinking water"],
            categories=["Pet Supplies", "Feeding & Watering"],
        )
        for index in range(2)
    ]
    low_quality = [
        _product(
            f"FEEDER-{index}",
            f"Automatic Cat Feeder {index}",
            description="Timed feeding food dispenser for cats.",
            features=["scheduled dry food portions"],
            categories=["Pet Supplies", "Feeding & Watering"],
        )
        for index in range(12)
    ]

    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(
        signature, [*qualified, *low_quality]
    )

    assert [item.parent_asin for item in result.peers] == ["FOUNTAIN-0", "FOUNTAIN-1"]
    assert result.insufficient_peer_products is True
    assert any(gap.code == "insufficient_peer_products" for gap in result.data_gaps)


def test_threshold_and_model_versions_are_recorded_in_match_metadata() -> None:
    signature = CandidateProductSignature.from_product(_candidate())
    peer = _product(
        "FOUNTAIN",
        "Stainless Steel Cat Water Fountain",
        description="Circulating drinking water fountain for cats.",
        features=["circulating drinking water"],
        categories=["Pet Supplies", "Fountains"],
    )

    result = PeerMatcher(TerminalProductEmbedding(), _config()).match(
        signature, [peer], group_context="catalog-source-a"
    )

    assert result.match_metadata == {
        "matcher_version": "peer-matcher-v2",
        "embedding_model": "terminal-product-embedding-v1",
        "minimum_rule_score": 0.2,
        "minimum_semantic_score": 0.5,
        "minimum_peer_count": 10,
        "acceptance_rule": "rule_score>=0.2 and semantic_score>=0.5",
    }
