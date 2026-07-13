import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.demo import DemoDomainAdapter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.rag.in_memory import InMemoryKnowledgeStore  # noqa: E402


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        product = DemoDomainAdapter().seed(
            session,
            SqlAlchemyProductRepository(session),
            InMemoryKnowledgeStore(),
        )
    print(f"DEMO fixture seeded: product_id={product.product_id}")


if __name__ == "__main__":
    main()
