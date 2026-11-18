"""Local-window scheduling and conservative six-uploads-per-day enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta
from .youtube import YouTubeUploader

DAILY_UPLOAD_LIMIT = 6
UPLOAD_EARLY_MINUTES = 15


def _minutes(value: str) -> int:
    h, m = (int(part) for part in value.split(":"))
    return h * 60 + m


def schedule_time(now: datetime, start: str, end: str, ordinal: int) -> datetime:
    """Return one of six evenly spaced slots, with one interval at each end."""
    if not 1 <= ordinal <= DAILY_UPLOAD_LIMIT:
        raise ValueError("Daily schedule has six slots")
    start_minute, end_minute = _minutes(start), _minutes(end)
    if end_minute <= start_minute:
        raise ValueError("Schedule end must be later than its start on the same day")
    slot_minute = start_minute + (end_minute - start_minute) * ordinal / (DAILY_UPLOAD_LIMIT + 1)
    hour = int(slot_minute // 60)
    minute = int(round(slot_minute % 60))
    if minute == 60:
        hour += 1
        minute = 0
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class UploadScheduler:
    def __init__(self, store, uploader: YouTubeUploader | None, now_provider=None):
        self.store = store
        self.uploader = uploader
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    def approve_and_schedule(self, job_id: str, start: str, end: str) -> datetime:
        jobs = self.store.list_jobs()
        target = next((item for item in jobs if item["id"] == job_id), None)
        if target is None:
            raise KeyError(job_id)
        current = self.now_provider()
        existing = []
        for job in jobs:
            value = job["data"].get("scheduled_at")
            if value:
                try:
                    existing.append(datetime.fromisoformat(value).astimezone(current.tzinfo))
                except ValueError:
                    continue
        when = None
        for day_offset in range(366):
            day = (current + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            used = {item.hour * 60 + item.minute for item in existing if item.date() == day.date()}
            for ordinal in range(1, DAILY_UPLOAD_LIMIT + 1):
                slot = schedule_time(day, start, end, ordinal)
                if slot > current + timedelta(minutes=UPLOAD_EARLY_MINUTES) and slot.hour * 60 + slot.minute not in used:
                    when = slot
                    break
            if when:
                break
        if when is None:
            raise RuntimeError("No schedule slot is available in the next year")
        self.store.update(job_id, "scheduled", {"approved": True, "scheduled_at": when.isoformat()})
        return when

    def upload_due(self, job_id: str) -> str | None:
        job = next((item for item in self.store.list_jobs() if item["id"] == job_id), None)
        if job is None:
            raise KeyError(job_id)
        if job["state"] != "scheduled" or not job["data"].get("approved"):
            raise RuntimeError("Clip is not approved and scheduled")
        now = self.now_provider()
        publish_at = datetime.fromisoformat(job["data"]["scheduled_at"])
        due = publish_at - timedelta(minutes=UPLOAD_EARLY_MINUTES)
        if now < due:
            return None
        if self.uploader is None:
            raise RuntimeError("YouTube OAuth is not configured")
        uploaded_at_day = now.date()
        uploads_today = sum(1 for item in self.store.list_jobs()
                            if item["state"] == "uploaded" and item["data"].get("uploaded_at") and
                            datetime.fromisoformat(item["data"]["uploaded_at"]).astimezone(now.tzinfo).date() == uploaded_at_day)
        if uploads_today >= DAILY_UPLOAD_LIMIT:
            raise RuntimeError("The six-upload daily upload limit has been reached")
        video_id = self.uploader.upload(job["data"]["file_path"], job["data"]["metadata"],
                                        publish_at.isoformat())
        self.store.update(job_id, "uploaded", {"youtube_video_id": video_id, "uploaded_at": now.isoformat()})
        return video_id
