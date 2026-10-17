# ScoreNow API Observer 구조

이 문서는 현재 구현된 기능을 실제 함수 호출 순서와 저장 데이터의 관계를 중심으로
설명합니다. 함수 이름은 코드에서 그대로 검색할 수 있도록 작성합니다.

현재 Upcoming 엔드포인트로 관찰할 경기를 탐색하고 Event View 엔드포인트를
수집·비교합니다. 보고서 분석은
`EventViewReportAnalysis`, endpoint 전체·종목별 Markdown 렌더러와 `report` CLI가
구현되어 있습니다. HTML 렌더러는 아직 구현되지 않았습니다.

## 전체 구조

```text
CLI
├── discover-upcoming ── 설정된 종목·리그의 예정 경기 탐색
├── collect           ── Event View API 호출 및 Capture 저장
├── watch             ── collect 반복 + 이벤트별 직전 응답 비교 + 변화 기록
├── compare           ── 저장된 특정 이벤트의 최근 응답 2개 비교
└── report            ── 저장된 전체 자료 분석 + endpoint·종목별 Markdown 보고서 저장

보고서 분석 라이브러리
└── 저장 파일 탐색 → 부분 성공 로드 → 이벤트 해석 → 보고서용 집계
```

`collect`와 `watch`는 하나의 공통 수집 함수인 `capture_event_view()`를 사용합니다.
`compare`와 `watch`의 구조 비교는 `compare_observations()`로 합쳐집니다. `report`는
저장된 자료만 사용하는 오프라인 명령이며 API 설정을 읽지 않습니다. 기능별 코드는
`event_view`, `upcoming`, `reporting` 하위 패키지로 분리되어 있습니다.

## `discover-upcoming` 호출 트리

```text
cli.discover_upcoming(target_date_value, league_labels)
├── cli._parse_target_date_or_exit(...)
├── upcoming.targets.load_upcoming_targets(...)
│   ├── config/betsapi_upcoming_targets.yaml 로드·검증
│   ├── sport_config.load_sport_codes_by_id(...)
│   └── 호출 단위 UpcomingTarget 목록 생성
├── upcoming.targets.select_upcoming_targets(...)
│   └── --league-labels가 있으면 설정된 대상 중 해당 label만 선택
├── settings.Settings()
└── upcoming.discovery.discover_upcoming_events(...)
    ├── 설정된 UpcomingTarget마다
    │   ├── upcoming.discovery.capture_upcoming_target(...)
    │   │   ├── bets_api_client.get_upcoming_events(...)
    │   │   │   └── GET /v3/events/upcoming?sport_id=...&league_id=...&day=...
    │   │   ├── upcoming.storage.save_upcoming_raw_response(...)
    │   │   ├── upcoming.response.analyze_upcoming_response(...)
    │   │   │   ├── returned_event_ids와 response_issues 계산
    │   │   │   ├── 페이징 필요 여부 확인
    │   │   │   └── Discovery에 포함 가능한 이벤트 추출
    │   │   ├── upcoming.models.UpcomingCaptureMetadata(...)
    │   │   └── upcoming.storage.save_upcoming_capture_metadata(...)
    │   ├── upcoming.models.LeagueUpcomingDiscovery(...)
    │   └── upcoming.storage.save_league_upcoming_discovery(...)
    ├── upcoming.models.UpcomingDiscoveryRun(...)
    └── upcoming.storage.save_upcoming_discovery_run(...)
```

일반적인 연결·응답·저장 실패는 해당 조회 대상의 실패로 남기고 다음 대상을 계속
처리합니다. HTTP 401, 402, 403, 429는 남은 유료 호출을 중단하며, 조회하지 않은 대상도
`SkippedTargetError`로 리그별 Discovery에 기록합니다. 일부 성공은 `partial`이지만 CLI
종료 코드는 `0`이고, 모든 대상 실패만 종료 코드 `1`입니다.

Upcoming 원문과 CaptureMetadata는 KST 호출 날짜·파일명을 사용하고, JSON 안의
`captured_at`은 UTC를 유지합니다. 리그별 Discovery와 실행 Run은 API에 전달한 UTC
`target_date`별로 저장하며 경기 예정 시각은 UTC와 KST를 모두 제공합니다. Run에는
이벤트를 중복 저장하지 않고 리그별 Discovery 경로만 기록합니다.

## `collect` 호출 트리

