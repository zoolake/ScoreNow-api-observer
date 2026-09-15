# ScoreNow API Observer

문서가 충분하지 않은 외부 스포츠 API의 응답을 반복 수집하고, 경기·리그·수집 시점에 따라 JSON 응답 구조가 어떻게 달라지는지 관찰하기 위한 Python CLI 프로젝트입니다.

현재는 BETS API의 Event View 엔드포인트를 대상으로 합니다. API 토큰은 호출에만 사용하며 원문, 메타데이터, 변화 기록 파일에는 저장하지 않습니다.

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

### 4. 관찰할 `event_id` 확인

이 프로젝트는 아직 Upcoming API 호출 기능을 제공하지 않습니다. 먼저 BETS API의 Upcoming API를 별도로 호출하여 예정 경기 목록을 받은 뒤, 관찰하려는 경기의 `event_id`를 확인해야 합니다.

ScoreNow 개발 환경에서는 ScoreNow DB에 저장된 경기의 BETS `event_id`를 사용할 수도 있습니다. 외부 사용자는 BETS API 응답에서 직접 확인해야 합니다.

아래 명령의 `BETS_EVENT_ID`는 실제로 확인한 값으로 교체합니다.

### 5. 첫 응답 수집

```bash
uv run observer collect --event-id BETS_EVENT_ID
```

정상적으로 실행되면 HTTP 상태 코드와 다음 두 파일의 저장 위치가 출력됩니다.

```text
data/raw/event-view/YYYY-MM-DD/...
data/metadata/event-view/YYYY-MM-DD/...
```

### 6. 반복 수집 및 구조 변화 관찰

다음 예시는 같은 경기를 30초 간격으로 3회 수집합니다.

```bash
uv run observer watch \
  --event-id BETS_EVENT_ID \
  --interval 30 \
  --count 3
```

직전 응답이 있으면 매 수집 후 구조를 비교합니다. 변화가 발견된 경우에는 `data/changes/event-view` 아래에 변화 기록도 저장됩니다.

호출 횟수를 제한하지 않고 직접 중단하려면 `--count`를 생략하고 `Ctrl+C`를 누릅니다.

```bash
uv run observer watch --event-id BETS_EVENT_ID --interval 30
```

### 7. 저장된 최근 응답 비교

같은 경기의 응답이 두 개 이상 저장된 후 다음 명령으로 최근 두 응답을 다시 비교할 수 있습니다.

```bash
uv run observer compare --event-id BETS_EVENT_ID
```

## 명령어

### `observer collect`

Event View API를 한 번 호출하고 원문 응답과 호출 메타데이터를 저장합니다.

```bash
uv run observer collect --event-id BETS_EVENT_ID
```

### `observer watch`

Event View API를 반복 호출하여 매 응답의 원문과 메타데이터를 저장합니다. 직전 수집이 있으면 현재 응답과 JSON 구조를 비교하고, 구조 변화가 발견된 경우에만 변화 기록을 추가로 저장합니다.

```bash
uv run observer watch \
  --event-id BETS_EVENT_ID \
  --interval 30 \
  --count 10
```

- `--interval`, `-i`: 호출 간격(초). 기본값은 `30`이며 최소값은 `1`입니다.
- `--count`, `-c`: 호출 횟수. 생략하면 `Ctrl+C`로 중단할 때까지 계속 수집합니다.
- 첫 수집처럼 직전 응답이 없으면 구조 비교를 생략합니다.
- 구조 변화가 없으면 변화 기록 파일을 만들지 않습니다.
- 변화 기록 저장에 실패해도 오류를 출력하고 다음 API 수집을 계속합니다.
- HTTP 오류 응답도 원문과 메타데이터는 저장하지만 구조 비교는 수행하지 않습니다.

### `observer compare`

저장된 메타데이터에서 같은 경기의 최근 응답 두 개를 찾아 JSON 구조를 비교하고 결과를 출력합니다.

```bash
uv run observer compare --event-id BETS_EVENT_ID
```

`compare`는 조회 전용 명령입니다. 변화가 발견되더라도 변화 기록 파일을 만들지 않습니다.

## 저장 구조

모든 경로는 프로젝트 루트를 기준으로 합니다.

```text
data/
├── raw/event-view/YYYY-MM-DD/
├── metadata/event-view/YYYY-MM-DD/
└── changes/event-view/YYYY-MM-DD/
```

### 원문 응답

```text
data/raw/event-view/{captured_at의 UTC 날짜}/{captured_at}_event-{event_id}.json
```

예시:

```text
data/raw/event-view/2026-09-15/20260915T003206645274Z_event-12322442.json
```

API에서 받은 응답 바이트를 그대로 저장합니다.

### 호출 메타데이터

```text
data/metadata/event-view/{captured_at의 UTC 날짜}/{원문과 같은 파일명}
```

예시:

```json
{
  "captured_at": "2026-09-15T00:32:06.645274Z",
  "provider": "betsapi",
  "endpoint": "/v1/event/view",
  "http_method": "GET",
  "event_ids": ["12322442"],
  "http_status_code": 200,
  "elapsed_ms": 182.47,
  "response_size_bytes": 15324,
  "content_type": "application/json",
  "raw_file_path": "data/raw/event-view/2026-09-15/20260915T003206645274Z_event-12322442.json"
}
```

### 구조 변화 기록

```text
data/changes/event-view/{current_captured_at의 UTC 날짜}/{현재 원문과 같은 파일명}
```

예시:

```json
{
  "detected_at": "2026-09-15T00:32:17.100000Z",
  "event_id": "12322442",
  "previous_captured_at": "2026-09-15T00:32:06.645274Z",
  "current_captured_at": "2026-09-15T00:32:17.088806Z",
  "previous_raw_file_path": "data/raw/event-view/2026-09-15/20260915T003206645274Z_event-12322442.json",
  "current_raw_file_path": "data/raw/event-view/2026-09-15/20260915T003217088806Z_event-12322442.json",
  "added_paths": ["$.results[].scores"],
  "removed_paths": ["$.results[].status"],
  "type_changes": [
    {
      "path": "$.results[].time",
      "previous_types": ["string"],
      "current_types": ["integer"]
    }
  ]
}
```

변화 기록은 현재 원문 파일과 일대일로 연결할 수 있도록 현재 원문과 같은 파일명을 사용합니다. 같은 경로의 변화 기록이 이미 존재하면 기존 파일을 덮어쓰지 않습니다.

## 구조 비교 기준

JSON 루트는 `$`, 객체의 키는 `.key`, 배열의 원소는 `[]`로 표현합니다. 예를 들어 `results` 배열 원소의 `scores` 필드는 `$.results[].scores`입니다.

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
