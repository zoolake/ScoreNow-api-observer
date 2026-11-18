# ScoreNow API Observer 구조

이 문서는 현재 구현된 기능을 실제 함수 호출 순서와 저장 데이터의 관계를 중심으로
설명합니다. 함수 이름은 코드에서 그대로 검색할 수 있도록 작성합니다.

현재 Upcoming 엔드포인트로 관찰할 경기를 탐색하고 Event View 엔드포인트를
수집·비교하며, Event Odds 엔드포인트의 누적 배당률 Snapshot을 수집합니다. 보고서 분석은
`EventViewReportAnalysis`, endpoint 전체·종목별·리그별 Markdown 렌더러와 `report` CLI,
이벤트별 단일 필드 변화를 만드는 `inspect-field`와 여러 주요 필드의 맥락을 같은
시간축에서 보여주는 `inspect-timeline` CLI가 구현되어 있습니다.
HTML 렌더러는 아직 구현되지 않았습니다.

## 전체 구조

```text
CLI
├── discover-upcoming ── 설정된 종목·리그의 예정 경기 탐색
├── discover-auto-watch ── 활성 리그의 UTC 오늘·내일 예정 경기 탐색
├── upcoming-candidates ── 저장된 Discovery에서 곧 시작할 경기 조회
├── watch-upcoming ── 곧 시작할 경기를 자동 선택해 Event View 반복 수집
├── auto-watch ── Discovery 재확인 + 활성 목록 복구 + 지속 Event View 수집
├── auto-watch-status ── 로컬 실행·요청량·예외 상태 조회(API 호출 없음)
├── collect-upcoming-odds ── 곧 시작할 경기를 자동 선택해 Event Odds 한 번 수집
├── collect           ── Event View API 호출 및 Capture 저장
├── collect-odds      ── 이벤트별 Event Odds API 호출 및 일간 최신 Snapshot 저장
├── watch             ── collect 반복 + 이벤트별 직전 응답 비교 + 변화 기록
├── compare           ── 저장된 특정 이벤트의 최근 응답 2개 비교
├── report            ── 저장된 전체 자료 분석 + endpoint·종목·리그별 Markdown 보고서 저장
├── inspect-field     ── 저장된 특정 필드의 이벤트별 값 변화 보고서 저장
└── inspect-timeline  ── 이벤트 하나의 설정 필드 통합 타임라인 보고서 저장

보고서 분석 라이브러리
└── 저장 파일 탐색 → 부분 성공 로드 → 이벤트 해석 → 보고서용 집계
```

`collect`, `watch`, `watch-upcoming`, `auto-watch`는 하나의 공통 수집 함수인
`capture_event_view()`를 사용합니다. `watch`와 `watch-upcoming`은
`_run_event_view_watch()`로 반복 제어와 동적 요청 배치를 공유합니다. `auto-watch`는
실행 중 후보를 추가하고 재시작 상태를 복구해야 하므로 `_run_auto_watch()`에서 별도
반복 제어를 하되, 종료 상태 해석은 같은 `event_view.watching` 함수를 사용합니다.
`collect-odds`와 `collect-upcoming-odds`는 Event Odds가 한 요청에 이벤트 하나만 받는
제약에 맞춰 `collect_event_odds()`를 공유하고, 이벤트별 호출 결과를 메모리에서
집계합니다. `compare`와 watch의 구조 비교는 `compare_observations()`로 합쳐집니다.
`report`는 저장된 자료만 사용하는 오프라인 명령이며 API 설정을 읽지 않습니다.
`auto-watch-status`도 상태·요청·예외 파일만 읽는 오프라인 명령입니다.
기능별 코드는 `event_view`, `upcoming`, `event_odds`, `reporting` 하위 패키지로
분리되어 있습니다. `auto_watch` 패키지는 활성 목록·예외·실행 상태를,
`bets_api_request_log` 모듈은 모든 endpoint의 API 요청 기록을 담당합니다.

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
    │   │   ├── bets_api_request_log.start_bets_api_request(...)
    │   │   │   └── HTTP 호출 전에 종목·리그·조회 날짜 기록
    │   │   ├── bets_api_client.get_upcoming_events(...)
    │   │   │   └── GET /v3/events/upcoming?sport_id=...&league_id=...&day=...
    │   │   ├── bets_api_request_log.finish_bets_api_request(...)
    │   │   │   └── HTTP 상태·연결 오류·X-RateLimit 헤더 반영
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
`captured_at`은 UTC를 유지합니다. 파일명의 시각은 같은 리그를 1초 안에 연속 조회해도
충돌하지 않도록 마이크로초까지 포함합니다. 리그별 Discovery와 실행 Run은 API에
전달한 UTC `target_date`별로 저장하며 경기 예정 시각은 UTC와 KST를 모두 제공합니다.
Run에는 이벤트를 중복 저장하지 않고 리그별 Discovery 경로만 기록합니다.

## `discover-auto-watch` 호출 트리

```text
cli.discover_auto_watch(dry_run)
├── upcoming.targets.load_upcoming_targets(...)
├── upcoming.auto_discovery.build_auto_watch_discovery_plan(...)
│   ├── auto_watch_enabled=true인 리그만 선택
│   ├── 명령 시작 시각을 UTC로 변환
│   └── UTC 오늘·내일과 최대 예상 호출 횟수 계산
├── --dry-run이면 계획 출력 후 종료
│   └── Settings·API·저장소 사용 없음
├── settings.Settings()
└── UTC 오늘부터 내일 순서로
    ├── upcoming.discovery.discover_upcoming_events(...)
    │   └── discover-upcoming과 같은 수집·부분 실패·저장 흐름
    └── upcoming.auto_discovery.find_fatal_http_status_code(...)
        └── 401·402·403·429이면 다음 UTC 날짜 호출도 중단
```

