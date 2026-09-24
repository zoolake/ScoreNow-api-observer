from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, get_args, get_type_hints

from scorenow_api_observer.event_observation import extract_observed_event
from scorenow_api_observer.event_view_response import EventViewResponseIssue
from scorenow_api_observer.json_structure import extract_json_structure
from scorenow_api_observer.models import CaptureMetadata, EventObservation
from scorenow_api_observer.sport_classification import classify_event_sport
from scorenow_api_observer.storage import (
    load_capture_metadata,
    load_event_observation,
    load_json_file,
)


@dataclass(frozen=True)
class ObservedEvent:
    """보고서 분석에 사용하는 개별 이벤트와 출처 정보입니다.

    Attributes:
        event_id: 외부 API에서 식별한 이벤트 ID입니다.
        captured_at: 이벤트가 포함된 Capture의 수집 시각입니다.
        raw_file_path: 이벤트 원문이 저장된 Capture 파일 경로입니다.
        result_index: Capture 원문의 results 배열에서 이벤트가 위치한
            0부터 시작하는 인덱스입니다.
        sport_code: sport_id를 매핑한 내부 종목 코드입니다. 분류할 수 없으면
            None입니다.
        event_data: Capture 원문에서 추출한 해당 이벤트의 JSON 객체입니다.
    """

    event_id: str
    captured_at: datetime
    raw_file_path: Path
    result_index: int
    sport_code: str | None
    event_data: dict[str, Any]


@dataclass(frozen=True)
class ObservedEventResolutionFailure:
    """EventObservation 하나를 ObservedEvent로 해석하지 못한 기록입니다.

    Attributes:
        observation_file_path: 해석에 실패한 EventObservation JSON 파일 경로입니다.
        error_message: 해석에 실패한 원인을 나타내는 오류 메시지입니다.
    """

    observation_file_path: Path
    error_message: str


@dataclass(frozen=True)
class ObservedEventResolutionResult:
    """여러 EventObservation을 ObservedEvent로 해석한 결과입니다.

    Attributes:
        observed_events: 정상적으로 해석된 보고서 분석용 이벤트 목록입니다.
        failures: 해석하지 못하고 건너뛴 EventObservation의 실패 기록 목록입니다.
    """

    observed_events: list[ObservedEvent]
    failures: list[ObservedEventResolutionFailure]


@dataclass(frozen=True)
class CaptureMetadataLoadFailure:
    """CaptureMetadata 파일 하나를 읽지 못한 기록입니다.

    Attributes:
        metadata_file_path: 읽기에 실패한 CaptureMetadata JSON 파일 경로입니다.
        error_message: 읽기에 실패한 원인을 나타내는 오류 메시지입니다.
    """

    metadata_file_path: Path
    error_message: str


@dataclass(frozen=True)
class CaptureMetadataLoadResult:
    """여러 CaptureMetadata 파일을 읽은 결과입니다.

    Attributes:
        metadata_items: 정상적으로 읽어 현재 스키마로 변환된 CaptureMetadata
            목록입니다.
        failures: 읽지 못하고 건너뛴 CaptureMetadata 파일의 실패 기록 목록입니다.
    """

    metadata_items: list[CaptureMetadata]
    failures: list[CaptureMetadataLoadFailure]


@dataclass(frozen=True)
class ResponseIssueSummary:
    """응답 이슈 코드 하나의 발생 현황입니다.

    Attributes:
        code: 응답 이슈 종류를 식별하는 코드입니다.
        occurrence_count: 모든 Capture에 기록된 해당 이슈의 총 발생 건수입니다.
        affected_capture_count: 해당 이슈가 한 번 이상 기록된 Capture 수입니다.
    """

    code: str
    occurrence_count: int
    affected_capture_count: int


@dataclass(frozen=True)
class ResponseAnalysisStatusSummary:
    """응답 분석 상태 하나에 해당하는 Capture 집계입니다.

    Attributes:
        status: CaptureMetadata에 기록되는 응답 분석 상태입니다.
        capture_count: 해당 분석 상태를 가진 Capture 수입니다.
    """

    status: str
    capture_count: int


