import json
from pathlib import Path

from app.core.enums import KnowledgeType
from app.rag.importers import iter_filtered_documents, validate_source
from app.rag.utils import clean_text, content_hash, stable_id


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_validate_source_maps_real_filtered_files(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "meta_pet_supplies_prefiltered.jsonl",
        [
            {
                "title": "Harness",
                "features": ["Durable"],
                "description": ["For dogs"],
                "average_rating": 4.5,
                "parent_asin": "P1",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "pet_supplies_reviews_prefiltered.jsonl",
        [{"rating": 5.0, "title": "Great", "text": "Works well", "user_id": "U1", "parent_asin": "P1"}],
    )

    summary = validate_source(tmp_path)

    assert [item.mapped_knowledge_type for item in summary.files] == ["product_knowledge", "review_insight"]
    assert summary.files[0].records == 1


def test_clean_text_removes_html_but_keeps_units_and_negation() -> None:
    assert clean_text("Not <b>bad</b><br />Size 3.5\" x 2 cm") == 'Not bad\nSize 3.5" x 2 cm'


def test_iter_filtered_documents_deduplicates_and_preserves_review_boundaries(tmp_path: Path) -> None:
    review = {
        "rating": 1.0,
        "title": "Rough edges",
        "text": "Dangerous rough metal edges.",
        "asin": "A1",
        "parent_asin": "P1",
        "user_id": "U1",
        "timestamp": 1,
        "verified_purchase": True,
    }
    _write_jsonl(tmp_path / "pet_supplies_reviews_prefiltered.jsonl", [review, review])

    documents, summary = iter_filtered_documents(
        tmp_path,
        knowledge_types={KnowledgeType.REVIEW_INSIGHT},
    )
    items = list(documents)

    assert len(items) == 1
    assert summary.skipped_duplicate == 1
    assert items[0].knowledge_type is KnowledgeType.REVIEW_INSIGHT
    assert items[0].metadata["review_id"]
    assert items[0].metadata["content_hash"] == content_hash(items[0].content)


def test_stable_id_is_repeatable() -> None:
    assert stable_id("product", "P1") == stable_id("product", "P1")
