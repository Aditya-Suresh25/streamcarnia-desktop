"""Creator workspace landing page backed by existing download/task state."""
from __future__ import annotations

from datetime import datetime
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.widgets.buttons import GhostButton, PrimaryButton
from ui.widgets.page_layout import configure_page_scroll


class DashboardPage(QWidget):
    navigate = Signal(str)
    activity_selected = Signal(str, str)

    def __init__(self, history_store, queue_manager, parent=None):
        super().__init__(parent)
        self._history = history_store
        self._queue = queue_manager
        self._studio_page = None
        self._live_enabled = False
        self._render_tasks: dict[str, dict] = {}
        self.setObjectName("DashboardPage")

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self._layout = QVBoxLayout(content)
        configure_page_scroll(scroll, content)
        self._layout.setContentsMargins(30, 26, 30, 30)
        self._layout.setSpacing(18)

        self._build_header()
        self._build_stats()
        self._build_work_area()
        self._build_activity()
        self._layout.addStretch(1)

        queue_manager.item_added.connect(self._queue_changed)
        queue_manager.item_updated.connect(self._queue_changed)
        queue_manager.item_finished.connect(self._queue_finished)
        self.refresh()

    def _build_header(self):
        hero = QFrame()
        hero.setObjectName("DashboardHero")
        row = QHBoxLayout(hero)
        row.setContentsMargins(24, 20, 24, 20)
        copy = QVBoxLayout()
        copy.setSpacing(7)
        eyebrow = QLabel("YOUR CREATOR WORKSPACE")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("Welcome to your creator workspace.")
        title.setObjectName("DashboardWelcome")
        subtitle = QLabel("See what is moving, revisit recent work, or start creating something new.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        copy.addWidget(eyebrow)
        copy.addWidget(title)
        copy.addWidget(subtitle)
        row.addLayout(copy, 1)
        self.new_download = PrimaryButton("Download a stream")
        self.new_download.clicked.connect(lambda: self.navigate.emit("home"))
        row.addWidget(self.new_download, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hero_row = row
        self._layout.addWidget(hero)

    def _build_stats(self):
        self._layout.addWidget(self._section_title("WORKSPACE OVERVIEW", "Your library and current workload"))
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)
        self.stat_buttons = {}
        for key, title, hint, target in (
            ("total_downloads", "Total downloads", "Across your download history", "history"),
            ("completed_tasks", "Completed tasks", "Successfully completed downloads", "history"),
            ("processing_tasks", "Processing now", "Downloads and active renders", "processing"),
        ):
            button = QPushButton()
            button.setObjectName("DashboardStat")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            button.setMinimumHeight(108)
            button.setToolTip(f"Open {target}")
            col = QVBoxLayout(button)
            col.setContentsMargins(16, 13, 16, 13)
            col.setSpacing(3)
            label = QLabel(title)
            label.setObjectName("DashboardStatLabel")
            number = QLabel("—")
            number.setObjectName("DashboardStatValue")
            hint_label = QLabel(hint)
            hint_label.setObjectName("Faint")
            hint_label.setWordWrap(True)
            col.addWidget(label)
            col.addWidget(number)
            col.addWidget(hint_label)
            if target == "processing":
                button.clicked.connect(self._open_processing)
            else:
                button.clicked.connect(lambda _checked=False, page=target: self.navigate.emit(page))
            self.stats_row.addWidget(button, 1)
            self.stat_buttons[key] = (button, number)
        self._layout.addLayout(self.stats_row)

    @staticmethod
    def _section_title(title: str, subtitle: str | None = None) -> QWidget:
        widget = QWidget()
        col = QVBoxLayout(widget)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("SectionHeader")
        col.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Faint")
            sub.setWordWrap(True)
            sub.setMinimumWidth(0)
            col.addWidget(sub)
        return widget

    def _build_work_area(self):
        self.work_columns = QHBoxLayout()
        columns = self.work_columns
        columns.setSpacing(14)
        self.active_panel = QFrame()
        self.active_panel.setObjectName("Card")
        active = QVBoxLayout(self.active_panel)
        active.setContentsMargins(17, 15, 17, 16)
        active.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(self._section_title("IN PROGRESS", "Live updates from current workers"), 1)
        self.active_count = QLabel("0")
        self.active_count.setObjectName("StatusBadge")
        self.active_count.setProperty("state", "active")
        head.addWidget(self.active_count, 0, Qt.AlignmentFlag.AlignTop)
        active.addLayout(head)
        self.active_content = QVBoxLayout()
        self.active_content.setSpacing(8)
        active.addLayout(self.active_content)
        self.active_empty = self._empty_message("Nothing is processing right now.", "Start a download or render and its progress will appear here.")
        active.addWidget(self.active_empty)
        empty_actions = QHBoxLayout()
        empty_download = GhostButton("Download stream")
        empty_download.clicked.connect(lambda: self.navigate.emit("home"))
        empty_clipper = GhostButton("Create clips")
        empty_clipper.clicked.connect(lambda: self.navigate.emit("clipper"))
        empty_actions.addWidget(empty_download)
        empty_actions.addWidget(empty_clipper)
        empty_actions.addStretch(1)
        active.addLayout(empty_actions)
        self.active_empty_buttons = (empty_download, empty_clipper)
        self.view_queue = GhostButton("Open queue")
        self.view_queue.clicked.connect(lambda: self.navigate.emit("queue"))
        active.addWidget(self.view_queue, 0, Qt.AlignmentFlag.AlignLeft)

        action_panel = QFrame()
        action_panel.setObjectName("DashboardStudioPanel")
        actions = QVBoxLayout(action_panel)
        actions.setContentsMargins(18, 16, 18, 16)
        actions.setSpacing(10)
        actions.addWidget(self._section_title("MAKE YOUR NEXT CLIP", "Choose a workflow to jump into"))
        action_grid = QGridLayout()
        self.action_grid = action_grid
        action_grid.setHorizontalSpacing(9)
        action_grid.setVerticalSpacing(9)
        action_grid.setColumnStretch(0, 1)
        action_grid.setColumnStretch(1, 1)
        self.quick_buttons = {}
        for index, (key, text, description) in enumerate((
            ("clipper", "Auto Clippr", "Find moments in a VOD"),
            ("studio", "Clip Studio", "Edit and publish clips"),
            ("live", "Live Auto Clipper", "Monitor a livestream"),
            ("home", "Download Stream", "Save a video locally"),
        )):
            button = QPushButton(f"{text}   ›\n{description}")
            button.setObjectName("DashboardAction")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(68)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            button.setToolTip(description)
            button.clicked.connect(lambda _checked=False, page=key: self.navigate.emit(page))
            self.quick_buttons[key] = button
            action_grid.addWidget(button, index // 2, index % 2)
        actions.addLayout(action_grid)
        columns.addWidget(self.active_panel, 1)
        columns.addWidget(action_panel, 1)
        self._layout.addLayout(columns)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        compact = self.width() < 1180
        self.work_columns.setDirection(QHBoxLayout.Direction.TopToBottom if compact else QHBoxLayout.Direction.LeftToRight)
        self.stats_row.setDirection(QHBoxLayout.Direction.TopToBottom if self.width() < 700 else QHBoxLayout.Direction.LeftToRight)
        self.hero_row.setDirection(QHBoxLayout.Direction.TopToBottom if compact else QHBoxLayout.Direction.LeftToRight)
        self.activity_header.setDirection(QHBoxLayout.Direction.TopToBottom if compact else QHBoxLayout.Direction.LeftToRight)

    def _build_activity(self):
        header = QHBoxLayout()
        header.addWidget(self._section_title("RECENT ACTIVITY", "Your latest downloads and studio work"), 1)
        self.view_history = GhostButton("View history")
        self.view_history.clicked.connect(lambda: self.navigate.emit("history"))
        header.addWidget(self.view_history)
        self.activity_header = header
        self._layout.addLayout(header)
        self.activity_panel = QFrame()
        self.activity_panel.setObjectName("Card")
        self.activity_list = QVBoxLayout(self.activity_panel)
        self.activity_list.setContentsMargins(10, 9, 10, 9)
        self.activity_list.setSpacing(4)
        self.activity_empty = self._empty_message("Your workspace is ready for its first project.", "Download a stream or bring a local video into Clip Studio to get started.")
        start = GhostButton("Get started with a download")
        start.clicked.connect(lambda: self.navigate.emit("home"))
        self.activity_empty.layout().addWidget(start, 0, Qt.AlignmentFlag.AlignLeft)
        self.activity_list.addWidget(self.activity_empty)
        self._layout.addWidget(self.activity_panel)

    @staticmethod
    def _empty_message(title: str, description: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("DashboardEmpty")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 13, 12, 13)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("DashboardEmptyTitle")
        body = QLabel(description)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        return frame

    def set_live_enabled(self, enabled: bool):
        self._live_enabled = bool(enabled)
        self.quick_buttons["live"].setVisible(self._live_enabled)
        for key, button in self.quick_buttons.items():
            self.action_grid.removeWidget(button)
        if self._live_enabled:
            positions = {"clipper": (0, 0), "studio": (0, 1), "live": (1, 0), "home": (1, 1)}
        else:
            positions = {"clipper": (0, 0), "studio": (0, 1)}
            self.action_grid.addWidget(self.quick_buttons["home"], 1, 0, 1, 2)
        for key, position in positions.items():
            self.action_grid.addWidget(self.quick_buttons[key], *position)

    def set_studio_page(self, page):
        self._studio_page = page
        self.refresh()

    def report_task(self, id: str, title: str, percent: int, message: str):
        self._render_tasks[id] = {"title": title, "percent": max(0, min(100, int(percent))), "message": message}
        self._refresh_tasks()

    def finish_task(self, task_id: str):
        self._render_tasks.pop(task_id, None)
        self._refresh_tasks()
        self.refresh()

    def _queue_changed(self, item):
        self._refresh_tasks()

    def _queue_finished(self, _item):
        self._refresh_tasks()
        self.refresh()

    def refresh(self):
        # Query the existing history table directly through its configured DB path.
        # The sibling backend package is shared with the parent project and is not
        # part of this desktop source checkout, so avoid changing its schema/API.
        with sqlite3.connect(self._history._db_path) as conn:
            row = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0)
                   FROM history"""
            ).fetchone()
        counts = {"total_downloads": int(row[0]), "completed_tasks": int(row[1])}
        values = {**counts, "processing_tasks": len(self._queue.active_items()) + len(self._render_tasks)}
        for key, value in values.items():
            self.stat_buttons[key][1].setText(str(value))
        self._refresh_tasks()
        self._refresh_activity()

    def _open_processing(self):
        if self._queue.active_items():
            target = "queue"
        else:
            targets = {"auto-clippr": "clipper", "clip-studio": "studio", "live-monitor": "live"}
            target = next((targets[key] for key in targets if key in self._render_tasks), "queue")
        self.navigate.emit(target)

    def _refresh_tasks(self):
        while self.active_content.count():
            item = self.active_content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = []
        for item in self._queue.active_items():
            entries.append((item.title or "Downloading video", int(item.percent or 0),
                            item.message or getattr(item.stage, "value", str(item.stage))))
        entries.extend((data["title"], data["percent"], data["message"]) for data in self._render_tasks.values())
        self.active_count.setText(str(len(entries)))
        self.stat_buttons["processing_tasks"][1].setText(str(len(entries)))
        self.active_empty.setVisible(not entries)
        for button in self.active_empty_buttons:
            button.setVisible(not entries)
        self.view_queue.setVisible(bool(entries))
        for title, percent, message in entries:
            row = QFrame()
            row.setObjectName("DashboardTask")
            col = QVBoxLayout(row)
            col.setContentsMargins(10, 8, 10, 8)
            col.setSpacing(4)
            top = QHBoxLayout()
            name = QLabel(title)
            name.setObjectName("DashboardTaskTitle")
            name.setWordWrap(True)
            state = QLabel(f"{percent}%")
            state.setObjectName("DashboardTaskPercent")
            top.addWidget(name, 1)
            top.addWidget(state)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(percent)
            bar.setTextVisible(False)
            detail = QLabel(message)
            detail.setObjectName("Faint")
            detail.setWordWrap(True)
            col.addLayout(top)
            col.addWidget(bar)
            col.addWidget(detail)
            self.active_content.addWidget(row)

    def _refresh_activity(self):
        self.activity_empty.hide()
        while self.activity_list.count():
            item = self.activity_list.takeAt(0)
            if item.widget() and item.widget() is not self.activity_empty:
                item.widget().deleteLater()
        entries = []
        for entry in self._history.list_recent(6):
            entries.append((entry.date, entry.title, f"Download · {entry.status}", "history", entry.id))
        if self._studio_page:
            for clip in self._studio_page.recent_clips(6):
                entries.append((clip.get("created_at", ""), clip.get("title") or "Untitled clip",
                                f"Clip Studio · {clip.get('aspect_ratio', 'rendered')}", "studio", clip.get("id", "")))
        entries.sort(key=lambda row: row[0], reverse=True)
        entries = entries[:6]
        if not entries:
            self.activity_list.addWidget(self.activity_empty)
            self.activity_empty.show()
            return
        for date_value, title, detail, page, record_id in entries:
            button = QPushButton()
            button.setObjectName("DashboardActivity")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row = QHBoxLayout(button)
            row.setContentsMargins(12, 10, 12, 10)
            copy = QVBoxLayout()
            heading = QLabel(title)
            heading.setObjectName("DashboardActivityTitle")
            heading.setWordWrap(True)
            sub = QLabel(f"{detail}  ·  {self._format_date(date_value)}")
            sub.setObjectName("Faint")
            copy.addWidget(heading)
            copy.addWidget(sub)
            row.addLayout(copy, 1)
            affordance = QLabel("›")
            affordance.setObjectName("DashboardActivityArrow")
            row.addWidget(affordance)
            button.clicked.connect(lambda _checked=False, p=page, rid=record_id: self.activity_selected.emit(p, rid))
            self.activity_list.addWidget(button)

    @staticmethod
    def _format_date(value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%b %d · %I:%M %p")
        except (TypeError, ValueError):
            return value[:16].replace("T", " ")
