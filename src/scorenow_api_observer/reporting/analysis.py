import json
from pathlib import Path
from typing import cast, get_args, get_type_hints

from scorenow_api_observer.event_view.models import CaptureMetadata
from scorenow_api_observer.event_view.response import EventViewResponseIssue
from scorenow_api_observer.json_structure import (
    extract_json_structure,
    get_json_type_name,
)
from scorenow_api_observer.reporting.field_path import (
    JsonScalar,
    UnsupportedArrayFieldValueError,
    resolve_json_field,
    validate_field_path,
)
from scorenow_api_observer.reporting.models import (
    EventViewReportAnalysis,
    LeagueDefinition,
    LeagueFieldSummary,
    LeagueObservationSummary,
    LeagueTrackedFieldSummary,
    ObservedEvent,
    ResponseAnalysisStatusSummary,
    ResponseIssueSummary,
    SportFieldSummary,
    SportObservationSummary,
    SportTrackedFieldSummary,
    TrackedFieldUnsupportedTypeSummary,
    TrackedFieldValueSummary,
)
from scorenow_api_observer.reporting.sources import (
    load_capture_metadata_files,
    resolve_observed_events,
)

type TrackedValueKey = tuple[bool, str, JsonScalar]


def summarize_response_issues(
    metadata_items: list[CaptureMetadata],
) -> list[ResponseIssueSummary]:
    """CaptureMetadata의 응답 이슈를 코드별로 집계합니다.

    occurrence_count에는 해당 코드의 이슈 기록 수를 모두 반영하고,
    affected_capture_count에는 같은 Capture에서 동일 코드가 반복되어도 한 번만
    반영합니다. 결과는 이슈 코드 이름순으로 반환합니다.
    """

    issue_codes = set()
    occurrence_counts_by_code: dict[str, int] = {}
    affected_capture_counts_by_code: dict[str, int] = {}

    for metadata in metadata_items:
        issues: list[EventViewResponseIssue] = metadata.response_issues
        issue_codes_in_capture = set()
        for issue in issues:
            count = occurrence_counts_by_code.setdefault(issue.code, 0)
            occurrence_counts_by_code[issue.code] = count + 1

            issue_codes.add(issue.code)

            if issue.code not in issue_codes_in_capture:
                issue_codes_in_capture.add(issue.code)
                count = affected_capture_counts_by_code.setdefault(issue.code, 0)
                affected_capture_counts_by_code[issue.code] = count + 1

    issue_summary_list = []
    for code in sorted(issue_codes):
        issue_summary_list.append(
            ResponseIssueSummary(
                code,
                occurrence_counts_by_code[code],
                affected_capture_counts_by_code[code],
            )
        )

    return issue_summary_list


def summarize_response_analysis_statuses(
    metadata_items: list[CaptureMetadata],
) -> list[ResponseAnalysisStatusSummary]:
    """CaptureMetadata를 응답 분석 상태별로 집계합니다.

    알려진 모든 분석 상태를 고정된 순서로 반환하며, 입력에 존재하지 않는 상태의
    Capture 수는 0으로 표시합니다.
    """

    counts_by_status: dict[str, int] = {}

    status_annotation = get_type_hints(CaptureMetadata)["response_analysis_status"]
    statuses = sorted(get_args(status_annotation))
    for status in statuses:
        counts_by_status[status] = 0

    for metadata in metadata_items:
        counts_by_status[metadata.response_analysis_status] += 1

    status_summaries = []
    for status, capture_count in counts_by_status.items():
        status_summaries.append(ResponseAnalysisStatusSummary(status, capture_count))

    return status_summaries


