from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from scorenow_api_observer.reporting.field_path import (
    JsonScalar,
    UnsupportedArrayFieldValueError,
    flatten_json_object_scalars,
    resolve_json_field,
    validate_field_path,
)
from scorenow_api_observer.reporting.models import (
    ObservedEvent,
    ObservedEventResolutionFailure,
)

type TimelineFieldStateKind = Literal["missing", "scalar", "object"]
type TimelineRowKind = Literal["initial", "unchanged", "changed", "failed"]


@dataclass(frozen=True)
class TimelineFieldState:
    """타임라인의 한 시점에서 JSON 경로가 가진 상태입니다.

    Attributes:
        path: 이벤트 JSON 안의 객체 경로입니다.
        kind: 필드 누락, 단일 값 또는 중첩 객체 상태를 구분합니다.
        value: 단일 값입니다. kind가 scalar가 아니면 사용하지 않습니다.
    """

    path: str
    kind: TimelineFieldStateKind
    value: JsonScalar = None


@dataclass(frozen=True)
class TimelineFieldChange:
    """연속한 두 유효 Observation 사이에서 발견한 필드 상태 변화입니다."""

    path: str
    previous: TimelineFieldState
    current: TimelineFieldState


@dataclass(frozen=True)
class TimelineFieldFailure:
    """설정 경로 하나를 타임라인 상태로 해석하지 못한 기록입니다."""

    path: str
    error_message: str


@dataclass(frozen=True)
class EventTimelineRow:
    """Observation 하나에 대응하는 이벤트 타임라인 행입니다.

    최초 유효 행은 전체 상태를, 변경 행은 직전 유효 행과의 차이를 가집니다.
    분석 실패 행은 실패 원인만 가지며 직전 유효 상태를 변경하지 않습니다.
    """

    captured_at: datetime
    raw_file_path: Path
    kind: TimelineRowKind
    initial_states: list[TimelineFieldState]
    changes: list[TimelineFieldChange]
    failures: list[TimelineFieldFailure]


@dataclass(frozen=True)
class EventTimelineAnalysis:
    """이벤트 하나에서 설정된 여러 필드의 시간순 상태를 분석한 결과입니다."""

    event_id: str
    sport_code: str
    configured_paths: tuple[str, ...]
    input_observation_count: int
    analyzed_observation_count: int
    rows: list[EventTimelineRow]
    resolution_failures: list[ObservedEventResolutionFailure]

    @property
    def failed_observation_count(self) -> int:
        """필드 값 형태 때문에 분석하지 못한 Observation 수입니다."""

        return self.input_observation_count - self.analyzed_observation_count

    @property
    def changed_observation_count(self) -> int:
        """직전 유효 Observation과 비교해 변화가 발견된 Observation 수입니다."""

        return sum(row.kind == "changed" for row in self.rows)


def analyze_event_timeline(
    *,
    observed_events: list[ObservedEvent],
    resolution_failures: list[ObservedEventResolutionFailure],
    event_id: str,
    paths_by_sport_code: dict[str, tuple[str, ...]],
) -> EventTimelineAnalysis:
    """이벤트의 종목을 추론하고 설정된 여러 필드의 시간순 변화를 분석합니다.

    이벤트 ID가 같은 Observation은 종목 분류가 불가능한 표본도 포함합니다. 분류된
    표본들이 서로 다른 종목을 가리키면 어떤 설정을 적용할 수 없으므로 실패합니다.
    배열이 발견된 Observation은 실패 행으로 남기고 나머지 분석을 계속합니다.
    """

    selected_events = [
        observed_event
        for observed_event in observed_events
        if observed_event.event_id == event_id
    ]
    if not selected_events:
        raise ValueError(f"이벤트 {event_id!r}의 EventObservation이 없습니다.")

    classified_sport_codes = {
        observed_event.sport_code
        for observed_event in selected_events
        if observed_event.sport_code is not None
    }
    if not classified_sport_codes:
        raise ValueError(
            f"이벤트 {event_id!r}의 종목을 분류할 수 있는 Observation이 없습니다."
        )
    if len(classified_sport_codes) > 1:
        sport_codes = ", ".join(sorted(classified_sport_codes))
        raise ValueError(
            f"이벤트 {event_id!r}에서 서로 다른 종목이 관측되었습니다: {sport_codes}"
        )

    sport_code = next(iter(classified_sport_codes))
    try:
        configured_paths = paths_by_sport_code[sport_code]
    except KeyError as error:
        raise ValueError(
            f"종목 {sport_code!r}의 타임라인 필드 설정이 없습니다."
        ) from error
    if not configured_paths:
        raise ValueError(f"종목 {sport_code!r}의 타임라인 필드 설정이 비어 있습니다.")

    path_keys_by_path = {path: validate_field_path(path) for path in configured_paths}
    selected_events.sort(key=_observed_event_sort_key)

    rows: list[EventTimelineRow] = []
    previous_snapshot: dict[str, TimelineFieldState] | None = None
    analyzed_observation_count = 0
    for observed_event in selected_events:
        try:
            snapshot = _build_timeline_snapshot(
                event_data=observed_event.event_data,
                configured_paths=configured_paths,
                path_keys_by_path=path_keys_by_path,
            )
        except UnsupportedArrayFieldValueError as error:
            rows.append(
                EventTimelineRow(
                    captured_at=observed_event.captured_at,
                    raw_file_path=observed_event.raw_file_path,
                    kind="failed",
                    initial_states=[],
                    changes=[],
                    failures=[
                        TimelineFieldFailure(
                            path=_failure_path(error, configured_paths),
                            error_message=str(error),
                        )
                    ],
                )
            )
            continue

        analyzed_observation_count += 1
        if previous_snapshot is None:
            row_kind: TimelineRowKind = "initial"
            initial_states = _ordered_snapshot_states(
                snapshot=snapshot,
                configured_paths=configured_paths,
            )
            changes: list[TimelineFieldChange] = []
        else:
            initial_states = []
            changes = _build_timeline_changes(
                previous_snapshot=previous_snapshot,
                current_snapshot=snapshot,
                configured_paths=configured_paths,
            )
            row_kind = "changed" if changes else "unchanged"

        rows.append(
            EventTimelineRow(
                captured_at=observed_event.captured_at,
                raw_file_path=observed_event.raw_file_path,
                kind=row_kind,
                initial_states=initial_states,
                changes=changes,
                failures=[],
            )
        )
        previous_snapshot = snapshot

    return EventTimelineAnalysis(
        event_id=event_id,
        sport_code=sport_code,
        configured_paths=configured_paths,
        input_observation_count=len(selected_events),
        analyzed_observation_count=analyzed_observation_count,
        rows=rows,
        resolution_failures=resolution_failures,
    )


