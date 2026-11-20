import json
import logging
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from pydantic import SecretStr

from scorenow_api_observer.discord_webhook import (
    DISCORD_TIMEOUT_SECONDS,
    DiscordAttachment,
    DiscordWebhook,
    load_discord_webhook,
)

WEBHOOK = "https://discord.example/api/webhooks/123/webhook-secret?thread_id=456"


def test_discord_webhook_reads_environment(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert load_discord_webhook() is None
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    webhook = load_discord_webhook()
    assert webhook is not None
    assert WEBHOOK not in repr(webhook)


def test_discord_webhook_sends_summary_and_attachment_together(caplog, monkeypatch):
    monkeypatch.setenv("BETS_API_TOKEN", "private-bets-token")
    caplog.set_level(logging.INFO, logger="httpx")

    def handler(request):
        assert request.method == "POST"
        assert dict(request.url.params) == {"thread_id": "456", "wait": "true"}
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
            + request.content
        )
        payload, attachment = list(message.iter_parts())
        report = json.loads(str(payload.get_content()))
        assert report["embeds"] == [
            {"title": "운영 보고서", "description": "요청 3회 [숨김]"}
        ]
        assert report["allowed_mentions"] == {"parse": []}
        assert report["attachments"] == [{"id": 0, "filename": "report.md"}]
        assert attachment.get_param("name", header="content-disposition") == "files[0]"
        assert attachment.get_filename() == "report.md"
        assert attachment.get_content() == "상세 [숨김]"
        return httpx.Response(200, json={"id": "123456"})

    webhook = DiscordWebhook(SecretStr(WEBHOOK), httpx.MockTransport(handler))
    assert (
        webhook.send(
            "운영 보고서",
            "요청 3회 private-bets-token",
            attachment=DiscordAttachment("report.md", f"상세 {WEBHOOK}".encode()),
        )
        == "123456"
    )
    assert "webhook-secret" not in caplog.text


@pytest.mark.parametrize(
    ("response", "log_text"),
    [
        (httpx.Response(204), "메시지 수신 확인 없음"),
        (httpx.Response(200, json={"id": "invalid"}), "메시지 수신 확인 없음"),
        (httpx.Response(429, text=WEBHOOK), "HTTP 429"),
    ],
)
def test_discord_webhook_requires_confirmed_message(response, log_text, caplog):
    caplog.set_level(logging.INFO, logger="httpx")

    def handler(request):
        assert json.loads(request.content)["embeds"] == [
            {"title": "운영 알림", "description": "수집 중단"}
        ]
        return response

    webhook = DiscordWebhook(SecretStr(WEBHOOK), httpx.MockTransport(handler))
    assert webhook.send("운영 알림", "수집 중단") is None
    assert log_text in caplog.text
    assert "webhook-secret" not in caplog.text


def test_discord_webhook_uses_timeout_and_hides_exception_text(caplog):
    def handler(request):
        assert request.extensions["timeout"]["read"] == DISCORD_TIMEOUT_SECONDS
        raise httpx.ReadTimeout(WEBHOOK, request=request)

    webhook = DiscordWebhook(SecretStr(WEBHOOK), httpx.MockTransport(handler))
    assert webhook.send("운영 알림", "수집 중단") is None
    assert "시간 초과" in caplog.text
    assert "webhook-secret" not in caplog.text