def summarize_sport_observations(
    *,
    observed_events: list[ObservedEvent],
    registered_sport_codes: set[str],
) -> list[SportObservationSummary]:
    """이벤트 Observation 수와 고유 이벤트 수를 종목별로 집계합니다.

    등록된 종목은 관측값이 없어도 0건으로 포함하고 이름순으로 반환합니다.
    분류할 수 없는 Observation은 sport_code가 None인 별도 항목으로 집계하여
    마지막에 반환합니다.
    """

    counts_by_sport_code: dict[str | None, int] = {}
    event_ids_by_sport_code: dict[str | None, set[str]] = {}

    counts_by_sport_code[None] = 0
    event_ids_by_sport_code[None] = set()

    for sport_code in sorted(registered_sport_codes):
        counts_by_sport_code[sport_code] = 0
        event_ids_by_sport_code[sport_code] = set()

    for observed_event in observed_events:
        counts_by_sport_code[observed_event.sport_code] += 1
        event_ids_by_sport_code[observed_event.sport_code].add(observed_event.event_id)

    sport_observation_summaries = []
    for sport_code in sorted(registered_sport_codes):
        sport_observation_summaries.append(
            SportObservationSummary(
                sport_code,
                counts_by_sport_code[sport_code],
                len(event_ids_by_sport_code[sport_code]),
            )
        )

    sport_observation_summaries.append(
        SportObservationSummary(
            None, counts_by_sport_code[None], len(event_ids_by_sport_code[None])
        )
    )

    return sport_observation_summaries


def analyze_event_view_report(
    *,
    metadata_file_paths: list[Path],
    observation_file_paths: list[Path],
    sport_code_by_id: dict[str, str],
    tracked_field_paths_by_sport_code: dict[str, tuple[str, ...]] | None = None,
    league_definitions: list[LeagueDefinition] | None = None,
) -> EventViewReportAnalysis:
    """저장된 Event View 자료를 읽어 보고서용 분석 결과를 만듭니다.

    읽거나 해석하지 못한 파일은 실패 기록으로 보존하고, 정상적으로 처리된
    CaptureMetadata와 ObservedEvent로 응답 상태·이슈·종목 및 필드 현황을 집계합니다.
    """

    capture_metadata_load_result = load_capture_metadata_files(
        metadata_file_paths=metadata_file_paths
    )
    observed_event_resolution_result = resolve_observed_events(
        observation_file_paths=observation_file_paths, sport_code_by_id=sport_code_by_id
    )

    status_summaries = summarize_response_analysis_statuses(
        capture_metadata_load_result.metadata_items
    )
    response_issue_summaries = summarize_response_issues(
        capture_metadata_load_result.metadata_items
    )
    sport_observation_summaries = summarize_sport_observations(
        observed_events=observed_event_resolution_result.observed_events,
        registered_sport_codes=set(sport_code_by_id.values()),
    )
    sport_field_summaries = summarize_sport_fields(
        observed_events=observed_event_resolution_result.observed_events
    )
    sport_tracked_field_summaries = summarize_tracked_field_values(
        observed_events=observed_event_resolution_result.observed_events,
        paths_by_sport_code=tracked_field_paths_by_sport_code or {},
    )
    league_observation_summaries = summarize_league_observations(
        observed_events=observed_event_resolution_result.observed_events,
        league_definitions=league_definitions or [],
    )
    league_field_summaries = summarize_league_fields(
        observed_events=observed_event_resolution_result.observed_events,
        league_observation_summaries=league_observation_summaries,
    )
    league_tracked_field_summaries = summarize_league_tracked_field_values(
        observed_events=observed_event_resolution_result.observed_events,
        league_observation_summaries=league_observation_summaries,
        paths_by_sport_code=tracked_field_paths_by_sport_code or {},
    )

    return EventViewReportAnalysis(
        response_analysis_status_summaries=status_summaries,
        response_issue_summaries=response_issue_summaries,
        sport_observation_summaries=sport_observation_summaries,
        capture_metadata_load_failures=capture_metadata_load_result.failures,
        observed_event_resolution_failures=(observed_event_resolution_result.failures),
        sport_field_summaries=sport_field_summaries,
        sport_tracked_field_summaries=sport_tracked_field_summaries,
        league_observation_summaries=league_observation_summaries,
        league_field_summaries=league_field_summaries,
        league_tracked_field_summaries=league_tracked_field_summaries,
    )