```text
cli.collect(event_ids)
├── cli._parse_requested_event_ids_or_exit(event_ids)
│   └── event_view.request.parse_requested_event_ids(event_ids)
│       ├── 쉼표 분리 및 공백 제거
│       ├── 중복 제거 및 정렬
│       └── 최대 10개 검증
├── settings.Settings()
├── event_view.collector.capture_event_view(requested_event_ids=...)
│   ├── bets_api_client.get_event_view(...)
│   │   └── GET /v1/event/view?event_id=A,B,...
│   ├── event_view.storage.save_raw_response(response.content, captured_at)
│   ├── response.json()
│   ├── event_view.response.analyze_event_view_response(...)
│   │   ├── returned_event_ids 계산
│   │   ├── response_issues 계산
│   │   └── observable_events 계산
│   ├── event_view.models.CaptureMetadata(...)
│   ├── event_view.storage.save_capture_metadata(metadata)
│   └── observable_event마다
│       ├── event_view.models.EventObservation(...)
│       └── event_view.storage.save_event_observation(observation)
├── cli._print_capture_summary(result)
├── cli._print_observation_save_failures(result)
└── HTTP 응답 JSON 출력
```

원문 또는 CaptureMetadata 저장이 실패하면 `capture_event_view()` 자체가 실패합니다.
개별 EventObservation 저장 실패는 `CaptureResult.observation_save_failures`에 모으고,
성공한 Capture는 유지합니다.

## `watch` 호출 트리

```text
cli.watch(event_ids, interval_seconds, count)
├── cli._parse_requested_event_ids_or_exit(event_ids)
├── settings.Settings()
└── 반복
    ├── event_view.collector.capture_event_view(...)
    │   └── collect와 동일한 공통 수집 흐름
    ├── cli._print_capture_summary(result)
    ├── cli._print_observation_save_failures(result)
    └── 생성된 EventObservation마다
        └── cli._compare_and_save_structure_change(current_observation)
            ├── event_view.comparison.compare_with_previous_observation(...)
            │   ├── event_view.storage.load_capture_metadata(current metadata)
            │   ├── event_view.comparison.find_previous_observation(...)
            │   │   ├── event_view.storage.load_event_observation(path)
            │   │   ├── event_id가 다른 Observation 제외
            │   │   └── event_view.storage.load_capture_metadata(matching observation)
            │   └── event_view.comparison.compare_observations(previous, current)
            │       ├── 두 CaptureMetadata 로드
            │       ├── 두 원문 JSON 로드
            │       ├── event_view.observation.extract_observed_event(...) × 2
            │       └── event_view.comparison.compare_json_structures(...)
            │           └── json_structure.extract_json_structure(...) × 2
            ├── event_view.comparison.convert_to_structure_change_record(...)
            ├── cli._print_structure_comparison(...)
            └── event_view.storage.save_structure_change_record(record)
```

`watch`는 API 연결, Capture 저장, Observation 저장, 비교 또는 변화 기록 중 일부가
실패해도 정해진 실패 경계에서 오류를 출력하고 다음 호출을 계속합니다. 직전
Observation이 없거나 구조 변화가 없으면 `StructureChangeRecord`를 저장하지 않습니다.

## `compare` 호출 트리

```text
cli.compare(event_id)
├── event_view.comparison.find_latest_observations(event_id, limit=2)
│   ├── event_view.storage.load_event_observation(path)
│   ├── event_id가 다른 Observation 제외
│   ├── event_view.storage.load_capture_metadata(matching observation)
│   └── captured_at 기준 최근 2개를 오래된 순서로 반환
├── event_view.comparison.compare_observations(previous, current)
│   ├── 두 CaptureMetadata 로드
│   ├── 두 원문 JSON 로드
│   ├── event_view.observation.extract_observed_event(...) × 2
│   └── event_view.comparison.compare_json_structures(...)
│       └── json_structure.extract_json_structure(...) × 2
└── cli._print_structure_comparison(...)
```

`compare`는 저장된 자료만 읽는 조회 전용 명령입니다. 비교 결과를 출력하지만 별도의
`StructureChangeRecord`는 저장하지 않습니다.

## 보고서 분석 호출 트리

`report` 명령은 설정과 저장 파일 경로를 준비하고 분석·렌더링·저장을 조합합니다.

