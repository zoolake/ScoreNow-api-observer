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
숫자, 하이픈 조합이어야 합니다. 종목별 Discovery 디렉터리에 사용하는 `sport_code`도
설정 전체에서 고유한 같은 형식이어야 합니다.

### 5. 예정 경기 탐색

다음 명령은 설정에 등록된 모든 종목·리그를 UTC 기준 2026년 10월 16일로 조회합니다.
BETS API의 `day` 파라미터가 UTC 날짜이므로 한국에서 10월 17일 오전에 시작하는
경기가 UTC로는 10월 16일 경기일 수 있습니다.

```bash
uv run observer discover-upcoming --target-date 2026-10-16
```

생성된 리그별 Discovery JSON의 `events`에서 `event_id`, UTC·KST 예정 시각, 리그와
대진을 확인한 뒤 관찰할 경기를 선택합니다. 한 번의 Event View 요청에는 이벤트 ID를
최대 10개까지 전달할 수 있습니다. 아래 명령의 `BETS_EVENT_ID_1`,
`BETS_EVENT_ID_2`는 실제로 확인한 값으로 교체합니다.

### 6. 곧 시작하는 경기 후보 확인

저장된 리그별 Discovery 중 최신 사용 가능 결과를 기준으로 현재부터 10분 이내
시작하는 경기를 확인합니다. 이 명령은 API를 호출하지 않습니다.

```bash
uv run observer upcoming-candidates --within-minutes 10
```

특정 종목이나 리그만 확인할 수도 있습니다.

```bash
uv run observer upcoming-candidates \
  --within-minutes 10 \
  --sport-code baseball \
  --league-labels kbo,mlb
```

### 7. 곧 시작하는 경기 자동 반복 수집

저장된 Discovery에서 현재부터 10분 이내 시작하는 경기를 자동으로 선택해 Event View
API를 반복 수집합니다. 후보가 10개를 초과하면 최대 10개씩 여러 요청으로 나눕니다.

```bash
uv run observer watch-upcoming \
  --within-minutes 10 \
  --sport-code baseball \
  --league-labels kbo,mlb \
  --interval 30 \
  --max-cycles 3
```

`--max-cycles`는 개별 API 호출 횟수가 아니라 선택한 후보 전체를 수집하는 최대 주기
횟수입니다. 후보가 11개라면 최초 한 주기에 Event View API를 2회 호출합니다. 종료
감지 후 15분 추가 수집을 마친 이벤트는 다음 주기부터 제외하므로 이후 배치 수와 실제
호출 횟수는 줄어들 수 있습니다. 이 명령은 Upcoming API를 다시 호출하지 않습니다.

### 8. 첫 응답 수집

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

### 9. 반복 수집 및 구조 변화 관찰

다음 예시는 두 경기를 한 요청으로 묶어 30초 간격으로 3회 수집합니다.

```bash
uv run observer watch \
  --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 \
  --interval 30 \
  --max-cycles 3
```

매 호출의 원문과 메타데이터는 Capture 단위로 한 번 저장합니다. 응답에서 고유하게 식별할 수 있는 각 이벤트에는 EventObservation을 만들고, 이벤트별 직전 응답이 있으면 구조를 비교합니다. 변화가 발견된 경우에는 `data/changes/event-view` 아래에 이벤트별 변화 기록도 저장됩니다.

최대 주기를 제한하지 않으려면 `--max-cycles`를 생략합니다. 모든 이벤트가 종료 감지 후
15분 추가 수집을 마치면 자동 종료하며, 그전에도 `Ctrl+C`로 중단할 수 있습니다.

```bash
uv run observer watch --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 --interval 30
```

### 10. 저장된 최근 응답 비교

같은 경기의 응답이 두 개 이상 저장된 후 다음 명령으로 최근 두 응답을 다시 비교할 수 있습니다.

```bash
uv run observer compare --event-id BETS_EVENT_ID_1
```

### 11. 저장된 자료의 Markdown 보고서 생성

```bash
uv run observer report
```

이 명령은 API를 호출하지 않고 현재 저장된 CaptureMetadata와 EventObservation을 모두
분석합니다. endpoint 전체 보고서와 등록된 각 종목의 보고서, 종목을 분류할 수 없는
Observation 보고서를 같은 UTC 생성 시각으로 저장합니다. 종목 보고서에는 리그별 필드
제공 비교가 포함되고, 표본이 있는 각 리그에는 별도의 상세 보고서를 생성합니다.