def summarize_sport_fields(
    observed_events: list[ObservedEvent],
) -> list[SportFieldSummary]:
    """이벤트 JSON 경로의 자료형과 제공 현황을 종목별로 집계합니다.

    루트 경로인 $는 제외합니다. 종목에서 한 번이라도 관측된 각 경로에 대해
    Observation 존재 횟수를 합산하고, 고유 이벤트별 제공 상태를 always, sometimes,
    never로 분류합니다.
    """

    # 이벤트별 observation 의 수 : {(sport_code,event_id),count}
    observation_counts_by_event_id: dict[tuple, int] = {}

    # 특정 이벤트에서 특정 경로가 존재하는 observation 의 수 : {(sport_code,event_id,path),count}
    observation_counts_by_path: dict[tuple, int] = {}

    # 특정 경로 별 관측된 자료형 : {(sport_code,path),set(types)}
    types_by_path: dict[tuple, set] = {}

    for observed_event in observed_events:
        structure = extract_json_structure(observed_event.event_data)

        sport_code = observed_event.sport_code
        event_id = observed_event.event_id

        observation_counts_by_event_id.setdefault((sport_code, event_id), 0)
        observation_counts_by_event_id[(sport_code, event_id)] += 1

        for path, observed_types in structure.items():
            # 루트는 제외
            if path == "$":
                continue

            observation_counts_by_path.setdefault((sport_code, event_id, path), 0)
            observation_counts_by_path[(sport_code, event_id, path)] += 1

            types_by_path.setdefault((sport_code, path), set())
            types_by_path[(sport_code, path)].update(observed_types)

    # 각 경로가 존재하는 이벤트의 개수 기준 판별
    # 전체 감지 observation 수 == '해당 경로가 존재하는 observation의 개수'      => always
    # 0 < '해당 경로가 존재하는 observation의 개수' < 전체 감지 observation의 개수  => sometimes
    # '해당 경로가 존재하는 observation의 개수' == 0                     => never
    result: list[SportFieldSummary] = []
    for (sport_code, path), observed_types in types_by_path.items():
        present_observation_count = 0
        always_count = 0
        sometimes_count = 0
        never_count = 0

        for (
            event_sport_code,
            event_id,
        ), total in observation_counts_by_event_id.items():
            if sport_code != event_sport_code:
                continue

            present = observation_counts_by_path.get(
                (sport_code, event_id, path),
                0,
            )

            present_observation_count += present

            if total == present:
                always_count += 1
            elif 0 < present < total:
                sometimes_count += 1
            else:
                never_count += 1

        result.append(
            SportFieldSummary(
                sport_code=sport_code,
                path=path,
                observed_types=observed_types,
                present_observation_count=present_observation_count,
                always_present_event_count=always_count,
                sometimes_present_event_count=sometimes_count,
                never_present_event_count=never_count,
            )
        )

    result.sort(
        key=lambda summary: (
            summary.sport_code is None,  # 1. sport_code 가 None 이 아닌게 앞에 위치
            summary.sport_code or "",  # 2. sport_code 이름순 정렬을 위한 문자열 값
            summary.path,  # 3. path 순 정렬
        )
    )
    return result


def extract_event_league_id(event_data: dict[str, object]) -> str | None:
    """이벤트의 유효한 문자열 league.id를 반환하고 분류 불가면 None을 반환합니다."""

    league = event_data.get("league")
    if not isinstance(league, dict):
        return None

    league_id = league.get("id")
    if not isinstance(league_id, str):
        return None

    normalized_league_id = league_id.strip()
    return normalized_league_id or None


