import json
import time
from pathlib import Path

import httpx
import typer

from scorenow_api_observer.collector import CaptureResult, capture_event_view
from scorenow_api_observer.comparison import (
    StructureComparison,
    compare_json_structures,
    compare_with_previous_capture,
    find_latest_captures,
    load_json_file,
)
from scorenow_api_observer.settings import Settings

app = typer.Typer(
    name="observer",
    help="BETS API 응답 수집 및 변화를 확인하는 CLI 도구",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """BETS API 응답 관측 도구입니다."""


def _print_capture_summary(result: CaptureResult) -> None:
    """호출 및 저장 결과를 간단하게 출력합니다."""

    typer.echo(f"HTTP 상태 코드: {result.response.status_code}")
    typer.echo(f"원문 저장 위치: {result.raw_file_path}")
    typer.echo(f"메타데이터 저장 위치: {result.metadata_file_path}")


@app.command()
def collect(
    event_id: str = typer.Option(
        ...,
        "--event-id",
        "-e",
        help="수집할 외부 API 경기 ID",
    ),
) -> None:
    """BETS View API를 호출하고 응답을 저장합니다."""

    # BaseSettings가 실행 시 .env 에서 필수 값을 읽어온다.
    settings = Settings()  # pyright: ignore[reportCallIssue]

    typer.echo(f"수집 대상 경기 ID: {event_id}")
    typer.echo("BETS View API를 호출합니다.")

    try:
        result = capture_event_view(
            base_url=settings.bets_api_base_url,
            token=settings.bets_api_token.get_secret_value(),
            event_id=event_id,
        )
    except httpx.RequestError:
        typer.echo(
            "API 서버에 연결하지 못했습니다.",
            err=True,
        )
        raise typer.Exit(code=1) from None

    _print_capture_summary(result)

    # HTTP status code : 4xx, 5xx
    if result.response.is_error:
        typer.echo("API가 오류 응답을 반환했습니다.", err=True)
        typer.echo(result.response.text)
        raise typer.Exit(code=1)

    try:
        response_data = result.response.json()
    except ValueError:
        typer.echo("응답이 JSON 형식이 아닙니다.", err=True)
        typer.echo(result.response.text)
        raise typer.Exit(code=1) from None

    formatted_json = json.dumps(
        response_data,
        ensure_ascii=False,
        indent=2,
    )

    typer.echo(formatted_json)


@app.command()
def watch(
    event_id: str = typer.Option(
        ...,
        "--event-id",
        "-e",
        help="수집할 외부 API 경기 ID",
    ),
    interval_seconds: int = typer.Option(
        30, "--interval", "-i", min=1, help="호출 간격(초))"
    ),
    count: int | None = typer.Option(
        None, "--count", "-c", min=1, help="호출할 횟수. 생략하면 계속 수집"
    ),
) -> None:
    """Event View API 를 일정한 간격으로 반복 호출합니다."""

    settings = Settings()  # pyright: ignore[reportCallIssue]

    count_description = str(count) if count is not None else "제한 없음"

    typer.echo(f"수집 대상 경기 ID: {event_id}")
    typer.echo(f"호출 간격: {interval_seconds}초")
    typer.echo(f"호출 횟수: {count_description}")
    typer.echo("중단하려면 Ctrl+C를 누르세요.")

    attempt_count = 0
    saved_count = 0

    try:
        while count is None or attempt_count < count:
            attempt_count += 1

            typer.echo("")
            typer.echo(f"[📡 {attempt_count}번째 호출]")

            try:
                result = capture_event_view(
                    base_url=settings.bets_api_base_url,
                    token=settings.bets_api_token.get_secret_value(),
                    event_id=event_id,
                )
            except httpx.RequestError:
                typer.echo("API 서버에 연결하지 못했습니다.", err=True)
            else:
                saved_count += 1

                _print_capture_summary(result)

                if result.response.is_error:
                    typer.echo("API가 오류 응답을 반환했습니다.", err=True)
                else:
                    try:
                        comparison = compare_with_previous_capture(
                            event_id, result.raw_file_path
                        )
                    except OSError, json.JSONDecodeError:
                        typer.echo(
                            "저장된 응답을 읽거나, 비교하지 못했습니다.", err=True
                        )
                    else:
                        if comparison is None:
                            typer.echo("직전 응답이 없어 구조 비교를 생략합니다.")
                        else:
                            _print_structure_comparison(comparison)

            if count is not None and attempt_count >= count:
                break

            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        typer.echo("")
        typer.echo(
            f"❌ 반복 수집을 중단했습니다. 호출: {attempt_count}회 / 저장: {saved_count}개"
        )
        return

    typer.echo("")
    typer.echo(
        f"✅ {attempt_count} 회 수집 완료했습니다. 호출: {attempt_count}회 / 저장: {saved_count}개"
    )


@app.command()
def compare(
    event_id: str = typer.Option(
        ...,
        "--event-id",
        "-e",
        help="비교할 외부 API 경기 ID",
    ),
) -> None:
    """동일 경기의 직전 응답과 최신 응답 구조를 비교합니다."""

    captures = find_latest_captures(event_id)

    if len(captures) < 2:
        typer.echo("비교하려면 동일 경기의 응답이 최소 2개 필요합니다.", err=True)
        raise typer.Exit(code=1)

    previous_capture = captures[0]
    current_capture = captures[1]

    previous_path = Path(previous_capture.raw_file_path)
    current_path = Path(current_capture.raw_file_path)

    try:
        previous_data = load_json_file(previous_path)
        current_data = load_json_file(current_path)
    except OSError, json.JSONDecodeError:
        typer.echo(
            "저장된 원문 파일을 읽거나 JSON 으로 변환하는데 실패했습니다.", err=True
        )
        raise typer.Exit(code=1) from None

    result = compare_json_structures(previous_data, current_data)

    typer.echo(f"경기 ID: {event_id}")
    typer.echo(f"직전 응답: {previous_capture.captured_at.isoformat()}")
    typer.echo(f"최신 응답: {current_capture.captured_at.isoformat()}")

    typer.echo("")
    _print_structure_comparison(result)


def _print_structure_comparison(result: StructureComparison) -> None:

    has_changes = bool(
        result.added_paths or result.removed_paths or result.type_changes
    )

    if not has_changes:
        typer.echo("")
        typer.echo("JSON 구조 변화가 없습니다.")
        return

    _print_added_paths(result.added_paths)
    _print_removed_paths(result.removed_paths)
    _print_type_changes(result.type_changes)


def _print_added_paths(added_paths: list[str]) -> None:
    typer.echo("")
    typer.echo(f"이번 응답에서 새로 보이는 경로: {len(added_paths)}개")
    for added_path in added_paths:
        typer.echo(f" + {added_path}")


def _print_removed_paths(removed_paths: list[str]) -> None:
    typer.echo("")
    typer.echo(f"이번 응답에서 보이지 않는 경로: {len(removed_paths)}개")
    for removed_path in removed_paths:
        typer.echo(f" - {removed_path}")


def _print_type_changes(type_changes: list) -> None:
    typer.echo("")
    typer.echo(f"자료형이 달라진 경로: {len(type_changes)}개")
    for type_change in type_changes:
        previous_types = ", ".join(sorted(type_change.previous_types))
        current_types = ", ".join(sorted(type_change.current_types))

        typer.echo(f" ~ {type_change.path}: {previous_types} → {current_types}")


if __name__ == "__main__":
    app()
