from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scorenow_api_observer.upcoming.models import (
    LeagueUpcomingDiscovery,
    UpcomingCaptureMetadata,
    UpcomingDiscoveryRun,
)

UPCOMING_RAW_DATA_DIRECTORY = Path("data/raw/events-upcoming")
UPCOMING_METADATA_DIRECTORY = Path("data/metadata/events-upcoming")
UPCOMING_DISCOVERY_DIRECTORY = Path("data/discoveries/events-upcoming")
KST = ZoneInfo("Asia/Seoul")


def save_upcoming_raw_response(
    *,
    response_body: bytes,
    captured_at: datetime,
    league_label: str,
    base_directory: Path = UPCOMING_RAW_DATA_DIRECTORY,
) -> Path:
    """Upcoming 응답 원문을 KST 호출 날짜와 리그 label 기준으로 저장합니다."""

    kst_captured_at = _as_kst(captured_at)
    output_directory = base_directory / kst_captured_at.strftime("%Y-%m-%d")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / _capture_file_name(
        league_label=league_label,
        kst_captured_at=kst_captured_at,
    )
    with output_path.open("xb") as output_file:
        output_file.write(response_body)

    return output_path


def save_upcoming_capture_metadata(
    metadata: UpcomingCaptureMetadata,
    *,
    base_directory: Path = UPCOMING_METADATA_DIRECTORY,
) -> Path:
    """Upcoming CaptureMetadata를 원문과 동일한 KST 날짜·파일명으로 저장합니다."""

    kst_captured_at = _as_kst(metadata.captured_at)
    output_directory = base_directory / kst_captured_at.strftime("%Y-%m-%d")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / Path(metadata.raw_file_path).name
    metadata_json = metadata.model_dump_json(indent=2)
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(metadata_json + "\n")

    return output_path


def save_league_upcoming_discovery(
    discovery: LeagueUpcomingDiscovery,
    *,
    base_directory: Path = UPCOMING_DISCOVERY_DIRECTORY,
) -> Path:
    """리그별 Discovery를 UTC target_date와 종목·리그 경로에 저장합니다."""

    target = discovery.target
    output_directory = (
        base_directory
        / discovery.target_date.isoformat()
        / "leagues"
        / target.sport_code
        / f"{target.league_id}-{target.league_label}"
    )
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / f"{discovery.discovery_run_id}_discovery.json"
    discovery_json = discovery.model_dump_json(indent=2)
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(discovery_json + "\n")

    return output_path


def save_upcoming_discovery_run(
    discovery_run: UpcomingDiscoveryRun,
    *,
    base_directory: Path = UPCOMING_DISCOVERY_DIRECTORY,
) -> Path:
    """Discovery 실행 기록을 UTC target_date의 runs 디렉터리에 저장합니다."""

    output_directory = base_directory / discovery_run.target_date.isoformat() / "runs"
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / f"{discovery_run.discovery_run_id}_run.json"
    run_json = discovery_run.model_dump_json(indent=2)
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(run_json + "\n")

    return output_path


def find_league_upcoming_discovery_paths(
    base_directory: Path = UPCOMING_DISCOVERY_DIRECTORY,
) -> list[Path]:
    """저장된 리그별 Discovery 파일 경로를 일정한 순서로 반환합니다."""

    return sorted(
        path
        for path in base_directory.glob(
            "*/leagues/*/*/*_discovery.json",
        )
        if path.is_file()
    )


def load_league_upcoming_discovery(
    file_path: Path,
) -> LeagueUpcomingDiscovery:
    """리그별 Discovery JSON 파일을 현재 모델로 읽습니다."""

    return LeagueUpcomingDiscovery.model_validate_json(
        file_path.read_text(encoding="utf-8")
    )


def _capture_file_name(*, league_label: str, kst_captured_at: datetime) -> str:
    timestamp = kst_captured_at.strftime("%Y-%m-%dT%H-%M-%S")
    return f"{league_label}_{timestamp}_KST_capture.json"


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("저장 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(KST)
