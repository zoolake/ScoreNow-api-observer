import json
from datetime import UTC, datetime

import httpx
import typer

from scorenow_api_observer.bets_api_client import get_event_view
from scorenow_api_observer.models import CaptureMetadata
from scorenow_api_observer.settings import Settings
from scorenow_api_observer.storage import save_capture_metadata, save_raw_response

app = typer.Typer(
    name="observer",
    help="BETS API 응답 수집 및 변화를 확인하는 CLI 도구",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """BETS API 응답 관측 도구입니다."""


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
        response = get_event_view(
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

    captured_at = datetime.now(UTC)

    raw_output_path = save_raw_response(
        event_id=event_id,
        response_body=response.content,
        captured_at=captured_at,
    )

    metadata = CaptureMetadata(
        captured_at=captured_at,
        provider="BETS API",
        endpoint="/v1/event/view",
        http_method="GET",
        event_ids=[event_id],
        http_status_code=response.status_code,
        elapsed_ms=round(response.elapsed.total_seconds() * 1000, 2),
        response_size_bytes=len(response.content),
        content_type=response.headers.get("content-type"),
        raw_file_path=str(raw_output_path),
    )
    
    metadata_output_path = save_capture_metadata(metadata)

    typer.echo(f"HTTP 상태 코드: {response.status_code}")
    typer.echo(f"원문 저장 위치: {raw_output_path}")
    typer.echo(f"메타데이터 저장 위치: {metadata_output_path}")

    # HTTP status code : 4xx, 5xx
    if response.is_error:
        typer.echo("API가 오류 응답을 반환했습니다.", err=True)
        typer.echo(response.text)
        raise typer.Exit(code=1)

    try:
        response_data = response.json()
    except ValueError:
        typer.echo("응답이 JSON 형식이 아닙니다.", err=True)
        typer.echo(response.text)
        raise typer.Exit(code=1) from None

    formatted_json = json.dumps(
        response_data,
        ensure_ascii=False,
        indent=2,
    )

    typer.echo(formatted_json)


if __name__ == "__main__":
    app()
