from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from scorenow_api_observer.reporting.storage import (
    ReportFormat,
    build_field_report_output_path,
    build_report_output_path,
    save_report_text,
)


def test_build_report_output_path_uses_utc_date_and_timestamp(tmp_path: Path) -> None:
    generated_at = datetime(
        2026,
        9,
        25,
        1,
        30,
        12,
        345678,
        tzinfo=timezone(timedelta(hours=9)),
    )

    result = build_report_output_path(
        generated_at=generated_at,
        report_name="endpoint",
        base_directory=tmp_path / "reports",
    )

    assert result == (
        tmp_path / "reports" / "2026-09-24" / "20260924T163012345678Z_endpoint.md"
    )


def test_build_report_output_path_normalizes_unsafe_report_name(
    tmp_path: Path,
) -> None:
    result = build_report_output_path(
        generated_at=datetime(2026, 9, 24, tzinfo=UTC),
        report_name="sport_base/ball",
        report_format="html",
        base_directory=tmp_path,
    )

    assert result.name == "20260924T000000000000Z_sport_base_ball.html"


def test_build_report_output_path_rejects_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        build_report_output_path(
            generated_at=datetime(2026, 9, 24, tzinfo=UTC).replace(tzinfo=None),
            report_name="endpoint",
            base_directory=tmp_path,
        )

    with pytest.raises(ValueError, match="안전한 파일명"):
        build_report_output_path(
            generated_at=datetime(2026, 9, 24, tzinfo=UTC),
            report_name="///",
            base_directory=tmp_path,
        )

    with pytest.raises(ValueError, match="지원하지 않는 보고서 형식"):
        build_report_output_path(
            generated_at=datetime(2026, 9, 24, tzinfo=UTC),
            report_name="endpoint",
            report_format=cast(ReportFormat, "pdf"),
            base_directory=tmp_path,
        )


def test_save_report_text_creates_parent_and_preserves_content(tmp_path: Path) -> None:
    output_path = tmp_path / "reports" / "endpoint.md"
    content = "# 보고서\n\n한글 내용\n"

    result = save_report_text(content=content, output_path=output_path)

    assert result == output_path
    assert output_path.read_text(encoding="utf-8") == content


def test_save_report_text_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    output_path = tmp_path / "endpoint.md"
    output_path.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        save_report_text(content="replacement\n", output_path=output_path)

    assert output_path.read_text(encoding="utf-8") == "existing\n"


def test_build_field_report_output_path_uses_sport_directory_and_safe_path(
    tmp_path: Path,
) -> None:
    result = build_field_report_output_path(
        generated_at=datetime(2026, 10, 20, 12, 30, tzinfo=UTC),
        sport_code="baseball",
        field_path="$.scores.10.home",
        base_directory=tmp_path / "reports",
    )

    assert result == (
        tmp_path
        / "reports"
        / "2026-10-20"
        / "field"
        / "baseball"
        / "20261020T123000000000Z_scores.10.home.md"
    )
