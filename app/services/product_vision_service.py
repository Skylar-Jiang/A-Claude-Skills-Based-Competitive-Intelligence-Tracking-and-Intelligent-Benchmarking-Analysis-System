from __future__ import annotations

import base64
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda, RunnableSequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.model_factory import create_vision_model, parse_json_object
from app.db.models.core import ProductFile
from app.schemas.product import ProductProfile
from app.schemas.vision import ProductVisionAnalysis

VISION_PROMPT = """
Analyze this user-uploaded image of an unlisted pet product. Return one JSON object containing summary,
visible_product_type, visible_materials, visible_structure, visible_features, usage_clues, and uncertainties.
Describe only visible attributes. Do not invent price, rating, sales, reviews, performance, material, or compatibility.
If an attribute cannot be verified visually, put it in uncertainties.
"""


class ProductVisionService:
    def __init__(self, *, session: Session, model: BaseChatModel | None = None) -> None:
        self.session = session
        self.model = model or create_vision_model()
        self.chain: RunnableSequence = (
            RunnableLambda(self._build_messages)
            | self.model
            | RunnableLambda(self._parse_response)
        )

    def analyze_if_available(self, product: ProductProfile) -> ProductVisionAnalysis | None:
        files = self.session.scalars(
            select(ProductFile)
            .where(ProductFile.product_id == product.product_id, ProductFile.file_type == "image")
            .order_by(ProductFile.file_id)
        ).all()
        for record in files:
            path = Path(record.file_path)
            metadata = record.metadata_json or {}
            content_type = str(metadata.get("content_type") or "")
            if not _verified_image(path, content_type):
                continue
            result = self.chain.invoke({"path": path, "content_type": content_type})
            return result.model_copy(
                update={
                    "image_file_id": record.file_id,
                    "image_hash": str(metadata.get("file_hash") or ""),
                }
            )
        return None

    @staticmethod
    def _build_messages(value: dict[str, object]) -> list[HumanMessage]:
        path = Path(str(value["path"]))
        content_type = str(value["content_type"])
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return [
            HumanMessage(
                content=[
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                    },
                ]
            )
        ]

    def _parse_response(self, message: AIMessage) -> ProductVisionAnalysis:
        payload = parse_json_object(str(message.content))
        payload.update(
            model_provider="qwen",
            model_name=str(getattr(self.model, "model_name", "configured-qwen-vision")),
            verified_image=True,
        )
        return ProductVisionAnalysis.model_validate(payload)


def _verified_image(path: Path, content_type: str) -> bool:
    if not path.is_file() or content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return False
    header = path.read_bytes()[:12]
    if content_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
