"""Performs first-time YouTube OAuth outside the GUI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class OAuthSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class YouTubeDisconnectWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = OAuthSignals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import revoke_youtube
            revoke_youtube(CredentialVault())
            self.signals.completed.emit(None)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class YouTubeOAuthWorker(QRunnable):
    def __init__(self, client_file: str):
        super().__init__()
        self.client_file = client_file
        self.signals = OAuthSignals()

    @Slot()
    def run(self):
        try:
            from services.live_clipper.secrets import CredentialVault
            from services.live_clipper.youtube import connected_channel, youtube_service
            vault = CredentialVault()
            service = youtube_service(self.client_file, vault)
            self.signals.completed.emit(connected_channel(service))
        except Exception as exc:
            self.signals.failed.emit(str(exc))