이 명령은 실행 전체를 위한 별도 Run 파일을 만들지 않습니다. 실제로 처리한 각 UTC
날짜에는 기존 `UpcomingDiscoveryRun`이 저장됩니다. 오류 응답은 공통 BETS API 요청
기록·원문·CaptureMetadata·리그 Discovery에 남고, 오류 때문에 조회하지 않은 다음 UTC
날짜는 CLI 로그에만 표시합니다. 명령 자체는 한 번 실행하고 종료하며 반복 실행은 외부
스케줄러가 담당합니다.

## `upcoming-candidates` 호출 트리

```text
cli.upcoming_candidates(within_minutes, sport_code, league_labels)
├── upcoming.candidates.candidate_target_dates(...)
│   └── now부터 now + N분까지 걸치는 UTC 날짜 계산
├── upcoming.storage.find_league_upcoming_discovery_paths(target_dates=...)
│   └── 계산한 UTC target_date 디렉터리만 탐색
├── upcoming.candidates.resolve_latest_league_discoveries(...)
│   ├── 파일마다 upcoming.storage.load_league_upcoming_discovery(...)
│   ├── 읽기·검증 실패를 모으고 나머지 파일 계속 처리
│   └── (target_date, sport_id, league_id)마다
│       ├── 최신 completed 또는 partial 선택
│       ├── 최신 시도가 failed이면 이전 사용 가능 결과로 fallback
│       └── 사용 가능 결과가 없으면 unavailable로 분류
├── upcoming.candidates.select_upcoming_candidates(...)
│   ├── 종목·리그 필터 적용
│   ├── now <= scheduled_at_utc <= now + N분 범위 적용
│   ├── 이벤트 ID 중복 제거
│   └── 예정 시각·이벤트 ID 순으로 정렬
└── 후보와 Discovery 경고 출력
```

이 명령은 저장 자료만 읽으며 API 설정이나 토큰을 사용하지 않습니다. 일부 Discovery
파일을 읽지 못하거나 특정 리그에 사용 가능한 결과가 없어도 다른 리그의 후보 계산은
계속합니다. 사용할 수 있는 Discovery 자체가 하나도 없는 경우에만 종료 코드 `1`입니다.

## `collect-upcoming-odds` 호출 트리

```text
cli.collect_upcoming_odds(within_minutes, sport_code, league_labels)
├── upcoming.candidates.normalize_candidate_sport_code(...)
├── upcoming.candidates.parse_candidate_league_labels(...)
├── upcoming.candidates.candidate_target_dates(...)
├── upcoming.storage.find_league_upcoming_discovery_paths(target_dates=...)
├── upcoming.candidates.resolve_latest_league_discoveries(...)
│   └── upcoming-candidates와 같은 최신 결과·fallback 규칙 사용
├── upcoming.candidates.select_upcoming_candidates(...)
│   ├── now <= scheduled_at_utc <= now + N분 범위 적용
│   ├── time_status는 후보 조건에 사용하지 않음
│   └── 이벤트 ID 중복 제거 후 예정 시각·ID 순으로 정렬
├── 후보가 있을 때만 settings.Settings()
└── cli._collect_odds_for_event_ids(event_ids, sport_codes_by_event_id)
    └── event_odds.collector.collect_event_odds(...)
        └── collect-odds와 같은 이벤트별 호출·검증·Snapshot 교체 수행
```

이 명령은 Upcoming API를 호출하지 않으며 명령 시작 시 저장된 Discovery만 사용합니다.
기존 Odds Snapshot의 존재 여부와 관계없이 선택된 이벤트를 다시 호출합니다. Discovery의
종목 코드를 Event Odds 요청 기록에 전달하므로 축구·야구 요청량을 분류할 수 있습니다.
후보가 없으면 API 설정도 읽지 않고 정상 종료하고, 이벤트별 부분 실패와 종료 코드
정책은 `collect-odds`와 같습니다.

## `watch-upcoming` 호출 트리

```text
cli.watch_upcoming(within_minutes, sport_code, league_labels, interval, max_cycles)
├── upcoming.candidates.normalize_candidate_sport_code(...)
├── upcoming.candidates.parse_candidate_league_labels(...)
├── upcoming.candidates.candidate_target_dates(...)
├── upcoming.storage.find_league_upcoming_discovery_paths(target_dates=...)
├── upcoming.candidates.resolve_latest_league_discoveries(...)
│   └── upcoming-candidates와 같은 최신 결과·fallback 규칙 사용
├── upcoming.candidates.select_upcoming_candidates(...)
│   ├── 명령 시작 시각을 기준으로 후보 한 번 확정
│   └── 예정 시각·이벤트 ID 순으로 정렬된 고유 이벤트 반환
├── 후보가 있을 때만 settings.Settings()
└── cli._run_event_view_watch(event_ids, interval, max_cycles)
    ├── event_view.watching.EventWatchState를 이벤트별로 생성
    ├── 종료 후 15분 추가 수집을 마친 이벤트 제외
    ├── 남은 이벤트를 최대 10개씩 매 주기 다시 배치
    ├── 각 배치마다 cli._capture_event_view_watch_batch(...)
    │   ├── event_view.collector.capture_event_view(...)
    │   ├── Capture·Observation 저장 결과 출력
    │   └── Observation마다 cli._compare_and_save_structure_change(...)
    ├── cli._update_event_watch_states(...)
    │   ├── 원문에서 이벤트별 time_status 추출
    │   ├── 3을 최초 관측하면 종료 감지 시각 기록
    │   └── 다른 숫자 상태가 관측되면 종료 감지 취소
    └── 전체 배치가 끝난 뒤 다음 주기 전까지 interval만큼 대기
```

