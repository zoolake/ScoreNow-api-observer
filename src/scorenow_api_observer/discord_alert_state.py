import logging
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from scorenow_api_observer.discord_webhook import DiscordSender
from scorenow_api_observer.operations_storage import (
    lock_operations_file,
    write_operations_text,
)

ALERT_STATE_DIRECTORY = Path("data/state/discord-alerts")
logger = logging.getLogger(__name__)


class DiscordAlertState:
    """확인된 디스코드 알림을 키별로 기록합니다."""

    def __init__(self, sender: DiscordSender, directory: Path = ALERT_STATE_DIRECTORY):
        self.sender = sender
        self.directory = directory
        self._unsaved: dict[str, str | None] = {}

    def notify(
        self,
        key: str,
        title: str,
        description: str,
        *,
        episode: str | None = "sent",
        can_replace: Callable[[str | None], bool] | None = None,
    ) -> bool:
        """새 상황을 알립니다. episode=None은 확인된 알림의 복구를 뜻합니다."""
        path = self.directory / f"{sha256(key.encode()).hexdigest()}.txt"
        attempted = False
        confirmed = False

        def should_send(previous: str | None) -> bool:
            return previous != episode and (
                can_replace is None or can_replace(previous)
            )

        def send() -> bool:
            nonlocal attempted, confirmed
            attempted = True
            confirmed = self.sender(title, description) is not None
            if confirmed:
                self._unsaved[key] = episode
            return confirmed

        try:
            with lock_operations_file(path.with_suffix(".lock")):
                try:
                    previous = path.read_text(encoding="utf-8").strip()
                except FileNotFoundError:
                    previous = None
                if key in self._unsaved:
                    previous = self._unsaved[key]
                    if previous is None:
                        path.unlink(missing_ok=True)
                    else:
                        write_operations_text(path, previous + "\n")
                    del self._unsaved[key]
                if should_send(previous) and send():
                    if episode is None:
                        path.unlink(missing_ok=True)
                    else:
                        write_operations_text(path, episode + "\n")
                    del self._unsaved[key]
        except OSError, ValueError:
            logger.warning("디스코드 알림 상태를 읽거나 저장하지 못했습니다.")
            if not attempted and should_send(self._unsaved.get(key)):
                return send()
        return confirmed

    def clear(self, key: str) -> None:
        path = self.directory / f"{sha256(key.encode()).hexdigest()}.txt"
        if key not in self._unsaved and not path.exists():
            return
        self._unsaved[key] = None
        try:
            with lock_operations_file(path.with_suffix(".lock")):
                path.unlink(missing_ok=True)
                del self._unsaved[key]
        except OSError:
            logger.warning("디스코드 알림 상태를 지우지 못했습니다.")
