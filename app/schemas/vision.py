from pydantic import BaseModel, Field


class ProductVisionAnalysis(BaseModel):
    summary: str
    visible_product_type: str = ""
    visible_materials: list[str] = Field(default_factory=list)
    visible_structure: list[str] = Field(default_factory=list)
    visible_features: list[str] = Field(default_factory=list)
    usage_clues: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    image_file_id: str = ""
    image_hash: str = ""
    model_provider: str = "qwen"
    model_name: str = ""
    verified_image: bool = True
