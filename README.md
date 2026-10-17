# ScoreNow API Observer

문서가 충분하지 않은 외부 스포츠 API의 응답을 반복 수집하고, 경기·리그·수집 시점에 따라 JSON 응답 구조가 어떻게 달라지는지 관찰하기 위한 Python CLI 프로젝트입니다.

현재는 BETS API의 Upcoming 엔드포인트로 설정된 종목·리그의 예정 경기를 탐색하고,
Event View 엔드포인트로 선택한 경기를 수집·비교·분석할 수 있습니다. API 토큰은
호출에만 사용하며 원문, 메타데이터, 변화 기록 파일에는 저장하지 않습니다.

현재 구현 구조와 수집·비교·보고서 분석의 실제 함수 호출 흐름은
[구조 문서](ARCHITECTURE.md)에서 확인할 수 있습니다.

## 요구 사항

- Python 3.14 이상
- [uv](https://docs.astral.sh/uv/)

## 빠른 시작

### 1. BETS API 토큰 준비

BETS API를 이용하려면 유료 플랜 결제 후 발급받은 API 토큰이 필요합니다. 실제 토큰은 Git 저장소나 수집 결과 파일에 기록하지 마세요.

### 2. 프로젝트 준비

저장소를 내려받고 프로젝트 루트로 이동한 뒤 의존성을 설치합니다. 현재 저장 경로가 프로젝트 루트 기준의 상대 경로이므로 이후 명령도 프로젝트 루트에서 실행해야 합니다.

```bash
cd ScoreNow-api-observer
uv sync
```

### 3. 환경변수 설정

예제 파일을 복사하여 `.env`를 만듭니다.

```bash
cp .env.example .env
```

`.env`의 `BETS_API_TOKEN`을 발급받은 토큰으로 교체합니다.

```dotenv
BETS_API_BASE_URL=https://api.b365api.com
BETS_API_TOKEN=your-token
```

실제 토큰이 들어 있는 `.env`는 Git에 포함하지 않습니다.

### 4. Upcoming 조회 대상 확인

[`config/betsapi_upcoming_targets.yaml`](config/betsapi_upcoming_targets.yaml)에
Upcoming API로 조회할 종목과 리그가 등록되어 있습니다.

```yaml
targets:
  - sport_id: "16"
    leagues:
      - league_id: "349"
        label: kbo
      - league_id: "225"
        label: mlb
```

`sport_id`는 [`config/betsapi_sports.yaml`](config/betsapi_sports.yaml)에 등록된
값이어야 합니다. `label`은 파일명에도 사용되므로 설정 전체에서 고유한 영문 소문자,
숫자, 하이픈 조합이어야 합니다.

### 5. 예정 경기 탐색

다음 명령은 설정에 등록된 모든 종목·리그를 UTC 기준 2026년 10월 16일로 조회합니다.
BETS API의 `day` 파라미터가 UTC 날짜이므로 한국에서 10월 17일 오전에 시작하는
경기가 UTC로는 10월 16일 경기일 수 있습니다.

```bash
uv run observer discover-upcoming --target-date 2026-10-16
```

생성된 Discovery JSON의 `events`에서 `event_id`, UTC·KST 예정 시각, 리그와 대진을
확인한 뒤 관찰할 경기를 선택합니다. 한 번의 Event View 요청에는 이벤트 ID를 최대
10개까지 전달할 수 있습니다. 아래 명령의 `BETS_EVENT_ID_1`, `BETS_EVENT_ID_2`는
실제로 확인한 값으로 교체합니다.

### 6. 첫 응답 수집

```bash
uv run observer collect --event-ids BETS_EVENT_ID_1
```

여러 이벤트를 한 번에 수집하려면 쉼표로 구분합니다.

```bash
uv run observer collect --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2
```

정상적으로 실행되면 HTTP 상태 코드와 다음 두 파일의 저장 위치가 출력됩니다.

```text
data/raw/event-view/YYYY-MM-DD/...
data/metadata/event-view/YYYY-MM-DD/...
```

### 7. 반복 수집 및 구조 변화 관찰

다음 예시는 두 경기를 한 요청으로 묶어 30초 간격으로 3회 수집합니다.

```bash
uv run observer watch \
  --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 \
  --interval 30 \
  --count 3
```

매 호출의 원문과 메타데이터는 Capture 단위로 한 번 저장합니다. 응답에서 고유하게 식별할 수 있는 각 이벤트에는 EventObservation을 만들고, 이벤트별 직전 응답이 있으면 구조를 비교합니다. 변화가 발견된 경우에는 `data/changes/event-view` 아래에 이벤트별 변화 기록도 저장됩니다.

호출 횟수를 제한하지 않고 직접 중단하려면 `--count`를 생략하고 `Ctrl+C`를 누릅니다.

```bash
uv run observer watch --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 --interval 30
```

### 8. 저장된 최근 응답 비교

같은 경기의 응답이 두 개 이상 저장된 후 다음 명령으로 최근 두 응답을 다시 비교할 수 있습니다.

```bash
uv run observer compare --event-id BETS_EVENT_ID_1
```

### 9. 저장된 자료의 Markdown 보고서 생성

```bash
uv run observer report
```

이 명령은 API를 호출하지 않고 현재 저장된 CaptureMetadata와 EventObservation을 모두
분석합니다. endpoint 전체 보고서와 등록된 각 종목의 보고서, 종목을 분류할 수 없는
Observation 보고서를 같은 UTC 생성 시각으로 저장합니다.

## 명령어

### `observer discover-upcoming`

설정된 종목·리그를 대상으로 Upcoming API를 한 번씩 호출하고, 원문·메타데이터와
통합 Discovery JSON을 저장합니다.

```bash
uv run observer discover-upcoming --target-date 2026-10-16
```

- `--target-date`: BETS API에 전달할 UTC 기준 날짜이며 `YYYY-MM-DD` 형식입니다.
- 조회 대상 하나의 실패가 다른 종목·리그의 호출을 막지 않습니다.
- 인증·결제·권한·호출 제한 오류(HTTP 401, 402, 403, 429)가 반환되면 불필요한
  후속 호출을 중단하고 조회하지 않은 대상을 실패 내역에 남깁니다.
- 전체 성공은 `completed`, 일부 실패나 응답 이슈는 `partial`, 모든 대상 실패는
  `failed`로 저장합니다.
- `partial`은 경고를 출력하지만 활용 가능한 결과를 보존하고 종료 코드 `0`으로
  끝납니다. `failed`는 Discovery를 저장한 뒤 종료 코드 `1`로 끝납니다.
- 설정 또는 날짜 입력 오류는 API를 호출하지 않고 종료 코드 `2`로 끝납니다.
- 페이징 호출은 수행하지 않습니다. 응답의 `pager.total`이 현재 `results` 개수보다
  크면 `pagination_required` 이슈와 `partial` 상태로 기록합니다.

### `observer collect`

Event View API를 한 번 호출하고 원문 응답과 호출 메타데이터를 저장합니다.

```bash
uv run observer collect --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2
```

- `--event-ids`, `-e`: 쉼표로 구분한 이벤트 ID입니다.
- 각 ID의 앞뒤 공백은 제거합니다.
- 중복 ID는 제거하고 문자열 기준으로 정렬합니다.
- 빈 ID가 포함되거나 고유 ID가 10개를 초과하면 API를 호출하지 않고 종료 코드 `2`로 끝납니다.

### `observer watch`

Event View API를 반복 호출하여 매 응답의 원문과 메타데이터를 저장합니다. 직전 수집이 있으면 현재 응답과 JSON 구조를 비교하고, 구조 변화가 발견된 경우에만 변화 기록을 추가로 저장합니다.

```bash
uv run observer watch \
  --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 \
  --interval 30 \
  --count 10
```

- `--event-ids`, `-e`: `collect`와 동일한 형식의 이벤트 ID 목록입니다.
- `--interval`, `-i`: 호출 간격(초). 기본값은 `30`이며 최소값은 `1`입니다.
- `--count`, `-c`: 호출 횟수. 생략하면 `Ctrl+C`로 중단할 때까지 계속 수집합니다.
- 각 이벤트의 첫 수집처럼 직전 EventObservation이 없으면 해당 이벤트의 구조 비교를 생략합니다.
- 구조 변화가 없으면 변화 기록 파일을 만들지 않습니다.
- 원문 또는 CaptureMetadata 저장에 실패하면 오류를 출력하고 다음 API 수집을 계속합니다.
- EventObservation 저장에 실패하면 오류를 출력하지만, 생성한 Observation으로 현재 호출의 비교는 계속 시도합니다.
- 변화 기록 저장에 실패해도 오류를 출력하고 다음 API 수집을 계속합니다.
- HTTP 오류 응답도 원문과 메타데이터는 저장하지만 구조 비교는 수행하지 않습니다.

### `observer compare`

저장된 EventObservation에서 같은 경기의 최근 응답 두 개를 찾아 이벤트 JSON 구조를 비교하고 결과를 출력합니다.

```bash
uv run observer compare --event-id BETS_EVENT_ID
```

`compare`는 조회 전용 명령입니다. 변화가 발견되더라도 변화 기록 파일을 만들지 않습니다.

### `observer report`

저장된 Event View 자료를 분석하여 Markdown 보고서를 생성합니다.

```bash
uv run observer report
```

- BETS API를 호출하거나 API 토큰을 읽지 않습니다.
- endpoint 보고서에는 파일 처리 현황, 응답 분석 상태·이슈, 종목별 표본과 분석 실패
  상세가 포함됩니다.
- 종목별 보고서에는 Observation·고유 이벤트 수와 필드별 자료형·제공 현황이
  포함됩니다.
- 관측값이 없는 등록 종목과 `unclassified` 보고서도 생성합니다.
- 일부 저장 파일을 읽거나 해석하지 못해도 나머지 자료를 분석하고, 실패 상세는
  endpoint 보고서에 남깁니다.
- 설정 로드, 렌더링 또는 보고서 저장에 실패하면 종료 코드 `1`로 끝납니다.

## 다중 이벤트 처리 원칙

- **Capture**는 Event View API 요청 한 번의 기록입니다. 요청 전체의 원문과 HTTP·분석 메타데이터를 한 번만 저장합니다.
- **EventObservation**은 Capture 원문 안에서 특정 이벤트를 찾기 위한 참조입니다. 이벤트 응답 본문을 복제하지 않고 CaptureMetadata 경로와 `results` 배열 인덱스만 저장합니다.
- `requested_event_ids`에는 정규화하여 실제 요청에 사용한 ID를 저장합니다.
- `returned_event_ids`에는 응답에서 확인한 ID를 응답 순서와 중복을 포함해 그대로 저장합니다.
- 요청하지 않은 이벤트가 고유한 ID와 함께 반환되면 이상 현상으로 기록하면서도 EventObservation을 만들고 분석에 포함합니다.
- ID가 없거나 같은 ID가 응답 안에서 중복되면 원문의 특정 이벤트를 안전하게 가리킬 수 없으므로 EventObservation을 만들지 않습니다.

응답 분석 중 발견할 수 있는 `response_issues` 코드는 다음과 같습니다.

| 코드 | 의미 |
|---|---|
| `missing_event_id` | `results` 원소에 이벤트 ID가 없습니다. |
| `missing_requested_event` | 요청한 이벤트가 응답에 없습니다. |
| `unexpected_event_id` | 요청하지 않은 이벤트가 응답에 있습니다. |
| `duplicate_event_id` | 같은 이벤트 ID가 응답에 두 번 이상 있습니다. |

응답이 JSON이 아니거나 Event View 응답의 기본 구조를 분석할 수 없으면 `response_analysis_status`를 각각 `invalid_json`, `invalid_response_shape`로 기록합니다. 이때 `returned_event_ids`, `response_issues`는 빈 목록이며 EventObservation도 만들지 않습니다.

## 저장 구조

모든 경로는 프로젝트 루트를 기준으로 합니다.

```text
data/
├── raw/event-view/YYYY-MM-DD/{capture_file}
├── raw/events-upcoming/{KST 호출 날짜}/{league_label}_{KST 시각}_KST_capture.json
├── metadata/event-view/YYYY-MM-DD/{capture_file}
├── metadata/events-upcoming/{KST 호출 날짜}/{raw와 같은 파일명}
├── observations/event-view/{event_id}/{capture_file}
├── changes/event-view/{event_id}/YYYY-MM-DD/{capture_file}
└── discoveries/events-upcoming/{UTC target_date}/{KST run_id}_discovery.json

reports/
└── event-view/YYYY-MM-DD/
    ├── {generated_at}_endpoint.md
    ├── {generated_at}_sport_{sport_code}.md
    └── {generated_at}_sport_unclassified.md
```

보고서 파일명에는 UTC 생성 시각이 `YYYYMMDDTHHMMSSffffffZ` 형식으로 들어갑니다.
같은 실행에서 생성한 모든 파일은 동일한 시각 접두사를 사용합니다. 기존 보고서와 같은
경로가 존재하면 덮어쓰지 않습니다.

### Upcoming 원문·메타데이터·Discovery

Upcoming 원문과 메타데이터는 사람이 호출 시점을 쉽게 찾을 수 있도록 KST 날짜
디렉터리와 KST 파일명을 사용합니다. 파일명에는 소수점 이하 초를 넣지 않으며 `:` 대신
`-`를 사용합니다.

```text
data/raw/events-upcoming/2026-10-17/mlb_2026-10-17T01-55-15_KST_capture.json
data/metadata/events-upcoming/2026-10-17/mlb_2026-10-17T01-55-15_KST_capture.json
```

JSON 안에서 수집 순서를 판별하는 `captured_at`, `started_at`, `completed_at`은 UTC로
저장합니다. 각 경기의 BETS Unix 시작 시각은 두 시간대로 변환합니다.

```json
{
  "event_id": "12345678",
  "sport_id": "16",
  "sport_code": "baseball",
  "time_status": "0",
  "scheduled_at_utc": "2026-10-16T23:00:00Z",
  "scheduled_at_kst": "2026-10-17T08:00:00+09:00",
  "league": {"id": "225", "name": "MLB", "country_code": "us"},
  "home": {"id": "1", "name": "Home Team"},
  "away": {"id": "2", "name": "Away Team"},
  "source_capture_metadata_file_path": "data/metadata/events-upcoming/...",
  "result_index": 0
}
```

Discovery의 `target_date`는 KST 경기 날짜가 아니라 API에 전달한 UTC 날짜입니다.
`events`는 이벤트 ID로 중복을 제거한 뒤 `scheduled_at_utc`, `event_id` 순으로
정렬합니다. 각 항목은 원문을 복제하지 않고 CaptureMetadata 경로와 0부터 시작하는
`result_index`로 출처를 가리킵니다.

Upcoming CaptureMetadata의 `returned_event_ids`는 응답 순서와 중복을 보존합니다.
다음 이슈는 계산 가능한 범위에서 메타데이터에 함께 기록합니다.

| 코드 | 의미 |
|---|---|
| `invalid_event_shape` | `results` 원소가 JSON 객체가 아닙니다. |
| `missing_event_id` | 이벤트 ID가 없거나 문자열이 아닙니다. |
| `duplicate_event_id` | 같은 이벤트 ID가 한 응답에 중복되어 있습니다. |
| `unexpected_sport_id` | 요청한 종목과 반환 이벤트의 종목이 다릅니다. |
| `unexpected_league_id` | 요청한 리그와 반환 이벤트의 리그가 다릅니다. |
| `invalid_scheduled_time` | Unix 시작 시각을 안전하게 변환할 수 없습니다. |
| `pagination_required` | 현재 응답에 전체 결과가 모두 포함되지 않았습니다. |

중복 ID, 예상 밖 종목·리그, 유효하지 않은 시작 시각의 이벤트는 원문과 이슈에는
남기지만 통합 Discovery의 `events`에서는 제외합니다.

### 원문 응답

```text
data/raw/event-view/{captured_at의 UTC 날짜}/{captured_at}_capture.json
```

예시:

```text
data/raw/event-view/2026-09-15/20260915T003206645274Z_capture.json
```

API에서 받은 응답 바이트를 변형하지 않고 그대로 저장합니다. 요청한 이벤트 ID나 실제 반환된 이벤트 ID는 파일명이 아니라 CaptureMetadata에서 확인합니다.

### 호출 메타데이터

```text
data/metadata/event-view/{captured_at의 UTC 날짜}/{원문과 같은 파일명}
```

예시:

```json
{
  "schema_version": 1,
  "response_analysis_status": "completed",
  "captured_at": "2026-09-15T00:32:06.645274Z",
  "provider": "betsapi",
  "endpoint": "/v1/event/view",
  "http_method": "GET",
  "requested_event_ids": ["12322442", "12322443"],
  "returned_event_ids": ["12322442", "12322499"],
  "response_issues": [
    {
      "code": "missing_requested_event",
      "event_id": "12322443",
      "result_indices": []
    },
    {
      "code": "unexpected_event_id",
      "event_id": "12322499",
      "result_indices": [1]
    }
  ],
  "http_status_code": 200,
  "elapsed_ms": 182.47,
  "response_size_bytes": 15324,
  "content_type": "application/json",
  "raw_file_path": "data/raw/event-view/2026-09-15/20260915T003206645274Z_capture.json"
}
```

### EventObservation

```text
data/observations/event-view/{event_id}/{CaptureMetadata와 같은 파일명}
```

예시:

```json
{
  "event_id": "12322442",
  "capture_metadata_file_path": "data/metadata/event-view/2026-09-15/20260915T003206645274Z_capture.json",
  "result_index": 0
}
```

`result_index`는 Capture 원문의 `results` 배열에서 해당 이벤트가 위치한 0부터 시작하는 인덱스입니다. 구조 비교 시 EventObservation을 통해 CaptureMetadata와 원문을 따라가 해당 이벤트 객체만 추출합니다.

### 구조 변화 기록

```text
data/changes/event-view/{event_id}/{current_captured_at의 UTC 날짜}/{현재 원문과 같은 파일명}
```

예시:

```json
{
  "detected_at": "2026-09-15T00:32:17.100000Z",
  "event_id": "12322442",
  "previous_captured_at": "2026-09-15T00:32:06.645274Z",
  "current_captured_at": "2026-09-15T00:32:17.088806Z",
  "previous_raw_file_path": "data/raw/event-view/2026-09-15/20260915T003206645274Z_capture.json",
  "current_raw_file_path": "data/raw/event-view/2026-09-15/20260915T003217088806Z_capture.json",
  "added_paths": ["$.scores"],
  "removed_paths": ["$.status"],
  "type_changes": [
    {
      "path": "$.time",
      "previous_types": ["string"],
      "current_types": ["integer"]
    }
  ]
}
```

변화 기록은 이벤트별 디렉터리 아래에서 현재 원문과 같은 파일명을 사용합니다. 따라서 하나의 Capture에 포함된 여러 이벤트가 동시에 변해도 서로 다른 경로에 저장됩니다. 같은 경로의 변화 기록이 이미 존재하면 기존 파일을 덮어쓰지 않습니다.

## 구조 비교 기준

구조 비교는 Capture 전체가 아니라 EventObservation이 가리키는 이벤트 객체 두 개를 대상으로 합니다. 비교 대상 이벤트 객체의 루트는 `$`, 객체의 키는 `.key`, 배열의 원소는 `[]`로 표현합니다. 예를 들어 이벤트 객체의 `scores` 필드는 `$.scores`입니다.

다음 항목을 구조 변화로 판단합니다.

- 이전 응답에는 없고 현재 응답에 새로 나타난 경로
- 이전 응답에는 있었지만 현재 응답에서 보이지 않는 경로
- 두 응답에 모두 존재하지만 자료형 집합이 달라진 경로

자료형은 `null`, `boolean`, `object`, `array`, `string`, `integer`, `number` 등으로 기록합니다. 하나의 배열에 서로 다른 자료형의 원소가 있으면 같은 경로에 여러 자료형이 함께 기록될 수 있습니다.

다음 항목은 비교하지 않습니다.

- 같은 경로에 있는 실제 값의 변화
- 객체 키나 배열 원소의 순서
- 배열 원소 개수 자체의 변화

경로와 자료형 목록은 변화 기록 결과가 실행마다 일정하도록 정렬하여 저장합니다.

## 시각의 의미와 시간대 정책

- `captured_at`: API 응답을 받은 뒤 원문을 수집한 시각
- `previous_captured_at`: 비교 대상인 직전 응답의 수집 시각
- `current_captured_at`: 비교 기준인 현재 응답의 수집 시각
- `detected_at`: 두 응답의 구조 비교를 완료하고 변화를 기록한 시각

시각은 UTC 기준의 시간대 정보가 포함된 값으로 저장합니다. 파일명의 마지막 `Z`도 UTC를 뜻합니다.

UTC를 기준으로 사용하면 실행 환경의 지역 설정과 무관하게 수집 순서를 비교할 수 있고, 동일한 순간을 하나의 값으로 표현할 수 있습니다. 한국 사용자에게 보여줄 때는 저장된 UTC 시각을 KST(`Asia/Seoul`, UTC+9)로 변환하여 표시하는 방식을 권장합니다.

구조 변화 파일의 날짜와 파일명은 `detected_at`이 아니라 `current_captured_at`을 기준으로 합니다. 나중에 같은 현재 응답을 다시 비교하더라도 동일한 저장 경로를 가리키게 하기 위해서입니다.
