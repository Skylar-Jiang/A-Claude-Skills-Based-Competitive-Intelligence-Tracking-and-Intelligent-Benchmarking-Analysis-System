from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import DataMode, DataOrigin, FileType
from app.schemas.common import DataGap


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=120)
    description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    materials: list[str] = Field(default_factory=list)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    use_scenarios: list[str] = Field(default_factory=list)
    target_market: str = ""
    target_audience: list[str] = Field(default_factory=list)
    target_price: Decimal | None = Field(default=None, ge=0)
    target_currency: str | None = None
    known_risks: list[str] = Field(default_factory=list)
    data_mode: DataMode = DataMode.DEMO


class ProductProfile(ProductCreate):
    product_id: str
    data_origin: DataOrigin
    file_references: list[str] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)

    @property
    def is_demo(self) -> bool:
        return self.data_origin is DataOrigin.DEMO


class ProductFileCreate(BaseModel):
    file_type: FileType
    file_name: str
    content_type: str
    file_hash: str
    file_size: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductFileRead(ProductFileCreate):
    file_id: str
    product_id: str
    file_path: str
