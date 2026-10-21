from typing import Literal

from pydantic import SecretStr, ValidationError
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.event_odds.collector import (
    OddsCollectionEventResult,
    OddsCollectionResult,
    OddsCollectionStatus,
)


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


def _result(
    *, statuses: list[Literal["captured", "request_failed"]]
) -> OddsCollectionResult:
    event_results = []
    for index, status in enumerate(statuses):
        event_id = chr(ord("A") + index)
        if status == "captured":
            event_results.append(
                OddsCollectionEventResult(
                    event_id=event_id,
                    status="captured",
                    http_status_code=200,
                    raw_file_path=f"raw/{event_id}.json",
                    metadata_file_path=f"metadata/{event_id}.json",
                )
            )
        else:
            event_results.append(
                OddsCollectionEventResult(
                    event_id=event_id,
                    status="request_failed",
                    error_type="ConnectError",
                    error_message="API 서버에 연결하지 못했습니다.",
                )
            )

    captured_count = sum(result.status == "captured" for result in event_results)
    if captured_count == len(event_results):
        collection_status: OddsCollectionStatus = "completed"
    elif captured_count == 0:
        collection_status = "failed"
    else:
        collection_status = "partial"

    return OddsCollectionResult(
        status=collection_status,
        event_results=event_results,
        snapshots=[],
    )


def test_collect_odds_normalizes_event_ids(monkeypatch) -> None:
    received_event_ids: list[str] = []
    monkeypatch.setattr(cli, "Settings", _FakeSettings)

    def collect_event_odds(**kwargs: object) -> OddsCollectionResult:
        received_event_ids.extend(kwargs["event_ids"])  # type: ignore[arg-type]
        return _result(statuses=["captured", "captured"])

    monkeypatch.setattr(cli, "collect_event_odds", collect_event_odds)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", " B, A, B "],
    )

    assert result.exit_code == 0
    assert received_event_ids == ["A", "B"]
    assert "Odds 수집 상태: completed" in result.output
    assert "Snapshot 저장: 2개" in result.output


def test_collect_odds_partial_result_warns_and_exits_zero(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "collect_event_odds",
        lambda **_kwargs: _result(statuses=["captured", "request_failed"]),
    )

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A,B"],
    )

    assert result.exit_code == 0
    assert "Odds 수집 상태: partial" in result.output
    assert "일부 이벤트의 배당률 수집에 실패했습니다." in result.output


def test_collect_odds_failed_result_exits_one(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "collect_event_odds",
        lambda **_kwargs: _result(statuses=["request_failed"]),
    )

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A"],
    )

    assert result.exit_code == 1
    assert "모든 이벤트의 배당률 수집에 실패했습니다." in result.output


def test_collect_odds_rejects_invalid_event_ids_before_loading_settings(
    monkeypatch,
) -> None:
    settings_loaded = False

    def load_settings() -> _FakeSettings:
        nonlocal settings_loaded
        settings_loaded = True
        return _FakeSettings()

    monkeypatch.setattr(cli, "Settings", load_settings)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A,,B"],
    )

    assert result.exit_code == 2
    assert not settings_loaded
    assert "이벤트 ID 입력이 올바르지 않습니다." in result.output


def test_collect_odds_settings_error_exits_two(monkeypatch) -> None:
    def fail_to_load_settings() -> _FakeSettings:
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr(cli, "Settings", fail_to_load_settings)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A"],
    )

    assert result.exit_code == 2
    assert "API 설정을 읽지 못했습니다." in result.output
