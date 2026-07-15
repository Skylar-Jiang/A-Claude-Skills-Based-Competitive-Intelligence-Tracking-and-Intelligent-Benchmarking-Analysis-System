from collections.abc import Callable

from sqlalchemy.orm import Session

from app.statistics.contracts import StatisticsProvider
from app.statistics.providers.pet_supplies import PetSuppliesStatisticsProvider

StatisticsProviderFactory = Callable[[Session], StatisticsProvider]


def create_statistics_provider(session: Session) -> StatisticsProvider:
    return PetSuppliesStatisticsProvider(session)
