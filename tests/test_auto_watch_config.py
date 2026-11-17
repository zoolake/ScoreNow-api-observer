from pathlib import Path

import pytest

from scorenow_api_observer.auto_watch.config import (
    InvalidAutoWatchConfigError,
    load_auto_watch_config,
)


def test_load_auto_watch_config_classifies_all_documented_statuses() -> None:
    config = load_auto_watch_config()

    assert config.classify_time_status(0) == "waiting_to_start"
    assert config.classify_time_status(1) == "inplay"
    assert config.classify_time_status(2) == "waiting_to_start"
    assert config.classify_time_status(3) == "ended"
    for time_status in (4, 5, 6, 8, 9, 11, 12, 99):
        assert config.classify_time_status(time_status) == "closing"
    for time_status in (7, 10):
        assert config.classify_time_status(time_status) == "temporarily_stopped"
    assert config.classify_time_status(13) == "unknown"
    assert config.classify_time_status(None) == "unknown"


def test_load_auto_watch_config_rejects_overlapping_statuses(tmp_path: Path) -> None:
    config_path = tmp_path / "auto_watch.yaml"
    config_path.write_text(
        """
status_policies:
  waiting_to_start:
    statuses: [0, 2]
    max_minutes_after_scheduled_at: 120
  temporarily_stopped:
    statuses: [2, 7, 10]
    max_continuous_minutes: 120
  closing:
    statuses: [4, 5]
    followup_minutes: 15
  unknown:
    max_continuous_minutes: 60
ended:
  status: 3
  followup_minutes: 15
request_limits:
  soccer_per_hour: 3600
  baseball_per_hour: 3600
  warning_percent: 80
  danger_percent: 90
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(InvalidAutoWatchConfigError, match="중복 등록"):
        load_auto_watch_config(config_path)
