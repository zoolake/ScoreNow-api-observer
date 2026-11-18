# Oracle VM systemd 운영 파일

이 디렉터리는 Oracle VM에서 Auto-watch를 자동 실행하기 위한 systemd 원본 파일을
관리합니다. 서비스는 모두 `scorenow` 사용자로 실행하며 프로젝트 위치는
`/opt/scorenow-api-observer`로 고정합니다.

```text
scorenow-discover-auto-watch.timer (6시간마다)
└── scorenow-discover-auto-watch.service
    └── discover-auto-watch → Upcoming Discovery 저장

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

## 설치와 문법 검증

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/scorenow-auto-watch.service \
  deploy/systemd/scorenow-discover-auto-watch.service \
  /etc/systemd/system/
sudo install -o root -g root -m 0644 \
  deploy/systemd/scorenow-discover-auto-watch.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/scorenow-auto-watch.service \
  /etc/systemd/system/scorenow-discover-auto-watch.service \
  /etc/systemd/system/scorenow-discover-auto-watch.timer
sudo systemctl daemon-reload
```

설치만으로 서비스나 타이머가 실행되지는 않습니다. 실제 BETS API 호출 승인을 받은 뒤
별도로 `enable --now`를 실행해야 합니다.

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