@dataclass(frozen=True)
class SportObservationSummary:
    """종목 하나에 해당하는 이벤트 관측 현황입니다.

    Attributes:
        sport_code: 내부 종목 코드입니다. 종목을 분류할 수 없으면 None입니다.
        observation_count: 해당 종목으로 분류된 전체 Observation 수입니다.
        unique_event_count: 해당 종목에서 관측한 고유 이벤트 ID 수입니다.
    """

    sport_code: str | None
    observation_count: int
    unique_event_count: int


@dataclass(frozen=True)
class SportFieldSummary:
    """종목 하나에서 관측한 JSON 필드 경로의 제공 현황입니다.

    Attributes:
        sport_code: 내부 종목 코드입니다. 종목을 분류할 수 없으면 None입니다.
        path: 이벤트 JSON에서 관측한 필드 경로입니다.
        observed_types: 해당 경로에서 관측한 JSON 자료형입니다. null도 필드가
            존재하는 경우의 자료형으로 포함합니다.
        present_observation_count: 해당 경로가 존재한 Observation 수입니다.
        always_present_event_count: 모든 Observation에서 해당 경로가 존재한 고유
            이벤트 수입니다.
        sometimes_present_event_count: 일부 Observation에서만 해당 경로가 존재한
            고유 이벤트 수입니다.
        never_present_event_count: 어떤 Observation에서도 해당 경로가 존재하지 않은
            고유 이벤트 수입니다.
    """

    sport_code: str | None
    path: str
    observed_types: set[str]
    present_observation_count: int
    always_present_event_count: int
    sometimes_present_event_count: int
    never_present_event_count: int


@dataclass(frozen=True)
class EventViewReportAnalysis:
    """저장된 Event View 자료를 보고서용으로 집계한 결과입니다.

    전체·성공·실패 개수는 각 요약의 개수 합과 실패 목록의 길이로 계산하며,
    파생된 개수는 별도 필드로 중복 저장하지 않습니다.

    Attributes:
        response_analysis_status_summaries: 응답 분석 상태별 Capture 집계입니다.
        response_issue_summaries: 응답 이슈 코드별 발생 현황입니다.
        sport_observation_summaries: 종목별 Observation 및 고유 이벤트 집계입니다.
        sport_field_summaries: 종목·JSON 경로별 자료형과 필드 제공 현황입니다.
        capture_metadata_load_failures: 읽지 못한 CaptureMetadata 파일 기록입니다.
        observed_event_resolution_failures: 해석하지 못한 EventObservation 파일
            기록입니다.
    """

    response_analysis_status_summaries: list[ResponseAnalysisStatusSummary]
    response_issue_summaries: list[ResponseIssueSummary]
    sport_observation_summaries: list[SportObservationSummary]
    capture_metadata_load_failures: list[CaptureMetadataLoadFailure]
    observed_event_resolution_failures: list[ObservedEventResolutionFailure]
    sport_field_summaries: list[SportFieldSummary]


def resolve_observed_event(
    *,
    observation: EventObservation,
    sport_code_by_id: dict[str, str],
) -> ObservedEvent:
    """EventObservation의 참조를 해석하여 보고서 분석용 이벤트를 만듭니다."""

    # 1. EventObservation 을 통해 CaptureMetadata 조회
    capture_metadata = load_capture_metadata(
        Path(observation.capture_metadata_file_path)
    )

    # 2. CaptureMetadata 를 통해 응답 원본 조회
    response_json = load_json_file(Path(capture_metadata.raw_file_path))

    # 3. 응답 원본과 EventObservation을 활용하여, 특정 이벤트의 데이터 추출
    event_data = extract_observed_event(
        observation=observation, response_json=response_json
    )

    # 4. 이벤트 데이터에서 sport_id 를 sport_code 로 변환
    sport_code = classify_event_sport(
        event=event_data, sport_code_by_id=sport_code_by_id
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

    return EventViewReportAnalysis(
        response_analysis_status_summaries=status_summaries,
        response_issue_summaries=response_issue_summaries,
        sport_observation_summaries=sport_observation_summaries,
        capture_metadata_load_failures=capture_metadata_load_result.failures,
        observed_event_resolution_failures=(observed_event_resolution_result.failures),
        sport_field_summaries=sport_field_summaries,
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
