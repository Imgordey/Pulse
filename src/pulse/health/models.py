from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class OverallStatus(StrEnum):
    no_alerts = "No alerts in this sample"
    attention = "Needs attention"
    critical = "Critical"


@dataclass(frozen=True)
class Issue:
    id: str
    category: str
    severity: Severity
    title: str
    description: str
    evidence: dict[str, float | int | str]
    recommendation: str
    actionability: str = "manual_review"

    @property
    def resource(self) -> str:
        return self.category

    @property
    def message(self) -> str:
        return self.description

    @property
    def suggestion(self) -> str:
        return self.recommendation


@dataclass(frozen=True)
class HealthReport:
    issues: tuple[Issue, ...]
    status: OverallStatus
    limitations: tuple[str, ...]
