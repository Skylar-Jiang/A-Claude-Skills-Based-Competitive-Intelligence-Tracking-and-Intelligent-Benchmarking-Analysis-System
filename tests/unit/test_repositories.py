from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.enums import AgentStatus, DataMode, DataOrigin, RunStatus
from app.db.base import Base
from app.db.repositories.protocols import AnalysisRepository, ProductRepository
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_base_defines_only_the_minimum_scaffold_tables() -> None:
    session = make_session()
    table_names = set(inspect(session.get_bind()).get_table_names())

    assert table_names == {
        "agent_outputs",
        "analysis_runs",
        "competitor_offers",
        "conversations",
        "evidence_references",
        "knowledge_sources",
        "messages",
        "product_files",
        "products",
        "reports",
        "reviews",
    }


def test_product_repository_round_trip_keeps_generic_json_fields() -> None:
    session = make_session()
    repository = SqlAlchemyProductRepository(session)
    assert isinstance(repository, ProductRepository)

    created = repository.create(
        ProductCreate(
            name="DEMO Portable Organizer",
            category="demo-generic",
            attributes={"color": "blue"},
            data_mode=DataMode.DEMO,
        ),
        data_origin=DataOrigin.DEMO,
    )
    loaded = repository.get(created.product_id)

    assert loaded == created
    assert loaded.attributes == {"color": "blue"}
    assert loaded.data_origin is DataOrigin.DEMO


def test_analysis_repository_persists_state_and_agent_outputs() -> None:
    session = make_session()
    product = SqlAlchemyProductRepository(session).create(
        ProductCreate(name="DEMO Product", category="demo", data_mode=DataMode.DEMO),
        data_origin=DataOrigin.DEMO,
    )
    repository = SqlAlchemyAnalysisRepository(session)
    assert isinstance(repository, AnalysisRepository)

    run = repository.create_run(
        AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO)
    )
    repository.save_agent_output(
        run.run_id,
        agent_name="ProductMarketAgent",
        status=AgentStatus.SUCCEEDED,
        input_data={"product_id": product.product_id},
        output_data={"data_origin": "demo", "implementation_status": "scaffold"},
    )
    updated = repository.update_run(
        run.run_id,
        status=RunStatus.SUCCEEDED,
        current_node="persist_and_export",
        retry_count=0,
        state={"is_demo": True},
    )

    assert updated.status is RunStatus.SUCCEEDED
    assert updated.state == {"is_demo": True}
    outputs = repository.list_agent_outputs(run.run_id)
    assert len(outputs) == 1
    assert outputs[0].agent_name == "ProductMarketAgent"
    assert outputs[0].output["implementation_status"] == "scaffold"