def _build_timeline_snapshot(
    *,
    event_data: dict[str, Any],
    configured_paths: tuple[str, ...],
    path_keys_by_path: dict[str, tuple[str, ...]],
) -> dict[str, TimelineFieldState]:
    snapshot: dict[str, TimelineFieldState] = {}

    for path in configured_paths:
        try:
            resolved = resolve_json_field(
                data=event_data,
                path_keys=path_keys_by_path[path],
            )
        except UnsupportedArrayFieldValueError as error:
            raise UnsupportedArrayFieldValueError(f"{path}: {error}") from error
        if not resolved.present:
            snapshot[path] = TimelineFieldState(path=path, kind="missing")
            continue

        value = resolved.value
        if isinstance(value, list):
            raise UnsupportedArrayFieldValueError(
                f"{path}에서 배열이 발견되어 해당 Observation을 제외했습니다."
            )
        if isinstance(value, dict):
            snapshot[path] = TimelineFieldState(path=path, kind="object")
            flattened_values = flatten_json_object_scalars(value=value, path=path)
            for leaf_path, leaf_value in flattened_values.items():
                snapshot[leaf_path] = TimelineFieldState(
                    path=leaf_path,
                    kind="scalar",
                    value=leaf_value,
                )
            continue

        snapshot[path] = TimelineFieldState(
            path=path,
            kind="scalar",
            value=cast(JsonScalar, value),
        )

    return snapshot


def _build_timeline_changes(
    *,
    previous_snapshot: dict[str, TimelineFieldState],
    current_snapshot: dict[str, TimelineFieldState],
    configured_paths: tuple[str, ...],
) -> list[TimelineFieldChange]:
    all_paths = set(previous_snapshot) | set(current_snapshot)
    changes: list[TimelineFieldChange] = []

    for path in sorted(
        all_paths,
        key=lambda current_path: _timeline_path_sort_key(
            current_path,
            configured_paths,
        ),
    ):
        previous = previous_snapshot.get(path, _missing_state(path))
        current = current_snapshot.get(path, _missing_state(path))
        if _timeline_states_are_equal(previous, current):
            continue
        changes.append(
            TimelineFieldChange(
                path=path,
                previous=previous,
                current=current,
            )
        )

    return changes


def _ordered_snapshot_states(
    *,
    snapshot: dict[str, TimelineFieldState],
    configured_paths: tuple[str, ...],
) -> list[TimelineFieldState]:
    return [
        snapshot[path]
        for path in sorted(
            snapshot,
            key=lambda current_path: _timeline_path_sort_key(
                current_path,
                configured_paths,
            ),
        )
    ]


def _timeline_states_are_equal(
    first: TimelineFieldState,
    second: TimelineFieldState,
) -> bool:
    if first.kind != second.kind:
        return False
    if first.kind != "scalar":
        return True
    return type(first.value) is type(second.value) and first.value == second.value


def _missing_state(path: str) -> TimelineFieldState:
    return TimelineFieldState(path=path, kind="missing")


def _observed_event_sort_key(observed_event: ObservedEvent) -> tuple[object, ...]:
    return (
        observed_event.captured_at,
        str(observed_event.raw_file_path),
        observed_event.result_index,
    )


def _timeline_path_sort_key(
    path: str,
    configured_paths: tuple[str, ...],
) -> tuple[object, ...]:
    for index, configured_path in enumerate(configured_paths):
        if path == configured_path:
            return (index, 0)
        if path.startswith(f"{configured_path}."):
            suffix = path.removeprefix(f"{configured_path}.")
            return (index, 1, *_json_path_sort_key(suffix))
    return (len(configured_paths), 1, *_json_path_sort_key(path))


def _json_path_sort_key(path: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(_object_key_sort_key(key) for key in path.split("."))


def _object_key_sort_key(key: str) -> tuple[int, int | str]:
    if key.isdecimal():
        return (0, int(key))
    return (1, key)


def _failure_path(
    error: UnsupportedArrayFieldValueError,
    configured_paths: tuple[str, ...],
) -> str:
    error_message = str(error)
    return next(
        (path for path in configured_paths if path in error_message),
        "<알 수 없음>",
    )
