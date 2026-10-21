from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

from scorenow_api_observer.bets_api_client import (
    EVENT_ODDS_ENDPOINT,
    get_event_odds,
)
from scorenow_api_observer.event_odds.models import (
    OddsRequestQuery,
    OddsSnapshotMetadata,
)
from scorenow_api_observer.event_odds.response import (
    InvalidEventOddsResponseShapeError,
    analyze_event_odds_response,
)
from scorenow_api_observer.event_odds.storage import (
    ODDS_METADATA_DIRECTORY,
    ODDS_RAW_DATA_DIRECTORY,
    build_event_odds_raw_response_path,
    save_event_odds_snapshot,
)

DEFAULT_ODDS_MARKETS = (1, 2, 3)
OddsCollectionEventStatus = Literal[
    "captured",
    "request_failed",
    "response_invalid",
    "storage_failed",
]
OddsCollectionStatus = Literal["completed", "partial", "failed"]


@dataclass(frozen=True)
class OddsCollectionEventResult:
    """현재 collect-odds 실행에서 이벤트 하나를 처리한 결과입니다."""

    event_id: str
    status: OddsCollectionEventStatus
    http_status_code: int | None = None
    raw_file_path: str | None = None
    metadata_file_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CollectedOddsSnapshot:
    """유효한 응답으로 저장된 이벤트 하나의 최신 Odds Snapshot입니다."""

    response: httpx.Response
    metadata: OddsSnapshotMetadata
    raw_file_path: Path
    metadata_file_path: Path


@dataclass(frozen=True)
class OddsCollectionResult:
    """현재 collect-odds 실행의 메모리 내 집계와 저장된 Snapshot 목록입니다."""

    status: OddsCollectionStatus
    event_results: list[OddsCollectionEventResult]
    snapshots: list[CollectedOddsSnapshot]


def collect_event_odds(
    *,
    base_url: str,
    token: str,
    event_ids: list[str],
    odds_markets: tuple[int, ...] = DEFAULT_ODDS_MARKETS,
    now: Callable[[], datetime] | None = None,
    raw_base_directory: Path = ODDS_RAW_DATA_DIRECTORY,
    metadata_base_directory: Path = ODDS_METADATA_DIRECTORY,
) -> OddsCollectionResult:
    """이벤트별 Odds API를 호출하고 성공한 일간 최신 Snapshot을 저장합니다."""

    if not event_ids:
        raise ValueError("Event Odds 수집 대상은 한 개 이상이어야 합니다.")
    if not odds_markets:
        raise ValueError("Event Odds 수집 마켓은 한 개 이상이어야 합니다.")

    clock = now or _utc_now
    event_results: list[OddsCollectionEventResult] = []
    snapshots: list[CollectedOddsSnapshot] = []

    for event_id in event_ids:
        event_result, snapshot = _collect_event_odds_snapshot(
            base_url=base_url,
            token=token,
            event_id=event_id,
            odds_markets=odds_markets,
            clock=clock,
            raw_base_directory=raw_base_directory,
            metadata_base_directory=metadata_base_directory,
        )
        event_results.append(event_result)
        if snapshot is not None:
            snapshots.append(snapshot)

    return OddsCollectionResult(
        status=_determine_collection_status(event_results),
        event_results=event_results,
        snapshots=snapshots,
    )