이 명령은 Upcoming API를 호출하지 않고 저장된 Discovery만 후보 선정에 사용합니다.
후보 목록은 시작할 때 한 번 확정하므로 실행 중 Discovery 변경은 반영하지 않습니다.
사용 가능한 Discovery가 있지만 후보가 없으면 API 설정도 읽지 않고 정상 종료합니다.
개별 Event View 배치가 실패해도 같은 주기의 다음 배치와 이후 수집 주기를 계속합니다.
이벤트 누락이나 해석 불가능한 time_status는 기존 종료 상태를 변경하지 않습니다. 모든
이벤트가 종료 후 15분 추가 수집을 마치면 `max_cycles`보다 일찍 종료합니다.
저장 결과는 일반 `watch`와 같은 Event View 원문·CaptureMetadata·EventObservation·
StructureChangeRecord이므로 별도의 `watch-upcoming` 저장 형식은 없습니다.

## `auto-watch` 호출 트리

```text
cli.auto_watch(within_minutes, interval, candidate_check_interval, max_cycles)
├── auto_watch.lock.acquire_auto_watch_process_lock(...)
│   ├── 운영체제 비차단 단독 잠금 획득
│   └── 이미 잠겨 있으면 초기화·API 호출 전 종료 코드 1
└── cli._start_auto_watch(...)
    ├── upcoming.targets.load_upcoming_targets(...)
    ├── upcoming.targets.select_auto_watch_targets(...)
    │   └── auto_watch_enabled=true인 리그만 새 후보 대상으로 선택
    ├── auto_watch.config.load_auto_watch_config(...)
    │   └── config/auto_watch.yaml의 상태 그룹·관찰 상한 검증
    ├── settings.Settings()
    ├── auto_watch.state.load_auto_watch_state(...)
    │   └── 없으면 빈 상태를 만들고 즉시 저장
    ├── auto_watch.heartbeat.new_auto_watch_heartbeat(...)
    │   └── 시작 시각·수집 간격·프로세스 ID를 원자적으로 저장
    └── cli._run_auto_watch(...)
        ├── 매 처리 주기 시작에 Heartbeat의 last_cycle_at 갱신
        ├── 후보 확인 시각이 되면 매번
        │   ├── 설정 파일 다시 로드
        │   ├── upcoming.candidates.candidate_target_dates(...)
        │   ├── upcoming.storage.find_league_upcoming_discovery_paths(
        │   │       target_dates=..., target_keys=활성 리그)
        │   │   └── 후보 UTC 날짜 안에서 auto_watch_enabled=true인 리그만 탐색
        │   ├── upcoming.candidates.resolve_latest_league_discoveries(...)
        │   ├── upcoming.candidates.select_upcoming_candidates(...)
        │   └── auto_watch.state.add_auto_watch_candidates(...)
        ├── auto_watch.policy.find_due_auto_watch_events(...)
        │   ├── time_status=3 감지 후 15분이면 정상 완료
        │   └── 그 밖의 상태는 그룹별 관찰 상한 적용
        ├── 중단 대상이 있으면
        │   ├── auto_watch.state.mark_auto_watch_stop_decisions(...)
        │   │   └── stopped_at을 상태 파일에 먼저 고정
        │   ├── 3이 아니면 auto_watch.exceptions.save_auto_watch_exception_record(...)
        │   └── 저장 성공 이벤트만 auto_watch.state.remove_auto_watch_events(...)
        ├── 활성 이벤트를 최대 10개씩 매 주기 다시 배치
        ├── 배치마다 cli._capture_auto_watch_batch(...)
        │   ├── bets_api_request_log.start_bets_api_request(...)
        │   │   └── HTTP 호출 전에 요청 ID·이벤트·종목·호출 분류 저장
        │   ├── event_view.collector.capture_event_view(...)
        │   ├── bets_api_request_log.finish_bets_api_request(...)
        │   │   └── 같은 파일에 HTTP 상태 또는 오류 유형을 원자적으로 반영
        │   ├── 성공 Observation 구조 비교
        │   └── 401·402·403·429면 전체 자동 수집 중단
        ├── cli._update_auto_watch_states(...)
        │   └── 상태 그룹·최초 감지 시각·마지막 CaptureMetadata 경로 반영
        ├── 상태가 바뀔 때 auto_watch.state.save_auto_watch_state(...)
        └── 정상 중단·실패 상태를 Heartbeat에 저장
```

```text
별도 discover-upcoming 실행
          │ 새 Discovery 저장
          ▼
data/discoveries/events-upcoming
          │ 5분마다 다시 읽기
          ▼
      auto-watch ──────► Event View Capture·Observation·구조 변화
          │
          ├────────────► data/state/auto-watch/auto-watch.lock
          ├────────────► data/state/auto-watch/state.json
          ├────────────► data/state/auto-watch/heartbeat.json
          ├────────────► data/exceptions/auto-watch/time-status-*/...
          └────────────► data/metrics/bets-api-requests/...
```

활성 목록은 메모리에만 두지 않고 상태 파일에 원자적으로 저장합니다. 따라서 프로세스가
재시작되어도 이벤트, 상태 그룹의 최초 감지 시각과 고정된 중단 결정 시각을 복구합니다.
예외 기록은 `stop_time_status` 디렉터리와 UTC `stopped_at` 날짜·파일명을 사용하고,
JSON에는 예정 시각을 UTC와 KST로 함께 저장합니다. 예외 저장에 실패한 이벤트는 상태
파일에 남지만 다음 유료 API 요청에서는 제외하고 같은 경로로 저장을 재시도합니다.
API 요청 기록도 실제 HTTP 호출 전에 먼저 만들어 기록 저장에 실패하면 유료 API를
호출하지 않습니다. Event View·Upcoming·Event Odds는 하나의 공통 기록 모델과 디렉터리를
사용합니다. endpoint별로 이벤트, 종목·리그·조회 날짜, 배당 마켓 등 토큰을 제외한 요청
정보를 보존합니다. 호출 분류는 `football_only`, `baseball_only`, `mixed`, `unknown` 중
하나입니다.