```text
cli.report()
├── sport_config.load_sport_codes_by_id(config/betsapi_sports.yaml)
├── event_view.storage.find_capture_metadata_paths(...)
├── event_view.storage.find_event_observation_paths(...)
├── reporting.analysis.analyze_event_view_report(...)
│   ├── reporting.analysis.load_capture_metadata_files(...)
│   │   └── 파일마다 event_view.storage.load_capture_metadata(path)
│   │       └── 구형 파일이면 원문을 다시 분석해 현재 모델로 변환
│   ├── reporting.analysis.resolve_observed_events(...)
│   │   └── 파일마다
│   │       ├── event_view.storage.load_event_observation(path)
│   │       └── reporting.analysis.resolve_observed_event(...)
│   │           ├── event_view.storage.load_capture_metadata(linked metadata)
│   │           ├── event_view.storage.load_json_file(linked raw response)
│   │           ├── event_view.observation.extract_observed_event(...)
│   │           └── sport_classification.classify_event_sport(...)
│   ├── reporting.analysis.summarize_response_analysis_statuses(...)
│   ├── reporting.analysis.summarize_response_issues(...)
│   ├── reporting.analysis.summarize_sport_observations(...)
│   ├── reporting.analysis.summarize_sport_fields(...)
│   │   └── json_structure.extract_json_structure(event_data)
│   └── reporting.analysis.EventViewReportAnalysis(...)
├── reporting.markdown.render_endpoint_report_markdown(...)
│   └── reporting/templates/markdown/event_view_endpoint.md.jinja 렌더링
├── 종목별 reporting.markdown.render_sport_report_markdown(...)
│   └── reporting/templates/markdown/event_view_sport.md.jinja 렌더링
├── reporting.storage.build_report_output_path(...) 전체 경로 사전 계산
│   └── 보고서 이름을 안전한 파일명으로 변환
├── 전체 출력 경로의 중복·기존 파일 검사
└── reporting.storage.save_report_text(...)로 UTF-8 저장
```

CaptureMetadata 또는 EventObservation 파일 하나를 읽거나 해석하지 못해도 전체 분석을
중단하지 않습니다. 실패한 파일과 오류 메시지를 결과에 남기고 나머지 표본을 계속
집계합니다.

현재 `EventViewReportAnalysis`는 다음 정보를 가집니다.

- 응답 분석 상태별 Capture 수
- 응답 이슈별 총 발생 건수와 영향을 받은 Capture 수
- 종목별 Observation 수와 고유 이벤트 수
- 종목·JSON 경로별 관측 자료형과 Observation 존재 횟수
- 각 경로가 항상·일부·전혀 제공되지 않은 고유 이벤트 수
- 읽지 못한 CaptureMetadata 파일과 원인
- 해석하지 못한 EventObservation 파일과 원인

전체·성공·실패 개수는 위 집계와 실패 목록에서 계산하며 중복 저장하지 않습니다.
endpoint Markdown 보고서는 처리 개요, 응답 분석 상태, 응답 이슈, 종목별 Observation
현황과 두 종류의 실패 상세를 보여줍니다. 종목별 Markdown 보고서는 선택한 종목의
Observation·고유 이벤트 수와 JSON 필드별 자료형 및 제공 현황을 보여줍니다.

## Capture와 저장 데이터의 관계

```text
Event View 요청 1회 (Capture)
├── Raw Response 1개
│   └── API 응답 바이트 원문
├── CaptureMetadata 1개
│   ├── 요청 ID
│   ├── 실제 반환 ID
│   ├── 응답 분석 상태와 이슈
│   ├── HTTP 메타데이터
│   └── raw_file_path ────────────────┐
└── 식별 가능한 이벤트마다 EventObservation
    ├── event_id                      │
    ├── capture_metadata_file_path ───┼──> CaptureMetadata
    └── result_index ─────────────────┴──> Raw Response의 results[index]
```

EventObservation은 이벤트 본문을 복제하지 않습니다. 실제 이벤트 데이터는 다음 참조를
따라가며 원문에서 꺼냅니다.

```text
EventObservation
→ CaptureMetadata
→ Raw Response
→ results[result_index]
→ event_id 일치 검증
→ 이벤트 JSON 객체
```

응답에 ID가 없거나 같은 ID가 중복되면 특정 이벤트를 안전하게 가리킬 수 없으므로
EventObservation을 만들지 않습니다. 요청하지 않은 이벤트라도 고유한 ID로 반환되면
Observation을 만들고, 예상 밖 반환이라는 사실은 CaptureMetadata의 이슈에도 남깁니다.

```text
data/
├── raw/event-view/YYYY-MM-DD/{capture_file}
├── metadata/event-view/YYYY-MM-DD/{capture_file}
├── observations/event-view/{event_id}/{capture_file}
├── changes/event-view/{event_id}/YYYY-MM-DD/{capture_file}
├── raw/events-upcoming/{KST 호출 날짜}/{capture_file}
├── metadata/events-upcoming/{KST 호출 날짜}/{capture_file}
└── discoveries/events-upcoming/{UTC target_date}/
    ├── runs/{KST run_id}_run.json
    └── leagues/{sport_code}/{league_id}-{league_label}/
        └── {KST run id}_discovery.json
```