def _collect_event_odds_snapshot(
    *,
    base_url: str,
    token: str,
    event_id: str,
    odds_markets: tuple[int, ...],
    clock: Callable[[], datetime],
    raw_base_directory: Path,
    metadata_base_directory: Path,
) -> tuple[OddsCollectionEventResult, CollectedOddsSnapshot | None]:
    try:
        response = get_event_odds(
            base_url=base_url,
            token=token,
            event_id=event_id,
            odds_markets=odds_markets,
        )
    except httpx.RequestError as error:
        return (
            _failed_event_result(
                event_id=event_id,
                status="request_failed",
                error_type=type(error).__name__,
                error_message="API 서버에 연결하지 못했습니다.",
            ),
            None,
        )

    captured_at = _require_aware_datetime(clock())
    if response.is_error:
        return (
            _failed_event_result(
                event_id=event_id,
                status="response_invalid",
                http_status_code=response.status_code,
                error_type="HttpStatusError",
                error_message=(
                    f"API가 HTTP {response.status_code} 오류를 반환했습니다."
                ),
            ),
            None,
        )

    try:
        response_json = response.json()
    except ValueError as error:
        return (
            _failed_event_result(
                event_id=event_id,
                status="response_invalid",
                http_status_code=response.status_code,
                error_type=type(error).__name__,
                error_message="Event Odds 응답이 JSON 형식이 아닙니다.",
            ),
            None,
        )

    try:
        analysis = analyze_event_odds_response(response_json)
    except InvalidEventOddsResponseShapeError as error:
        return (
            _failed_event_result(
                event_id=event_id,
                status="response_invalid",
                http_status_code=response.status_code,
                error_type=type(error).__name__,
                error_message=str(error),
            ),
            None,
        )

    try:
        raw_file_path = build_event_odds_raw_response_path(
            event_id=event_id,
            captured_at=captured_at,
            base_directory=raw_base_directory,
        )
        metadata = OddsSnapshotMetadata(
            captured_at=captured_at,
            provider="betsapi",
            endpoint=EVENT_ODDS_ENDPOINT,
            http_method="GET",
            query=OddsRequestQuery(
                event_id=event_id,
                odds_market=",".join(str(market) for market in odds_markets),
            ),
            returned_market_keys=analysis.returned_market_keys,
            record_counts_by_market=analysis.record_counts_by_market,
            http_status_code=response.status_code,
            elapsed_ms=_response_elapsed_ms(response),
            response_size_bytes=len(response.content),
            content_type=response.headers.get("content-type"),
            raw_file_path=str(raw_file_path),
        )
        raw_file_path, metadata_file_path = save_event_odds_snapshot(
            response_body=response.content,
            metadata=metadata,
            raw_base_directory=raw_base_directory,
            metadata_base_directory=metadata_base_directory,
        )
    except (OSError, ValueError) as error:
        return (
            _failed_event_result(
                event_id=event_id,
                status="storage_failed",
                http_status_code=response.status_code,
                error_type=type(error).__name__,
                error_message=f"Event Odds Snapshot 저장에 실패했습니다: {error}",
            ),
            None,
        )

    snapshot = CollectedOddsSnapshot(
        response=response,
        metadata=metadata,
        raw_file_path=raw_file_path,
        metadata_file_path=metadata_file_path,
    )
    return (
        OddsCollectionEventResult(
            event_id=event_id,
            status="captured",
            http_status_code=response.status_code,
            raw_file_path=str(raw_file_path),
            metadata_file_path=str(metadata_file_path),
        ),
        snapshot,
    )


def _failed_event_result(
    *,
    event_id: str,
    status: OddsCollectionEventStatus,
    error_type: str,
    error_message: str,
    http_status_code: int | None = None,
    raw_file_path: str | None = None,
) -> OddsCollectionEventResult:
    return OddsCollectionEventResult(
        event_id=event_id,
        status=status,
        http_status_code=http_status_code,
        raw_file_path=raw_file_path,
        metadata_file_path=None,
        error_type=error_type,
        error_message=error_message,
    )


def _determine_collection_status(
    event_results: list[OddsCollectionEventResult],
) -> OddsCollectionStatus:
    captured_count = sum(result.status == "captured" for result in event_results)
    if captured_count == len(event_results):
        return "completed"
    if captured_count == 0:
        return "failed"
    return "partial"


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Odds 수집 시각에는 시간대 정보가 필요합니다.")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _response_elapsed_ms(response: httpx.Response) -> float:
    try:
        elapsed_seconds = response.elapsed.total_seconds()
    except RuntimeError:
        return 0.0
    return round(elapsed_seconds * 1000, 2)