`state.json`은 실행 중인 이벤트와 상태 타이머를 담는 프로그램 작성 체크포인트이고,
`config/auto_watch.yaml`은 상태 그룹·관찰 시간·시간당 요청 한도를 담는 사람 작성 운영
정책입니다. 전자는 재시작 복구를 위해 계속 갱신되고 Git에서 제외되며, 후자는 실행
방식을 코드와 분리하기 위해 Git에 포함됩니다. `heartbeat.json`은 활성 이벤트 내용이
아니라 프로세스가 마지막으로 처리 주기를 시작한 시각과 정상·실패 종료 여부만
기록합니다.

`auto-watch.lock`은 같은 데이터 디렉터리를 사용하는 Auto-watch 프로세스 하나만
운영체제 단독 잠금을 갖도록 합니다. 잠금 파일은 고정된 경로에 유지하고 삭제하지
않습니다. 정상·오류 종료에서는 파일 설명자를 닫아 잠금을 해제하며, 강제 종료나 VM
재부팅에서는 운영체제가 자동으로 해제합니다. 잠금을 얻지 못한 두 번째 프로세스는
설정·상태·Heartbeat를 읽거나 유료 API를 호출하기 전에 종료합니다.

`AutoWatchCollectionMode`는 응답 상태에 따른 수집 처리 방식을 나타냅니다.
`inplay`는 1, `ended`는 3, `waiting_to_start`는 0·2,
`temporarily_stopped`는 7·10, `closing`은 4·5·6·8·9·11·12·99에 대응하며,
나머지는 `unknown`입니다. 이 중 시간 제한을 저장해야 하는 네 그룹만
`AutoWatchTimeLimitedStatusGroup`으로 제한합니다. 기존 상태 파일의 `prestart`와
`resumable` 값은 읽을 때 각각 `waiting_to_start`, `temporarily_stopped`로 변환합니다.

연결 오류와 재시도 가능한 HTTP 오류는 즉시 반복 호출하지 않고 다음 정규 수집 주기에
다시 시도합니다. 인증·결제·권한·호출 제한을 뜻하는 401·402·403·429와 로컬 Capture
저장 실패는 자동 반복으로 해결할 수 없거나 비용만 발생시킬 수 있으므로 명령을
중단합니다. `time_status=1`은 경기 중, `3`은 정상 종료로 처리합니다. `0·2`는 예정
시각 이후 2시간, `7·10`은 연속 2시간, `4·5·6·8·9·11·12·99`는 15분까지
관찰합니다. 설정에 없는 값은 연속 1시간 관찰한 뒤 예외 기록 대상으로 처리합니다.

1단계의 잠금은 동일한 macOS·Linux 파일 시스템과 데이터 디렉터리를 사용하는
프로세스를 대상으로 합니다. 여러 VM 사이의 분산 잠금과 리더 선출은 포함하지
않습니다.

## `auto-watch-status` 호출 트리

```text
cli.auto_watch_status(date, recent_exceptions, all_exceptions)
└── auto_watch.status.build_auto_watch_status_report(...)
    ├── config/auto_watch.yaml 로드
    ├── data/state/auto-watch/state.json 로드
    ├── data/state/auto-watch/heartbeat.json 로드
    ├── 명령 실행 시각이 속한 UTC 정각 구간의 전체 BETS API 요청 기록 로드
    ├── 기존 Event View 전용 요청 기록도 함께 로드
    ├── 선택한 KST 날짜와 겹치는 UTC 날짜의 요청·예외 기록 로드
    ├── 손상된 파일은 실패 목록에 남기고 나머지 파일 계속 처리
    └── auto_watch.status.render_auto_watch_status(...)
```

이 명령은 API 클라이언트와 `Settings`를 생성하지 않습니다. 현재 UTC 정각 이상 다음
정각 미만을 요청 제한 구간으로 사용하고, 아직 발생하지 않은 미래 시각의 기록은
제외합니다. Event View·Upcoming·Event Odds별 횟수와 종목 분류별 횟수를 함께
보여줍니다. 혼합·분류 불가 요청은 로컬 Soccer·Baseball 추정치 양쪽에 보수적으로
포함합니다. `X-RateLimit-Reset`이 현재 구간 종료 시각과 일치하는 응답만 유효한 현재
구간 정보로 선택하고, 축구 전용·야구 전용·혼합·분류 불가별 가장 최근 값을 분리해
보여줍니다. 일간 요청과 예외는 KST 날짜를 기준으로 집계하지만, 저장 디렉터리는 UTC
날짜이므로 해당 KST 하루와 겹치는 두 UTC 날짜 디렉터리만 탐색합니다.

## `collect` 호출 트리

```text
cli.collect(event_ids)
├── cli._parse_requested_event_ids_or_exit(event_ids)
│   └── event_view.request.parse_requested_event_ids(event_ids)
│       ├── 쉼표 분리 및 공백 제거
│       └── 중복 제거 및 정렬
├── settings.Settings()
├── event_view.request.build_event_view_request_batches(...)
│   └── 전체 ID를 최대 10개씩 한 수집 주기의 요청 배치로 구성
└── 각 배치마다 event_view.collector.capture_event_view(requested_event_ids=...)
    ├── bets_api_request_log.start_bets_api_request(...)
    │   └── HTTP 호출 전에 토큰 없는 요청 파일 저장
    ├── bets_api_client.get_event_view(...)
    │   └── GET /v1/event/view?event_id=A,B,...
    ├── bets_api_request_log.finish_bets_api_request(...)
    │   └── HTTP 상태 또는 연결 오류 유형을 같은 파일에 반영
    ├── event_view.storage.save_raw_response(response.content, captured_at)
    ├── response.json()
    ├── event_view.response.analyze_event_view_response(...)
    │   ├── returned_event_ids 계산
    │   ├── response_issues 계산
    │   └── observable_events 계산
    ├── event_view.models.CaptureMetadata(...)
    ├── event_view.storage.save_capture_metadata(metadata)
    └── observable_event마다
        ├── event_view.models.EventObservation(...)
        └── event_view.storage.save_event_observation(observation)
```

