import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

REPORT_DIRECTORY = Path("reports/event-view")

ReportFormat = Literal["md", "html"]


def build_report_output_path(
    *,
    generated_at: datetime,
    report_name: str,
    report_format: ReportFormat = "md",
    base_directory: Path = REPORT_DIRECTORY,
) -> Path:
    """보고서 생성 시각과 이름으로 날짜별 출력 경로를 계산합니다."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("보고서 생성 시각에는 timezone 정보가 필요합니다.")

    if report_format not in ("md", "html"):
        raise ValueError(f"지원하지 않는 보고서 형식입니다: {report_format!r}")

    safe_report_name = _to_safe_report_name(report_name)
    generated_at_utc = generated_at.astimezone(UTC)
    date_directory = generated_at_utc.strftime("%Y-%m-%d")
    timestamp = generated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")

    return (
        base_directory
        / date_directory
        / f"{timestamp}_{safe_report_name}.{report_format}"
    )


def build_field_report_output_path(
    *,
    generated_at: datetime,
    sport_code: str,
    field_path: str,
    base_directory: Path = REPORT_DIRECTORY,
) -> Path:
    """종목·필드별 분석 보고서의 날짜별 출력 경로를 계산합니다."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("보고서 생성 시각에는 timezone 정보가 필요합니다.")

    safe_sport_code = _to_safe_report_name(sport_code)
    path_report_name = field_path.removeprefix("$.")
    if path_report_name == "$":
        path_report_name = "root"
    safe_field_path = _to_safe_report_name(path_report_name)
    generated_at_utc = generated_at.astimezone(UTC)
    date_directory = generated_at_utc.strftime("%Y-%m-%d")
    timestamp = generated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")

    return (
        base_directory
        / date_directory
        / "field"
        / safe_sport_code
        / f"{timestamp}_{safe_field_path}.md"
    )


def save_report_text(*, content: str, output_path: Path) -> Path:
    """보고서 텍스트를 UTF-8로 새 파일에 저장하고 경로를 반환합니다."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as report_file:
        report_file.write(content)
    return output_path


def _to_safe_report_name(value: str) -> str:
    """보고서 이름을 경로 구분자가 없는 안전한 파일명 조각으로 변환합니다."""

    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not safe_value:
        raise ValueError(
            f"보고서 이름을 안전한 파일명으로 변환할 수 없습니다: {value!r}"
        )
    return safe_value
