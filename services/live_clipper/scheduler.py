"""Local-window scheduling with hourly pacing and YouTube quota safeguards."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import calendar

from .youtube import YouTubeUploader

HOURLY_UPLOAD_LIMIT = 6
# YouTube's default videos.insert quota bucket is 100 uploads per project day.
DAILY_UPLOAD_LIMIT = 100
UPLOAD_EARLY_MINUTES = 15
SLOT_INTERVAL_MINUTES = 10


def _youtube_quota_date(value: datetime):
    """Get the YouTube quota date without requiring a Windows tzdata install."""
    utc = value.astimezone(timezone.utc)
    year = utc.year
    march_calendar = calendar.monthcalendar(year, 3)
    november_calendar = calendar.monthcalendar(year, 11)
    march_sundays = [week[calendar.SUNDAY] for week in march_calendar if week[calendar.SUNDAY]]
    november_sundays = [week[calendar.SUNDAY] for week in november_calendar if week[calendar.SUNDAY]]
    # US Pacific DST begins at 10:00 UTC on the second Sunday in March and
    # ends at 09:00 UTC on the first Sunday in November.
    dst_start = datetime(year, 3, march_sundays[1], 10, tzinfo=timezone.utc)
    dst_end = datetime(year, 11, november_sundays[0], 9, tzinfo=timezone.utc)
    offset = timedelta(hours=-7 if dst_start <= utc < dst_end else -8)
    return (utc + offset).date()


def _minutes(value: str) -> int:
    h, m = (int(part) for part in value.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Schedule times must use HH:MM")
    return h * 60 + m


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def schedule_time(now: datetime, start: str, end: str, ordinal: int) -> datetime:
    """Return the legacy six-per-day evenly spaced slot for API compatibility."""
    if not 1 <= ordinal <= 6:
        raise ValueError("Legacy daily schedule has six sample slots")
    start_minute, end_minute = _minutes(start), _minutes(end)
    if end_minute <= start_minute:
        raise ValueError("Schedule end must be later than its start on the same day")
    slot_minute = start_minute + (end_minute - start_minute) * ordinal / 7
    hour, minute = divmod(round(slot_minute), 60)
    if minute == 60:
        hour, minute = hour + 1, 0
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class UploadScheduler:
    def __init__(self, store, uploader: YouTubeUploader | None, now_provider=None):
        self.store = store
        self.uploader = uploader
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    def approve_and_schedule(self, job_id: str, start: str, end: str) -> datetime:
        jobs = self.store.list_jobs()
        if not any(item["id"] == job_id for item in jobs):
            raise KeyError(job_id)
        current = self.now_provider()
        start_minute, end_minute = _minutes(start), _minutes(end)
        if end_minute <= start_minute:
            raise ValueError("Schedule end must be later than its start on the same day")

        scheduled = []
        for job in jobs:
            value = job["data"].get("scheduled_at")
            if value:
                try:
                    scheduled.append(_parse_time(value).astimezone(current.tzinfo))
                except (ValueError, TypeError):
                    continue
        scheduled_hours = Counter((item.date(), item.hour) for item in scheduled)
        scheduled_days = Counter(item.date() for item in scheduled)
        existing_times = set(scheduled)

        when = None
        for day_offset in range(366):
            day = (current + timedelta(days=day_offset)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            if scheduled_days[day.date()] >= DAILY_UPLOAD_LIMIT:
                continue
            for minute_of_day in range(start_minute, end_minute, SLOT_INTERVAL_MINUTES):
                hour, minute = divmod(minute_of_day, 60)
                slot = day.replace(hour=hour, minute=minute)
                if slot <= current + timedelta(minutes=UPLOAD_EARLY_MINUTES):
                    continue
                if slot in existing_times:
                    continue
                if scheduled_hours[(slot.date(), slot.hour)] >= HOURLY_UPLOAD_LIMIT:
                    continue
                when = slot
                break
            if when:
                break
        if when is None:
            raise RuntimeError("No schedule slot is available in the next year")
        self.store.update(job_id, "scheduled", {"approved": True, "scheduled_at": when.isoformat()})
        return when

    def upload_due(self, job_id: str) -> str | None:
        return self._upload(job_id, require_due=True)

    def upload_now(self, job_id: str) -> str | None:
        """Upload a just-approved Studio job now, still honoring quota safeguards."""
        return self._upload(job_id, require_due=False)

    def _upload(self, job_id: str, require_due: bool) -> str | None:
        jobs = self.store.list_jobs()
        job = next((item for item in jobs if item["id"] == job_id), None)
        if job is None:
            raise KeyError(job_id)
        if job["state"] != "scheduled" or not job["data"].get("approved"):
            raise RuntimeError("Clip is not approved and scheduled")
        now = self.now_provider()
        publish_at = _parse_time(job["data"]["scheduled_at"])
        due = publish_at - timedelta(minutes=UPLOAD_EARLY_MINUTES)
        if require_due and now < due:
            return None
        if self.uploader is None:
            raise RuntimeError("YouTube OAuth is not configured")

        uploaded = []
        for item in jobs:
            value = item["data"].get("uploaded_at")
            if item["state"] == "uploaded" and value:
                try:
                    uploaded.append(_parse_time(value))
                except (ValueError, TypeError):
                    continue
        local_hour = sum(1 for value in uploaded if value.astimezone(now.tzinfo).replace(
            minute=0, second=0, microsecond=0) == now.replace(minute=0, second=0, microsecond=0))
        quota_date = _youtube_quota_date(now)
        quota_day = sum(1 for value in uploaded if _youtube_quota_date(value) == quota_date)
        if local_hour >= HOURLY_UPLOAD_LIMIT:
            raise RuntimeError("The six-upload-per-hour limit has been reached")
        if quota_day >= DAILY_UPLOAD_LIMIT:
            raise RuntimeError("YouTube's 100-upload daily quota safeguard has been reached")

        # Persist the in-flight state before making the non-idempotent insert.
        # If the process dies after Google accepts the upload but before the ID
        # is saved, surface an explicit unknown state instead of retrying and
        # silently creating a duplicate.
        self.store.update(job_id, "uploading", {"upload_started_at": now.isoformat()})
        try:
            video_id = self.uploader.upload(job["data"]["file_path"], job["data"]["metadata"],
                                            publish_at.isoformat())
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            state = "failed" if status_code and 400 <= status_code < 500 else "unknown"
            self.store.update(job_id, state, error=str(exc)[:500])
            raise
        self.store.update(job_id, "uploaded", {"youtube_video_id": video_id, "uploaded_at": now.isoformat()})
        return video_id