def summarize_league_observations(
    *,
    observed_events: list[ObservedEvent],
    league_definitions: list[LeagueDefinition],
) -> list[LeagueObservationSummary]:
    """설정 순서를 보존하여 리그별 Observation과 고유 이벤트를 집계합니다.

    설정 리그는 표본이 없어도 0건으로 포함합니다. 유효한 ID를 가진 미등록 리그는
    설정 리그 뒤에 ID 순으로 추가하고, ID를 분류할 수 없는 표본은 종목별
    unclassified 항목으로 마지막에 추가합니다. 종목을 분류할 수 없는 Observation은
    리그 집계에서 제외합니다.
    """

    observation_counts_by_key: dict[tuple[str, str | None], int] = {}
    event_ids_by_key: dict[tuple[str, str | None], set[str]] = {}

    for definition in league_definitions:
        key = (definition.sport_code, definition.league_id)
        observation_counts_by_key.setdefault(key, 0)
        event_ids_by_key.setdefault(key, set())

    for observed_event in observed_events:
        if observed_event.sport_code is None:
            continue

        league_id = extract_event_league_id(observed_event.event_data)
        key = (observed_event.sport_code, league_id)
        observation_counts_by_key[key] = observation_counts_by_key.get(key, 0) + 1
        event_ids_by_key.setdefault(key, set()).add(observed_event.event_id)

    configured_keys = {
        (definition.sport_code, definition.league_id)
        for definition in league_definitions
    }
    summaries = [
        LeagueObservationSummary(
            sport_code=definition.sport_code,
            league_id=definition.league_id,
            label=definition.label,
            configured=True,
            observation_count=observation_counts_by_key[
                (definition.sport_code, definition.league_id)
            ],
            unique_event_count=len(
                event_ids_by_key[(definition.sport_code, definition.league_id)]
            ),
        )
        for definition in league_definitions
    ]

    unregistered_keys = sorted(
        (
            key
            for key in observation_counts_by_key
            if key not in configured_keys and key[1] is not None
        ),
        key=lambda key: (key[0], key[1] or ""),
    )
    for sport_code, league_id in unregistered_keys:
        assert league_id is not None
        summaries.append(
            LeagueObservationSummary(
                sport_code=sport_code,
                league_id=league_id,
                label=f"league-{league_id}",
                configured=False,
                observation_count=observation_counts_by_key[(sport_code, league_id)],
                unique_event_count=len(event_ids_by_key[(sport_code, league_id)]),
            )
        )

    unclassified_keys = sorted(
        (key for key in observation_counts_by_key if key[1] is None),
        key=lambda key: key[0],
    )
    for sport_code, league_id in unclassified_keys:
        summaries.append(
            LeagueObservationSummary(
                sport_code=sport_code,
                league_id=league_id,
                label="unclassified",
                configured=False,
                observation_count=observation_counts_by_key[(sport_code, league_id)],
                unique_event_count=len(event_ids_by_key[(sport_code, league_id)]),
            )
        )

    return summaries


