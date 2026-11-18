"""Performs first-time YouTube OAuth outside the GUI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class OAuthSignals(QObject):
    completed = Signal()
    failed = Signal(str)


class YouTubeOAuthWorker(QRunnable):
    def __init__(self, client_file: str):
        super().__init__()
        self.client_file = client_file
        self.signals = OAuthSignals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import youtube_service
            vault = CredentialVault()
            youtube_service(self.client_file, vault)
            self.signals.completed.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
