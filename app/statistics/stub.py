from app.core.enums import AgentStatus
from app.schemas.common import DataGap
from app.schemas.product import ProductProfile
from app.statistics.contracts import StatisticsResult


class ScaffoldStatisticsProvider:
    """Injection default; real SQL statistics are intentionally deferred."""

    def get_statistics(
        self,
        *,
        product: ProductProfile,
        peer_group_id: str | None = None,
    ) -> StatisticsResult:
        del peer_group_id
        return StatisticsResult(
            product_id=product.product_id,
            status=AgentStatus.INSUFFICIENT_EVIDENCE,
            data_origin=product.data_origin,
            data_gaps=[
                DataGap(
                    code="statistics_not_implemented",
                    field="statistics",
                    reason="The scaffold statistics provider does not calculate business metrics.",
                    required_for="evidence-grounded analysis",
                )
            ],
        )
