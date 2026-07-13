from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.enums import DataMode, DataOrigin, FileType
from app.db.models.core import ProductFile
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.schemas.product import ProductCreate, ProductFileRead, ProductProfile


class ProductService:
    def __init__(self, session: Session, upload_dir: Path) -> None:
        self.session = session
        self.products = SqlAlchemyProductRepository(session)
        self.upload_dir = upload_dir

    def create(self, payload: ProductCreate) -> ProductProfile:
        origins = {
            DataMode.DEMO: DataOrigin.DEMO,
            DataMode.MOCK: DataOrigin.MOCK,
            DataMode.REAL: DataOrigin.USER,
        }
        return self.products.create(payload, data_origin=origins[payload.data_mode])

    def get(self, product_id: str) -> ProductProfile:
        return self.products.get(product_id)

    def add_file(
        self,
        product_id: str,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
        file_type: FileType,
    ) -> ProductFileRead:
        self.products.get(product_id)
        file_id = str(uuid4())
        safe_name = Path(file_name).name
        directory = self.upload_dir / product_id
        directory.mkdir(parents=True, exist_ok=True)
        path = (directory / f"{file_id}-{safe_name}").resolve()
        path.write_bytes(content)
        digest = sha256(content).hexdigest()
        record = ProductFile(
            file_id=file_id,
            product_id=product_id,
            file_type=file_type.value,
            file_path=str(path),
            metadata_json={
                "file_name": safe_name,
                "content_type": content_type,
                "file_hash": digest,
                "file_size": len(content),
            },
        )
        self.session.add(record)
        self.session.commit()
        return ProductFileRead(
            file_id=file_id,
            product_id=product_id,
            file_type=file_type,
            file_name=safe_name,
            content_type=content_type,
            file_hash=digest,
            file_size=len(content),
            metadata={},
            file_path=str(path),
        )
