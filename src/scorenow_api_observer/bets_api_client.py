import httpx

EVENT_VIEW_ENDPOINT = "/v1/event/view"


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
