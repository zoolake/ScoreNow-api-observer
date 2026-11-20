import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from scorenow_api_observer.auto_watch.status import KST, Sport
from scorenow_api_observer.discord_webhook import (
    DISCORD_WEBHOOK_ENV,
    DiscordAttachment,
    DiscordSender,
)
from scorenow_api_observer.operations_storage import (
    lock_operations_file,
    write_operations_text,
)
from scorenow_api_observer.reporting.daily_operations import (
    DailyOperations,
    collect_daily_operations,
)

DAILY_REPORT_DIRECTORY = Path("reports/daily-operations")
SPORT_LABELS: dict[Sport, str] = {"football": "축구", "baseball": "야구"}
ENDPOINT_LABELS = {
    "/v1/event/view": "Event View",
    "/v3/events/upcoming": "Upcoming",
    "/v2/event/odds": "Event Odds",
}


@dataclass(frozen=True)
class DailyPublication:
    path: Path
    outcome: Literal["published", "already_published", "failed"]


def render_daily_report(report: DailyOperations) -> str:
    title = f"{report.target_date} KST 일간 운영 보고서"
    endpoints = " · ".join(
        f"{ENDPOINT_LABELS[endpoint]} {count}회"
        for endpoint, count in report.endpoint_counts.items()
    )
    peaks = " · ".join(
        (
            f"{label} {peak.percent:.1f}% ({peak.count:,}/{peak.limit:,}회, "
            f"{peak.window_start.astimezone(KST):%H:%M} 시작)"
        )
        for sport, label in SPORT_LABELS.items()
        if (peak := report.hourly_peaks.get(sport)) is not None
    )
    summary = [
        f"- 요청 시도 {sum(report.endpoint_counts.values())}회 ({endpoints})",
        f"- 시간당 최고 사용률 {peaks or '확인 불가'}",
        (
            f"- HTTP 오류 {report.http_errors.total()}회 · "
            f"연결 실패 {report.connection_failures}회 · "
            f"완료 기록 없음 {report.unfinished_requests}회"
        ),
        f"- 경기별 예외 종료 {len(report.exceptions)}건",
    ]
    if report.failures:
        summary.insert(0, f"⚠️ 부분 집계 · 읽기 실패 {len(report.failures)}건")

    lines = [f"# {title}", "", *summary, "", "## HTTP 오류", ""]
    lines.extend(
        [
            f"- HTTP {code} · {count}회"
            for code, count in sorted(report.http_errors.items())
        ]
        or ["- 기록 없음"]
    )
    lines.extend(["", "## 상태별 경기 수집 예외 종료", ""])
    lines.extend(
        [
            f"- time_status={status if status is not None else '미확인'} · {count}건"
            for status, count in sorted(
                report.exception_counts.items(),
                key=lambda item: (item[0] is None, item[0] or 0),
            )
        ]
        or ["- 기록 없음"]
    )
    if report.exceptions:
        lines.extend(["", "### 예외 상세", ""])
        for item in report.exceptions:
            record = item.record
            status = record.stop_time_status
            league = " ".join(record.league_label.split())
            event_id = " ".join(record.event_id.split())
            lines.append(
                f"- 경기 {event_id} · {league} · "
                f"{record.stopped_at.astimezone(KST):%Y-%m-%d %H:%M:%S} KST · "
                f"time_status={status if status is not None else '미확인'}"
            )
    if report.failures:
        lines.extend(["", "## 기록 읽기 실패", ""])
        counts: dict[str, int] = {}
        for failure in report.failures:
            counts[failure.area] = counts.get(failure.area, 0) + 1
        lines.extend(f"- {area} · {count}건" for area, count in counts.items())
    lines.extend(
        [
            "",
            (
                "종목별 사용률은 로컬 요청 기록과 현재 설정의 시간당 한도를 기준으로 "
                "계산했습니다. 혼합·분류 불가 요청은 두 종목에 포함합니다."
            ),
            "",
        ]
    )

    text = "\n".join(lines)
    for secret in (
        os.getenv(DISCORD_WEBHOOK_ENV, "").strip(),
        os.getenv("BETS_API_TOKEN", ""),
    ):
        if secret:
            text = text.replace(secret, "[숨김]")
    return text


def publish_daily_report(
    target_date: date,
    *,
    sender: DiscordSender | None,
    manual: bool = False,
    base_directory: Path = DAILY_REPORT_DIRECTORY,
    collect: Callable[[date], DailyOperations] = collect_daily_operations,
) -> DailyPublication:
    report_path = base_directory / f"{target_date}.md"
    receipt_path = report_path.with_suffix(".published")
    with lock_operations_file(report_path.with_suffix(".lock")):
        if not manual and receipt_path.is_file():
            return DailyPublication(report_path, "already_published")
        try:
            markdown = report_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            markdown = render_daily_report(collect(target_date))
            write_operations_text(report_path, markdown)

        if sender is None:
            return DailyPublication(report_path, "failed")
        heading, summary, _ = markdown.split("\n\n", maxsplit=2)
        message_id = sender(
            heading.removeprefix("# "),
            summary,
            attachment=DiscordAttachment(report_path.name, markdown.encode("utf-8")),
        )
        if message_id is None:
            return DailyPublication(report_path, "failed")
        write_operations_text(receipt_path, f"{message_id}\n")
        return DailyPublication(report_path, "published")
