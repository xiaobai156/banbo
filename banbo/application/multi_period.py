from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from banbo.domain import FailureCode, FailureResult

from .models import SiteRun
from .single_period import SinglePeriodRunner


@dataclass(frozen=True)
class MultiPeriodSiteResult:
    site_id: str
    periods: tuple[SiteRun, ...]

    @property
    def passed(self) -> bool:
        return any(run.succeeded for run in self.periods)

    @property
    def failure(self) -> FailureResult | None:
        if self.passed:
            return None
        failures = tuple(
            run.outcome
            for run in self.periods
            if isinstance(run.outcome, FailureResult)
        )
        messages = "; ".join(
            f"{failure.code.value}: {failure.message}" for failure in failures
        )
        codes = {failure.code for failure in failures}
        return FailureResult(
            site_id=self.site_id,
            target_issue=self.periods[0].outcome.target_issue,
            code=(
                next(iter(codes))
                if len(codes) == 1
                else FailureCode.MULTI_PERIOD_FAILED
            ),
            message=messages,
        )


def run_periods(
    runner: SinglePeriodRunner,
    periods: Sequence[int],
    *,
    site_ids: Sequence[str] | None = None,
) -> tuple[MultiPeriodSiteResult, ...]:
    by_site: dict[str, list[SiteRun]] = {}
    for period in periods:
        for run in runner.run_many(period, site_ids=site_ids):
            by_site.setdefault(run.site.site_id, []).append(run)
    return tuple(
        MultiPeriodSiteResult(site_id, tuple(runs))
        for site_id, runs in by_site.items()
    )
