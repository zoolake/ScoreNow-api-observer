import json
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import SecretStr

DISCORD_WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_TIMEOUT_SECONDS = 5.0
logger = logging.getLogger(__name__)

# HTTPX의 요청 로그에는 비밀 경로를 포함한 URL 전체가 들어갑니다.
_sending_webhook: ContextVar[bool] = ContextVar("sending_webhook", default=False)


def _outside_webhook_send(record: logging.LogRecord) -> bool:
    return not _sending_webhook.get()


for _logger_name in ("httpx", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_logger_name).addFilter(_outside_webhook_send)


@dataclass(frozen=True)
class DiscordAttachment:
    filename: str
    content: bytes


class DiscordSender(Protocol):
    def __call__(
        self,
        title: str,
        description: str,
        *,
        attachment: DiscordAttachment | None = None,
    ) -> str | None: ...


@dataclass(frozen=True)
class DiscordWebhook:
    url: SecretStr = field(repr=False)
    transport: httpx.BaseTransport | None = field(default=None, repr=False)

    def send(
        self,
        title: str,
        description: str,
        *,
        attachment: DiscordAttachment | None = None,
    ) -> str | None:
        """디스코드가 확인한 메시지 ID를 반환합니다."""
        raw_url = self.url.get_secret_value()
        try:
            url = httpx.URL(raw_url)
            if url.scheme != "https" or not url.host:
                raise httpx.InvalidURL("HTTPS URL이 필요합니다.")
        except httpx.InvalidURL, ValueError:
            logger.warning("디스코드 전송 실패 (웹훅 설정 오류)")
            return None

        secrets = (
            raw_url,
            url.path.rsplit("/", 1)[-1],
            os.getenv("BETS_API_TOKEN", ""),
        )
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            title = title.replace(secret, "[숨김]")
            description = description.replace(secret, "[숨김]")
            if attachment is not None:
                attachment = DiscordAttachment(
                    attachment.filename.replace(secret, "[숨김]"),
                    attachment.content.replace(secret.encode(), "[숨김]".encode()),
                )

        payload = {
            "embeds": [{"title": title[:256], "description": description[:4096]}],
            "allowed_mentions": {"parse": []},
        }
        context = _sending_webhook.set(True)
        try:
            with httpx.Client(
                timeout=DISCORD_TIMEOUT_SECONDS, transport=self.transport
            ) as client:
                url = url.copy_merge_params({"wait": "true"})
                if attachment is None:
                    response = client.post(url, json=payload)
                else:
                    response = client.post(
                        url,
                        data={
                            "payload_json": json.dumps(
                                {
                                    **payload,
                                    "attachments": [
                                        {"id": 0, "filename": attachment.filename}
                                    ],
                                }
                            )
                        },
                        files={
                            "files[0]": (
                                attachment.filename,
                                attachment.content,
                                "text/markdown; charset=utf-8",
                            )
                        },
                    )
        except httpx.TimeoutException:
            logger.warning("디스코드 전송 실패 (시간 초과)")
            return None
        except httpx.RequestError, httpx.InvalidURL, ValueError:
            logger.warning("디스코드 전송 실패 (연결 또는 요청 오류)")
            return None
        finally:
            _sending_webhook.reset(context)

        if not response.is_success:
            logger.warning("디스코드 전송 실패 (HTTP %d)", response.status_code)
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        message_id = body.get("id") if isinstance(body, dict) else None
        if (
            not isinstance(message_id, str)
            or not message_id.isascii()
            or not message_id.isdecimal()
        ):
            logger.warning("디스코드 전송 실패 (메시지 수신 확인 없음)")
            return None
        return message_id


def load_discord_webhook() -> DiscordWebhook | None:
    url = os.getenv(DISCORD_WEBHOOK_ENV, "").strip()
    return DiscordWebhook(SecretStr(url)) if url else None
