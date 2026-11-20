# Oracle VM systemd 운영 파일

이 디렉터리는 Oracle VM에서 Auto-watch를 자동 실행하기 위한 systemd 원본 파일을
관리합니다. 서비스는 모두 `scorenow` 사용자로 실행하며 프로젝트 위치는
`/opt/scorenow-api-observer`로 고정합니다.

```text
scorenow-discover-auto-watch.timer (6시간마다)
└── scorenow-discover-auto-watch.service
    └── discover-auto-watch → Upcoming Discovery 저장

scorenow-daily-report.timer (매일 09:00 KST)
└── scorenow-daily-report.service
    └── publish-daily-report → 전날 KST 일간 보고서 저장 및 디스코드 발행

scorenow-operations-alerts.timer (1분마다)
└── scorenow-operations-alerts.service
    └── check-operations-alerts → 마지막 처리 시각과 정각 구간 요청량 점검

scorenow-auto-watch.service (계속 실행)
└── 저장된 Discovery 확인 → Event View 반복 수집
```

## 파일 역할

- `scorenow-auto-watch.service`: Auto-watch를 계속 실행합니다.
- `scorenow-discover-auto-watch.service`: 활성 리그의 UTC 오늘·내일 Discovery를 한 번
  실행합니다.
- `scorenow-discover-auto-watch.timer`: Discovery 서비스를 UTC 00·06·12·18시에
  예약합니다. KST로는 09·15·21시와 다음 날 03시이며, 최대 5분의 무작위 지연을
  적용합니다.
- `scorenow-daily-report.service`와 `scorenow-daily-report.timer`는 전날 KST
  보고서의 발행을 매일 09:00 KST(00:00 UTC)에 시작합니다. 무작위 지연은 0이며
  VM이 종료되어 놓친 날짜는 수동으로 지정합니다.
- `scorenow-operations-alerts.service`와 `scorenow-operations-alerts.timer`는
  Auto-watch 밖에서 1분마다 로컬 실행 상태와 요청량을 점검합니다.

## API 설정 파일

API 토큰은 Git 저장소와 `/opt/scorenow-api-observer` 안에 저장하지 않습니다. 다음
경로를 root가 만들고 `scorenow` 그룹만 읽을 수 있게 관리합니다.

```text
/etc/scorenow-api-observer/bets-api.env
```

처음 만들 때는 다음 명령을 사용합니다.

```bash
sudo install -d -o root -g scorenow -m 0750 /etc/scorenow-api-observer
sudo install -o root -g scorenow -m 0640 /dev/null \
  /etc/scorenow-api-observer/bets-api.env
sudoedit /etc/scorenow-api-observer/bets-api.env
```

파일 내용은 다음 두 환경변수만 사용합니다.

```dotenv
BETS_API_BASE_URL=https://api.b365api.com
BETS_API_TOKEN=replace-with-your-token
```

## 디스코드 웹훅 설정

웹훅 URL은 저장소 밖의 `/etc/scorenow-api-observer/discord.env`에 저장합니다.
처음 만들 때 파일 소유자를 `root:scorenow`, 권한을 `0640`으로 설정합니다.

```bash
sudo install -o root -g scorenow -m 0640 /dev/null \
  /etc/scorenow-api-observer/discord.env
sudoedit /etc/scorenow-api-observer/discord.env
```

파일에는 디스코드 웹훅 URL을 `DISCORD_WEBHOOK_URL` 환경변수로 설정합니다.
이 값이 설정된 Auto-watch에서 수집 결과 알림이 켜집니다. 일간 보고서와 주기 점검도
같은 웹훅을 사용합니다. 웹훅 값은 작은따옴표로 감싸면 수동 명령에서 같은 환경 파일을
읽을 수 있습니다.

## 설치와 문법 검증

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/scorenow-auto-watch.service \
  deploy/systemd/scorenow-discover-auto-watch.service \
  deploy/systemd/scorenow-daily-report.service \
  deploy/systemd/scorenow-operations-alerts.service \
  /etc/systemd/system/
