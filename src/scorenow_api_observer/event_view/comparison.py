from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scorenow_api_observer.event_view.models import (
    CaptureMetadata,
    EventObservation,
    StructureChangeRecord,
    TypeChangeRecord,
)
from scorenow_api_observer.event_view.observation import extract_observed_event
from scorenow_api_observer.event_view.storage import (
    OBSERVATION_DIRECTORY,
    load_capture_metadata,
    load_event_observation,
    load_json_file,
)
from scorenow_api_observer.json_structure import extract_json_structure


@dataclass(frozen=True)
class TypeChange:
    """동일한 JSON 경로에서 발견된 자료형 변화입니다."""

    path: str
    previous_types: set[str]
    current_types: set[str]


@dataclass(frozen=True)
class StructureComparison:
    """두 JSON 구조를 비교한 결과입니다."""

    added_paths: list[str]
    removed_paths: list[str]
    type_changes: list[TypeChange]

    @property
    def has_changes(self) -> bool:
        return bool(self.added_paths or self.removed_paths or self.type_changes)


@dataclass(frozen=True)
class CaptureComparison:
    """특정 경기에 대한 응답 구조 비교 결과입니다."""

    event_id: str
    previous_capture: CaptureMetadata
    current_capture: CaptureMetadata
    structure_comparison: StructureComparison


def compare_json_structures(
    previous_data: Any,
    current_data: Any,
) -> StructureComparison:
    """두 JSON에서 발견되는 경로와 자료형을 비교합니다."""

    previous_structure = extract_json_structure(previous_data)
    current_structure = extract_json_structure(current_data)

    previous_paths = set(previous_structure)
    current_paths = set(current_structure)

    added_paths = sorted(current_paths - previous_paths)
    removed_paths = sorted(previous_paths - current_paths)

    common_paths = previous_paths & current_paths
    type_changes = []
    for path in sorted(common_paths):
        previous_types = previous_structure[path]
        current_types = current_structure[path]

        if previous_types != current_types:
            type_changes.append(
                TypeChange(
                    path=path,
                    previous_types=previous_types,
                    current_types=current_types,
                )
            )

    return StructureComparison(
        added_paths=added_paths,
        removed_paths=removed_paths,
        type_changes=type_changes,
    )


def compare_with_previous_observation(
    current_observation: EventObservation,
) -> CaptureComparison | None:
    """현재 Observation이 가리키는 이벤트와 직전 Observation의 구조를 비교합니다."""

    event_id = current_observation.event_id

    current_metadata = load_capture_metadata(
        Path(current_observation.capture_metadata_file_path)
    )

    previous_observation = find_previous_observation(
        event_id,
        current_metadata.captured_at,
    )

    if previous_observation is None:
        return None

    return compare_observations(previous_observation, current_observation)


def compare_observations(
    previous_observation: EventObservation,
    current_observation: EventObservation,
) -> CaptureComparison:
    """두 Observation이 가리키는 동일 이벤트의 응답 구조를 비교합니다."""

    if previous_observation.event_id != current_observation.event_id:
        raise ValueError("두 Observation의 event_id가 일치하지 않습니다.")

    previous_metadata = load_capture_metadata(
        Path(previous_observation.capture_metadata_file_path)
    )
    current_metadata = load_capture_metadata(
        Path(current_observation.capture_metadata_file_path)
    )

    previous_response_json = load_json_file(Path(previous_metadata.raw_file_path))
    current_response_json = load_json_file(Path(current_metadata.raw_file_path))

    previous_event = extract_observed_event(
        observation=previous_observation,
        response_json=previous_response_json,
    )

    current_event = extract_observed_event(
        observation=current_observation,
        response_json=current_response_json,
    )

    structure_comparison = compare_json_structures(previous_event, current_event)

    return CaptureComparison(
        event_id=current_observation.event_id,
        previous_capture=previous_metadata,
        current_capture=current_metadata,
        structure_comparison=structure_comparison,
    )


def find_previous_observation(
    event_id: str,
    reference_captured_at: datetime,
    base_directory: Path = OBSERVATION_DIRECTORY,
) -> EventObservation | None:
    """동일 이벤트에서 기준 시각보다 앞선 가장 최근 Observation을 찾습니다."""

    observation_candidates: list[tuple[datetime, EventObservation]] = []

    for observation_path in base_directory.rglob("*.json"):
        observation = load_event_observation(observation_path)

        if observation.event_id != event_id:
            continue

        metadata = load_capture_metadata(Path(observation.capture_metadata_file_path))

        if metadata.captured_at < reference_captured_at:
            observation_candidates.append((metadata.captured_at, observation))

    if not observation_candidates:
        return None

    # captured_at 오름차순으로 정렬
    observation_candidates.sort(key=lambda candidate: candidate[0])
    return observation_candidates[-1][1]


def find_latest_observations(
    event_id: str,
    limit: int = 2,
    base_directory: Path = OBSERVATION_DIRECTORY,
) -> list[EventObservation]:
    """동일 이벤트의 최근 Observation을 오래된 순서로 최대 limit개 반환합니다."""

    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    observation_candidates: list[tuple[datetime, EventObservation]] = []

    for observation_path in base_directory.rglob("*.json"):
        observation = load_event_observation(observation_path)

        if observation.event_id != event_id:
            continue

        metadata = load_capture_metadata(Path(observation.capture_metadata_file_path))
        observation_candidates.append((metadata.captured_at, observation))

    observation_candidates.sort(key=lambda candidate: candidate[0])
    return [candidate[1] for candidate in observation_candidates[-limit:]]


def convert_to_structure_change_record(
    capture_comparison: CaptureComparison,
    detected_at: datetime,
) -> StructureChangeRecord | None:
    """변경 정보를 기록하기 위한 형태로 변환한다"""

    structure_comparison = capture_comparison.structure_comparison
    if not structure_comparison.has_changes:
        return None

    previous_capture = capture_comparison.previous_capture
    current_capture = capture_comparison.current_capture

    added_paths = sorted(structure_comparison.added_paths)
    removed_paths = sorted(structure_comparison.removed_paths)
    type_changes = [
        TypeChangeRecord(
            path=type_change.path,
            previous_types=sorted(type_change.previous_types),
            current_types=sorted(type_change.current_types),
        )
        for type_change in structure_comparison.type_changes
    ]

    type_changes.sort(key=lambda type_change_record: type_change_record.path)

    return StructureChangeRecord(
        detected_at=detected_at,
        event_id=capture_comparison.event_id,
        previous_captured_at=previous_capture.captured_at,
        current_captured_at=current_capture.captured_at,
        previous_raw_file_path=previous_capture.raw_file_path,
        current_raw_file_path=current_capture.raw_file_path,
        added_paths=added_paths,
        removed_paths=removed_paths,
        type_changes=type_changes,
    )
