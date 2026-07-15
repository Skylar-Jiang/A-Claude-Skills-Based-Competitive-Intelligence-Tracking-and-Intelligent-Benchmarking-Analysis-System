import json
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda, RunnableSequence
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.enums import DataMode, DataOrigin
from app.db.base import Base
from app.db.models.core import ProductFile
from app.schemas.product import ProductCreate, ProductProfile
from app.services.product_vision_service import ProductVisionService


def _product() -> ProductProfile:
    return ProductProfile(
        product_id="new-product",
        data_origin=DataOrigin.USER,
        **ProductCreate(name="New Fountain", category="Fountains", data_mode=DataMode.REAL).model_dump(),
    )


def test_reliable_uploaded_image_uses_qwen_compatible_lcel_model(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    image_path = tmp_path / "product.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"test-image-payload")
    calls = 0

    def invoke(_value):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return AIMessage(
            content=json.dumps(
                {
                    "summary": "图片显示带透明水位窗的完整饮水机。",
                    "visible_product_type": "cat water fountain",
                    "visible_materials": ["plastic"],
                    "visible_structure": ["reservoir", "water window"],
                    "visible_features": ["transparent water level"],
                    "usage_clues": ["indoor pet hydration"],
                    "uncertainties": ["无法仅凭图片确认噪音"],
                },
                ensure_ascii=False,
            )
        )

    with Session(engine) as session:
        session.add(
            ProductFile(
                file_id="image-1",
                product_id="new-product",
                file_type="image",
                file_path=str(image_path),
                metadata_json={"content_type": "image/png", "file_hash": "test-hash"},
            )
        )
        session.commit()
        service = ProductVisionService(session=session, model=RunnableLambda(invoke))  # type: ignore[arg-type]

        result = service.analyze_if_available(_product())

    assert isinstance(service.chain, RunnableSequence)
    assert calls == 1
    assert result is not None
    assert result.model_provider == "qwen"
    assert result.verified_image is True
    assert "透明水位窗" in result.summary


def test_missing_or_unverified_image_does_not_call_model(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    invalid = tmp_path / "not-an-image.png"
    invalid.write_text("not an image", encoding="utf-8")

    def unexpected(_value):  # type: ignore[no-untyped-def]
        raise AssertionError("unverified image must not be sent to a multimodal model")

    with Session(engine) as session:
        session.add(
            ProductFile(
                file_id="image-1",
                product_id="new-product",
                file_type="image",
                file_path=str(invalid),
                metadata_json={"content_type": "image/png"},
            )
        )
        session.commit()
        service = ProductVisionService(session=session, model=RunnableLambda(unexpected))  # type: ignore[arg-type]

        assert service.analyze_if_available(_product()) is None