def summarize_league_fields(
    *,
    observed_events: list[ObservedEvent],
    league_observation_summaries: list[LeagueObservationSummary],
) -> list[LeagueFieldSummary]:
    """종목에서 관측된 모든 JSON 경로의 제공 현황을 리그별로 집계합니다.

    각 종목의 경로 합집합을 사용하므로 한 리그에서만 발견된 경로도 같은 종목의
    다른 리그에는 미제공으로 집계됩니다. 표본이 없는 설정 리그는 제외합니다.
    """

    observation_counts_by_event: dict[tuple[str, str | None, str], int] = {}
    observation_counts_by_path: dict[tuple[str, str | None, str, str], int] = {}
    types_by_path: dict[tuple[str, str | None, str], set[str]] = {}
    paths_by_sport_code: dict[str, set[str]] = {}

    for observed_event in observed_events:
        sport_code = observed_event.sport_code
        if sport_code is None:
            continue

        league_id = extract_event_league_id(observed_event.event_data)
        event_key = (sport_code, league_id, observed_event.event_id)
        observation_counts_by_event[event_key] = (
            observation_counts_by_event.get(event_key, 0) + 1
        )

        structure = extract_json_structure(observed_event.event_data)
        for path, observed_types in structure.items():
            if path == "$":
                continue

            paths_by_sport_code.setdefault(sport_code, set()).add(path)
            path_key = (sport_code, league_id, observed_event.event_id, path)
            observation_counts_by_path[path_key] = (
                observation_counts_by_path.get(path_key, 0) + 1
            )
            types_by_path.setdefault((sport_code, league_id, path), set()).update(
                observed_types
            )

    result: list[LeagueFieldSummary] = []
    for league_summary in league_observation_summaries:
        if league_summary.observation_count == 0:
            continue

        sport_code = league_summary.sport_code
        league_id = league_summary.league_id
        league_event_totals = {
            event_id: total
            for (event_sport_code, event_league_id, event_id), total in (
                observation_counts_by_event.items()
            )
            if event_sport_code == sport_code and event_league_id == league_id
        }

        for path in sorted(paths_by_sport_code.get(sport_code, set())):
            present_observation_count = 0
            always_count = 0
            sometimes_count = 0
            never_count = 0

            for event_id, total in league_event_totals.items():
                present = observation_counts_by_path.get(
                    (sport_code, league_id, event_id, path),
                    0,
                )
                present_observation_count += present

                if present == total:
                    always_count += 1
                elif present > 0:
                    sometimes_count += 1
                else:
                    never_count += 1

            result.append(
                LeagueFieldSummary(
                    sport_code=sport_code,
                    league_id=league_id,
                    path=path,
                    observed_types=types_by_path.get(
                        (sport_code, league_id, path), set()
                    ),
                    present_observation_count=present_observation_count,
                    always_present_event_count=always_count,
                    sometimes_present_event_count=sometimes_count,
                    never_present_event_count=never_count,
                )
            )

    return result


def summarize_tracked_field_values(
    *,
    observed_events: list[ObservedEvent],
    paths_by_sport_code: dict[str, tuple[str, ...]],
) -> list[SportTrackedFieldSummary]:
    """설정된 단일 값 JSON 경로의 상태를 종목별로 집계합니다.

    문자열·숫자·boolean·null과 필드 누락을 서로 다른 상태로 집계합니다. 요청
    경로의 값이 객체나 배열이면 해당 Observation을 값 집계에서 제외하고 자료형별
    제외 현황에 반영합니다.
    """

    events_by_sport_code: dict[str, list[ObservedEvent]] = {}
    for observed_event in observed_events:
        if observed_event.sport_code is None:
            continue
        events_by_sport_code.setdefault(observed_event.sport_code, []).append(
            observed_event
        )

    summaries: list[SportTrackedFieldSummary] = []
    for sport_code, paths in paths_by_sport_code.items():
        sport_events = events_by_sport_code.get(sport_code, [])
        for path in paths:
            path_keys = validate_field_path(path)
            summaries.append(
                _summarize_tracked_field(
                    observed_events=sport_events,
                    sport_code=sport_code,
                    path=path,
                    path_keys=path_keys,
                )
            )

    return summaries


def summarize_league_tracked_field_values(
    *,
    observed_events: list[ObservedEvent],
    league_observation_summaries: list[LeagueObservationSummary],
    paths_by_sport_code: dict[str, tuple[str, ...]],
) -> list[LeagueTrackedFieldSummary]:
    """설정된 단일 값 JSON 경로의 상태를 표본이 있는 리그별로 집계합니다."""

    events_by_league: dict[tuple[str, str | None], list[ObservedEvent]] = {}
    for observed_event in observed_events:
        if observed_event.sport_code is None:
            continue

        key = (
            observed_event.sport_code,
            extract_event_league_id(observed_event.event_data),
        )
        events_by_league.setdefault(key, []).append(observed_event)

    summaries: list[LeagueTrackedFieldSummary] = []
    for league_summary in league_observation_summaries:
        if league_summary.observation_count == 0:
            continue

        sport_code = league_summary.sport_code
        league_id = league_summary.league_id
        league_events = events_by_league[(sport_code, league_id)]
        for path in paths_by_sport_code.get(sport_code, ()):
            path_keys = validate_field_path(path)
            sport_summary = _summarize_tracked_field(
                observed_events=league_events,
                sport_code=sport_code,
                path=path,
                path_keys=path_keys,
            )
            summaries.append(
                LeagueTrackedFieldSummary(
                    sport_code=sport_code,
                    league_id=league_id,
                    path=path,
                    value_summaries=sport_summary.value_summaries,
                    unsupported_type_summaries=(
                        sport_summary.unsupported_type_summaries
                    ),
                )
            )

    return summaries


