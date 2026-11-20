from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from operator import itemgetter
from pathlib import Path

from scorenow_api_observer.auto_watch.config import (
    AUTO_WATCH_CONFIG_PATH,
    load_auto_watch_config,
)
from scorenow_api_observer.auto_watch.exceptions import AUTO_WATCH_EXCEPTION_DIRECTORY
from scorenow_api_observer.auto_watch.status import (
    API_ENDPOINTS,
    ApiRequestRecord,
    Sport,
    StatusReadFailure,
    StoredAutoWatchException,
    current_hour_window,
    kst_day_utc_window,
    load_exceptions_for_window,
    load_request_records,
    sport_request_counts,
)
from scorenow_api_observer.bets_api_request_log import (
    BETS_API_REQUEST_LOG_DIRECTORY,
    BetsApiEndpoint,
)
from scorenow_api_observer.event_view.request_log import (
    EVENT_VIEW_REQUEST_LOG_DIRECTORY,
)


@dataclass(frozen=True)
class HourlyPeak:
    count: int
    limit: int
    window_start: datetime

    @property
    def percent(self) -> float:
        return 100 * self.count / self.limit


@dataclass(frozen=True)
class DailyOperations:
    target_date: date
    endpoint_counts: dict[BetsApiEndpoint, int]
    http_errors: Counter[int]
    connection_failures: int
    unfinished_requests: int
    hourly_peaks: dict[Sport, HourlyPeak]
    exceptions: list[StoredAutoWatchException]
    failures: list[StatusReadFailure]

    @property
    def exception_counts(self) -> Counter[int | None]:
        return Counter(item.record.stop_time_status for item in self.exceptions)


def collect_daily_operations(
    target_date: date,
    *,
    config_path: Path = AUTO_WATCH_CONFIG_PATH,
    request_base_directory: Path = BETS_API_REQUEST_LOG_DIRECTORY,
    legacy_base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
    exception_base_directory: Path = AUTO_WATCH_EXCEPTION_DIRECTORY,
) -> DailyOperations:
    failures: list[StatusReadFailure] = []
    start, end = kst_day_utc_window(target_date)
    records = [
        record
        for record in load_request_records(
            windows=((start, end),),
            request_base_directory=request_base_directory,
            legacy_base_directory=legacy_base_directory,
            failures=failures,
        )
        if start <= record.requested_at < end
    ]
    endpoint_counts = Counter(record.endpoint for record in records)
    per_hour: dict[datetime, list[ApiRequestRecord]] = defaultdict(list)
    for record in records:
        window_start, _ = current_hour_window(record.requested_at)
        per_hour[window_start].append(record)
    hourly_counts = {
        hour: sport_request_counts(per_hour[hour]) for hour in sorted(per_hour)
    }
    if not hourly_counts:
        hourly_counts[start] = sport_request_counts([])

    peaks: dict[Sport, HourlyPeak] = {}
    try:
        limits = load_auto_watch_config(config_path).request_limits
    except (OSError, ValueError) as error:
        failures.append(StatusReadFailure("요청 한도 설정", config_path, str(error)))
    else:
        sport_limits: dict[Sport, int] = {
            "football": limits.soccer_per_hour,
            "baseball": limits.baseball_per_hour,
        }
        for sport, limit in sport_limits.items():
            hour, count = max(
                ((hour, counts[sport]) for hour, counts in hourly_counts.items()),
                key=itemgetter(1),
            )
            peaks[sport] = HourlyPeak(count, limit, hour)

    exceptions = load_exceptions_for_window(
        start=start, end=end, base_directory=exception_base_directory, failures=failures
    )
    return DailyOperations(
        target_date=target_date,
        endpoint_counts={
            endpoint: endpoint_counts[endpoint] for endpoint in API_ENDPOINTS
        },
        http_errors=Counter(
            code
            for record in records
            if (code := record.http_status_code) is not None and code >= 400
        ),
        connection_failures=sum(
            record.outcome == "request_error" for record in records
        ),
        unfinished_requests=sum(record.outcome == "started" for record in records),
        hourly_peaks=peaks,
        exceptions=exceptions,
        failures=failures,
    )