## 명령어

### `observer discover-upcoming`

설정에서 선택한 종목·리그를 대상으로 Upcoming API를 한 번씩 호출하고,
원문·메타데이터, 리그별 Discovery와 실행 Run JSON을 저장합니다.

```bash
uv run observer discover-upcoming --target-date 2026-10-16
```

- `--target-date`: BETS API에 전달할 UTC 기준 날짜이며 `YYYY-MM-DD` 형식입니다.
- `--league-labels`: 설정 파일의 리그 label을 쉼표로 구분해 일부 리그만 조회합니다.
  생략하면 설정된 전체 리그를 조회합니다. 중복 label은 한 번만 선택합니다.
- 다음 예시는 같은 날짜에서 KBO와 MLB만 다시 조회합니다.

  ```bash
  uv run observer discover-upcoming \
    --target-date 2026-10-16 \
    --league-labels kbo,mlb
  ```

- 조회 대상 하나의 실패가 다른 종목·리그의 호출을 막지 않습니다.
- 인증·결제·권한·호출 제한 오류(HTTP 401, 402, 403, 429)가 반환되면 불필요한
  후속 호출을 중단하고 조회하지 않은 대상을 실패 내역에 남깁니다.
- 전체 성공은 `completed`, 일부 실패나 응답 이슈는 `partial`, 모든 대상 실패는
  `failed`로 저장합니다.
- `partial`은 경고를 출력하지만 활용 가능한 결과를 보존하고 종료 코드 `0`으로
  끝납니다. `failed`는 리그별 Discovery와 Run을 저장한 뒤 종료 코드 `1`로
  끝납니다.
- 설정 또는 날짜 입력 오류는 API를 호출하지 않고 종료 코드 `2`로 끝납니다.
- 페이징 호출은 수행하지 않습니다. 응답의 `pager.total`이 현재 `results` 개수보다
  크면 `pagination_required` 이슈와 `partial` 상태로 기록합니다.

### `observer upcoming-candidates`

저장된 리그별 Discovery를 읽어 현재부터 지정한 시간 안에 시작하는 경기 후보를
출력합니다. BETS API나 API 토큰을 사용하지 않으며 파일도 새로 저장하지 않습니다.

```bash
uv run observer upcoming-candidates --within-minutes 10
```

- `--within-minutes`: 현재부터 후보로 포함할 분 단위 범위입니다. 기본값은 `10`이며
  최소값은 `1`입니다. 현재 시각과 정확히 범위의 마지막 시각도 포함합니다.
- `--sport-code`: 특정 내부 종목 코드만 조회합니다. 생략하면 전체 종목을 대상으로
  합니다.
- `--league-labels`: 리그 label을 쉼표로 구분해 필터링합니다. 생략하면 전체 리그를
  대상으로 합니다.
- Discovery는 `(target_date, sport_id, league_id)`별로 구분합니다. 각 그룹의 최신
  `completed` 또는 `partial` 결과를 사용합니다.
- 가장 최신 시도가 `failed`이면 이전의 최신 사용 가능 결과를 사용하고 경고합니다.
  최신 사용 가능 결과가 `partial`인 경우도 경고합니다.
- 읽지 못한 파일이나 사용 가능한 결과가 없는 리그가 있어도 다른 리그의 후보 조회는
  계속합니다.
- 같은 이벤트 ID가 여러 Discovery에 있으면 가장 최근에 완료된 Discovery의 값을
  사용해 한 번만 출력하고 중복 사실을 알립니다.
- 후보마다 이벤트 ID, 종목·리그, 대진, UTC·KST 시작 시각, 남은 시간, 사용한
  Discovery 상태·완료 시각·파일 경로를 출력합니다.
- 사용 가능한 Discovery는 있지만 범위 안의 경기가 없으면 후보 `0개`와 종료 코드
  `0`을 반환합니다. 사용할 수 있는 Discovery가 전혀 없으면 종료 코드 `1`, 잘못된
  필터나 시간 범위는 종료 코드 `2`입니다.

### `observer watch-upcoming`