## 주요 모델

| 모델 | 의미 | 원문 본문 포함 여부 |
|---|---|---|
| `CaptureMetadata` | API 요청 한 번의 요청·응답·분석 메타데이터 | 포함하지 않음 |
| `EventObservation` | Capture 안의 특정 이벤트를 역추적하는 참조 | 포함하지 않음 |
| `StructureChangeRecord` | 같은 이벤트의 두 시점 사이에서 발견한 구조 변화 | 포함하지 않음 |
| `ObservedEvent` | 보고서 분석 중 원문에서 해석한 이벤트와 출처 | 메모리에서만 포함 |
| `EventViewReportAnalysis` | 보고서 렌더링에 사용할 집계 결과 | 원문 대신 요약 포함 |
| `UpcomingCaptureMetadata` | Upcoming 호출 한 번의 조건·응답·이슈 | 포함하지 않음 |
| `LeagueUpcomingDiscovery` | 한 리그의 조회 결과·이벤트 또는 실패 내역 | 이벤트 요약만 포함 |
| `UpcomingDiscoveryRun` | 한 CLI 실행의 대상과 리그별 Discovery 경로 | 포함하지 않음 |

## 주요 모듈과 함수

| 모듈 | 주요 함수·클래스 | 책임 |
|---|---|---|
| `cli.py` | `discover_upcoming`, `collect`, `watch`, `compare`, `report` | 명령 조합과 사용자 출력 |
| `event_view/request.py` | `parse_requested_event_ids` | 쉼표 입력 정규화와 최대 10개 검증 |
| `bets_api_client.py` | `get_event_view`, `get_upcoming_events` | BETS API HTTP 호출 |
| `upcoming/targets.py` | `load_upcoming_targets`, `select_upcoming_targets` | Upcoming 설정 로드·검증과 리그 선택 |
| `upcoming/response.py` | `analyze_upcoming_response` | Upcoming 이벤트·이슈·페이징 분석 |
| `upcoming/discovery.py` | `discover_upcoming_events`, `capture_upcoming_target` | 대상별 부분 실패 수집과 리그·Run Discovery 생성 |
| `upcoming/storage.py` | `save_upcoming_*`, `save_league_*` | Upcoming 원문·메타데이터·Discovery 저장 |
| `upcoming/models.py` | `UpcomingCaptureMetadata`, `LeagueUpcomingDiscovery`, `UpcomingDiscoveryRun` 등 | Upcoming 영속 데이터 모델 |
| `event_view/collector.py` | `capture_event_view`, `CaptureResult` | 원문·Metadata·Observation 생성 및 저장 |
| `event_view/response.py` | `analyze_event_view_response` | 반환 ID, 이슈, 관측 가능 이벤트 분석 |
| `event_view/models.py` | `CaptureMetadata`, `EventObservation`, `StructureChangeRecord` | 영속 데이터 모델 |
| `event_view/storage.py` | `save_*`, `load_*`, `find_*_paths` | 파일 저장·로드·탐색과 구형 Metadata 호환 |
| `event_view/observation.py` | `extract_observed_event` | Observation 참조 검증과 이벤트 추출 |
| `json_structure.py` | `extract_json_structure` | JSON 경로와 경로별 자료형 추출 |
| `event_view/comparison.py` | `find_*_observations`, `compare_observations`, `compare_json_structures` | 이벤트별 시점 탐색과 JSON 구조 비교 |
| `sport_config.py` | `load_sport_codes_by_id` | 외부 종목 ID와 내부 코드 설정 로드 |
| `sport_classification.py` | `classify_event_sport` | 이벤트의 `sport_id` 분류 |
| `reporting/analysis.py` | `resolve_*`, `summarize_*`, `analyze_event_view_report` | 부분 실패 처리와 보고서용 집계 |
| `reporting/markdown.py` | `render_endpoint_report_markdown`, `render_sport_report_markdown` | endpoint·종목별 분석 결과의 Markdown 렌더링 |
| `reporting/storage.py` | `build_report_output_path`, `save_report_text` | 날짜별 보고서 경로 계산과 텍스트 저장 |

## 문서 갱신 기준

- CLI 진입점에서 호출하는 주요 함수가 바뀌면 해당 명령의 호출 트리를 수정합니다.
- 저장 모델의 참조 방향이 바뀌면 `Capture와 저장 데이터의 관계`를 수정합니다.
- 보고서 결과 필드가 추가되면 보고서 호출 트리와 현재 결과 목록을 함께 수정합니다.
- 세부 구현문 하나까지 나열하지 않고, 책임이 다른 함수 호출과 실패 경계만 남깁니다.
