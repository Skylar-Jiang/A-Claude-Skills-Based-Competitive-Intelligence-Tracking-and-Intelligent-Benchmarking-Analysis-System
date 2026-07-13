from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Product(Base):
    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120))
    data_mode: Mapped[str] = mapped_column(String(16))
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProductFile(Base):
    __tablename__ = "product_files"

    file_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    file_type: Mapped[str] = mapped_column(String(32))
    file_path: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CompetitorOffer(Base):
    __tablename__ = "competitor_offers"

    offer_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Review(Base):
    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.product_id"), index=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    data_mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), index=True)
    current_node: Mapped[str] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AgentOutput(Base):
    __tablename__ = "agent_outputs"

    output_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.run_id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EvidenceReferenceRecord(Base):
    __tablename__ = "evidence_references"

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    evidence_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.run_id"), index=True)
    knowledge_type: Mapped[str] = mapped_column(String(32))
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Report(Base):
    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.run_id"), index=True)
    format: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.product_id"), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.conversation_id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