`upcoming-candidates`와 동일한 기준으로 저장된 Discovery에서 곧 시작할 경기를 선택한
뒤 Event View API를 반복 호출합니다. Upcoming API는 호출하지 않습니다.

```bash
uv run observer watch-upcoming \
  --within-minutes 10 \
  --sport-code baseball \
  --league-labels kbo,mlb \
  --interval 30 \
  --max-cycles 10
```

- `--within-minutes`: 현재부터 수집 대상으로 포함할 분 단위 범위입니다. 기본값은
  `10`이며 최소값은 `1`입니다.
- `--sport-code`, `--league-labels`: `upcoming-candidates`와 동일한 선택 필터입니다.
- `--interval`, `-i`: 후보 전체를 한 번 수집한 뒤 다음 수집 주기까지 기다릴
  시간입니다. 기본값은 `30`초이며 최소값은 `1`초입니다.
- `--max-cycles`, `-c`: 후보 전체를 반복 수집할 최대 주기 횟수입니다. 생략하면 모든
  이벤트가 종료 후 추가 수집을 마치거나 `Ctrl+C`로 중단할 때까지 계속 수집합니다.
- 후보는 명령 시작 시 한 번 확정합니다. 실행 중 새 Discovery가 저장되거나 예정
  경기가 추가되어도 현재 실행의 수집 대상은 바뀌지 않습니다.
- 활성 후보 순서를 유지하면서 최대 10개씩 Event View 요청 배치로 나눕니다. 종료
  감지 후 15분 추가 수집을 마친 이벤트를 제외하고 매 주기 배치를 다시 구성합니다.
  예를 들어 활성 후보 23개에는 한 주기에 3번의 API 호출이 발생합니다.
- 배치 사이에는 기다리지 않고, 한 수집 주기의 모든 배치 처리가 끝난 뒤에만
  `--interval`만큼 기다립니다.
- 개별 배치의 연결·저장 실패는 출력하고 나머지 배치와 다음 수집 주기를 계속합니다.
  성공한 Capture는 일반 `watch`와 같은 원문·메타데이터·Observation·구조 변화
  기록으로 저장합니다.
- 사용 가능한 Discovery는 있지만 후보가 없으면 API 설정을 읽거나 API를 호출하지
  않고 종료 코드 `0`으로 끝납니다. 사용할 수 있는 Discovery가 전혀 없으면 종료
  코드 `1`, 잘못된 필터나 API 설정은 종료 코드 `2`입니다.
- 이벤트별로 `time_status=3`을 최초 관측한 시각을 기록하고 이후 15분 동안 추가
  수집합니다. 그사이 다른 숫자 상태가 관측되면 종료 감지를 취소하며, 이벤트 누락이나
  해석할 수 없는 상태는 기존 종료 감지를 변경하지 않습니다.
- 모든 이벤트의 추가 수집이 끝나면 `--max-cycles`보다 일찍 자동 종료합니다.

### `observer collect`

지정한 이벤트를 Event View API로 한 수집 주기 호출하고 원문 응답과 호출 메타데이터를
저장합니다.

```bash
uv run observer collect --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2
```

- `--event-ids`, `-e`: 쉼표로 구분한 이벤트 ID입니다.
- 각 ID의 앞뒤 공백은 제거합니다.
- 중복 ID는 제거하고 문자열 기준으로 정렬합니다.
- 빈 ID가 포함되면 API를 호출하지 않고 종료 코드 `2`로 끝납니다.
- 고유 ID가 10개를 초과하면 최대 10개씩 나눠 각 배치를 한 번 호출합니다. 일부 배치가
  실패해도 남은 배치를 계속 처리한 뒤 종료 코드 `1`로 끝납니다.

### `observer collect-odds`

지정한 이벤트마다 Event Odds API를 한 번 호출하여 승무패·아시안 핸디캡·언더/오버
누적 배당률을 수집합니다.

```bash
uv run observer collect-odds --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2
```

- `--event-ids`, `-e`: 쉼표로 구분한 이벤트 ID입니다. 공백과 중복을 제거한 뒤
  문자열 기준으로 정렬합니다.
- Event Odds API는 한 요청에 이벤트 하나만 받으므로 이벤트 ID마다 독립적으로
  `odds_market=1,2,3`을 호출합니다.