원문 또는 CaptureMetadata 저장이 실패하면 해당 배치는 실패하지만 이후 배치는 계속
처리합니다. 하나 이상의 배치가 실패하면 모든 배치를 처리한 뒤 종료 코드 `1`을
반환합니다.
개별 EventObservation 저장 실패는 `CaptureResult.observation_save_failures`에 모으고,
성공한 Capture는 유지합니다.
호출 기록을 시작하지 못하면 API를 호출하지 않습니다. `collect`, `watch`,
`watch-upcoming`, `auto-watch`가 이 공통 함수를 사용하므로 네 명령의 Event View 요청이
모두 공통 BETS API 호출 기록 디렉터리에 남습니다.

## `collect-odds` 호출 트리

```text
cli.collect_odds(event_ids)
├── event_odds.request.parse_odds_event_ids(...)
│   └── 쉼표 분리, 공백 제거, 중복 제거 및 정렬
└── cli._collect_odds_for_event_ids(event_ids)
    ├── settings.Settings()
    └── event_odds.collector.collect_event_odds(...)
        ├── 이벤트마다 bets_api_request_log.start_bets_api_request(...)
        │   └── HTTP 호출 전에 이벤트·종목·배당 마켓 기록
        ├── bets_api_client.get_event_odds(...)
        │   └── GET /v2/event/odds?event_id=...&odds_market=1,2,3
        ├── bets_api_request_log.finish_bets_api_request(...)
        │   └── HTTP 상태·연결 오류·X-RateLimit 헤더 반영
        ├── HTTP·JSON 오류이면 기존 Snapshot 유지 후 실패 결과 생성
        ├── event_odds.response.analyze_event_odds_response(...)
        │   ├── success와 results.odds 구조 검증
        │   └── 반환 마켓 키와 마켓별 레코드 수 계산
        ├── event_odds.storage.save_event_odds_snapshot(...)
        │   ├── 같은 UTC 날짜·이벤트 원문을 임시 파일로 원자적 교체
        │   └── 메타데이터 저장 실패 시 이전 원문 복구
        ├── event_odds.models.OddsSnapshotMetadata(...)
        ├── event_odds.storage.save_event_odds_snapshot_metadata(...)
        └── 이벤트별 성공·실패를 메모리의 OddsCollectionEventResult로 집계
```

이벤트 하나의 연결·응답·저장 실패는 다음 이벤트 호출을 막지 않습니다. 유효한 응답만
일간 최신 Snapshot을 교체하며, 실행 전체가 성공하면 `completed`, 일부만 성공하면
`partial`, 모두 실패하면 `failed`입니다. 실행 결과와 실패 원인은 CLI에 출력하고
별도 실행 이력 파일은 저장하지 않습니다.

## `watch` 호출 트리

```text
cli.watch(event_ids, interval_seconds, max_cycles)
├── cli._parse_requested_event_ids_or_exit(event_ids)
├── settings.Settings()
└── cli._run_event_view_watch(event_ids, interval_seconds, max_cycles)
    ├── watch-upcoming과 같은 이벤트별 상태·동적 배치 처리
    ├── cli._capture_event_view_watch_batch(...)
    │   ├── event_view.collector.capture_event_view(...)
    │   │   └── collect와 동일한 공통 수집 흐름
    │   ├── cli._print_capture_summary(result)
    │   └── cli._print_observation_save_failures(result)
    ├── 생성된 EventObservation마다
    │   └── cli._compare_and_save_structure_change(current_observation)
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
    └── cli._update_event_watch_states(...)
        └── time_status에 따라 종료 감지 시각 기록 또는 취소
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
├── upcoming.targets.load_upcoming_targets(config/betsapi_upcoming_targets.yaml)
│   └── 리그 ID·label·보고서 표시 순서 준비
├── reporting.tracked_field_config.load_tracked_fields_config(...)
│   ├── config/event_view_tracked_fields.yaml 로드
│   ├── 등록된 종목 코드·경로·중복 검증
│   └── reporting.field_path.validate_field_path(...)
├── event_view.storage.find_capture_metadata_paths(...)
├── event_view.storage.find_event_observation_paths(...)
│   └── event_id가 있으면 find_event_observation_paths_for_event(...) 사용
├── reporting.analysis.analyze_event_view_report(...)
│   ├── reporting.sources.load_capture_metadata_files(...)
│   │   └── 파일마다 event_view.storage.load_capture_metadata(path)
│   │       └── 구형 파일이면 원문을 다시 분석해 현재 모델로 변환
│   ├── reporting.sources.resolve_observed_events(...)
│   │   └── 파일마다
│   │       ├── event_view.storage.load_event_observation(path)
│   │       └── reporting.sources.resolve_observed_event(...)
│   │           ├── event_view.storage.load_capture_metadata(linked metadata)
│   │           ├── event_view.storage.load_json_file(linked raw response)
│   │           ├── event_view.observation.extract_observed_event(...)
│   │           └── sport_classification.classify_event_sport(...)
│   ├── reporting.analysis.summarize_response_analysis_statuses(...)
│   ├── reporting.analysis.summarize_response_issues(...)
│   ├── reporting.analysis.summarize_sport_observations(...)
│   ├── reporting.analysis.summarize_sport_fields(...)
│   │   └── json_structure.extract_json_structure(event_data)
│   ├── reporting.analysis.summarize_tracked_field_values(...)
│   │   └── Observation마다 reporting.field_path.resolve_json_field(...)
│   ├── reporting.analysis.summarize_league_observations(...)
│   │   └── league.id로 설정·미등록·unclassified 리그 분류
│   ├── reporting.analysis.summarize_league_fields(...)
│   │   └── 종목별 경로 합집합의 리그별 제공 현황 계산
│   ├── reporting.analysis.summarize_league_tracked_field_values(...)
│   │   └── 설정된 추적 필드 값을 리그 범위로 집계
│   └── reporting.models.EventViewReportAnalysis(...)
├── reporting.markdown.render_endpoint_report_markdown(...)
│   └── reporting/templates/markdown/event_view_endpoint.md.jinja 렌더링
├── 종목별 reporting.markdown.render_sport_report_markdown(...)
│   ├── 리그별 필드 제공 비교와 표본 없는 설정 리그 표시
│   └── reporting/templates/markdown/event_view_sport.md.jinja 렌더링
├── 표본이 있는 리그별 reporting.markdown.render_league_report_markdown(...)
│   └── reporting/templates/markdown/event_view_league.md.jinja 렌더링
├── reporting.storage.build_report_output_path(...)과
│   reporting.storage.build_league_report_output_path(...)로 전체 경로 사전 계산
│   └── 보고서 이름과 종목·리그 디렉터리를 안전한 경로로 변환
├── 전체 출력 경로의 중복·기존 파일 검사
└── reporting.storage.save_report_text(...)로 UTF-8 저장
```

