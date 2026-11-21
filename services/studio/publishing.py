"""Studio scheduling helpers and an adapter for the existing upload scheduler."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from services.live_clipper.scheduler import _youtube_quota_date


def collection_schedule(start: date, publish_time: time, weekdays: set[int], frequency_days: int,
                        count: int, existing: list[dict] | None = None,
                        now: datetime | None = None, window_end: time | None = None) -> list[datetime]:
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise ValueError("Choose at least one valid publishing day.")
    if not 1 <= frequency_days <= 30:
        raise ValueError("Publishing frequency must be between 1 and 30 days.")
    if count < 1:
        raise ValueError("Select at least one clip to schedule.")
    now = now or datetime.now().astimezone()
    window_end = window_end or publish_time
    if window_end <= publish_time:
        raise ValueError("The publishing window must end later than it starts on the same day.")
    baseline = datetime.combine(start, publish_time, tzinfo=now.tzinfo)
    if baseline <= now + timedelta(minutes=15):
        raise ValueError("The first publishing time must be at least 15 minutes in the future.")
    existing_times = set()
    for job in existing or []:
        if job.get("scheduled_at") and job.get("status") not in {"cancelled", "failed"}:
            try:
                existing_times.add(datetime.fromisoformat(job["scheduled_at"]).astimezone(now.tzinfo))
            except (ValueError, TypeError):
                continue
    hourly = Counter((item.date(), item.hour) for item in existing_times)
    daily = Counter(_youtube_quota_date(item) for item in existing_times)
    scheduled: list[datetime] = []
    candidate = baseline
    ordinal = 0
    while len(scheduled) < count:
        minutes = (window_end.hour * 60 + window_end.minute) - (publish_time.hour * 60 + publish_time.minute)
        minute_of_day = publish_time.hour * 60 + publish_time.minute + round(minutes * (ordinal + 1) / (count + 1))
        hour, minute = divmod(minute_of_day, 60)
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for _ in range(366 * 2):
            if candidate.date() >= start and candidate.weekday() in weekdays and candidate > now + timedelta(minutes=15):
                hour_key = (candidate.date(), candidate.hour)
                quota_day = _youtube_quota_date(candidate)
                if (candidate not in existing_times and candidate not in scheduled
                        and hourly[hour_key] < 6 and daily[quota_day] < 100):
                    break
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=publish_time.hour, minute=publish_time.minute,
                                          second=0, microsecond=0)
        else:
            raise RuntimeError("Could not find an available collection schedule slot.")
        scheduled.append(candidate)
        existing_times.add(candidate)
        hourly[(candidate.date(), candidate.hour)] += 1
        daily[_youtube_quota_date(candidate)] += 1
        ordinal += 1
        candidate = candidate + timedelta(days=frequency_days)
        candidate = candidate.replace(hour=publish_time.hour, minute=publish_time.minute,
                                      second=0, microsecond=0)

    return scheduled


class StudioPublishStoreAdapter:
    """Expose Studio publish jobs to the already-used Live UploadScheduler."""
    def __init__(self, catalog):
        self.catalog = catalog

    def list_jobs(self) -> list[dict]:
        result = []
        for job in self.catalog.list_publish_jobs():
            state = job["status"]
            if state == "scheduled" and job.get("youtube_video_id"):
                state = "uploaded"
            data = {"approved": state in {"scheduled", "uploaded"},
                    "scheduled_at": job.get("scheduled_at"), "file_path": job.get("file_path"),
                    "metadata": job.get("metadata", {}), "youtube_video_id": job.get("youtube_video_id"),
                    "uploaded_at": job.get("uploaded_at")}
            result.append({"id": job["id"], "state": state, "data": data})
        return result

    def update(self, job_id: str, state: str, data: dict | None = None, error: str | None = None) -> None:
        data = data or {}
        stored_state = "scheduled" if state == "uploaded" else state
        self.catalog.update_publish_job(job_id, stored_state,
            youtube_video_id=data.get("youtube_video_id"), error=error,
            uploaded_at=data.get("uploaded_at"))