- HTTP 오류, JSON·응답 구조 오류가 발생하면 기존 Snapshot을 바꾸지 않습니다.
- 유효한 응답은 같은 UTC 날짜·이벤트 ID의 원문과 SnapshotMetadata를 최신 값으로
  교체합니다. 원문 응답 바이트는 변형하지 않습니다.
- 이벤트 하나가 실패해도 나머지 이벤트 수집을 계속하며, 실패 이벤트와 원인을 CLI에
  출력합니다. 실패 실행 이력은 별도 파일로 저장하지 않습니다.
- 전체 성공은 `completed`, 일부 성공은 `partial`, 전체 실패는 `failed`입니다.
  `partial`은 경고와 종료 코드 `0`, `failed`는 종료 코드 `1`을 반환합니다.
- 잘못된 이벤트 ID 입력이나 API 설정 오류는 API를 호출하지 않고 종료 코드 `2`로
  끝납니다.

### `observer watch`

Event View API를 반복 호출하여 매 응답의 원문과 메타데이터를 저장합니다. 직전 수집이 있으면 현재 응답과 JSON 구조를 비교하고, 구조 변화가 발견된 경우에만 변화 기록을 추가로 저장합니다.

```bash
uv run observer watch \
  --event-ids BETS_EVENT_ID_1,BETS_EVENT_ID_2 \
  --interval 30 \
  --max-cycles 10
```

- `--event-ids`, `-e`: `collect`와 동일한 형식의 이벤트 ID 목록입니다. 10개를
  초과하면 활성 이벤트를 최대 10개씩 나눠 호출합니다.
- `--interval`, `-i`: 전체 활성 이벤트를 한 번 수집한 뒤 다음 수집 주기까지 기다릴
  시간입니다. 기본값은 `30`초이며 최소값은 `1`초입니다.
- `--max-cycles`, `-c`: 최대 수집 주기 횟수입니다. 개별 API 호출 횟수가 아닙니다.
  생략하면 모든 이벤트가 완료되거나 `Ctrl+C`로 중단할 때까지 계속 수집합니다.
- 이벤트별로 `time_status=3`을 감지한 후 15분 동안 추가 수집합니다. 완료된 이벤트는
  다음 주기부터 제외하고 남은 활성 이벤트로 요청 배치를 다시 구성합니다.
- 추가 수집 중 다른 숫자 상태가 관측되면 종료 감지를 취소하고, 이후 다시 `3`을
  관측한 시각부터 15분을 새로 계산합니다.
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

종목 보고서에서 값을 집계할 단일 값 필드는
[`config/event_view_tracked_fields.yaml`](config/event_view_tracked_fields.yaml)에
종목별 JSON 객체 경로로 등록합니다.

```yaml
sports:
  football:
    - $.timer.md
    - $.time_status
  baseball:
    - $.time_status
```

- BETS API를 호출하거나 API 토큰을 읽지 않습니다.
- endpoint 보고서에는 파일 처리 현황, 응답 분석 상태·이슈, 종목별 표본과 분석 실패
  상세가 포함됩니다.
- 종목별 보고서에는 Observation·고유 이벤트 수, 필드별 자료형·제공 현황과 설정된
  필드의 값별 Observation·고유 이벤트 수가 포함됩니다. 또한 `league.id`를 기준으로
  모든 관측 필드의 리그별 항상·일부·미제공 상태를 비교합니다.
- 리그 ID와 표시 순서는
  [`config/betsapi_upcoming_targets.yaml`](config/betsapi_upcoming_targets.yaml)의
  설정을 사용합니다. 유효한 미등록 리그도 분석하며, ID를 분류할 수 없는
  Observation은 종목별 `unclassified` 리그로 집계합니다.
- 표본이 있는 리그에는 해당 리그 범위의 필드 제공 현황과 추적 필드 값 현황을 담은
  상세 보고서를 생성합니다. 설정에는 있지만 표본이 없는 리그는 종목 보고서에 별도
  목록으로 표시하고 상세 보고서는 만들지 않습니다.
- 값 집계는 문자열·정수·실수·boolean·`null`·필드 누락을 서로 다른 상태로
  구분합니다. 객체와 배열은 하나의 값으로 집계하지 않고 제외 현황을 표시합니다.
