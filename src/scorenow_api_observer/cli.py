import json

import httpx
import typer

from collector import CaptureResult, capture_event_view
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


if __name__ == "__main__":
    app()