CaptureMetadata 또는 EventObservation 파일 하나를 읽거나 해석하지 못해도 전체 분석을
중단하지 않습니다. 실패한 파일과 오류 메시지를 결과에 남기고 나머지 표본을 계속
집계합니다.

## `inspect-field` 호출 트리

`inspect-field`는 저장된 EventObservation만 사용하며 BETS API 설정을 읽거나 API를
호출하지 않습니다.

```text
cli.inspect_field(sport_code, field_path, event_id)
├── reporting.field_path.validate_field_path(...)
├── sport_config.load_sport_codes_by_id(...)
├── event_view.storage.find_event_observation_paths_for_event(event_id)
├── reporting.sources.resolve_observed_events(...)
├── reporting.field_inspection.analyze_field_inspection(...)
│   └── 이벤트별 reporting.field_inspection._analyze_event_field(...)
│       ├── 요청 객체 경로 조회
│       ├── 중첩 객체이면 하위 단일 값 경로를 재귀 전개
│       ├── 각 경로의 최초 상태·등장·변경·사라짐 계산
│       └── 배열이 발견된 Observation은 실패 기록 후 제외
├── reporting.markdown.render_field_inspection_markdown(...)
│   └── reporting/templates/markdown/event_view_field.md.jinja 렌더링
├── reporting.storage.build_field_report_output_path(...)
└── reporting.storage.save_report_text(...)
```

같은 값이 연속된 구간은 변화 기록에서 생략하지만, `null`과 필드 누락은 서로 다른
상태로 취급합니다. 중첩 객체는 객체 전체를 하나의 값으로 비교하지 않고 모든 분석
시점에서 발견된 하위 단일 값 경로의 합집합을 만든 뒤 경로별 타임라인으로 분석합니다.
요청 경로가 한 번도 나타나지 않은 이벤트는 이벤트별 본문에서 생략하고 개수만 분석
개요에 표시합니다. 한 번이라도 나타난 이벤트는 등장 전과 사라진 후의 누락 상태까지
타임라인에 포함합니다. 배열은 원소의 안정적인 식별 규칙이 없으므로 현재 분석
범위에서 제외합니다.

## `inspect-timeline` 호출 트리

`inspect-timeline`은 이벤트 ID만 입력받으며 저장된 Observation에서 종목을 추론하고,
해당 종목의 타임라인 설정을 적용합니다. BETS API 설정을 읽거나 API를 호출하지
않습니다.

```text
cli.inspect_timeline(event_id)
├── sport_config.load_sport_codes_by_id(...)
├── reporting.timeline_config.load_timeline_fields_config(...)
│   ├── config/event_view_timeline_fields.yaml 로드
│   └── 종목·객체 경로·중복 및 상하위 경로 중첩 검증
├── event_view.storage.find_event_observation_paths(...)
├── reporting.sources.resolve_observed_events(...)
├── reporting.event_timeline.analyze_event_timeline(...)
│   ├── 이벤트 ID가 같은 Observation 선택과 종목 추론
│   ├── 설정된 중첩 객체를 하위 단일 값 경로로 재귀 전개
│   ├── 모든 Observation의 최초 상태·변화·변화 없음 계산
│   └── 배열이 발견된 Observation은 실패 행으로 기록
├── reporting.markdown.render_event_timeline_markdown(...)
│   └── reporting/templates/markdown/event_view_timeline.md.jinja 렌더링
├── reporting.storage.build_timeline_report_output_path(...)
└── reporting.storage.save_report_text(...)
```

분석 실패 행은 직전 유효 상태를 바꾸지 않습니다. 따라서 다음 유효 Observation은
마지막으로 정상 분석된 시점과 비교됩니다. `null`, 경로 누락, 단일 값 자료형 차이는
서로 다른 상태이며, 객체는 객체 자체의 존재와 펼친 하위 경로를 함께 비교합니다.

현재 `EventViewReportAnalysis`는 다음 정보를 가집니다.

- 응답 분석 상태별 Capture 수
- 응답 이슈별 총 발생 건수와 영향을 받은 Capture 수
- 종목별 Observation 수와 고유 이벤트 수
- 종목·JSON 경로별 관측 자료형과 Observation 존재 횟수
- 각 경로가 항상·일부·전혀 제공되지 않은 고유 이벤트 수
- 설정된 종목·단일 값 경로별 값의 Observation 수와 고유 이벤트 수
- 설정된 경로의 필드 누락과 객체·배열 제외 현황
- 설정·미등록·unclassified 리그별 Observation 수와 고유 이벤트 수
- 종목에서 관측한 전체 경로의 리그별 제공 상태와 자료형
- 설정된 추적 필드의 리그별 값과 객체·배열 제외 현황
- 읽지 못한 CaptureMetadata 파일과 원인
- 해석하지 못한 EventObservation 파일과 원인