- 관측값이 없는 등록 종목과 `unclassified` 보고서도 생성합니다.
- 일부 저장 파일을 읽거나 해석하지 못해도 나머지 자료를 분석하고, 실패 상세는
  endpoint 보고서에 남깁니다.
- 설정 로드, 렌더링 또는 보고서 저장에 실패하면 종료 코드 `1`로 끝납니다.

보고서는 다음 경로에 저장합니다.

```text
reports/event-view/{UTC 생성 날짜}/
├── {generated_at}_endpoint.md
├── {generated_at}_sport_{sport_code}.md
└── league/{sport_code}/
    ├── {generated_at}_{league_id}-{league_label}.md
    └── {generated_at}_unclassified.md
```

### `observer inspect-field`

저장된 EventObservation과 원문을 사용하여 특정 JSON 필드의 값 변화를 이벤트별로
분석하고 Markdown 보고서를 생성합니다. BETS API는 호출하지 않습니다.

```bash
uv run observer inspect-field \
  --sport-code baseball \
  --path '$.scores.10'
```

특정 이벤트만 분석하려면 `--event-id`를 추가합니다.

```bash
uv run observer inspect-field \
  --sport-code baseball \
  --event-id BETS_EVENT_ID \
  --path '$.scores.10.home'
```

- `--sport-code`: `config/betsapi_sports.yaml`에 등록된 내부 종목 코드입니다.
- `--path`: `$`, `$.field`, `$.field.child` 형식의 객체 경로입니다.
- `--event-id`, `-e`: 생략하면 해당 종목의 저장된 전체 이벤트에서 요청 경로가 한 번
  이상 관측된 이벤트를 분석합니다. 경로가 끝까지 나타나지 않은 이벤트는 본문에서
  생략하고 개수만 분석 개요에 표시합니다.
- 단일 값 경로는 최초 상태, 값 변경, 등장, 사라짐을 시간순으로 기록합니다.
- 중첩 객체 경로는 모든 Observation에서 관측한 하위 단일 값 경로를 재귀적으로
  펼쳐 각각의 타임라인을 생성하고, 객체 자체의 등장·사라짐도 보여줍니다.
- 필드가 나중에 등장한 이벤트는 등장 전 `필드 없음` 상태부터 보여주지만, 모든
  Observation에서 필드가 없었던 이벤트에는 별도의 타임라인을 만들지 않습니다.
- 값이 `null`인 상태와 필드가 존재하지 않는 상태를 구분합니다.
- 배열 경로는 지원하지 않습니다. 분석 중 배열 값이 발견된 Observation은 제외
  내역에 남기고 나머지 자료를 계속 분석합니다.
- 원문 또는 Observation 일부를 읽지 못해도 실패 상세를 보고서에 남기고 나머지
  자료를 계속 분석합니다.
- 잘못된 경로·종목·이벤트 입력은 종료 코드 `2`, 분석 대상 없음 또는 보고서 생성
  실패는 종료 코드 `1`로 끝납니다.

### `observer inspect-timeline`

저장된 EventObservation과 원문을 사용하여 이벤트 하나의 주요 필드를 같은 시간축에서
비교하는 Markdown 보고서를 생성합니다. BETS API는 호출하지 않습니다.

```bash
uv run observer inspect-timeline --event-id BETS_EVENT_ID
```

타임라인에 표시할 필드는
[`config/event_view_timeline_fields.yaml`](config/event_view_timeline_fields.yaml)에
종목별로 등록합니다. 필드의 표시 순서도 설정 순서를 따릅니다.

- 이벤트 ID에 해당하는 저장 Observation에서 종목을 자동으로 추론합니다. 일부
  Observation의 종목을 분류할 수 없어도, 분류된 나머지 표본이 한 종목으로 일치하면
  함께 분석합니다. 서로 다른 종목이 관측되거나 모두 분류할 수 없으면 실패합니다.
- 모든 Observation을 시간순으로 표시합니다. 최초 유효 시점은 전체 상태를, 이후
  시점은 `변화 없음` 또는 직전 유효 시점과의 차이를 보여줍니다.
- 🟠은 필드 변화, 🔴은 해당 Observation의 분석 실패를 뜻합니다.
- 중첩 객체 설정은 하위 단일 값 경로로 재귀적으로 펼칩니다. `null`, 필드 누락,
  값의 자료형 변화를 서로 다른 상태로 비교합니다.
