from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import AgentStatus, AuditStatus, DataOrigin, RunStageStatus, RunStatus
from app.core.exceptions import ResourceNotFoundError
from app.db.models.core import (
    AgentOutput,
    AnalysisEvent,
    AnalysisRun,
    AnalysisRunStage,
    EvidenceReferenceRecord,
    Product,
    Report,
)
from app.schemas.analysis import (
    AgentOutputRead,
    AnalysisEventRead,
    AnalysisRunCreate,
    AnalysisRunRead,
    RunStageRead,
)
from app.schemas.common import AgentExecution
from app.schemas.product import ProductCreate, ProductProfile
from app.schemas.report import FinalReport
from app.workflows.state import TradePilotState


class SqlAlchemyProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: ProductCreate, *, data_origin: DataOrigin) -> ProductProfile:
        serialized = payload.model_dump(mode="json")
        record = Product(
            name=payload.name,
            category=payload.category,
            data_mode=payload.data_mode.value,
            data_origin=data_origin.value,
            attributes_json=serialized["attributes"],
            metadata_json={},
            payload_json=serialized,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_profile(record)

    def get(self, product_id: str) -> ProductProfile:
        record = self.session.get(Product, product_id)
        if record is None:
            raise ResourceNotFoundError("product", product_id)
        return self._to_profile(record)

    def list(self) -> list[ProductProfile]:
        records = self.session.scalars(select(Product).order_by(Product.created_at)).all()
        return [self._to_profile(record) for record in records]

    @staticmethod
    def _to_profile(record: Product) -> ProductProfile:
        return ProductProfile(
            product_id=record.product_id,
            data_origin=record.data_origin,
            **record.payload_json,
        )


class SqlAlchemyAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, payload: AnalysisRunCreate) -> AnalysisRunRead:
        record = AnalysisRun(
            product_id=payload.product_id,
            data_mode=payload.data_mode.value,
            status=RunStatus.PENDING.value,
            current_node="created",
            request_json=payload.model_dump(mode="json"),
            state_json={},
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def get_run(self, run_id: str) -> AnalysisRunRead:
        record = self.session.get(AnalysisRun, run_id)
        if record is None:
            raise ResourceNotFoundError("analysis_run", run_id)
        return self._to_run(record)

    def list_run_ids(self, statuses: set[RunStatus]) -> list[str]:
        if not statuses:
            return []
        statement = (
            select(AnalysisRun.run_id)
            .where(AnalysisRun.status.in_([status.value for status in statuses]))
            .order_by(AnalysisRun.created_at)
        )
        return list(self.session.scalars(statement).all())

    def get_run_request(self, run_id: str) -> dict[str, Any]:
        record = self.session.get(AnalysisRun, run_id)
        if record is None:
            raise ResourceNotFoundError("analysis_run", run_id)
        return record.request_json

    def initialize_stages(self, run_id: str, stage_keys: list[str]) -> list[RunStageRead]:
        self.get_run(run_id)
        existing = {
            item.stage_key
            for item in self.session.scalars(
                select(AnalysisRunStage).where(AnalysisRunStage.run_id == run_id)
            ).all()
        }
        for sequence, stage_key in enumerate(stage_keys):
            if stage_key not in existing:
                self.session.add(
                    AnalysisRunStage(
                        run_id=run_id,
                        stage_key=stage_key,
                        sequence=sequence,
                        status=RunStageStatus.PENDING.value,
                    )
                )
        self.session.commit()
        return self.list_stages(run_id)

    def transition_stage(
        self,
        run_id: str,
        stage_key: str,
        status: RunStageStatus,
        *,
        payload: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> RunStageRead:
        record = self.session.scalar(
            select(AnalysisRunStage).where(
                AnalysisRunStage.run_id == run_id,
                AnalysisRunStage.stage_key == stage_key,
            )
        )
        if record is None:
            raise ResourceNotFoundError("analysis_run_stage", f"{run_id}:{stage_key}")
        timestamp = datetime.now(UTC)
        if status is RunStageStatus.RUNNING and record.started_at is None:
            record.started_at = timestamp
        if status in {RunStageStatus.SUCCEEDED, RunStageStatus.FAILED, RunStageStatus.SKIPPED}:
            if record.started_at is None:
                record.started_at = timestamp
            record.completed_at = timestamp
            started_at = record.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            record.duration_ms = round((timestamp - started_at).total_seconds() * 1000)
        record.status = status.value
        if payload is not None:
            record.payload_json = payload
            explicit_duration = payload.get("duration_ms")
            if isinstance(explicit_duration, int):
                record.duration_ms = explicit_duration
        record.error_json = error
        self.session.flush()
        result = self._to_stage(record)
        self.session.commit()
        return result

    def list_stages(self, run_id: str) -> list[RunStageRead]:
        self.get_run(run_id)
        statement = (
            select(AnalysisRunStage)
            .where(AnalysisRunStage.run_id == run_id)
            .order_by(AnalysisRunStage.sequence)
        )
        return [self._to_stage(record) for record in self.session.scalars(statement).all()]

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        stage_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AnalysisEventRead:
        self.get_run(run_id)
        record = AnalysisEvent(
            run_id=run_id,
            event_type=event_type,
            stage_key=stage_key,
            payload_json=payload or {},
        )
        self.session.add(record)
        self.session.flush()
        result = self._to_event(record)
        self.session.commit()
        return result

    def list_events(self, run_id: str, *, after_event_id: int = 0) -> list[AnalysisEventRead]:
        self.get_run(run_id)
        statement = (
            select(AnalysisEvent)
            .where(AnalysisEvent.run_id == run_id, AnalysisEvent.event_id > after_event_id)
            .order_by(AnalysisEvent.event_id)
        )
        return [self._to_event(record) for record in self.session.scalars(statement).all()]

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        current_node: str,
        retry_count: int,
        state: dict[str, Any],
        report_id: str | None = None,
    ) -> AnalysisRunRead:
        record = self.session.get(AnalysisRun, run_id)
        if record is None:
            raise ResourceNotFoundError("analysis_run", run_id)
        record.status = status.value
        record.current_node = current_node
        record.retry_count = retry_count
        record.state_json = state
        if report_id is not None:
            record.report_id = report_id
        record.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def set_current_node(self, run_id: str, current_node: str) -> None:
        record = self.session.get(AnalysisRun, run_id)
        if record is None:
            raise ResourceNotFoundError("analysis_run", run_id)
        record.current_node = current_node
        record.updated_at = datetime.now(UTC)
        self.session.commit()

    def save_agent_output(
        self,
        run_id: str,
        *,
        agent_name: str,
        status: AgentStatus,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> AgentOutputRead:
        record = AgentOutput(
            run_id=run_id,
            agent_name=agent_name,
            status=status.value,
            input_json=input_data,
            output_json=output_data,
            error_json=error,
        )
        self.session.add(record)
        self.session.commit()
        return self._to_output(record)

    def list_agent_outputs(self, run_id: str) -> list[AgentOutputRead]:
        statement = select(AgentOutput).where(AgentOutput.run_id == run_id).order_by(AgentOutput.agent_name)
        return [self._to_output(record) for record in self.session.scalars(statement).all()]

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        statement = (
            select(EvidenceReferenceRecord)
            .where(EvidenceReferenceRecord.run_id == run_id)
            .order_by(EvidenceReferenceRecord.evidence_id)
        )
        return [record.payload_json for record in self.session.scalars(statement).all()]

    def get_evidence(self, run_id: str, evidence_id: str) -> dict[str, Any]:
        self.get_run(run_id)
        statement = select(EvidenceReferenceRecord).where(
            EvidenceReferenceRecord.run_id == run_id,
            EvidenceReferenceRecord.evidence_id == evidence_id,
        )
        record = self.session.scalar(statement)
        if record is None:
            raise ResourceNotFoundError("evidence", evidence_id)
        return record.payload_json

    def persist_result(
        self,
        state: TradePilotState,
        report: FinalReport,
    ) -> AnalysisRunRead:
        run = self.session.get(AnalysisRun, state.run_id)
        if run is None:
            raise ResourceNotFoundError("analysis_run", state.run_id)
        self.session.execute(delete(AgentOutput).where(AgentOutput.run_id == state.run_id))
        self.session.execute(
            delete(EvidenceReferenceRecord).where(EvidenceReferenceRecord.run_id == state.run_id)
        )
        outputs = {
            "ProductMarketAgent": ("product_market_agent", state.product_market_analysis),
            "UserInsightAgent": ("user_insight_agent", state.user_insight),
            "OperationsDecisionAgent": ("operations_decision_agent", state.operation_plan),
            "EvidenceAuditAgent": ("evidence_audit_agent", state.audit_result),
        }
        for name, (node_name, output) in outputs.items():
            if output is None:
                raise ValueError(f"missing Agent output: {name}")
            status = getattr(output, "status", AgentStatus.SUCCEEDED)
            agent_status = status if isinstance(status, AgentStatus) else AgentStatus.SUCCEEDED
            execution = state.node_status.get(node_name)
            self.session.add(
                AgentOutput(
                    run_id=state.run_id,
                    agent_name=name,
                    status=agent_status.value,
                    input_json={
                        "product_id": state.product_profile.product_id,
                        "peer_group_id": state.peer_group_id,
                        "selected_parent_asins": state.selected_parent_asins,
                    },
                    output_json=output.model_dump(mode="json"),
                    started_at=execution.started_at if execution else None,
                    completed_at=execution.completed_at if execution else None,
                    duration_ms=execution.duration_ms if execution else None,
                )
            )
        for evidence in state.rag_evidence:
            self.session.add(
                EvidenceReferenceRecord(
                    evidence_id=evidence.evidence_id,
                    run_id=state.run_id,
                    knowledge_type=evidence.knowledge_type.value,
                    data_origin=evidence.data_origin.value,
                    is_demo=evidence.is_demo,
                    payload_json=evidence.model_dump(mode="json"),
                )
            )
        self.session.add(
            Report(
                report_id=report.report_id,
                run_id=state.run_id,
                version=report.version,
                parent_report_id=report.parent_report_id,
                changed_section_ids_json=report.changed_section_ids,
                change_json={},
                format="json+markdown",
                file_path=report.json_path,
                is_demo=report.is_demo,
                metadata_json=report.model_dump(mode="json"),
            )
        )
        persisted_state = state.model_copy(
            update={
                "current_node": "persist_and_export",
                "report_id": report.report_id,
                "report_version": report.version,
                "report_paths": {"json": report.json_path, "markdown": report.markdown_path},
                "node_status": {
                    **state.node_status,
                    "persist_and_export": AgentExecution(
                        agent_name="persist_and_export",
                        status=AgentStatus.SUCCEEDED,
                    ),
                },
            }
        )
        final_status = (
            RunStatus.MANUAL_REVIEW
            if state.audit_result is not None and state.audit_result.status is AuditStatus.REJECTED
            else RunStatus.SUCCEEDED
        )
        run.status = final_status.value
        run.current_node = "persist_and_export"
        run.retry_count = state.retry_count
        run.report_id = report.report_id
        run.state_json = persisted_state.model_dump(mode="json")
        self.session.commit()
        self.session.refresh(run)
        return self._to_run(run)

    def get_report(self, report_id: str) -> FinalReport:
        record = self.session.get(Report, report_id)
        if record is None:
            raise ResourceNotFoundError("report", report_id)
        return FinalReport.model_validate(record.metadata_json)

    def list_report_versions(self, run_id: str) -> list[FinalReport]:
        self.get_run(run_id)
        records = self.session.scalars(
            select(Report).where(Report.run_id == run_id).order_by(Report.version)
        ).all()
        return [FinalReport.model_validate(record.metadata_json) for record in records]

    def get_latest_report(self, run_id: str) -> FinalReport:
        self.get_run(run_id)
        record = self.session.scalar(
            select(Report).where(Report.run_id == run_id).order_by(Report.version.desc()).limit(1)
        )
        if record is None:
            raise ResourceNotFoundError("report_for_run", run_id)
        return FinalReport.model_validate(record.metadata_json)

    def save_report_version(
        self,
        report: FinalReport,
        *,
        change: dict[str, Any],
    ) -> FinalReport:
        run = self.session.get(AnalysisRun, report.run_id)
        if run is None:
            raise ResourceNotFoundError("analysis_run", report.run_id)
        self.session.add(
            Report(
                report_id=report.report_id,
                run_id=report.run_id,
                version=report.version,
                parent_report_id=report.parent_report_id,
                changed_section_ids_json=report.changed_section_ids,
                change_json=change,
                format="json+markdown",
                file_path=report.json_path,
                is_demo=report.is_demo,
                metadata_json=report.model_dump(mode="json"),
            )
        )
        run.report_id = report.report_id
        run.state_json = {
            **run.state_json,
            "report_id": report.report_id,
            "report_version": report.version,
            "report_paths": {"json": report.json_path, "markdown": report.markdown_path},
        }
        run.updated_at = datetime.now(UTC)
        self.session.commit()
        return report

    @staticmethod
    def _to_run(record: AnalysisRun) -> AnalysisRunRead:
        return AnalysisRunRead(
            run_id=record.run_id,
            product_id=record.product_id,
            data_mode=record.data_mode,
            status=record.status,
            current_node=record.current_node,
            retry_count=record.retry_count,
            report_id=record.report_id,
            state=record.state_json,
        )

    @staticmethod
    def _to_output(record: AgentOutput) -> AgentOutputRead:
        return AgentOutputRead(
            agent_name=record.agent_name,
            status=record.status,
            input=record.input_json,
            output=record.output_json,
            error=record.error_json,
            started_at=record.started_at,
            completed_at=record.completed_at,
            duration_ms=record.duration_ms,
        )

    @staticmethod
    def _to_stage(record: AnalysisRunStage) -> RunStageRead:
        return RunStageRead(
            stage_key=record.stage_key,
            sequence=record.sequence,
            status=record.status,
            started_at=record.started_at,
            completed_at=record.completed_at,
            duration_ms=record.duration_ms,
            payload=record.payload_json,
            error=record.error_json,
        )

    @staticmethod
    def _to_event(record: AnalysisEvent) -> AnalysisEventRead:
        return AnalysisEventRead(
            event_id=record.event_id,
            run_id=record.run_id,
            event_type=record.event_type,
            stage_key=record.stage_key,
            payload=record.payload_json,
            created_at=record.created_at,
        )
