from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import EvidenceAuditAgentInput
from app.core.enums import AuditStatus, DataOrigin, ImplementationStatus
from app.schemas.analysis import AuditResult


class EvidenceAuditAgent(BaseScaffoldAgent[EvidenceAuditAgentInput, AuditResult]):
    """Checks scaffold markers only; semantic evidence auditing is deliberately absent."""

    input_model = EvidenceAuditAgentInput
    output_model = AuditResult

    def _run_stub(self, context: EvidenceAuditAgentInput) -> AuditResult:
        issues: list[str] = []
        plan = context.operation_plan
        if plan.data_origin is not DataOrigin.DEMO:
            issues.append("missing_demo_origin")
        if plan.implementation_status is not ImplementationStatus.SCAFFOLD:
            issues.append("missing_scaffold_status")
        # TODO(team-three): add claim-level evidence auditing and bounded correction details.
        return AuditResult(
            status=AuditStatus.REJECTED if issues else AuditStatus.PASS,
            data_origin=DataOrigin.DEMO,
            issues=issues,
            manual_review_required=bool(issues),
        )
