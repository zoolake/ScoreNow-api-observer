from datetime import date

import httpx

EVENT_VIEW_ENDPOINT = "/v1/event/view"
UPCOMING_EVENTS_ENDPOINT = "/v3/events/upcoming"
EVENT_ODDS_ENDPOINT = "/v2/event/odds"


def get_event_view(
    base_url: str,
    token: str,
    requested_event_ids: list[str],
) -> httpx.Response:
    """BETS API에서 경기 상세 응답을 한 번 조회합니다."""

    url = f"{base_url.rstrip('/')}{EVENT_VIEW_ENDPOINT}"

    response = httpx.get(
        url,
        params={
            "token": token,
            "event_id": ",".join(requested_event_ids),
        },
        timeout=30.0,
    )

    return response


def get_upcoming_events(
    *,
    base_url: str,
    token: str,
    sport_id: str,
    league_id: str,
    target_date: date,
) -> httpx.Response:
    """BETS API에서 특정 종목·리그·UTC 날짜의 예정 경기를 조회합니다."""

    url = f"{base_url.rstrip('/')}{UPCOMING_EVENTS_ENDPOINT}"

    return httpx.get(
        url,
        params={
            "token": token,
            "sport_id": sport_id,
            "league_id": league_id,
            "day": target_date.strftime("%Y%m%d"),
        },
        timeout=30.0,
    )


def get_event_odds(
    *,
    base_url: str,
    token: str,
    event_id: str,
    odds_markets: tuple[int, ...],
) -> httpx.Response:
    """BETS API에서 이벤트 하나의 지정된 마켓 배당률을 조회합니다."""

    url = f"{base_url.rstrip('/')}{EVENT_ODDS_ENDPOINT}"

    return httpx.get(
        url,
        params={
            "token": token,
            "event_id": event_id,
            "odds_market": ",".join(str(market) for market in odds_markets),
        },
        timeout=30.0,
    )
