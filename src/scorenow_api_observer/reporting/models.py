from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from scorenow_api_observer.event_view.models import CaptureMetadata
from scorenow_api_observer.reporting.field_path import JsonScalar


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
class TrackedFieldValueSummary:
    """추적 필드에서 관측한 단일 값 하나의 집계입니다.

    Attributes:
        value_type: JSON 자료형입니다. 필드 누락은 missing으로 표현합니다.
        present: 필드가 응답에 존재했는지 나타냅니다.
        value: 실제 JSON 단일 값입니다. present가 False이면 사용하지 않습니다.
        observation_count: 해당 상태가 관측된 Observation 수입니다.
        unique_event_count: 해당 상태가 한 번 이상 관측된 고유 이벤트 수입니다.
    """

    value_type: str
    present: bool
    value: JsonScalar
    observation_count: int
    unique_event_count: int


@dataclass(frozen=True)
class TrackedFieldUnsupportedTypeSummary:
    """단일 값이 아니어서 추적 필드 값 집계에서 제외한 자료형 현황입니다.

    Attributes:
        value_type: 집계에서 제외한 JSON 자료형입니다.
        observation_count: 해당 자료형이 관측된 Observation 수입니다.
        unique_event_count: 해당 자료형이 한 번 이상 관측된 고유 이벤트 수입니다.
    """

    value_type: str
    observation_count: int
    unique_event_count: int


@dataclass(frozen=True)
class SportTrackedFieldSummary:
    """종목 하나의 설정된 JSON 경로에서 관측한 값과 제외 현황입니다.

    Attributes:
        sport_code: 값 집계 설정이 적용된 내부 종목 코드입니다.
        path: 값을 집계한 JSON 객체 경로입니다.
        value_summaries: 필드 누락을 포함한 단일 값별 집계입니다.
        unsupported_type_summaries: 객체·배열이라 값 집계에서 제외한 자료형별
            현황입니다.
    """

    sport_code: str
    path: str
    value_summaries: list[TrackedFieldValueSummary]
    unsupported_type_summaries: list[TrackedFieldUnsupportedTypeSummary]


@dataclass(frozen=True)
class LeagueDefinition:
    """보고서에서 사용할 설정 리그의 안정적인 식별 정보입니다.

    Attributes:
        sport_code: 리그가 속한 내부 종목 코드입니다.
        league_id: 외부 API에서 사용하는 리그 ID입니다.
        label: 설정 파일에 정의한 사람이 읽을 수 있는 안정적인 label입니다.
    """

    sport_code: str
    league_id: str
    label: str


@dataclass(frozen=True)
class LeagueObservationSummary:
    """종목 안의 리그 하나에 해당하는 이벤트 관측 현황입니다.

    Attributes:
        sport_code: 리그가 속한 내부 종목 코드입니다.
        league_id: 외부 API 리그 ID입니다. 분류할 수 없으면 None입니다.
        label: 보고서에서 리그를 표시할 안정적인 label입니다.
        configured: 리그가 조회 대상 설정에 등록되어 있는지 나타냅니다.
        observation_count: 해당 리그로 분류된 전체 Observation 수입니다.
        unique_event_count: 해당 리그에서 관측한 고유 이벤트 ID 수입니다.
    """

    sport_code: str
    league_id: str | None
    label: str
    configured: bool
    observation_count: int
    unique_event_count: int


@dataclass(frozen=True)
class LeagueFieldSummary:
    """리그 하나에서 관측한 JSON 필드 경로의 제공 현황입니다.

    Attributes:
        sport_code: 리그가 속한 내부 종목 코드입니다.
        league_id: 외부 API 리그 ID입니다. 분류할 수 없으면 None입니다.
        path: 이벤트 JSON에서 관측한 필드 경로입니다.
        observed_types: 해당 리그의 경로에서 관측한 JSON 자료형입니다.
        present_observation_count: 해당 경로가 존재한 Observation 수입니다.
        always_present_event_count: 모든 Observation에서 해당 경로가 존재한 고유
            이벤트 수입니다.
        sometimes_present_event_count: 일부 Observation에서만 해당 경로가 존재한
            고유 이벤트 수입니다.
        never_present_event_count: 어떤 Observation에서도 해당 경로가 존재하지 않은
            고유 이벤트 수입니다.
    """

    sport_code: str
    league_id: str | None
    path: str
    observed_types: set[str]
    present_observation_count: int
    always_present_event_count: int
    sometimes_present_event_count: int
    never_present_event_count: int


@dataclass(frozen=True)
class LeagueTrackedFieldSummary:
    """리그 하나의 설정된 JSON 경로에서 관측한 값과 제외 현황입니다.

    Attributes:
        sport_code: 리그가 속한 내부 종목 코드입니다.
        league_id: 외부 API 리그 ID입니다. 분류할 수 없으면 None입니다.
        path: 값을 집계한 JSON 객체 경로입니다.
        value_summaries: 필드 누락을 포함한 단일 값별 집계입니다.
        unsupported_type_summaries: 객체·배열이라 값 집계에서 제외한 자료형별
            현황입니다.
    """

    sport_code: str
    league_id: str | None
    path: str
    value_summaries: list[TrackedFieldValueSummary]
    unsupported_type_summaries: list[TrackedFieldUnsupportedTypeSummary]


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
        sport_tracked_field_summaries: 설정된 종목·JSON 경로별 값과 집계 제외
            자료형 현황입니다.
        league_observation_summaries: 설정 리그와 실제 관측 리그의 Observation 및
            고유 이벤트 집계입니다.
        league_field_summaries: 종목·리그·JSON 경로별 자료형과 필드 제공
            현황입니다.
        league_tracked_field_summaries: 설정된 종목·JSON 경로의 리그별 값과 집계
            제외 자료형 현황입니다.
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
    sport_tracked_field_summaries: list[SportTrackedFieldSummary] = field(
        default_factory=list
    )
    league_observation_summaries: list[LeagueObservationSummary] = field(
        default_factory=list
    )
    league_field_summaries: list[LeagueFieldSummary] = field(default_factory=list)
    league_tracked_field_summaries: list[LeagueTrackedFieldSummary] = field(
        default_factory=list
    )
