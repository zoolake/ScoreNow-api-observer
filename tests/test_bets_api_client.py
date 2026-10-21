from datetime import date
from unittest.mock import Mock

import httpx
import pytest

from scorenow_api_observer import bets_api_client


def test_get_event_view_requests_multiple_event_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(200, json={"success": 1, "results": []})
    httpx_get = Mock(return_value=response)
    monkeypatch.setattr(bets_api_client.httpx, "get", httpx_get)

    result = bets_api_client.get_event_view(
        base_url="https://example.test/",
        token="test-token",
        requested_event_ids=["A", "B", "C"],
    )

    assert result is response
    httpx_get.assert_called_once_with(
        "https://example.test/v1/event/view",
        params={
            "token": "test-token",
            "event_id": "A,B,C",
        },
        timeout=30.0,
    )


def test_get_upcoming_events_requests_target_sport_league_and_utc_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(200, json={"success": 1, "results": []})
    httpx_get = Mock(return_value=response)
    monkeypatch.setattr(bets_api_client.httpx, "get", httpx_get)

    result = bets_api_client.get_upcoming_events(
        base_url="https://example.test/",
        token="test-token",
        sport_id="16",
        league_id="225",
        target_date=date(2026, 10, 16),
    )

    assert result is response
    httpx_get.assert_called_once_with(
        "https://example.test/v3/events/upcoming",
        params={
            "token": "test-token",
            "sport_id": "16",
            "league_id": "225",
            "day": "20261016",
        },
        timeout=30.0,
    )


def test_get_event_odds_requests_one_event_and_selected_markets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(200, json={"success": 1, "results": {"odds": {}}})
    httpx_get = Mock(return_value=response)
    monkeypatch.setattr(bets_api_client.httpx, "get", httpx_get)

    result = bets_api_client.get_event_odds(
        base_url="https://example.test/",
        token="test-token",
        event_id="EVENT-A",
        odds_markets=(1, 2, 3),
    )

    assert result is response
    httpx_get.assert_called_once_with(
        "https://example.test/v2/event/odds",
        params={
            "token": "test-token",
            "event_id": "EVENT-A",
            "odds_market": "1,2,3",
        },
        timeout=30.0,
    )