전체·성공·실패 개수는 위 집계와 실패 목록에서 계산하며 중복 저장하지 않습니다.
endpoint Markdown 보고서는 처리 개요, 응답 분석 상태, 응답 이슈, 종목별 Observation
현황과 두 종류의 실패 상세를 보여줍니다. 종목별 Markdown 보고서는 선택한 종목의
Observation·고유 이벤트 수, JSON 필드별 자료형·제공 현황과 리그별 제공 비교를
보여줍니다. 표본이 있는 리그별 상세 보고서는 같은 분석을 해당 리그의 Observation으로
제한하고, 리그 범위의 추적 필드 값 집계도 함께 보여줍니다.

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
├── raw/event-odds/{UTC 수집 날짜}/{event_id}.json
├── metadata/event-odds/{UTC 수집 날짜}/{event_id}.json
├── observations/event-view/{event_id}/{capture_file}
├── changes/event-view/{event_id}/YYYY-MM-DD/{capture_file}
├── metrics/bets-api-requests/{UTC 요청 날짜}/{request_id}.json
├── metrics/event-view-api-requests/{UTC 요청 날짜}/{request_id}.json  # 기존 기록
├── state/auto-watch/auto-watch.lock
├── state/auto-watch/state.json
├── state/auto-watch/heartbeat.json
├── exceptions/auto-watch/time-status-{값}/{UTC stopped_at 날짜}/
│   └── {UTC stopped_at 시각 Z}_{event_id}.json
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
| `EventTimelineAnalysis` | 이벤트 하나의 설정 필드별 시간순 상태와 변화 | 원문 대신 변화·출처 경로 포함 |
| `UpcomingCaptureMetadata` | Upcoming 호출 한 번의 조건·응답·이슈 | 포함하지 않음 |
| `LeagueUpcomingDiscovery` | 한 리그의 조회 결과·이벤트 또는 실패 내역 | 이벤트 요약만 포함 |
| `UpcomingDiscoveryRun` | 한 CLI 실행의 대상과 리그별 Discovery 경로 | 포함하지 않음 |
| `OddsSnapshotMetadata` | 이벤트별 일간 최신 Odds 원문의 요청·응답 정보 | 포함하지 않음 |
| `AutoWatchState` | 재시작할 활성 이벤트와 상태별 관찰·중단 결정 시각 | 포함하지 않음 |
| `AutoWatchLockMetadata` | 잠금을 보유한 프로세스 ID·시작 시각·호스트 | 포함하지 않음 |
| `AutoWatchHeartbeat` | Auto-watch 프로세스의 시작·최근 처리·종료 상태 | 포함하지 않음 |
| `AutoWatchExceptionRecord` | 정상 종료 외 상태로 관찰 상한에 도달한 이벤트 | 원문 대신 상태·출처 경로 포함 |
| `BetsApiRequestRecord` | BETS API 요청 한 번의 endpoint·입력·종목 조합·결과·응답 요청 한도 | 포함하지 않음 |

## 주요 모듈과 함수

