"""Main application window: sidebar + stacked pages, wired to the shared
settings/queue/history stores."""
from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from backend.services.history_store import HistoryStore

from core.cookies import CookieExtractionError, resolve_cookies_path
from core.paths import asset_path
from core.queue_manager import QueueManager
from core.settings_store import SettingsStore
from services.live_clipper.config import LiveClipperSettings
from ui.pages.history_page import HistoryPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.home_page import HomePage
from ui.pages.auto_clipper_page import AutoClipperPage
from ui.pages.studio_page import StudioPage
from ui.pages.queue_page import QueuePage
from ui.pages.settings_page import SettingsPage
from ui.theme import build_qss
from ui.widgets.sidebar import Sidebar
from ui.widgets.toast import ToastHost

PAGE_ORDER = ["dashboard", "home", "clipper", "studio", "queue", "history", "settings"]


class MainWindow(QMainWindow):
    def __init__(self, settings_store: SettingsStore, history_store: HistoryStore):
        super().__init__()
        self._settings_store = settings_store
        self._history_store = history_store
        self._live_settings = LiveClipperSettings()
        self._live_page = None
        self._page_keys = list(PAGE_ORDER)
        self._active_page_key = "dashboard"

        self.setWindowTitle("StreamCarnia")
        icon_path = asset_path("logo.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1180, 800)
        self.setMinimumSize(900, 620)

        def cookies_provider():
            try:
                return resolve_cookies_path(self._settings_store.get())
            except CookieExtractionError:
                return None

        self._queue_manager = QueueManager(
            settings_store=settings_store,
            history_store=history_store,
            ffmpeg_path_provider=lambda: self._settings_store.ffmpeg_path,
            cookies_path_provider=cookies_provider,
        )
        self._queue_manager.item_finished.connect(lambda _item: self._history_page.refresh())

        root = QWidget()
        root.setObjectName("RootWindow")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_selected.connect(self._on_page_selected)
        root_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.home_page = HomePage(settings_store, self._queue_manager)
        self.clipper_page = AutoClipperPage(
            settings_store,
            lambda media_root=None: resolve_cookies_path(self._settings_store.get(), media_root),
        )
        self.studio_page = StudioPage(settings_store)
        self.queue_page = QueuePage(self._queue_manager)
        self._history_page = HistoryPage(history_store)
        self.settings_page = SettingsPage(settings_store)
        self.queue_page.download_requested.connect(lambda: self._on_page_selected("home"))
        self._history_page.download_requested.connect(lambda: self._on_page_selected("home"))
        self.dashboard_page = DashboardPage(history_store, self._queue_manager)
        self.dashboard_page.set_studio_page(self.studio_page)
        self.dashboard_page.navigate.connect(self._on_page_selected)
        self.dashboard_page.activity_selected.connect(self._on_dashboard_activity)
        self._queue_manager.item_finished.connect(lambda _item: self.dashboard_page.refresh())
        self.clipper_page.task_progress.connect(lambda event: self.dashboard_page.report_task(**event))
        self.clipper_page.task_finished.connect(lambda: self.dashboard_page.finish_task("auto-clippr"))
        self.studio_page.task_progress.connect(lambda event: self.dashboard_page.report_task(**event))
        self.studio_page.task_finished.connect(lambda: self.dashboard_page.finish_task("clip-studio"))

        self.home_page.toast.connect(self._show_toast)
        self.home_page.download_started.connect(lambda: self._on_page_selected("queue"))
        self.settings_page.theme_changed.connect(self._apply_theme)
        self.settings_page.queue_settings_changed.connect(self._queue_manager.refresh_concurrency)
        self.settings_page.live_settings_changed.connect(self._set_live_page_enabled)

        for page in (self.dashboard_page, self.home_page, self.clipper_page, self.studio_page,
                     self.queue_page, self._history_page, self.settings_page):
            self.stack.addWidget(page)

        self._set_live_page_enabled(self._live_settings.get().enabled)
        self._on_page_selected("dashboard")

        self._toast_host = ToastHost(self)
        self._toast_host.move(self.width() - 340, 20)
        self._toast_host.hide()

        self._apply_theme(settings_store.get().accent)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._toast_host.move(self.width() - 340, 20)
        self.sidebar.set_compact(self.width() < 1080)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Request cancellation of any in-flight downloads so background
        # worker threads wind down cleanly instead of touching UI/signal
        # objects after the window is gone.
        self._queue_manager.cancel_all()
        self.clipper_page.cancel()
        self.studio_page.shutdown()
        if self._live_page:
            self._live_page.shutdown()
        QThreadPool.globalInstance().waitForDone(20000)
        super().closeEvent(event)

    def _on_page_selected(self, key: str) -> None:
        if key not in self._page_keys:
            return
        index = self._page_keys.index(key)
        self.stack.setCurrentIndex(index)
        self._active_page_key = key
        self.sidebar.select(key)
        if key == "history":
            self._history_page.refresh()
        elif key == "dashboard":
            self.dashboard_page.refresh()

    def _on_dashboard_activity(self, page: str, record_id: str) -> None:
        self._on_page_selected(page)
        if page == "history":
            self._history_page.focus_entry(record_id)
        elif page == "studio":
            self.studio_page.open_clip(record_id)

    def _set_live_page_enabled(self, enabled: bool) -> None:
        if enabled and self._live_page is None:
            from ui.pages.live_auto_clipper_page import LiveAutoClipperPage
            self._live_page = LiveAutoClipperPage(self._settings_store)
            self._live_page.task_progress.connect(lambda event: self.dashboard_page.report_task(**event))
            self._live_page.task_finished.connect(lambda: self.dashboard_page.finish_task("live-monitor"))
            self.stack.addWidget(self._live_page)
            self._page_keys.append("live")
        elif not enabled and self._live_page is not None:
            if self._active_page_key == "live":
                self._on_page_selected("settings")
            self._live_page.shutdown()
            self.stack.removeWidget(self._live_page)
            self._live_page.deleteLater()
            self._live_page = None
            self._page_keys.remove("live")
        self.sidebar.set_live_enabled(enabled)
        self.dashboard_page.set_live_enabled(enabled)

    def _apply_theme(self, accent_name: str) -> None:
        self.setStyleSheet(build_qss(accent_name))
        self._settings_store.update(accent=accent_name)
        self.studio_page.set_accent(accent_name)

    def _show_toast(self, message: str, kind: str) -> None:
        self._toast_host.show_toast(message, kind)