def _summarize_tracked_field(
    *,
    observed_events: list[ObservedEvent],
    sport_code: str,
    path: str,
    path_keys: tuple[str, ...],
) -> SportTrackedFieldSummary:
    observation_counts_by_value: dict[TrackedValueKey, int] = {}
    event_ids_by_value: dict[TrackedValueKey, set[str]] = {}
    unsupported_observation_counts_by_type: dict[str, int] = {}
    unsupported_event_ids_by_type: dict[str, set[str]] = {}

    for observed_event in observed_events:
        try:
            resolved_field = resolve_json_field(
                data=observed_event.event_data,
                path_keys=path_keys,
            )
        except UnsupportedArrayFieldValueError:
            _record_unsupported_tracked_field_value(
                value_type="array",
                event_id=observed_event.event_id,
                observation_counts_by_type=unsupported_observation_counts_by_type,
                event_ids_by_type=unsupported_event_ids_by_type,
            )
            continue

        if not resolved_field.present:
            value_key: TrackedValueKey = (False, "missing", None)
        elif isinstance(resolved_field.value, (dict, list)):
            _record_unsupported_tracked_field_value(
                value_type=get_json_type_name(resolved_field.value),
                event_id=observed_event.event_id,
                observation_counts_by_type=unsupported_observation_counts_by_type,
                event_ids_by_type=unsupported_event_ids_by_type,
            )
            continue
        else:
            scalar_value = cast(JsonScalar, resolved_field.value)
            value_key = (
                True,
                get_json_type_name(scalar_value),
                scalar_value,
            )

        observation_counts_by_value[value_key] = (
            observation_counts_by_value.get(value_key, 0) + 1
        )
        event_ids_by_value.setdefault(value_key, set()).add(observed_event.event_id)

    value_summaries = [
        TrackedFieldValueSummary(
            present=present,
            value_type=value_type,
            value=value,
            observation_count=observation_count,
            unique_event_count=len(event_ids_by_value[(present, value_type, value)]),
        )
        for (present, value_type, value), observation_count in (
            observation_counts_by_value.items()
        )
    ]
    value_summaries.sort(key=_tracked_field_value_sort_key)

    unsupported_type_summaries = [
        TrackedFieldUnsupportedTypeSummary(
            value_type=value_type,
            observation_count=observation_count,
            unique_event_count=len(unsupported_event_ids_by_type[value_type]),
        )
        for value_type, observation_count in (
            unsupported_observation_counts_by_type.items()
        )
    ]
    unsupported_type_summaries.sort(key=lambda summary: summary.value_type)

    return SportTrackedFieldSummary(
        sport_code=sport_code,
        path=path,
        value_summaries=value_summaries,
        unsupported_type_summaries=unsupported_type_summaries,
    )


def _record_unsupported_tracked_field_value(
    *,
    value_type: str,
    event_id: str,
    observation_counts_by_type: dict[str, int],
    event_ids_by_type: dict[str, set[str]],
) -> None:
    observation_counts_by_type[value_type] = (
        observation_counts_by_type.get(value_type, 0) + 1
    )
    event_ids_by_type.setdefault(value_type, set()).add(event_id)


def _tracked_field_value_sort_key(
    summary: TrackedFieldValueSummary,
) -> tuple[int, str]:
    type_order = {
        "boolean": 0,
        "integer": 1,
        "number": 2,
        "string": 3,
        "null": 4,
        "missing": 5,
    }
    serialized_value = json.dumps(summary.value, ensure_ascii=False)
    return (type_order.get(summary.value_type, 99), serialized_value)
