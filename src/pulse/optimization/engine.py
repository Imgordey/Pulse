from dataclasses import dataclass

from pulse.cleanup.scanner import CleanupCandidate
from pulse.health.models import HealthReport


@dataclass(frozen=True)
class Recommendation:
    id: str
    title: str
    reason: str
    action: str
    automatic: bool = False


def recommend_maintenance(
    health: HealthReport,
    candidates: tuple[CleanupCandidate, ...] = (),
) -> tuple[Recommendation, ...]:
    result = [
        Recommendation(issue.id, issue.title, issue.description, issue.recommendation)
        for issue in health.issues
    ]
    for candidate in candidates:
        if candidate.complete and candidate.size >= 1024**3:
            result.append(
                Recommendation(
                    f"review_cache:{candidate.path}",
                    f"Review {candidate.description}",
                    "A large cache was observed; its contents may still be useful.",
                    "Review the cleanup plan. Cache rebuilds may take time or require downloads.",
                )
            )
    return tuple(result)