| 모듈 | 주요 함수·클래스 | 책임 |
|---|---|---|
| `cli.py` | `discover_upcoming`, `discover_auto_watch`, `upcoming_candidates`, `watch_upcoming`, `auto_watch`, `auto_watch_status`, `collect_upcoming_odds`, `collect`, `collect_odds`, `watch`, `compare`, `report`, `inspect_field`, `inspect_timeline` | 명령 조합과 사용자 출력 |
| `auto_watch/config.py` | `load_auto_watch_config`, `AutoWatchConfig` | 상태 그룹과 관찰 상한 설정 검증 |
| `auto_watch/policy.py` | `apply_auto_watch_time_status`, `find_due_auto_watch_events` | 상태 전이와 수집 종료 시각 판정 |
| `auto_watch/exceptions.py` | `build_auto_watch_exception_record`, `save_auto_watch_exception_record` | 상태값·UTC 중단 시각별 예외 기록 저장 |
| `auto_watch/lock.py` | `acquire_auto_watch_process_lock`, `AutoWatchProcessLock` | 동일 데이터 디렉터리의 Auto-watch 단일 실행 보장 |
| `auto_watch/heartbeat.py` | `new_auto_watch_heartbeat`, `touch_auto_watch_heartbeat`, `finish_auto_watch_heartbeat` | 프로세스 시작·최근 처리·종료 상태 저장 |
| `auto_watch/status.py` | `build_auto_watch_status_report`, `render_auto_watch_status` | 로컬 실행·요청량·예외 상태 부분 성공 조회 |
| `auto_watch/state.py` | `load_auto_watch_state`, `save_auto_watch_state`, `add_auto_watch_candidates`, `mark_auto_watch_stop_decisions`, `remove_auto_watch_events` | 활성 이벤트의 재시작 복구와 중단 처리 |
| `bets_api_request_log.py` | `start_bets_api_request`, `finish_bets_api_request`, `classify_request_category`, `parse_rate_limit_headers` | 모든 BETS endpoint의 HTTP 호출 전 기록, 종목 조합별 분류와 응답 요청 한도 보존 |
| `event_view/request_log.py` | `EventViewApiRequestRecord` | 기존 Event View 전용 요청 기록 호환 |
| `event_view/request.py` | `parse_requested_event_ids`, `build_event_view_request_batches` | 직접 입력 검증과 최대 10개 요청 배치 구성 |
| `event_view/watching.py` | `EventWatchState`, `apply_event_time_status`, `find_completed_event_ids` | 이벤트별 종료 감지와 종료 후 15분 추가 수집 판정 |
| `bets_api_client.py` | `get_event_view`, `get_upcoming_events`, `get_event_odds` | BETS API HTTP 호출 |
| `upcoming/targets.py` | `load_upcoming_targets`, `select_upcoming_targets`, `select_auto_watch_targets` | Upcoming 설정 로드·검증과 직접·자동 리그 선택 |
| `upcoming/auto_discovery.py` | `build_auto_watch_discovery_plan`, `find_fatal_http_status_code` | 활성 리그의 UTC 오늘·내일 계획과 전체 중단 상태 판정 |
| `upcoming/candidates.py` | `resolve_latest_league_discoveries`, `select_upcoming_candidates` | 최신 사용 가능 Discovery 선택과 시간 범위 후보 계산 |
| `upcoming/response.py` | `analyze_upcoming_response` | Upcoming 이벤트·이슈·페이징 분석 |
| `upcoming/discovery.py` | `discover_upcoming_events`, `capture_upcoming_target` | 대상별 부분 실패 수집과 리그·Run Discovery 생성 |
| `upcoming/storage.py` | `save_upcoming_*`, `save_league_*`, `find_*`, `load_*` | Upcoming 원문·메타데이터·Discovery 저장·탐색·로드 |
| `upcoming/models.py` | `UpcomingCaptureMetadata`, `LeagueUpcomingDiscovery`, `UpcomingDiscoveryRun` 등 | Upcoming 영속 데이터 모델 |
| `event_view/collector.py` | `capture_event_view`, `CaptureResult` | 원문·Metadata·Observation 생성 및 저장 |
| `event_view/response.py` | `analyze_event_view_response` | 반환 ID, 이슈, 관측 가능 이벤트 분석 |
| `event_view/models.py` | `CaptureMetadata`, `EventObservation`, `StructureChangeRecord` | 영속 데이터 모델 |
| `event_view/storage.py` | `save_*`, `load_*`, `find_*_paths` | 파일 저장·로드·탐색과 구형 Metadata 호환 |
| `event_odds/request.py` | `parse_odds_event_ids` | 직접 입력한 Odds 이벤트 ID 검증·정규화 |
| `event_odds/response.py` | `analyze_event_odds_response` | 유효 응답 구조 검증과 마켓별 레코드 집계 |
| `event_odds/collector.py` | `collect_event_odds` | 이벤트별 부분 실패 수집과 현재 실행 결과 집계 |
| `event_odds/storage.py` | `save_event_odds_*` | 일간 최신 원문·메타데이터 교체와 실패 시 복구 |
| `event_odds/models.py` | `OddsSnapshotMetadata` | Odds 영속 데이터 모델 |
| `event_view/observation.py` | `extract_observed_event` | Observation 참조 검증과 이벤트 추출 |
| `json_structure.py` | `extract_json_structure`, `get_json_type_name` | JSON 경로와 경로별 자료형 추출 |
| `event_view/comparison.py` | `find_*_observations`, `compare_observations`, `compare_json_structures` | 이벤트별 시점 탐색과 JSON 구조 비교 |
| `sport_config.py` | `load_sport_codes_by_id` | 외부 종목 ID와 내부 코드 설정 로드 |
| `sport_classification.py` | `classify_event_sport` | 이벤트의 `sport_id` 분류 |
| `reporting/models.py` | `ObservedEvent`, `EventViewReportAnalysis`, 각종 요약·실패 모델 | 보고서 분석 단계 사이에서 전달하는 데이터 구조 |
| `reporting/sources.py` | `resolve_observed_event(s)`, `load_capture_metadata_files` | 저장 파일을 읽어 보고서 분석 입력으로 해석하고 부분 실패 기록 |
| `reporting/analysis.py` | `summarize_*`, `analyze_event_view_report` | 종목·리그별 보고서용 집계와 전체 분석 결과 조합 |
| `reporting/field_path.py` | `validate_field_path`, `resolve_json_field`, `flatten_json_object_scalars` | 보고서 분석에서 공유하는 JSON 객체 경로 처리 |
| `reporting/field_inspection.py` | `analyze_field_inspection` | 중첩 객체 전개와 이벤트별 값 변화 계산 |
| `reporting/event_timeline.py` | `analyze_event_timeline` | 이벤트 종목 추론과 설정된 여러 필드의 통합 시간순 변화 계산 |
| `reporting/timeline_config.py` | `load_timeline_fields_config` | 종목별 타임라인 경로 설정 로드·검증 |
| `reporting/tracked_field_config.py` | `load_tracked_fields_config` | 종목별 값 집계 경로 설정 로드·검증 |
| `reporting/markdown.py` | `render_endpoint_report_markdown`, `render_sport_report_markdown`, `render_league_report_markdown`, `render_field_inspection_markdown`, `render_event_timeline_markdown` | endpoint·종목·리그·필드·이벤트 타임라인 분석 결과의 Markdown 렌더링 |
| `reporting/storage.py` | `build_report_output_path`, `build_field_report_output_path`, `build_league_report_output_path`, `build_timeline_report_output_path`, `save_report_text` | 날짜별 보고서와 종목·리그·타임라인 하위 경로 계산 및 텍스트 저장 |

## 문서 갱신 기준

- CLI 진입점에서 호출하는 주요 함수가 바뀌면 해당 명령의 호출 트리를 수정합니다.
- 저장 모델의 참조 방향이 바뀌면 `Capture와 저장 데이터의 관계`를 수정합니다.
- 보고서 결과 필드가 추가되면 보고서 호출 트리와 현재 결과 목록을 함께 수정합니다.
- 세부 구현문 하나까지 나열하지 않고, 책임이 다른 함수 호출과 실패 경계만 남깁니다.