sudo install -o root -g root -m 0644 \
  deploy/systemd/scorenow-discover-auto-watch.timer \
  deploy/systemd/scorenow-daily-report.timer \
  deploy/systemd/scorenow-operations-alerts.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/scorenow-auto-watch.service \
  /etc/systemd/system/scorenow-discover-auto-watch.service \
  /etc/systemd/system/scorenow-discover-auto-watch.timer \
  /etc/systemd/system/scorenow-daily-report.service \
  /etc/systemd/system/scorenow-daily-report.timer \
  /etc/systemd/system/scorenow-operations-alerts.service \
  /etc/systemd/system/scorenow-operations-alerts.timer
TZ=Asia/Seoul systemd-analyze calendar '*-*-* 00:00:00 UTC'
sudo systemctl daemon-reload
```

설치와 문법 검증은 단위의 등록과 검토 절차입니다. BETS API를 호출하는 Auto-watch와
Discovery는 실제 호출 승인을 받은 뒤 시작합니다. 디스코드 발행과 주기 점검은 운영
웹훅 설정 및 발송 승인 후 각 타이머를 시작합니다.

## 재시작 정책

Auto-watch는 연결 오류처럼 다시 시도 가능한 문제를 다음 정상 수집 주기에 처리합니다.
401·402·403·429, 설정 오류, 로컬 저장 실패로 프로세스가 종료되면 운영자 확인 전에는
다시 시작하지 않습니다. systemd의 `Restart=on-abnormal`은 종료 코드가 있는 일반
실패가 아니라 신호·타임아웃 같은 비정상 종료에서만 Auto-watch를 다시 시작합니다.

Discovery 서비스는 실패 직후 재시도하지 않습니다. 다음 6시간 예약 시각에 다시
실행합니다. `Persistent=true`이므로 VM이 꺼져 예약을 놓친 경우에는 다음 부팅 후 누락된
작업을 한 번 실행합니다.

## 상태와 로그 확인

```bash
systemctl status scorenow-auto-watch.service
systemctl status scorenow-discover-auto-watch.timer
journalctl -u scorenow-auto-watch.service
journalctl -u scorenow-discover-auto-watch.service
```

프로그램이 저장한 상태와 요청량은 API를 호출하지 않고 다음 명령으로 확인할 수
있습니다.

```bash
sudo -u scorenow -H sh -c \
  'cd /opt/scorenow-api-observer && .venv/bin/observer auto-watch-status'
```

## 디스코드 운영 알림 점검

```bash
systemctl status scorenow-operations-alerts.timer
systemctl list-timers scorenow-operations-alerts.timer
journalctl -u scorenow-operations-alerts.service
```

- Event View 연결 오류와 HTTP 5xx는 연속 3수집 주기부터 알립니다. 한 주기에
  여러 배치가 실패해도 한 번 셉니다. 정상 수집이 돌아오면 복구를 한 번 알립니다.
- 같은 경기 누락은 연속 3수집 주기부터 알립니다. 정상 응답 한 건에서 2경기 이상이
  빠지면 즉시 알립니다.
- `time_status=2`는 예정 시각 이후 연속 30분 관측했을 때 알립니다.
- 마지막 처리 시각이 `max(수집 간격 × 2, 수집 간격 + 60초)`보다 오래됐으면 주기
  점검에서 알립니다.
- 요청 한도는 `config/auto_watch.yaml`의 종목별 시간당 한도와 주의 80%·위험 90%
  기본값을 사용합니다. 정각 구간마다 각 기준을 한 번씩 알립니다.

주기 점검을 수동으로 실행하면 같은 로컬 기록과 알림 상태를 사용합니다. 명령이
디스코드 메시지를 전송할 수 있습니다.

```bash
sudo -u scorenow -H sh -c '
  cd /opt/scorenow-api-observer
  set -a
  . /etc/scorenow-api-observer/discord.env
  set +a
  exec .venv/bin/observer check-operations-alerts
'
```

## 일간 보고서 확인과 재발행

```bash
systemctl status scorenow-daily-report.timer
systemctl list-timers scorenow-daily-report.timer
journalctl -u scorenow-daily-report.service
```

놓친 날짜를 발행하거나 저장된 보고서를 다시 보낼 때는 KST 날짜를 지정합니다.
날짜를 직접 지정한 경우에는 이전 발행 기록이 있어도 디스코드로 전송합니다.

```bash
sudo -u scorenow -H sh -c '
  cd /opt/scorenow-api-observer
  set -a
  . /etc/scorenow-api-observer/discord.env
  set +a
  exec .venv/bin/observer publish-daily-report --date 2026-11-19
'
```
