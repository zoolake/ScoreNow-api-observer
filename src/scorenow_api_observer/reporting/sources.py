from pathlib import Path

from scorenow_api_observer.event_view.models import CaptureMetadata, EventObservation
from scorenow_api_observer.event_view.observation import extract_observed_event
from scorenow_api_observer.event_view.storage import (
    load_capture_metadata,
    load_event_observation,
    load_json_file,
)
from scorenow_api_observer.reporting.models import (
    CaptureMetadataLoadFailure,
    CaptureMetadataLoadResult,
    ObservedEvent,
    ObservedEventResolutionFailure,
    ObservedEventResolutionResult,
)
from scorenow_api_observer.sport_classification import classify_event_sport


def resolve_observed_event(
    *,
    observation: EventObservation,
    sport_code_by_id: dict[str, str],
) -> ObservedEvent:
    """EventObservation의 참조를 해석하여 보고서 분석용 이벤트를 만듭니다."""

    capture_metadata = load_capture_metadata(
        Path(observation.capture_metadata_file_path)
    )
    response_json = load_json_file(Path(capture_metadata.raw_file_path))
    event_data = extract_observed_event(
        observation=observation,
        response_json=response_json,
    )
    sport_code = classify_event_sport(
        event=event_data,
        sport_code_by_id=sport_code_by_id,
    )

    return ObservedEvent(
        event_id=observation.event_id,
        captured_at=capture_metadata.captured_at,
        raw_file_path=Path(capture_metadata.raw_file_path),
        result_index=observation.result_index,
        sport_code=sport_code,
        event_data=event_data,
    )


def resolve_observed_events(
    *,
    observation_file_paths: list[Path],
    sport_code_by_id: dict[str, str],
) -> ObservedEventResolutionResult:
    """여러 EventObservation 파일을 보고서 분석용 이벤트로 해석합니다.

    각 파일을 독립적으로 처리하여 해석에 실패한 파일은 실패 기록으로 남기고,
    나머지 파일은 계속 처리합니다. 성공 및 실패 목록은 각각 입력 경로의 상대적인
    순서를 유지합니다.
    """

    observed_events: list[ObservedEvent] = []
    failures: list[ObservedEventResolutionFailure] = []

    for observation_file_path in observation_file_paths:
        try:
            observation = load_event_observation(observation_file_path)
            observed_event = resolve_observed_event(
                observation=observation,
                sport_code_by_id=sport_code_by_id,
            )
        except (OSError, ValueError, KeyError) as error:
            failures.append(
                ObservedEventResolutionFailure(
                    observation_file_path=observation_file_path,
                    error_message=f"{type(error).__name__}: {error}",
                )
            )
        else:
            observed_events.append(observed_event)

    return ObservedEventResolutionResult(observed_events, failures)


def load_capture_metadata_files(
    *,
    metadata_file_paths: list[Path],
) -> CaptureMetadataLoadResult:
    """여러 CaptureMetadata 파일을 현재 스키마의 모델로 읽습니다.

    각 파일을 독립적으로 처리하여 읽기에 실패한 파일은 실패 기록으로 남기고,
    나머지 파일은 계속 처리합니다. 성공 및 실패 목록은 각각 입력 경로의 상대적인
    순서를 유지합니다.
    """

    metadata_items: list[CaptureMetadata] = []
    failures: list[CaptureMetadataLoadFailure] = []

    for metadata_file_path in metadata_file_paths:
        try:
            metadata = load_capture_metadata(metadata_file_path)
        except (OSError, ValueError, KeyError) as error:
            failures.append(
                CaptureMetadataLoadFailure(
                    metadata_file_path=metadata_file_path,
                    error_message=f"{type(error).__name__}: {error}",
                )
            )
        else:
            metadata_items.append(metadata)

    return CaptureMetadataLoadResult(
        metadata_items=metadata_items,
        failures=failures,
    )