- 배열은 지원하지 않습니다. 설정 경로나 그 하위에서 배열이 발견된 Observation은
  실패 행으로 남기고, 다음 Observation은 마지막 유효 상태와 비교합니다.
- 결과는
  `reports/event-view/{UTC 날짜}/timeline/{sport_code}/{generated_at}_{event_id}.md`에
  저장합니다.
- 잘못된 이벤트 ID나 설정은 종료 코드 `2`, 분석 대상 없음·종목 추론 실패·보고서
  생성 실패는 종료 코드 `1`로 끝납니다.

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
├── raw/event-odds/{UTC 수집 날짜}/{event_id}.json
├── raw/events-upcoming/{KST 호출 날짜}/{league_label}_{KST 시각}_KST_capture.json
├── metadata/event-view/YYYY-MM-DD/{capture_file}
├── metadata/event-odds/{UTC 수집 날짜}/{event_id}.json
├── metadata/events-upcoming/{KST 호출 날짜}/{raw와 같은 파일명}
├── observations/event-view/{event_id}/{capture_file}
├── changes/event-view/{event_id}/YYYY-MM-DD/{capture_file}
└── discoveries/events-upcoming/{UTC target_date}/
    ├── runs/{KST run_id}_run.json
    └── leagues/{sport_code}/{league_id}-{league_label}/
        └── {KST run id}_discovery.json

reports/
└── event-view/YYYY-MM-DD/
    ├── {generated_at}_endpoint.md
    ├── {generated_at}_sport_{sport_code}.md
    ├── {generated_at}_sport_unclassified.md
    ├── field/{sport_code}/{generated_at}_{field_path}.md
    └── timeline/{sport_code}/{generated_at}_{event_id}.md
```

보고서 파일명에는 UTC 생성 시각이 `YYYYMMDDTHHMMSSffffffZ` 형식으로 들어갑니다.
같은 실행에서 생성한 모든 파일은 동일한 시각 접두사를 사용합니다. 기존 보고서와 같은
경로가 존재하면 덮어쓰지 않습니다.

### Event Odds Snapshot

Event Odds 응답은 이전 배당률 레코드를 누적하여 제공하므로 호출마다 원문을 추가하지
않고, 같은 UTC 날짜의 이벤트별 최신 Snapshot을 유지합니다.

```text
data/raw/event-odds/2026-10-22/12345678.json
data/metadata/event-odds/2026-10-22/12345678.json
```

원문은 API 응답 바이트이고 `OddsSnapshotMetadata`에는 토큰을 제외한 요청 조건,
반환된 마켓 키, 마켓별 레코드 수, HTTP 및 파일 정보가 들어갑니다. 유효하지 않은
응답은 기존 Snapshot을 교체하지 않습니다.

현재 명령의 이벤트별 결과는 메모리에서 `captured`, `request_failed`,
`response_invalid`, `storage_failed`로 구분하여 CLI에 출력합니다. 실행 이력은 별도
파일로 남기지 않으며, 실패한 이벤트가 있어도 기존의 정상 Snapshot은 유지합니다.

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
각 리그 Discovery의 `events`는 `scheduled_at_utc`, `event_id` 순으로 정렬합니다.
각 항목은 원문을 복제하지 않고 CaptureMetadata 경로와 0부터 시작하는
`result_index`로 출처를 가리킵니다.

리그 Discovery는 해당 리그의 한 번의 조회 결과만 담습니다. 성공·일부 응답 이슈는
각각 `completed`·`partial`, 호출·HTTP·응답 분석 실패는 `failed`로 기록합니다.
실패한 시도도 파일로 남기므로 가장 최근 시도가 실패했다는 사실을 확인할 수 있습니다.

Run JSON은 `discover-upcoming` 명령 한 번의 실행 기록입니다. 실행 시각, 전체 상태,
조회 대상과 생성된 리그 Discovery 경로만 담으며 이벤트 목록은 중복 저장하지 않습니다.
따라서 일부 리그만 다시 조회해도 다른 리그의 과거 Discovery와 섞거나 덮어쓰지
않습니다.

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
남기지만 해당 리그 Discovery의 `events`에서는 제외합니다.

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
