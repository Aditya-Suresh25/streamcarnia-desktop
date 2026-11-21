"""Background Gemini and publishing work for the local Studio catalog."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class MetadataVariantsWorker(QRunnable):
    def __init__(self, transcript: str, source_title: str, tone: str, language: str):
        super().__init__()
        self.transcript, self.source_title = transcript, source_title
        self.tone, self.language = tone, language
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.metadata import generate_metadata_variations
            from services.live_clipper.secrets import CredentialVault
            api_key = CredentialVault().get("gemini.api_key")
            result = generate_metadata_variations(self.transcript, self.source_title, api_key,
                self.tone, self.language, count=3)
            self.signals.completed.emit(result)
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:400]}")


class YouTubeAccountWorker(QRunnable):
    def __init__(self, oauth_client_file: str):
        super().__init__()
        self.oauth_client_file = oauth_client_file
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import connected_channel, youtube_service
            service = youtube_service(self.oauth_client_file, CredentialVault())
            channel = connected_channel(service)
            avatar = b""
            if channel and channel.get("avatar_url"):
                import requests
                response = requests.get(channel["avatar_url"], timeout=15)
                response.raise_for_status()
                avatar = response.content
            self.signals.completed.emit({"channel": channel, "avatar": avatar})
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:400]}")


class UploadApprovedStudioWorker(QRunnable):
    def __init__(self, catalog_path: Path, job_id: str, oauth_client_file: str):
        super().__init__()
        self.catalog_path, self.job_id = Path(catalog_path), job_id
        self.oauth_client_file = oauth_client_file
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import YouTubeUploader, youtube_service
            from services.live_clipper.scheduler import UploadScheduler
            from services.studio.catalog import StudioCatalog
            from services.studio.publishing import StudioPublishStoreAdapter
            vault = CredentialVault()
            service = youtube_service(self.oauth_client_file, vault)
            scheduler = UploadScheduler(StudioPublishStoreAdapter(StudioCatalog(self.catalog_path)),
                                        YouTubeUploader(service))
            video_id = scheduler.upload_now(self.job_id)
            self.signals.completed.emit({"job_id": self.job_id, "video_id": video_id})
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:500]}")


class StudioScheduleUpdateWorker(QRunnable):
    def __init__(self, oauth_client_file: str, video_id: str, publish_at: str | None,
                 job_id: str, catalog_path: Path, cancel: bool = False):
        super().__init__()
        self.oauth_client_file, self.video_id = oauth_client_file, video_id
        self.publish_at, self.job_id, self.catalog_path, self.cancel = publish_at, job_id, Path(catalog_path), cancel
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import YouTubeUploader, youtube_service
            from services.studio.catalog import StudioCatalog
            service = youtube_service(self.oauth_client_file, CredentialVault())
            YouTubeUploader(service).update_schedule(self.video_id, self.publish_at)
            catalog = StudioCatalog(self.catalog_path)
            catalog.update_publish_job(self.job_id, "cancelled" if self.cancel else "scheduled",
                                       scheduled_at=self.publish_at)
            self.signals.completed.emit({"job_id": self.job_id, "cancelled": self.cancel,
                                         "scheduled_at": self.publish_at})
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:500]}")


class RefreshStudioPublishWorker(QRunnable):
    def __init__(self, oauth_client_file: str, catalog_path: Path):
        super().__init__()
        self.oauth_client_file, self.catalog_path = oauth_client_file, Path(catalog_path)
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import YouTubeUploader, youtube_service
            from services.studio.catalog import StudioCatalog
            catalog = StudioCatalog(self.catalog_path)
            uploader = YouTubeUploader(youtube_service(self.oauth_client_file, CredentialVault()))
            updated = []
            for job in catalog.list_publish_jobs():
                video_id = job.get("youtube_video_id")
                if not video_id or job["status"] in {"cancelled", "published"}:
                    continue
                status = uploader.status(video_id)
                if status and status["status"].get("privacyStatus") == "public":
                    catalog.update_publish_job(job["id"], "published")
                    updated.append(job["id"])
            self.signals.completed.emit(updated)
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:500]}")


class StudioThumbnailWorker(QRunnable):
    def __init__(self, oauth_client_file: str, video_id: str, thumbnail_path: Path):
        super().__init__()
        self.oauth_client_file, self.video_id = oauth_client_file, video_id
        self.thumbnail_path = Path(thumbnail_path)
        self.cancel_event = Event()
        self.signals = _Signals()

    def cancel(self):
        self.cancel_event.set()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import YouTubeUploader, youtube_service
            service = youtube_service(self.oauth_client_file, CredentialVault())
            YouTubeUploader(service).set_thumbnail_when_ready(self.video_id, self.thumbnail_path,
                                                               cancel_event=self.cancel_event)
            self.signals.completed.emit(self.video_id)
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {str(exc)[:400]}")
