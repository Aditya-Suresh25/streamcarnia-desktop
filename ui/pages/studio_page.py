"""Local-first Clip Studio, creator library, metadata editor, and publisher."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QTime, QTimer, QUrl, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QProgressBar, QScrollArea, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget, QPlainTextEdit, QSizePolicy,
)

from core.settings_store import SettingsStore
from services.live_clipper.config import LiveClipperSettings
from services.studio.catalog import StudioCatalog
from services.studio.media import extract_thumbnail
from services.studio.projects import StudioProjectStore
from services.studio.publishing import collection_schedule
from ui.effects import apply_card_shadow
from ui.widgets.buttons import GhostButton, PrimaryButton
from ui.widgets.facecam_selector import FacecamSelector
from ui.widgets.stack_layout_control import StackLayoutControl
from ui.widgets.page_layout import configure_page_scroll
from workers.clip_worker import ClipWorker
from workers.studio_workers import (
    MetadataVariantsWorker, RefreshStudioPublishWorker, StudioScheduleUpdateWorker,
    StudioThumbnailWorker, UploadApprovedStudioWorker, YouTubeAccountWorker,
)
from workers.studio_import_worker import StudioImportWorker
from workers.studio_discovery import StudioDiscoveryWorker
from workers.studio_timeline_thumbnails import StudioTimelineThumbnailWorker
from workers.studio_preview_proxy import StudioPreviewProxyWorker


class StudioPage(QWidget):
    task_progress = Signal(object)
    task_finished = Signal()

    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings = settings_store
        self._catalog: StudioCatalog | None = None
        self._workspace = Path()
        self._sources: list[dict] = []
        self._clips: list[dict] = []
        self._publish_jobs: list[dict] = []
        self._ranges: list[tuple[float, float]] = []
        self._active_clip_worker: ClipWorker | None = None
        self._active_preview_proxy: StudioPreviewProxyWorker | None = None
        self._preview_job_dir: Path | None = None
        self._preview_render_active = False
        self._active_import_worker: StudioImportWorker | None = None
        self._active_discovery_worker: StudioDiscoveryWorker | None = None
        self._active_timeline_thumbnail_worker: StudioTimelineThumbnailWorker | None = None
        self._import_pool = QThreadPool(self)
        self._import_pool.setMaxThreadCount(1)
        self._discovery_pool = QThreadPool(self)
        self._discovery_pool.setMaxThreadCount(1)
        self._timeline_thumbnail_pool = QThreadPool(self)
        self._timeline_thumbnail_pool.setMaxThreadCount(1)
        self._preview_pool = QThreadPool(self)
        self._preview_pool.setMaxThreadCount(1)
        self._project_store: StudioProjectStore | None = None
        self._active_project_id: str | None = None
        self._pending_qml_source_path: str | None = None
        self._publish_active = False
        self._metadata_variants: list[dict] = []
        self._active_thumbnail_workers: set[StudioThumbnailWorker] = set()
        self._oauth_pool = QThreadPool(self)
        self._oauth_pool.setMaxThreadCount(2)
        self._publish_pool = QThreadPool(self)
        self._publish_pool.setMaxThreadCount(1)
        self._thumbnail_pool = QThreadPool(self)
        self._thumbnail_pool.setMaxThreadCount(2)
        self._project_save_timer = QTimer(self)
        self._project_save_timer.setSingleShot(True)
        self._project_save_timer.setInterval(500)
        self._project_save_timer.timeout.connect(self._save_project_state)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        configure_page_scroll(scroll, content)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(14)

        eyebrow = QLabel("STREAMCARNIA STUDIO")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Clip Studio")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Build a local clip library, refine metadata, and schedule approved videos.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        workspace_card, workspace = self._section("STUDIO WORKSPACE")
        self.workspace_input = QLineEdit()
        self.choose_workspace_btn = GhostButton("Choose folder…")
        self.choose_workspace_btn.clicked.connect(self._choose_workspace)
        workspace_row = QHBoxLayout()
        workspace_row.addWidget(self.workspace_input, 1)
        workspace_row.addWidget(self.choose_workspace_btn)
        workspace.addWidget(QLabel("Library folder (source videos are referenced in place)"))
        workspace.addLayout(workspace_row)
        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Recent project"))
        self.project_combo = QComboBox()
        self.project_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        project_row.addWidget(self.project_combo, 1)
        self.open_project_btn = GhostButton("Open project")
        self.open_project_btn.clicked.connect(self._open_selected_project)
        project_row.addWidget(self.open_project_btn)
        self.relink_source_btn = GhostButton("Relink missing source…")
        self.relink_source_btn.clicked.connect(self._relink_active_project)
        self.relink_source_btn.hide()
        project_row.addWidget(self.relink_source_btn)
        self.project_save_label = QLabel("Autosave ready")
        self.project_save_label.setObjectName("Faint")
        self.project_save_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        project_row.addWidget(self.project_save_label)
        workspace.addLayout(project_row)
        layout.addWidget(workspace_card)

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.tabs.setUsesScrollButtons(True)
        self.clip_tab = self._build_clip_tab()
        self.library_tab = self._build_library_tab()
        self.publish_tab = self._build_publish_tab()
        self.tabs.addTab(self.clip_tab, "Clip Studio")
        self.tabs.addTab(self.library_tab, "Library & metadata")
        self.tabs.addTab(self.publish_tab, "Publish calendar")
        self.qml_studio_page = None
        try:
            from ui.studio_qml import StudioQmlPage
            self.qml_studio_page = StudioQmlPage(self._settings.get().accent, self)
            self.qml_studio_page.render_requested.connect(self._qml_render_requested)
            self.qml_studio_page.preview_requested.connect(self._qml_preview_requested)
            self.qml_studio_page.editor_settings_changed.connect(self._qml_settings_changed)
            self.qml_studio_page.source_opened.connect(self._select_qml_source)
            self.qml_studio_page.discovery_requested.connect(self._qml_discovery_requested)
            self.qml_studio_page.discovery_cancel_requested.connect(self._cancel_discovery)
            self.qml_studio_page.candidate_review_requested.connect(self._qml_candidate_review)
            self.qml_studio_page.controller.candidate_chosen.connect(self._qml_candidate_chosen)
            self.qml_studio_page.cancel_requested.connect(self._cancel_clip_job)
            self.qml_studio_page.controller.ranges_changed.connect(self._qml_ranges_changed)
            self.qml_studio_page.set_renderer_available(True)
            self.tabs.insertTab(1, self.qml_studio_page, "Timeline editor")
        except Exception as exc:
            # A QML/plugin problem must not make the established Widgets Studio
            # unavailable. Keep the fallback and explain why the new surface
            # could not be loaded.
            self.qml_studio_error = QLabel(f"Timeline editor unavailable: {exc}")
            self.qml_studio_error.setWordWrap(True)
            self.qml_studio_error.setObjectName("Faint")
            self.tabs.insertTab(1, self.qml_studio_error, "Timeline editor")
        layout.addWidget(self.tabs, 1)

        self.workspace_input.setText(self._initial_workspace())
        self.workspace_input.editingFinished.connect(self._workspace_changed)
        self._load_preferences()
        self._workspace_changed()
        self.tabs.currentChanged.connect(self._tab_changed)
        self._publish_timer = QTimer(self)
        self._publish_timer.setInterval(10000)
        self._publish_timer.timeout.connect(self._tick_publish_queue)
        self._publish_timer.start()
    def _tab_changed(self, index: int):
        if self.tabs.widget(index) is self.publish_tab:
            self._refresh_account()

    @staticmethod
    def _section(title: str):
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(9)
        heading = QLabel(title)
        heading.setObjectName("Eyebrow")
        layout.addWidget(heading)
        apply_card_shadow(frame)
        return frame, layout

    def _initial_workspace(self) -> str:
        settings = self._settings.get()
        if settings.studio_workspace_dir:
            return str(Path(settings.studio_workspace_dir).expanduser())
        configured = settings.clip_output_dir or settings.download_dir
        return str(Path(configured).expanduser() / "StreamCarnia Studio")

    def _build_clip_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        source_card, source = self._section("1 · IMPORT AND PREVIEW")
        actions = QHBoxLayout()
        self.import_btn = PrimaryButton("Import local videos…")
        self.import_btn.clicked.connect(self._import_sources)
        actions.addWidget(self.import_btn)
        self.new_streamer_btn = GhostButton("New streamer profile…")
        self.new_streamer_btn.clicked.connect(self._new_streamer)
        actions.addWidget(self.new_streamer_btn)
        actions.addStretch(1)
        source.addLayout(actions)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Organize under"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("No streamer profile", "")
        profile_row.addWidget(self.profile_combo, 1)
        source.addLayout(profile_row)
        self.source_list = QListWidget()
        self.source_list.setMaximumHeight(125)
        self.source_list.currentRowChanged.connect(self._source_selected)
        source.addWidget(self.source_list)

        self.source_player = QMediaPlayer(self)
        self.source_audio = QAudioOutput(self)
        self.source_player.setAudioOutput(self.source_audio)
        self.source_video = QVideoWidget()
        self.source_video.setMinimumHeight(260)
        self.source_video.setMaximumHeight(420)
        self.source_player.setVideoOutput(self.source_video)
        source.addWidget(self.source_video)
        playback = QHBoxLayout()
        play = GhostButton("Play / pause")
        play.clicked.connect(self._toggle_source_playback)
        playback.addWidget(play)
        self.timeline = QSpinBox()
        self.timeline.setRange(0, 0)
        self.timeline.setSuffix(" ms")
        self.timeline.valueChanged.connect(lambda value: self.source_player.setPosition(value))
        playback.addWidget(self.timeline, 1)
        self.position_label = QLabel("0:00 / 0:00")
        playback.addWidget(self.position_label)
        source.addLayout(playback)
        self.source_player.positionChanged.connect(self._source_position_changed)
        self.source_player.durationChanged.connect(self._source_duration_changed)
        layout.addWidget(source_card)

        discovery_card, discovery = self._section("FIND MOMENTS")
        discovery_help = QLabel("Analyse this local video for real highlight candidates. You can review them, adjust the range, or create a range manually.")
        discovery_help.setObjectName("Faint")
        discovery_help.setWordWrap(True)
        discovery.addWidget(discovery_help)
        discovery_actions = QHBoxLayout()
        discovery_actions.addWidget(QLabel("Candidates"))
        self.candidate_count = QSpinBox()
        self.candidate_count.setRange(1, 30)
        self.candidate_count.setValue(8)
        discovery_actions.addWidget(self.candidate_count)
        self.find_highlights_btn = PrimaryButton("Find highlight moments")
        self.find_highlights_btn.clicked.connect(self._start_discovery)
        discovery_actions.addWidget(self.find_highlights_btn)
        self.cancel_discovery_btn = GhostButton("Cancel analysis")
        self.cancel_discovery_btn.clicked.connect(self._cancel_discovery)
        self.cancel_discovery_btn.hide()
        discovery_actions.addWidget(self.cancel_discovery_btn)
        discovery_actions.addStretch(1)
        discovery.addLayout(discovery_actions)
        self.discovery_progress = QProgressBar()
        self.discovery_progress.setRange(0, 0)
        self.discovery_progress.setTextVisible(False)
        self.discovery_progress.hide()
        discovery.addWidget(self.discovery_progress)
        self.candidate_list = QListWidget()
        self.candidate_list.setMaximumHeight(135)
        self.candidate_list.itemDoubleClicked.connect(self._use_selected_candidate)
        discovery.addWidget(self.candidate_list)
        candidate_actions = QHBoxLayout()
        self.use_candidate_btn = GhostButton("Use selected moment as a range")
        self.use_candidate_btn.clicked.connect(self._use_selected_candidate)
        candidate_actions.addWidget(self.use_candidate_btn)
        self.favorite_candidate_btn = GhostButton("Favorite")
        self.favorite_candidate_btn.clicked.connect(lambda: self._set_candidate_review("favorite"))
        candidate_actions.addWidget(self.favorite_candidate_btn)
        self.reject_candidate_btn = GhostButton("Reject")
        self.reject_candidate_btn.clicked.connect(lambda: self._set_candidate_review("rejected"))
        candidate_actions.addWidget(self.reject_candidate_btn)
        candidate_actions.addStretch(1)
        discovery.addLayout(candidate_actions)
        layout.addWidget(discovery_card)

        trim_card, trim = self._section("2 · SELECT CLIP RANGES")
        trim_row = QHBoxLayout()
        self.start_seconds = QDoubleSpinBox()
        self.start_seconds.setRange(0, 86400)
        self.start_seconds.setDecimals(2)
        self.start_seconds.setSuffix(" sec")
        self.end_seconds = QDoubleSpinBox()
        self.end_seconds.setRange(0, 86400)
        self.end_seconds.setDecimals(2)
        self.end_seconds.setSuffix(" sec")
        trim_row.addWidget(QLabel("In"))
        trim_row.addWidget(self.start_seconds)
        set_in = GhostButton("Set in at playhead")
        set_in.clicked.connect(lambda: self.start_seconds.setValue(self.source_player.position() / 1000))
        trim_row.addWidget(set_in)
        trim_row.addSpacing(12)
        trim_row.addWidget(QLabel("Out"))
        trim_row.addWidget(self.end_seconds)
        set_out = GhostButton("Set out at playhead")
        set_out.clicked.connect(lambda: self.end_seconds.setValue(self.source_player.position() / 1000))
        trim_row.addWidget(set_out)
        self.add_range_btn = PrimaryButton("Add range")
        self.add_range_btn.clicked.connect(self._add_range)
        trim_row.addWidget(self.add_range_btn)
        trim.addLayout(trim_row)
        self.range_list = QListWidget()
        self.range_list.setMaximumHeight(100)
        trim.addWidget(self.range_list)
        self.remove_range_btn = GhostButton("Remove selected range")
        self.remove_range_btn.clicked.connect(self._remove_range)
        trim.addWidget(self.remove_range_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(trim_card)

        options_card, options = self._section("3 · OUTPUT AND CAPTIONS")
        options_row = QHBoxLayout()
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItem("Portrait · 9:16", "blur")
        self.aspect_combo.addItem("Top facecam / bottom gameplay · 9:16", "stack")
        self.aspect_combo.addItem("Landscape · 16:9", "landscape")
        self.aspect_combo.addItem("Square · 1:1", "square")
        self.aspect_combo.currentIndexChanged.connect(self._layout_changed)
        self.caption_combo = QComboBox()
        for label, key in (("Pop", "pop"), ("Bounce", "bounce"), ("Word", "word"), ("Karaoke", "karaoke")):
            self.caption_combo.addItem(label, key)
        self.model_combo = QComboBox()
        for label, key in (("Small · faster", "small"), ("Medium · recommended", "medium"),
                           ("Large-v3 · best accuracy", "large-v3")):
            self.model_combo.addItem(label, key)
        self.aspect_combo.currentIndexChanged.connect(self._queue_project_save)
        self.caption_combo.currentIndexChanged.connect(self._queue_project_save)
        self.model_combo.currentIndexChanged.connect(self._queue_project_save)
        self.aspect_combo.currentIndexChanged.connect(self._update_qml_editor_settings)
        self.caption_combo.currentIndexChanged.connect(self._update_qml_editor_settings)
        self.model_combo.currentIndexChanged.connect(self._update_qml_editor_settings)
        for label, widget in (("Aspect ratio", self.aspect_combo), ("Animated captions", self.caption_combo),
                              ("Speech model · shared with Auto Clippr", self.model_combo)):
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            col.addWidget(widget)
            options_row.addLayout(col, 1)
        options.addLayout(options_row)
        self.facecam_box = QWidget()
        face_layout = QVBoxLayout(self.facecam_box)
        face_layout.setContentsMargins(0, 8, 0, 0)
        self.facecam_selector = FacecamSelector(accent=self._settings.get().accent)
        self.facecam_input = QLineEdit(self._settings.get().clip_facecam)
        self.facecam_selector.coordinatesChanged.connect(self.facecam_input.setText)
        self.facecam_input.textChanged.connect(self.facecam_selector.setCoordinates)
        self.facecam_input.textChanged.connect(self._queue_project_save)
        self.stack_layout = StackLayoutControl(self._settings.get().clip_stack_facecam_percent,
                                               accent=self._settings.get().accent)
        self.stack_layout.valueChanged.connect(self._queue_project_save)
        face_layout.addWidget(QLabel("Choose the source facecam crop"))
        face_layout.addWidget(self.facecam_selector)
        face_layout.addWidget(self.facecam_input)
        face_layout.addWidget(self.stack_layout)
        options.addWidget(self.facecam_box)
        self.facecam_box.hide()

        self.clip_status = QLabel("Import a video, preview it, then add one or more ranges.")
        self.clip_status.setObjectName("Faint")
        self.clip_status.setWordWrap(True)
        options.addWidget(self.clip_status)
        self.clip_progress = QProgressBar()
        self.clip_progress.setRange(0, 100)
        self.clip_progress.hide()
        options.addWidget(self.clip_progress)
        generate_row = QHBoxLayout()
        self.generate_btn = PrimaryButton("Generate selected clips")
        self.generate_btn.clicked.connect(self._generate_clips)
        generate_row.addWidget(self.generate_btn)
        self.cancel_clip_btn = GhostButton("Cancel")
        self.cancel_clip_btn.clicked.connect(self._cancel_clip_job)
        self.cancel_clip_btn.hide()
        generate_row.addWidget(self.cancel_clip_btn)
        generate_row.addStretch(1)
        options.addLayout(generate_row)
        layout.addWidget(options_card)
        layout.addStretch(1)
        return page

    def _build_library_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)
        profile_card, profile = self._section("STREAMER LIBRARY")
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile"))
        self.library_profile_combo = QComboBox()
        self.library_profile_combo.currentIndexChanged.connect(self._profile_changed)
        profile_row.addWidget(self.library_profile_combo, 1)
        self.profile_avatar = QLineEdit()
        self.profile_avatar.setPlaceholderText("Optional avatar image path")
        pick_avatar = GhostButton("Choose avatar…")
        pick_avatar.clicked.connect(self._pick_profile_avatar)
        profile_row.addWidget(self.profile_avatar, 1)
        profile_row.addWidget(pick_avatar)
        profile.addLayout(profile_row)
        profile_fields = QHBoxLayout()
        self.profile_description = QLineEdit()
        self.profile_description.setPlaceholderText("Short streamer description")
        profile_fields.addWidget(self.profile_description, 2)
        self.profile_categories = QLineEdit()
        self.profile_categories.setPlaceholderText("Categories, comma separated")
        profile_fields.addWidget(self.profile_categories, 1)
        self.profile_genres = QLineEdit()
        self.profile_genres.setPlaceholderText("Genres")
        profile_fields.addWidget(self.profile_genres, 1)
        self.profile_games = QLineEdit()
        self.profile_games.setPlaceholderText("Games")
        profile_fields.addWidget(self.profile_games, 1)
        self.profile_tags = QLineEdit()
        self.profile_tags.setPlaceholderText("Tags")
        profile_fields.addWidget(self.profile_tags, 1)
        profile.addLayout(profile_fields)
        save_profile = PrimaryButton("Save profile")
        save_profile.clicked.connect(self._save_profile)
        profile.addWidget(save_profile, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(profile_card)

        clips_card, clips = self._section("CLIP LIBRARY")
        search_row = QHBoxLayout()
        self.clip_search = QLineEdit()
        self.clip_search.setPlaceholderText("Search titles, categories, games, or tags")
        self.clip_search.textChanged.connect(self._refresh_clips)
        search_row.addWidget(self.clip_search, 1)
        clips.addLayout(search_row)
        self.clip_table = QTableWidget(0, 6)
        self.clip_table.setHorizontalHeaderLabels(["Title", "Streamer", "Category", "Game", "Ratio", "Status"])
        self.clip_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.clip_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.clip_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clip_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            self.clip_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.clip_table.setMinimumHeight(190)
        self.clip_table.itemSelectionChanged.connect(self._clip_selected)
        clips.addWidget(self.clip_table)
        layout.addWidget(clips_card)

        editor_card, editor = self._section("EDITABLE METADATA")
        editor_row = QHBoxLayout()
        self.clip_preview_player = QMediaPlayer(self)
        self.clip_preview_audio = QAudioOutput(self)
        self.clip_preview_player.setAudioOutput(self.clip_preview_audio)
        self.clip_preview_video = QVideoWidget()
        self.clip_preview_video.setMinimumHeight(200)
        self.clip_preview_video.setMaximumHeight(310)
        self.clip_preview_player.setVideoOutput(self.clip_preview_video)
        editor_row.addWidget(self.clip_preview_video, 1)
        fields = QFormLayout()
        self.metadata_title = QLineEdit()
        self.metadata_description = QPlainTextEdit()
        self.metadata_description.setMaximumHeight(100)
        self.metadata_tags = QLineEdit()
        self.metadata_hashtags = QLineEdit()
        self.metadata_category = QComboBox()
        for label, category_id in (("People & Blogs", "22"), ("Gaming", "20"),
                                   ("Entertainment", "24"), ("Comedy", "23"),
                                   ("Education", "27"), ("Howto & Style", "26"),
                                   ("Science & Technology", "28"), ("Other / not set", "")):
            self.metadata_category.addItem(label, category_id)
        self.metadata_genre = QLineEdit()
        self.metadata_game = QLineEdit()
        self.metadata_language = QComboBox()
        for label, value in (("Auto · match transcript", "auto"), ("Hinglish", "hi-Latn"),
                             ("Hindi", "hi"), ("English", "en"), ("Other…", "other")):
            self.metadata_language.addItem(label, value)
        self.metadata_language_other = QLineEdit()
        self.metadata_language_other.setPlaceholderText("Language code")
        self.thumbnail_path = QLineEdit()
        self.thumbnail_path.setPlaceholderText("Thumbnail image path")
        thumbnail_row = QHBoxLayout()
        thumbnail_row.addWidget(self.thumbnail_path, 1)
        choose_thumb = GhostButton("Choose image…")
        choose_thumb.clicked.connect(self._choose_thumbnail)
        thumbnail_row.addWidget(choose_thumb)
        capture_thumb = GhostButton("Capture preview frame")
        capture_thumb.clicked.connect(self._capture_thumbnail)
        thumbnail_row.addWidget(capture_thumb)
        for label, widget in (("Title (<60 characters)", self.metadata_title), ("Description", self.metadata_description),
                              ("Tags", self.metadata_tags), ("Hashtags", self.metadata_hashtags),
                              ("Category", self.metadata_category), ("Genre", self.metadata_genre),
                              ("Game", self.metadata_game), ("Language", self.metadata_language)):
            fields.addRow(label, widget)
        fields.addRow("Custom language", self.metadata_language_other)
        fields.addRow("Thumbnail", thumbnail_row)
        editor_row.addLayout(fields, 2)
        editor.addLayout(editor_row)
        controls = QHBoxLayout()
        self.tone_combo = QComboBox()
        for label, value in (("Casual", "casual"), ("Energetic", "energetic"),
                             ("Humorous", "humorous"), ("Informative", "informative")):
            self.tone_combo.addItem(label, value)
        self.language_preference = QComboBox()
        for label, value in (("Match transcript", "auto"), ("Natural Hinglish", "Hinglish"),
                             ("English", "English"), ("Hindi · Roman script", "Hindi in Roman script")):
            self.language_preference.addItem(label, value)
        controls.addWidget(QLabel("AI tone"))
        controls.addWidget(self.tone_combo)
        controls.addWidget(QLabel("Writing language"))
        controls.addWidget(self.language_preference)
        self.variation_combo = QComboBox()
        self.variation_combo.currentIndexChanged.connect(self._apply_metadata_variation)
        controls.addWidget(self.variation_combo, 1)
        generate_ai = GhostButton("Generate 3 Gemini options")
        generate_ai.clicked.connect(self._generate_metadata)
        controls.addWidget(generate_ai)
        save_metadata = PrimaryButton("Save metadata")
        save_metadata.clicked.connect(self._save_clip_metadata)
        controls.addWidget(save_metadata)
        editor.addLayout(controls)
        self.metadata_status = QLabel("Metadata can be edited and saved at any time.")
        self.metadata_status.setObjectName("Faint")
        self.metadata_status.setWordWrap(True)
        editor.addWidget(self.metadata_status)
        layout.addWidget(editor_card)
        layout.addStretch(1)
        return page

    def _build_publish_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        account_card, account = self._section("YOUTUBE ACCOUNT")
        account_row = QHBoxLayout()
        self.channel_avatar = QLabel()
        self.channel_avatar.setFixedSize(48, 48)
        account_row.addWidget(self.channel_avatar)
        self.account_status = QLabel("Connect YouTube in Settings to schedule uploads.")
        self.account_status.setObjectName("Muted")
        self.account_status.setWordWrap(True)
        account_row.addWidget(self.account_status, 1)
        self.refresh_publish_btn = GhostButton("Refresh status")
        self.refresh_publish_btn.clicked.connect(self._refresh_publish_status)
        account_row.addWidget(self.refresh_publish_btn)
        account.addLayout(account_row)
        layout.addWidget(account_card)

        schedule_card, schedule = self._section("SCHEDULE A COLLECTION")
        schedule.addWidget(QLabel("Select clips in the Library tab first. Selected clips follow their visible library order."))
        fields = QHBoxLayout()
        self.collection_name = QLineEdit()
        self.collection_name.setPlaceholderText("Collection name")
        self.schedule_date = QDateEdit(QDate.currentDate().addDays(1))
        self.schedule_date.setCalendarPopup(True)
        self.schedule_time = QTimeEdit(QTime(18, 0))
        self.schedule_end_time = QTimeEdit(QTime(22, 0))
        self.schedule_frequency = QSpinBox()
        self.schedule_frequency.setRange(1, 30)
        self.schedule_frequency.setValue(2)
        for label, widget in (("Collection", self.collection_name), ("Start date", self.schedule_date),
                              ("Window starts", self.schedule_time), ("Window ends", self.schedule_end_time),
                              ("Every N days", self.schedule_frequency)):
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            col.addWidget(widget)
            fields.addLayout(col, 1)
        schedule.addLayout(fields)
        days = QHBoxLayout()
        self.weekday_checks = []
        for label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            check = QCheckBox(label)
            check.setChecked(label in {"Mon", "Wed", "Fri"})
            self.weekday_checks.append(check)
            days.addWidget(check)
        schedule.addLayout(days)
        self.approve_before_upload = QCheckBox("Review and approve before uploading")
        self.approve_before_upload.setChecked(True)
        schedule.addWidget(self.approve_before_upload)
        publish_note = QLabel("Approved clips upload privately with their scheduled publish time. Keep StreamCarnia open until the queue finishes uploading; after upload, YouTube publishes on schedule.")
        publish_note.setObjectName("Faint")
        publish_note.setWordWrap(True)
        schedule.addWidget(publish_note)
        schedule_action = PrimaryButton("Review schedule & approve")
        schedule_action.clicked.connect(self._schedule_collection)
        schedule.addWidget(schedule_action, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(schedule_card)

        calendar_card, calendar = self._section("PUBLISHING CALENDAR")
        self.publish_table = QTableWidget(0, 6)
        self.publish_table.setHorizontalHeaderLabels(["", "Clip", "State", "Publish time", "YouTube ID", "Details"])
        self.publish_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.publish_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.publish_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.publish_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.publish_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(2, 6):
            self.publish_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.publish_table.setMinimumHeight(190)
        calendar.addWidget(self.publish_table)
        actions = QHBoxLayout()
        reschedule = GhostButton("Reschedule selected…")
        reschedule.clicked.connect(self._reschedule_selected)
        actions.addWidget(reschedule)
        cancel = GhostButton("Cancel selected")
        cancel.clicked.connect(self._cancel_schedule_selected)
        actions.addWidget(cancel)
        retry = GhostButton("Retry failed upload")
        retry.clicked.connect(self._retry_upload_selected)
        actions.addWidget(retry)
        actions.addStretch(1)
        calendar.addLayout(actions)
        layout.addWidget(calendar_card)
        layout.addStretch(1)
        return page

    def _workspace_changed(self):
        path = Path(self.workspace_input.text().strip()).expanduser()
        if not path.is_absolute():
            self.clip_status.setText("Choose an absolute workspace folder.")
            return
        try:
            root = path.resolve()
            root.mkdir(parents=True, exist_ok=True)
            state_dir = root / ".streamcarnia"
            catalog = StudioCatalog(state_dir / "studio_library.sqlite3")
            project_store = StudioProjectStore(state_dir / "studio_library.sqlite3")
            self._workspace = root
            self._catalog = catalog
            self._project_store = project_store
            self._active_project_id = None
            self._settings.update(studio_workspace_dir=str(root))
            self._refresh_projects()
            self._refresh_sources()
            self._refresh_profiles()
            self._refresh_clips()
            self._refresh_publish_jobs()
        except (OSError, ValueError) as exc:
            self.clip_status.setText(f"Could not open the Studio workspace: {exc}")

    def _choose_workspace(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Studio workspace", self.workspace_input.text())
        if path:
            self.workspace_input.setText(path)
            self._workspace_changed()

    def _refresh_projects(self):
        if not self._project_store or not hasattr(self, "project_combo"):
            return
        previous = self._active_project_id or self.project_combo.currentData()
        projects = self._project_store.list_projects()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Choose a recent project…", "")
        for project in projects:
            source = Path(project["source_path"]) if project.get("source_path") else None
            source_state = " · source missing" if source and not source.is_file() else ""
            self.project_combo.addItem(project["name"] + source_state, project["id"])
        index = self.project_combo.findData(previous or "")
        self.project_combo.setCurrentIndex(max(0, index))
        self.project_combo.blockSignals(False)

    def _open_selected_project(self):
        if not self._project_store:
            return
        project_id = self.project_combo.currentData()
        if not project_id:
            return
        project = self._project_store.get_project(project_id)
        if not project:
            return
        source_path = project.get("source_path")
        if not source_path or not Path(source_path).is_file():
            self._active_project_id = project_id
            self.relink_source_btn.show()
            self.clip_status.setText("This project's source is missing. Relink the original file to recover its ranges and settings.")
            return
        row = next((index for index, source in enumerate(self._sources)
                    if str(Path(source.get("path", "")).resolve()) == str(Path(source_path).resolve())), -1)
        if row >= 0:
            self.source_list.setCurrentRow(row)
        else:
            self._pending_qml_source_path = str(Path(source_path).resolve())
            self._start_import_paths([source_path])

    def _relink_active_project(self):
        if not self._project_store or not self._active_project_id:
            QMessageBox.information(self, "Choose a project", "Open a project with a missing source first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Relink project source", str(self._workspace),
            "Video files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v);;All files (*)")
        if not path:
            return
        try:
            project = self._project_store.relink_source(self._active_project_id, path)
            self._pending_qml_source_path = project["source_path"]
            self._start_import_paths([project["source_path"]])
            self._refresh_projects()
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Could not relink source", str(exc))

    def _load_preferences(self):
        settings = self._settings.get()
        model = self.model_combo.findData(settings.transcription_model)
        if model >= 0:
            self.model_combo.setCurrentIndex(model)
        style = self.caption_combo.findData(settings.caption_style)
        if style >= 0:
            self.caption_combo.setCurrentIndex(style)
        layout = self.aspect_combo.findData(settings.clip_layout)
        if layout >= 0:
            self.aspect_combo.setCurrentIndex(layout)
        self.facecam_input.setText(settings.clip_facecam)
        self.stack_layout.setValue(settings.clip_stack_facecam_percent)
        self._update_qml_editor_settings()

    def _import_sources(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import local video files", str(self._workspace),
            "Video files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v);;All files (*)")
        if not files or not self._catalog:
            return
        self._start_import_paths(files)

    def _start_import_paths(self, files: list[str]):
        if not self._catalog:
            return
        if (self._active_import_worker or self._active_clip_worker or self._active_discovery_worker
                or self._preview_render_active or self._active_preview_proxy):
            self.clip_status.setText("A Studio task is already running. Wait for it to finish before adding another video.")
            return
        streamer_id = self.profile_combo.currentData() or None
        worker = StudioImportWorker(files, self._catalog.path, self._settings.ffmpeg_path, streamer_id)
        self._active_import_worker = worker
        self.import_btn.setEnabled(False)
        self.clip_status.setText(f"Checking {len(files)} video(s)… originals stay in their current locations.")
        worker.signals.progress.connect(self._import_progress)
        worker.signals.finished.connect(self._import_finished)
        worker.signals.cancelled.connect(self._import_cancelled)
        worker.signals.failed.connect(self._import_failed)
        self._set_editor_busy(True)
        self._import_pool.start(worker)

    def _import_progress(self, event: dict):
        self.clip_status.setText(
            f"Checking video {event.get('completed', 0)} of {event.get('total', 0)}… "
            "originals stay in their current locations."
        )

    def _import_finished(self, result: dict):
        self._active_import_worker = None
        self._set_editor_busy(False)
        imported = result.get("imported", [])
        errors = result.get("errors", [])
        self._refresh_sources()
        self._refresh_clips()
        if imported:
            imported_id = imported[-1].get("id")
            row = next((i for i, source in enumerate(self._sources) if source.get("id") == imported_id), -1)
            if row >= 0:
                self.source_list.setCurrentRow(row)
        if self._pending_qml_source_path:
            pending = str(Path(self._pending_qml_source_path).expanduser().resolve())
            row = next((i for i, source in enumerate(self._sources)
                        if str(Path(source.get("path", "")).resolve()) == pending), -1)
            if row >= 0:
                self.source_list.setCurrentRow(row)
                if self.qml_studio_page:
                    self.qml_studio_page.controller.set_status("Video added to the library. Set a range or find highlight moments to continue.")
            self._pending_qml_source_path = None
        if errors:
            names = "\n".join(f"• {Path(item['path']).name}: {item['error']}" for item in errors[:5])
            suffix = f"\n…and {len(errors) - 5} more." if len(errors) > 5 else ""
            self.clip_status.setText(
                f"Imported {len(imported)} video(s); {len(errors)} could not be checked.\n{names}{suffix}"
            )
        elif imported:
            self.clip_status.setText(
                f"Ready: {len(imported)} video(s) checked. Originals stay in their current locations."
            )

    def _import_cancelled(self, result: dict):
        self._active_import_worker = None
        self._set_editor_busy(False)
        self._refresh_sources()
        count = len(result.get("imported", []))
        self.clip_status.setText(f"Import stopped. {count} completed video(s) remain in your library.")

    def _import_failed(self, error: str):
        self._active_import_worker = None
        self._set_editor_busy(False)
        self.clip_status.setText(f"Could not import videos: {error}")

    def _refresh_sources(self):
        if not self._catalog:
            return
        current = self.source_list.currentRow()
        self._sources = self._catalog.list_sources()
        self.source_list.blockSignals(True)
        self.source_list.clear()
        for source in self._sources:
            streamer = source.get("streamer_name") or "Unassigned"
            duration = self._format_time(source.get("duration", 0))
            item = QListWidgetItem(f"{source['title']}   ·   {streamer}   ·   {duration}")
            item.setToolTip(source["path"])
            self.source_list.addItem(item)
        self.source_list.blockSignals(False)
        if self.qml_studio_page:
            self.qml_studio_page.set_sources(self._sources)
        if self._sources:
            self.source_list.setCurrentRow(max(0, min(current, len(self._sources) - 1)))

    def _refresh_profiles(self):
        if not self._catalog:
            return
        selected = self.profile_combo.currentData()
        profiles = self._catalog.list_streamers()
        for combo in (self.profile_combo, self.library_profile_combo):
            old = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if combo is self.profile_combo:
                combo.addItem("No streamer profile", "")
            else:
                combo.addItem("All streamers", "")
            for profile in profiles:
                combo.addItem(profile["name"], profile["id"])
            index = combo.findData(old or selected or "")
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        self._profile_changed(self.library_profile_combo.currentIndex())

    def _new_streamer(self):
        from PySide6.QtWidgets import QInputDialog
        name, accepted = QInputDialog.getText(self, "New streamer profile", "Streamer name")
        if accepted and name.strip() and self._catalog:
            try:
                self._catalog.add_streamer(name)
                self._refresh_profiles()
                index = self.profile_combo.findText(name.strip())
                if index >= 0:
                    self.profile_combo.setCurrentIndex(index)
                self._refresh_sources()
            except Exception as exc:
                QMessageBox.warning(self, "Could not create profile", str(exc))

    def _profile_changed(self, _index: int):
        if not self._catalog:
            return
        profile_id = self.library_profile_combo.currentData()
        profile = next((item for item in self._catalog.list_streamers() if item["id"] == profile_id), None)
        self.profile_description.setText((profile or {}).get("description", ""))
        self.profile_avatar.setText((profile or {}).get("avatar_path", ""))
        self.profile_categories.setText(", ".join((profile or {}).get("categories", [])))
        self.profile_genres.setText(", ".join((profile or {}).get("genres", [])))
        self.profile_games.setText(", ".join((profile or {}).get("games", [])))
        self.profile_tags.setText(", ".join((profile or {}).get("tags", [])))
        self._refresh_clips()

    def _pick_profile_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose streamer avatar", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.profile_avatar.setText(path)

    def _save_profile(self):
        if not self._catalog:
            return
        profile_id = self.library_profile_combo.currentData()
        profile = next((item for item in self._catalog.list_streamers() if item["id"] == profile_id), None)
        if not profile:
            QMessageBox.information(self, "Choose a profile", "Create or select a streamer profile first.")
            return
        # Profile fields are updated through a narrow local SQL update so IDs remain stable.
        from contextlib import closing
        with closing(self._catalog._connect()) as db, db:
            db.execute("""UPDATE streamers SET description=?,avatar_path=?,categories_json=?,genres_json=?,
                games_json=?,tags_json=? WHERE id=?""",
                (self.profile_description.text().strip(), self.profile_avatar.text().strip(),
                 self._catalog._json(self._split(self.profile_categories.text())),
                 self._catalog._json(self._split(self.profile_genres.text())),
                 self._catalog._json(self._split(self.profile_games.text())),
                 self._catalog._json(self._split(self.profile_tags.text())), profile_id))
        self.clip_status.setText("Streamer profile saved.")
        self._refresh_clips()

    @staticmethod
    def _split(value: str) -> list[str]:
        return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))

    def _source_selected(self, row: int):
        if not 0 <= row < len(self._sources):
            return
        source = self._sources[row]
        source_path = Path(source["path"])
        if not source_path.is_file():
            self._cancel_timeline_thumbnails()
            if self.qml_studio_page:
                self.qml_studio_page.set_thumbnails([])
                self.qml_studio_page.controller.clear_source()
            project = next((item for item in self._project_store.list_projects()
                            if item.get("source_path") and Path(item["source_path"]).resolve() == source_path.resolve()), None) if self._project_store else None
            self._active_project_id = project["id"] if project else None
            self.relink_source_btn.setVisible(project is not None)
            if project:
                self._refresh_projects()
                self.project_combo.setCurrentIndex(self.project_combo.findData(project["id"]))
                self._ranges = [(float(start), float(end)) for start, end in project.get("ranges", [])]
                self.candidate_list.clear()
                self._display_candidates(project.get("candidates", []))
                if self.qml_studio_page:
                    self.qml_studio_page.set_ranges(self._ranges)
            self.clip_status.setText(f"Source file is missing: {source_path}. Relink it by importing the file again.")
            return
        self.relink_source_btn.hide()
        self.project_save_label.setText("Saved")
        self.source_player.setSource(QUrl.fromLocalFile(source["path"]))
        self.source_player.pause()
        if self.qml_studio_page and self.qml_studio_page.controller.sourcePath != str(source_path.resolve()):
            self.qml_studio_page.open_source(str(source_path))
        self.start_seconds.setValue(0)
        self.end_seconds.setValue(float(source.get("duration", 0)))
        self._ranges.clear()
        self.range_list.clear()
        self._active_project_id = None
        self.candidate_list.clear()
        if self._project_store:
            project = next((item for item in self._project_store.list_projects()
                            if item.get("source_path") and Path(item["source_path"]).resolve() == source_path.resolve()), None)
            if project is None:
                project_id = self._project_store.create_project(source.get("title") or source_path.stem, source_path)
                project = self._project_store.get_project(project_id)
            self._active_project_id = project["id"]
            self._project_store.save_project(self._active_project_id, current_stage="editor")
            self._refresh_projects()
            self.project_combo.setCurrentIndex(self.project_combo.findData(self._active_project_id))
            self._display_candidates(project.get("candidates", []))
            self._ranges = [(float(start), float(end)) for start, end in project.get("ranges", [])]
            for index, (start, end) in enumerate(self._ranges, 1):
                self.range_list.addItem(f"Clip {index} · {self._format_time(start)} – {self._format_time(end)}")
            self._restore_project_settings(project.get("editor_settings", {}))
            if not self._ranges:
                self._queue_project_save()
        if self.qml_studio_page:
            self.qml_studio_page.set_ranges(self._ranges)
            self.qml_studio_page.set_candidates(project.get("candidates", []) if self._project_store else [])
        self._load_timeline_thumbnails(source)
        self.clip_status.setText(f"Previewing {source['title']}. Set in/out points and add clip ranges.")

    def _select_qml_source(self, path: str):
        resolved = str(Path(path).expanduser().resolve())
        row = next((index for index, source in enumerate(self._sources)
                    if str(Path(source.get("path", "")).expanduser().resolve()) == resolved), -1)
        if row >= 0 and row != self.source_list.currentRow():
            self.source_list.setCurrentRow(row)
        elif row < 0 and Path(resolved).is_file():
            if self._active_import_worker:
                if self.qml_studio_page:
                    self.qml_studio_page.controller.set_status("Wait for the current import to finish, then choose this video again.")
                return
            self._pending_qml_source_path = resolved
            self.clip_status.setText("Adding this video to the Studio library…")
            self._start_import_paths([resolved])

    def _load_timeline_thumbnails(self, source: dict):
        self._cancel_timeline_thumbnails()
        if not self.qml_studio_page:
            return
        self.qml_studio_page.set_thumbnails([])
        if not self._settings.ffmpeg_path or not self._active_project_id:
            return
        output = self._workspace / ".streamcarnia" / "timeline_frames"
        worker = StudioTimelineThumbnailWorker(source["path"], source.get("duration", 0), output,
                                               self._settings.ffmpeg_path)
        self._active_timeline_thumbnail_worker = worker
        worker.signals.finished.connect(
            lambda frames, path=source["path"], active=worker: self._timeline_thumbnails_finished(path, active, frames))
        worker.signals.failed.connect(
            lambda error, path=source["path"], active=worker: self._timeline_thumbnails_failed(path, active, error))
        worker.signals.cancelled.connect(lambda active=worker: self._timeline_thumbnails_cancelled(active))
        self._timeline_thumbnail_pool.start(worker)

    def _timeline_thumbnails_finished(self, source_path: str, worker, frames: list[dict]):
        if self._active_timeline_thumbnail_worker is worker:
            self._active_timeline_thumbnail_worker = None
        if self.qml_studio_page and Path(self.qml_studio_page.controller.sourcePath).resolve() == Path(source_path).resolve():
            self.qml_studio_page.set_thumbnails(frames)

    def _timeline_thumbnails_failed(self, source_path: str, worker, error: str):
        if self._active_timeline_thumbnail_worker is worker:
            self._active_timeline_thumbnail_worker = None
        # Source preview and editing remain available even when this optional
        # enhancement cannot extract a frame.

    def _timeline_thumbnails_cancelled(self, worker):
        if self._active_timeline_thumbnail_worker is worker:
            self._active_timeline_thumbnail_worker = None

    def _cancel_timeline_thumbnails(self):
        worker = self._active_timeline_thumbnail_worker
        self._active_timeline_thumbnail_worker = None
        if worker:
            worker.cancel()

    def _qml_ranges_changed(self):
        if not self.qml_studio_page:
            return
        ranges = [(item["startMs"] / 1000.0, item["endMs"] / 1000.0)
                  for item in self.qml_studio_page.controller.ranges]
        self._ranges = ranges
        self.range_list.clear()
        for index, (start, end) in enumerate(ranges, 1):
            self.range_list.addItem(f"Clip {index} · {self._format_time(start)} – {self._format_time(end)}")
        if ranges:
            active = self.qml_studio_page.controller.activeRange
            if not 0 <= active < len(ranges):
                active = len(ranges) - 1
            start, end = ranges[active]
            self.start_seconds.setValue(start)
            self.end_seconds.setValue(end)
        self._queue_project_save()

    def _qml_render_requested(self, path: str, ranges):
        resolved = str(Path(path).expanduser().resolve())
        row = next((index for index, source in enumerate(self._sources)
                    if str(Path(source.get("path", "")).expanduser().resolve()) == resolved), -1)
        if row < 0:
            if self.qml_studio_page:
                self.qml_studio_page.controller.set_status("Import this video into the Studio library before rendering.")
            return
        if self.source_list.currentRow() != row:
            self.source_list.setCurrentRow(row)
        try:
            parsed = [(float(start), float(end)) for start, end in ranges]
            if not parsed or any(start < 0 or end <= start for start, end in parsed):
                raise ValueError("Add a valid clip range before rendering.")
        except (TypeError, ValueError) as exc:
            if self.qml_studio_page:
                self.qml_studio_page.controller.set_status(str(exc))
            return
        self._ranges = parsed
        self.range_list.clear()
        for index, (start, end) in enumerate(parsed, 1):
            self.range_list.addItem(f"Clip {index} · {self._format_time(start)} – {self._format_time(end)}")
        self._queue_project_save()
        self._generate_clips()

    def _qml_preview_requested(self, path: str, start: float, end: float):
        if (self._active_clip_worker or self._active_preview_proxy or self._active_import_worker
                or self._active_discovery_worker or self._preview_render_active):
            self.qml_studio_page.controller.set_status("Wait for the current Studio task to finish before rendering a preview.")
            return
        resolved = str(Path(path).expanduser().resolve())
        source = next((item for item in self._sources
                       if str(Path(item.get("path", "")).expanduser().resolve()) == resolved), None)
        if not source or not Path(resolved).is_file():
            self.qml_studio_page.controller.set_status("Import this source into the Studio library before previewing it.")
            return
        if not self._settings.ffmpeg_path or not Path(self._settings.ffmpeg_path).is_file():
            self.qml_studio_page.controller.set_status("FFmpeg is unavailable. Restore FFmpeg, then retry the preview.")
            return
        if start < 0 or end <= start:
            self.qml_studio_page.controller.set_status("Select a valid range before rendering the preview.")
            return
        preview_end = min(end, start + 15.0)
        layout = str(self.aspect_combo.currentData() or "blur")
        style = str(self.caption_combo.currentData() or "pop")
        model = str(self.model_combo.currentData() or "medium")
        job_dir = self._workspace / ".streamcarnia" / "studio_preview" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        options = {"url": resolved, "ranges": f"{start:.3f}-{preview_end:.3f}", "count": 1,
                   "layout": layout, "style": style, "model": model, "language": None,
                   "facecam": self.facecam_input.text().strip() if layout == "stack" else None,
                   "stack_facecam_percent": self.stack_layout.value(), "media_root": str(self._workspace)}
        self._settings.update(transcription_model=model, caption_style=style, clip_layout=layout,
            clip_facecam=self.facecam_input.text().strip(), clip_stack_facecam_percent=self.stack_layout.value())
        self._preview_render_active = True
        self._preview_job_dir = job_dir
        self._active_clip_worker = ClipWorker(options, job_dir, self._settings.ffmpeg_path)
        worker = self._active_clip_worker
        worker.signals.progress.connect(self._clip_progress)
        worker.signals.finished.connect(self._qml_preview_rendered)
        worker.signals.failed.connect(self._qml_preview_failed)
        worker.signals.cancelled.connect(self._qml_preview_cancelled)
        self._set_editor_busy(True)
        self.generate_btn.setEnabled(False)
        self.cancel_clip_btn.show()
        self.clip_progress.show()
        self.clip_progress.setValue(0)
        self.clip_status.setText("Rendering a 15-second preview with the current layout and captions…")
        self.qml_studio_page.report_started()
        QThreadPool.globalInstance().start(worker)

    def _qml_preview_rendered(self, payload: dict):
        self._active_clip_worker = None
        entries = payload.get("clips", [])
        rendered_path = next((str(item.get("file")) for item in entries
                              if item.get("file") and Path(str(item["file"])).is_file()), None)
        if not rendered_path:
            detail = payload.get("fatal_error") or "The clip pipeline produced no preview output."
            self._qml_preview_failed(str(detail))
            return
        layout = str(self.aspect_combo.currentData() or "blur")
        ratio = self._ratio_for_layout(layout)
        proxy = StudioPreviewProxyWorker(rendered_path, self._preview_job_dir / "playback_preview.mp4",
                                         self._settings.ffmpeg_path, ratio)
        self._active_preview_proxy = proxy
        proxy.signals.completed.connect(self._qml_preview_proxy_ready)
        proxy.signals.failed.connect(self._qml_preview_failed)
        proxy.signals.cancelled.connect(self._qml_preview_cancelled)
        self.clip_status.setText("Preparing a lightweight preview for smooth playback…")
        self._preview_pool.start(proxy)

    def _qml_preview_proxy_ready(self, path: str):
        try:
            self.qml_studio_page.show_rendered_preview(path)
            self.clip_status.setText("Rendered preview ready. It uses the selected layout and caption settings.")
            self.qml_studio_page.controller.set_status(self.clip_status.text())
        except (OSError, ValueError) as exc:
            self._qml_preview_failed(f"Preview rendered but could not be opened: {exc}")
            return
        self._finish_preview_job()

    def _qml_preview_failed(self, error: str):
        self.clip_status.setText(error)
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(error)
        self._finish_preview_job()

    def _qml_preview_cancelled(self):
        self.clip_status.setText("Preview rendering cancelled.")
        self._finish_preview_job()

    def _finish_preview_job(self):
        self._preview_render_active = False
        self._active_clip_worker = None
        self._active_preview_proxy = None
        self._clip_worker_done()

    def _restore_project_settings(self, values: dict):
        for widget, key in ((self.aspect_combo, "layout"), (self.caption_combo, "caption_style"),
                            (self.model_combo, "model")):
            index = widget.findData(values.get(key))
            if index >= 0:
                widget.setCurrentIndex(index)
        if "facecam" in values:
            self.facecam_input.setText(str(values["facecam"]))
        if "stack_facecam_percent" in values:
            self.stack_layout.setValue(int(values["stack_facecam_percent"]))
        self._update_qml_editor_settings()

    def _update_qml_editor_settings(self, *_args):
        if self.qml_studio_page:
            self.qml_studio_page.set_editor_settings(
                str(self.aspect_combo.currentData() or "blur"),
                str(self.caption_combo.currentData() or "pop"),
                str(self.model_combo.currentData() or "medium"),
            )

    def _qml_settings_changed(self, layout: str, caption_style: str, model: str):
        for widget, value in ((self.aspect_combo, layout), (self.caption_combo, caption_style),
                              (self.model_combo, model)):
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
        self._queue_project_save()

    def _queue_project_save(self, *_args):
        if self._active_project_id and self._project_store:
            self.project_save_label.setText("Saving…")
            self._project_save_timer.start()

    def _save_project_state(self):
        if not self._active_project_id or not self._project_store:
            return
        settings = {
            "layout": self.aspect_combo.currentData(),
            "caption_style": self.caption_combo.currentData(),
            "model": self.model_combo.currentData(),
            "facecam": self.facecam_input.text().strip(),
            "stack_facecam_percent": self.stack_layout.value(),
        }
        try:
            self._project_store.autosave(
                self._active_project_id,
                ranges=[[start, end] for start, end in self._ranges],
                editor_settings=settings,
            )
            self.project_save_label.setText("Saved")
        except (OSError, ValueError, KeyError) as exc:
            self.project_save_label.setText("Save needs attention")
            self.clip_status.setText(f"Project save needs attention: {exc}")

    def _toggle_source_playback(self):
        if self.source_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.source_player.pause()
        else:
            self.source_player.play()

    def _source_duration_changed(self, duration: int):
        self.timeline.setRange(0, max(0, duration))
        if duration:
            self.end_seconds.setMaximum(duration / 1000)
            self.end_seconds.setValue(duration / 1000)

    def _source_position_changed(self, position: int):
        if not self.timeline.isSliderDown():
            self.timeline.blockSignals(True)
            self.timeline.setValue(position)
            self.timeline.blockSignals(False)
        self.position_label.setText(f"{self._format_time(position / 1000)} / {self._format_time(self.source_player.duration() / 1000)}")

    def _start_discovery(self):
        if self._active_discovery_worker:
            return
        if self._active_import_worker:
            self.clip_status.setText("Wait for the current video import to finish before analysing highlights.")
            return
        if self._active_clip_worker or self._preview_render_active or self._active_preview_proxy:
            self.clip_status.setText("Wait for clip rendering to finish before analysing another source.")
            return
        if not self._catalog or not self._project_store or not self._active_project_id:
            QMessageBox.information(self, "Choose a video", "Import and select a local video before analysing it.")
            return
        row = self.source_list.currentRow()
        if not 0 <= row < len(self._sources):
            QMessageBox.information(self, "Choose a video", "Select one of the videos in your Studio library.")
            return
        source = self._sources[row]
        if not Path(source["path"]).is_file():
            QMessageBox.warning(self, "Source unavailable", "This source file is missing. Import or relink the file, then try again.")
            return
        run_dir = (self._workspace / ".streamcarnia" / "analysis" / self._active_project_id /
                   datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        worker = StudioDiscoveryWorker(source["path"], run_dir, top=self.candidate_count.value(),
                                       ffmpeg_path=self._settings.ffmpeg_path)
        self._active_discovery_worker = worker
        self.find_highlights_btn.setEnabled(False)
        self.cancel_discovery_btn.show()
        self.discovery_progress.show()
        self.clip_status.setText("Analysing the selected video for highlight moments…")
        self._project_store.save_project(self._active_project_id, current_stage="analysing")
        self._set_editor_busy(True)
        worker.signals.progress.connect(self._discovery_progress)
        worker.signals.completed.connect(self._discovery_completed)
        worker.signals.failed.connect(self._discovery_failed)
        worker.signals.cancelled.connect(self._discovery_cancelled)
        if self.qml_studio_page:
            self.qml_studio_page.report_discovery_started()
        self._discovery_pool.start(worker)

    def _qml_discovery_requested(self, path: str, count: int):
        resolved = str(Path(path).expanduser().resolve())
        row = next((index for index, source in enumerate(self._sources)
                    if str(Path(source.get("path", "")).expanduser().resolve()) == resolved), -1)
        if row < 0:
            if self.qml_studio_page:
                self.qml_studio_page.controller.set_status("Wait for this video to finish importing before analysis.")
            return
        self.candidate_count.setValue(max(1, min(30, int(count))))
        if row != self.source_list.currentRow():
            self.source_list.setCurrentRow(row)
        self._start_discovery()

    def _discovery_progress(self, event: dict):
        # The detector has no measurable fraction during signal analysis. Keep
        # an indeterminate bar and show only its real current stage.
        self.clip_status.setText(str(event.get("message") or "Analysing the selected video…"))
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())

    def _discovery_completed(self, candidates: list[dict]):
        self._discovery_worker_done()
        if not self._project_store or not self._active_project_id:
            self.clip_status.setText("Analysis finished, but the active project is no longer available.")
            return
        try:
            self._project_store.save_candidates(self._active_project_id, candidates)
            self._project_store.save_project(self._active_project_id, current_stage="review")
        except (OSError, ValueError, KeyError) as exc:
            self.clip_status.setText(f"Found candidates, but could not save the review state: {exc}")
            return
        self._display_candidates(self._project_store.list_candidates(self._active_project_id))
        self.clip_status.setText(
            f"Analysis complete · {len(candidates)} candidate(s). Select one to preview and add it to your ranges."
            if candidates else "Analysis complete · no highlight candidates were found. You can still mark ranges manually."
        )
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())

    def _display_candidates(self, records: list[dict]):
        self.candidate_list.clear()
        for record in records:
            candidate = record.get("payload", record)
            state = record.get("review_state", "pending")
            start, end = candidate.get("start"), candidate.get("end")
            label = str(candidate.get("label") or "Highlight")
            score = candidate.get("score")
            reasons = candidate.get("reasons") or []
            score_text = f" · score {float(score):.2f}" if isinstance(score, (int, float)) else ""
            reason_text = ", ".join(str(reason).replace("_", " ") for reason in reasons)
            reason_text = f" · {reason_text}" if reason_text else ""
            state_text = f" · {state.title()}" if state != "pending" else ""
            item = QListWidgetItem(f"#{candidate.get('rank', '?')}  {label}{score_text}{reason_text}{state_text}")
            item_data = dict(candidate)
            item_data["_studio_candidate_id"] = str(record.get("id") or candidate.get("id") or candidate.get("rank", ""))
            item_data["_studio_review_state"] = state
            item.setData(Qt.ItemDataRole.UserRole, item_data)
            item.setToolTip("Detector output: " + json.dumps(candidate, ensure_ascii=False))
            self.candidate_list.addItem(item)
        if self.qml_studio_page:
            self.qml_studio_page.set_candidates(records)

    def _set_candidate_review(self, state: str):
        item = self.candidate_list.currentItem()
        candidate = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not candidate or not self._project_store or not self._active_project_id:
            self.clip_status.setText("Choose an analysed candidate first.")
            return
        candidate_id = str(candidate.get("_studio_candidate_id") or "")
        self._record_candidate_review(candidate_id, state)

    def _qml_candidate_review(self, candidate_id: str, state: str):
        self._record_candidate_review(candidate_id, state)

    def _qml_candidate_chosen(self, candidate_id: str):
        self._record_candidate_review(candidate_id, "selected")

    def _record_candidate_review(self, candidate_id: str, state: str):
        if not self._project_store or not self._active_project_id:
            return
        try:
            self._project_store.set_candidate_review(self._active_project_id, candidate_id, state)
            self._display_candidates(self._project_store.list_candidates(self._active_project_id))
            for index in range(self.candidate_list.count()):
                entry = self.candidate_list.item(index).data(Qt.ItemDataRole.UserRole)
                if entry.get("_studio_candidate_id") == candidate_id:
                    self.candidate_list.setCurrentRow(index)
                    break
            self.clip_status.setText(f"Candidate marked {state}.")
        except (OSError, ValueError, KeyError) as exc:
            self.clip_status.setText(f"Could not save candidate review state: {exc}")

    def _discovery_failed(self, error: str):
        self._discovery_worker_done()
        self.clip_status.setText(f"Highlight analysis failed: {error}")
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())

    def _discovery_cancelled(self):
        self._discovery_worker_done()
        self.clip_status.setText("Highlight analysis cancelled.")
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())

    def _discovery_worker_done(self):
        self._active_discovery_worker = None
        self.find_highlights_btn.setEnabled(True)
        self.cancel_discovery_btn.hide()
        self.discovery_progress.hide()
        self._set_editor_busy(False)
        if self.qml_studio_page:
            self.qml_studio_page.report_discovery_finished()

    def _cancel_discovery(self):
        if self._active_discovery_worker:
            self._active_discovery_worker.cancel()

    def _use_selected_candidate(self, *_args):
        item = self.candidate_list.currentItem()
        candidate = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(candidate, dict):
            self.clip_status.setText("Choose a candidate first.")
            return
        try:
            start, end = float(candidate["start"]), float(candidate["end"])
            if start < 0 or end <= start:
                raise ValueError("The detector returned an invalid time range.")
        except (KeyError, TypeError, ValueError) as exc:
            self.clip_status.setText(f"This candidate cannot be used: {exc}")
            return
        duration = self.source_player.duration() / 1000
        self.start_seconds.setValue(min(start, duration) if duration else start)
        self.end_seconds.setValue(min(end, duration) if duration else end)
        self.source_player.setPosition(int(start * 1000))
        self._add_range()
        if self._project_store and self._active_project_id:
            candidate_id = str(candidate.get("_studio_candidate_id") or candidate.get("id") or candidate.get("rank") or "")
            if candidate_id:
                try:
                    self._project_store.set_candidate_review(self._active_project_id, candidate_id, "selected")
                except KeyError:
                    pass

    def _add_range(self):
        start, end = self.start_seconds.value(), self.end_seconds.value()
        if end <= start:
            QMessageBox.information(self, "Invalid trim", "The out point must be after the in point.")
            return
        self._ranges.append((start, end))
        self.range_list.addItem(f"Clip {len(self._ranges)} · {self._format_time(start)} – {self._format_time(end)}")
        if self.qml_studio_page:
            self.qml_studio_page.set_ranges(self._ranges)
        self._queue_project_save()

    def _remove_range(self):
        row = self.range_list.currentRow()
        if row >= 0:
            self.range_list.takeItem(row)
            self._ranges.pop(row)
            for index, (start, end) in enumerate(self._ranges, 1):
                self.range_list.item(index - 1).setText(f"Clip {index} · {self._format_time(start)} – {self._format_time(end)}")
            if self.qml_studio_page:
                self.qml_studio_page.set_ranges(self._ranges)
            self._queue_project_save()

    def _layout_changed(self, _index: int):
        self.facecam_box.setVisible(self.aspect_combo.currentData() == "stack")

    def _generate_clips(self):
        if self._active_clip_worker or self._active_preview_proxy or self._preview_render_active:
            self.clip_status.setText("A clip render is already running. Cancel it or wait for it to finish.")
            if self.qml_studio_page:
                self.qml_studio_page.controller.set_status(self.clip_status.text())
            return
        if self._active_discovery_worker:
            self.clip_status.setText("Wait for highlight analysis to finish before rendering clips.")
            return
        if self._active_import_worker:
            self.clip_status.setText("Wait for video import to finish before rendering clips.")
            return
        if not self._catalog or not self._ranges:
            QMessageBox.information(self, "Add clip ranges", "Select a source video and add at least one range.")
            return
        if not self._settings.ffmpeg_path:
            QMessageBox.warning(self, "FFmpeg unavailable", "Restore the bundled FFmpeg or install FFmpeg, then retry.")
            return
        source_index = self.source_list.currentRow()
        if not 0 <= source_index < len(self._sources):
            QMessageBox.information(self, "Choose a source", "Select a video from the imported source list.")
            return
        source = self._sources[source_index]
        selected_ranges = list(self._ranges)
        ranges = ",".join(f"{start:.3f}-{end:.3f}" for start, end in selected_ranges)
        job_dir = self._workspace / "clips" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        options = {"url": source["path"], "ranges": ranges, "count": len(selected_ranges),
                   "layout": self.aspect_combo.currentData(), "style": self.caption_combo.currentData(),
                   "model": self.model_combo.currentData(), "language": None,
                   "facecam": self.facecam_input.text().strip() if self.aspect_combo.currentData() == "stack" else None,
                   "stack_facecam_percent": self.stack_layout.value(), "media_root": str(self._workspace)}
        profile_id = self.profile_combo.currentData() or None
        self._settings.update(transcription_model=options["model"], caption_style=options["style"],
            clip_layout=options["layout"], clip_facecam=self.facecam_input.text().strip(),
            clip_stack_facecam_percent=self.stack_layout.value())
        if self._active_project_id and self._project_store:
            self._project_store.save_project(self._active_project_id, current_stage="exporting")
        self._active_clip_worker = ClipWorker(options, job_dir, self._settings.ffmpeg_path)
        self._active_clip_worker.signals.progress.connect(self._clip_progress)
        self._active_clip_worker.signals.finished.connect(
            lambda payload, sid=source["id"], sp=source["path"], pid=profile_id,
                   ratio=self._ratio_for_layout(options["layout"]), project_id=self._active_project_id:
                   self._clip_finished(payload, sid, sp, pid, ratio, project_id))
        self._active_clip_worker.signals.failed.connect(self._clip_failed)
        self._active_clip_worker.signals.cancelled.connect(self._clip_cancelled)
        self._set_editor_busy(True)
        self.generate_btn.setEnabled(False)
        self.cancel_clip_btn.show()
        self.clip_progress.show()
        self.clip_progress.setValue(0)
        self.clip_status.setText("Starting local clip job…")
        if self.qml_studio_page:
            self.qml_studio_page.report_started()
        QThreadPool.globalInstance().start(self._active_clip_worker)

    @staticmethod
    def _ratio_for_layout(layout: str) -> str:
        return {"landscape": "16:9", "square": "1:1"}.get(layout, "9:16")

    def _clip_progress(self, event: dict):
        percent = int(event.get("percent", 0))
        self.clip_progress.setValue(percent)
        eta = event.get("eta_seconds")
        remaining = "calculating" if eta is None else self._format_time(eta)
        clip, total = event.get("clip", 0), event.get("total", 0)
        self.clip_status.setText(f"{clip} of {total} · {event.get('message', 'Working')} · {percent}% · Time remaining: {remaining}")
        self.task_progress.emit({"id": "clip-studio", "title": "Clip Studio render",
                                 "percent": percent, "message": event.get("message", "Rendering clips")})
        if self.qml_studio_page:
            self.qml_studio_page.report_progress(event)

    def _clip_finished(self, payload: dict, source_id: str, source_path: str,
                       streamer_id: str | None, ratio: str, project_id: str | None = None):
        try:
            entries = payload.get("clips", [])
            identifiers = self._catalog.add_clips(source_id, source_path, streamer_id, entries, ratio) if entries else []
            summary = payload.get("summary", {})
            failed = summary.get("failed", [])
            self.clip_status.setText(f"Generated {len(identifiers)} clip(s); {len(failed)} failed. Saved to {self._workspace / 'clips'}.")
            if payload.get("fatal_error"):
                self.clip_status.setText(str(payload["fatal_error"]))
            self._refresh_clips()
            if identifiers:
                self.tabs.setCurrentWidget(self.library_tab)
                self._select_clip(identifiers[-1])
        except Exception as exc:
            self.clip_status.setText(f"Clips rendered, but the Studio catalog could not be updated: {exc}")
        if project_id and self._project_store:
            try:
                self._project_store.save_project(project_id, current_stage="review")
            except (OSError, ValueError, KeyError) as exc:
                self.clip_status.setText(f"Clips rendered, but project state could not be updated: {exc}")
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())
        self._clip_worker_done()

    def _clip_failed(self, error: str):
        self.clip_status.setText(error)
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(error)
        self._clip_worker_done()

    def _clip_cancelled(self):
        self.clip_status.setText("Clip job cancelled.")
        if self._active_project_id and self._project_store:
            self._project_store.save_project(self._active_project_id, current_stage="editor")
        if self.qml_studio_page:
            self.qml_studio_page.controller.set_status(self.clip_status.text())
        self._clip_worker_done()

    def _clip_worker_done(self):
        self._active_clip_worker = None
        self.task_finished.emit()
        if self.qml_studio_page:
            self.qml_studio_page.report_finished()
        self._set_editor_busy(False)
        self.generate_btn.setEnabled(True)
        self.cancel_clip_btn.hide()
        self.clip_progress.hide()

    def _set_editor_busy(self, busy: bool):
        enabled = not busy
        for name in ("workspace_input", "choose_workspace_btn", "project_combo", "open_project_btn",
                     "relink_source_btn", "import_btn", "source_list", "profile_combo", "find_highlights_btn",
                     "candidate_count", "candidate_list", "use_candidate_btn", "favorite_candidate_btn",
                     "reject_candidate_btn", "timeline", "start_seconds", "end_seconds", "add_range_btn",
                     "remove_range_btn", "range_list", "aspect_combo", "caption_combo", "model_combo",
                     "facecam_input", "facecam_selector", "stack_layout"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(enabled)
        if not busy:
            self.generate_btn.setEnabled(True)

    def recent_clips(self, limit: int = 6) -> list[dict]:
        if not self._catalog:
            return []
        return self._catalog.list_clips()[:max(0, limit)]

    def open_clip(self, clip_id: str) -> None:
        if not self._catalog:
            return
        self._refresh_clips()
        self.tabs.setCurrentWidget(self.library_tab)
        self._select_clip(clip_id)

    def _cancel_clip_job(self):
        if self._active_clip_worker:
            self._active_clip_worker.cancel()
        elif self._active_preview_proxy:
            self._active_preview_proxy.cancel()

    def _refresh_clips(self, *_args):
        if not self._catalog:
            return
        streamer = self.library_profile_combo.currentData() or None
        self._clips = self._catalog.list_clips(self.clip_search.text() if hasattr(self, "clip_search") else "", streamer)
        if not hasattr(self, "clip_table"):
            return
        selected = self._selected_clip_id()
        self.clip_table.setRowCount(0)
        for clip in self._clips:
            row = self.clip_table.rowCount()
            self.clip_table.insertRow(row)
            values = [clip["title"], clip.get("streamer_name") or "—", clip.get("category") or "—",
                      clip.get("game") or "—", clip.get("aspect_ratio", "9:16"), clip.get("publish_status", "draft")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, clip["id"])
                self.clip_table.setItem(row, col, item)
        if selected:
            self._select_clip(selected)

    def _selected_clip_id(self) -> str | None:
        row = self.clip_table.currentRow() if hasattr(self, "clip_table") else -1
        item = self.clip_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_clip(self, clip_id: str):
        for row in range(self.clip_table.rowCount()):
            if self.clip_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == clip_id:
                self.clip_table.selectRow(row)
                return

    def _clip_selected(self):
        clip_id = self._selected_clip_id()
        clip = self._catalog.get_clip(clip_id) if self._catalog and clip_id else None
        if not clip:
            return
        self.metadata_title.setText(clip.get("title", ""))
        self.metadata_description.setPlainText(clip.get("description", ""))
        self.metadata_tags.setText(", ".join(clip.get("tags", [])))
        metadata = clip.get("metadata", {})
        self.metadata_hashtags.setText(", ".join(metadata.get("hashtags", [])))
        category = clip.get("category", "")
        category_index = self.metadata_category.findData(clip.get("metadata", {}).get("category_id", ""))
        if category_index < 0:
            category_index = self.metadata_category.findText(category, Qt.MatchFlag.MatchFixedString)
        self.metadata_category.setCurrentIndex(max(0, category_index))
        self.metadata_genre.setText(clip.get("genre", ""))
        self.metadata_game.setText(clip.get("game", ""))
        language = metadata.get("language", "auto")
        index = self.metadata_language.findData(language)
        if index >= 0:
            self.metadata_language.setCurrentIndex(index)
        elif language and language != "auto":
            self.metadata_language.setCurrentIndex(self.metadata_language.findData("other"))
            self.metadata_language_other.setText(language)
        self.thumbnail_path.setText(clip.get("thumbnail_path", ""))
        self.clip_preview_player.setSource(QUrl.fromLocalFile(clip["file_path"]))
        self.clip_preview_player.pause()

    def _save_clip_metadata(self):
        clip_id = self._selected_clip_id()
        if not clip_id or not self._catalog:
            QMessageBox.information(self, "Choose a clip", "Select a clip from the library first.")
            return
        title = self.metadata_title.text().strip()
        if not title or len(title) >= 60:
            QMessageBox.warning(self, "Invalid title", "YouTube titles must contain 1–59 characters.")
            return
        clip = self._catalog.get_clip(clip_id)
        meta = clip.get("metadata", {})
        meta.update({"hashtags": self._split(self.metadata_hashtags.text()),
                     "category_id": self.metadata_category.currentData(),
                     "language": self._selected_language(), "tone": self.tone_combo.currentData()})
        category = self.metadata_category.currentText()
        self._catalog.update_clip(clip_id, title=title, description=self.metadata_description.toPlainText().strip(),
            tags=self._split(self.metadata_tags.text()), category=category,
            genre=self.metadata_genre.text().strip(), game=self.metadata_game.text().strip(),
            thumbnail_path=self.thumbnail_path.text().strip(), metadata=meta)
        clip = self._catalog.get_clip(clip_id)
        publish_metadata = dict(clip.get("metadata", {}))
        publish_metadata.update({"title": title, "description": self.metadata_description.toPlainText().strip(),
            "tags": self._split(self.metadata_tags.text()), "hashtags": meta.get("hashtags", []),
            "category": category, "category_id": meta.get("category_id"),
            "language": meta.get("language", "auto"),
            "thumbnail_path": self.thumbnail_path.text().strip()})
        for job in self._catalog.list_publish_jobs():
            if job["clip_id"] == clip_id and job["status"] in {"approved", "scheduled"} and not job.get("youtube_video_id"):
                self._catalog.update_publish_job(job["id"], job["status"], metadata=publish_metadata)
        self.metadata_status.setText("Metadata saved to the local Studio catalog.")
        self._refresh_clips()
        self._refresh_publish_jobs()
        self._select_clip(clip_id)

    def _selected_language(self) -> str:
        if self.metadata_language.currentData() == "other":
            return self.metadata_language_other.text().strip()
        return self.metadata_language.currentData()

    def _generate_metadata(self):
        clip_id = self._selected_clip_id()
        clip = self._catalog.get_clip(clip_id) if self._catalog and clip_id else None
        if not clip:
            QMessageBox.information(self, "Choose a clip", "Select a clip with a transcript first.")
            return
        if not clip.get("transcript"):
            QMessageBox.information(self, "Transcript unavailable", "This clip has no transcript. Generate captions by processing it in Clip Studio first.")
            return
        self.metadata_status.setText("Gemini is preparing three transcript-grounded variations…")
        worker = MetadataVariantsWorker(clip["transcript"], clip.get("source_title") or clip["title"],
            self.tone_combo.currentData(), self.language_preference.currentData())
        worker.signals.completed.connect(self._metadata_generated)
        worker.signals.failed.connect(lambda error: self.metadata_status.setText(f"Could not generate metadata: {error}"))
        self._oauth_pool.start(worker)

    def _metadata_generated(self, variants: list[dict]):
        self._metadata_variants = variants
        self.variation_combo.blockSignals(True)
        self.variation_combo.clear()
        for index, variant in enumerate(variants, 1):
            self.variation_combo.addItem(f"Option {index}: {variant['title']}", index - 1)
        self.variation_combo.blockSignals(False)
        self._apply_metadata_variation(0)
        self.metadata_status.setText("Generated three editable variations. Review and save the one you want.")

    def _apply_metadata_variation(self, index: int):
        if not 0 <= index < len(self._metadata_variants):
            return
        variant = self._metadata_variants[index]
        self.metadata_title.setText(variant["title"])
        self.metadata_description.setPlainText(variant["description"])
        self.metadata_tags.setText(", ".join(variant.get("tags", [])))
        self.metadata_hashtags.setText(", ".join(variant.get("hashtags", [])))
        category_index = self.metadata_category.findText(variant.get("category", ""), Qt.MatchFlag.MatchFixedString)
        if category_index >= 0:
            self.metadata_category.setCurrentIndex(category_index)
        language = variant.get("language", "auto")
        found = self.metadata_language.findData(language)
        if found >= 0:
            self.metadata_language.setCurrentIndex(found)
        self.metadata_status.setText("Selected AI option is editable. Save metadata to keep your changes.")

    def _choose_thumbnail(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a thumbnail image", str(self._workspace),
                                               "Images (*.jpg *.jpeg *.png)")
        if path:
            self._copy_thumbnail(Path(path))

    def _copy_thumbnail(self, path: Path):
        clip_id = self._selected_clip_id()
        if not clip_id:
            QMessageBox.information(self, "Choose a clip", "Select a clip before choosing its thumbnail.")
            return
        target_dir = self._workspace / "thumbnails"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{clip_id}.jpg"
        pixmap = QPixmap(str(path))
        if pixmap.isNull() or not pixmap.save(str(target), "JPEG", 92):
            QMessageBox.warning(self, "Invalid thumbnail", "Choose a readable JPG or PNG image.")
            return
        self.thumbnail_path.setText(str(target))

    def _capture_thumbnail(self):
        clip_id = self._selected_clip_id()
        clip = self._catalog.get_clip(clip_id) if self._catalog and clip_id else None
        if not clip:
            QMessageBox.information(self, "Choose a clip", "Select a clip before capturing a frame.")
            return
        if not self._settings.ffmpeg_path:
            return
        target = self._workspace / "thumbnails" / f"{clip_id}.jpg"
        try:
            extract_thumbnail(Path(clip["file_path"]), self.clip_preview_player.position() / 1000,
                              target, self._settings.ffmpeg_path)
            self.thumbnail_path.setText(str(target))
        except Exception as exc:
            QMessageBox.warning(self, "Could not capture thumbnail", str(exc))

    def _refresh_account(self):
        config = LiveClipperSettings().get()
        try:
            from services.live_clipper.secrets import CredentialVault
            connected = bool(CredentialVault().get("youtube.oauth"))
        except Exception:
            connected = False
        if not connected or not config.oauth_client_file:
            self.account_status.setText("Connect YouTube in Settings to schedule uploads.")
            return
        self.account_status.setText("Loading connected YouTube channel…")
        worker = YouTubeAccountWorker(config.oauth_client_file)
        worker.signals.completed.connect(self._account_loaded)
        worker.signals.failed.connect(lambda error: self.account_status.setText(f"YouTube account unavailable: {error}"))
        self._oauth_pool.start(worker)

    def _account_loaded(self, result: dict):
        channel = result.get("channel") or {}
        self.account_status.setText(f"Connected channel: {channel.get('title', 'YouTube channel')} · {channel.get('custom_url', '')}")
        avatar = QPixmap()
        avatar.loadFromData(result.get("avatar", b""))
        if not avatar.isNull():
            self.channel_avatar.setPixmap(avatar.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation))

    def _refresh_publish_jobs(self):
        if not self._catalog or not hasattr(self, "publish_table"):
            return
        self._publish_jobs = self._catalog.list_publish_jobs()
        self.publish_table.setRowCount(0)
        for job in self._publish_jobs:
            row = self.publish_table.rowCount()
            self.publish_table.insertRow(row)
            preview = QTableWidgetItem()
            image_path = job.get("metadata", {}).get("thumbnail_path") or job.get("thumbnail_path", "")
            pixmap = QPixmap(image_path) if image_path else QPixmap()
            if not pixmap.isNull():
                preview.setIcon(QIcon(pixmap.scaled(64, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)))
            self.publish_table.setItem(row, 0, preview)
            state = job["status"]
            if state == "scheduled" and job.get("youtube_video_id"):
                state = "Scheduled on YouTube"
            elif state == "scheduled":
                state = "Queued for upload"
            if state == "unknown":
                state = "Upload outcome unknown · review before retry"
            values = [job.get("metadata", {}).get("title") or job.get("title", "Clip"), state, job.get("scheduled_at", ""),
                      job.get("youtube_video_id", ""), job.get("error", "") or ""]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(str(value))
                if col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, job["id"])
                self.publish_table.setItem(row, col, item)

    @staticmethod
    def _live_publish_jobs(config) -> list[dict]:
        output = Path(config.output_dir).expanduser() if config.output_dir else None
        database = output / ".streamcarnia" / "live_jobs.sqlite3" if output else None
        if not database or not database.is_file():
            return []
        try:
            from services.live_clipper.store import LiveJobStore
            return LiveJobStore(database).list_jobs()
        except (OSError, ValueError):
            return []

    def _schedule_collection(self):
        if not self._catalog:
            return
        rows = self.clip_table.selectionModel().selectedRows()
        clip_ids = []
        for row in rows:
            item = self.clip_table.item(row.row(), 0)
            if item:
                clip_ids.append(item.data(Qt.ItemDataRole.UserRole))
        clips = [clip for clip in self._clips if clip["id"] in clip_ids]
        if not clips:
            QMessageBox.information(self, "Select clips", "Choose one or more clips in the Library tab first.")
            return
        config = LiveClipperSettings().get()
        if not config.oauth_client_file or not Path(config.oauth_client_file).is_file():
            QMessageBox.information(self, "Connect YouTube", "Choose your desktop OAuth client and connect YouTube in Settings first.")
            return
        weekdays = {index for index, checkbox in enumerate(self.weekday_checks) if checkbox.isChecked()}
        try:
            existing_jobs = self._catalog.list_publish_jobs()
            existing_jobs.extend(
                {"status": job["state"], "scheduled_at": job["data"].get("scheduled_at")}
                for job in self._live_publish_jobs(config)
                if job["state"] not in {"failed", "unknown"}
            )
            publish_dates = collection_schedule(
                date.fromisoformat(self.schedule_date.date().toString("yyyy-MM-dd")),
                time.fromisoformat(self.schedule_time.time().toString("HH:mm:ss")), weekdays,
                self.schedule_frequency.value(), len(clips), existing_jobs,
                window_end=time.fromisoformat(self.schedule_end_time.time().toString("HH:mm:ss")))
        except Exception as exc:
            QMessageBox.warning(self, "Schedule unavailable", str(exc))
            return
        collection_name = self.collection_name.text().strip() or f"Collection · {publish_dates[0].date().isoformat()}"
        lines = [f"{slot.astimezone().strftime('%a, %d %b %Y %H:%M')}  —  {clip['title']}"
                 for slot, clip in zip(publish_dates, clips)]
        text = "\n".join(lines)
        if self.approve_before_upload.isChecked():
            answer = QMessageBox.question(self, "Review collection schedule",
                f"{collection_name}\n\n{text}\n\nApprove and upload these videos privately with their publish times?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        profile_id = clips[0].get("streamer_id")
        collection_id = self._catalog.create_collection(collection_name, profile_id,
            {"start_date": publish_dates[0].date().isoformat(), "frequency_days": self.schedule_frequency.value(),
             "weekdays": sorted(weekdays), "window_start": self.schedule_time.time().toString("HH:mm"),
             "window_end": self.schedule_end_time.time().toString("HH:mm")})
        self._catalog.set_collection_clips(collection_id, clip_ids)
        created = []
        try:
            for clip, slot in zip(clips, publish_dates):
                metadata = clip.get("metadata", {})
                metadata.update({"title": clip["title"], "description": clip.get("description", ""),
                    "tags": clip.get("tags", []), "hashtags": metadata.get("hashtags", ["#Shorts"]),
                    "category": clip.get("category", ""), "category_id": metadata.get("category_id"),
                    "language": metadata.get("language", "auto"),
                    "thumbnail_path": clip.get("thumbnail_path", "")})
                self._catalog.create_publish_job(clip["id"], slot.isoformat(), metadata, status="scheduled")
                created.append(clip["id"])
        except Exception as exc:
            QMessageBox.warning(self, "Could not save schedule", f"Some entries may have been saved. Refresh the calendar. {exc}")
        self._refresh_publish_jobs()
        self._tick_publish_queue()

    def _tick_publish_queue(self):
        if self._publish_active or not self._catalog:
            return
        config = LiveClipperSettings().get()
        if not config.oauth_client_file or not Path(config.oauth_client_file).is_file():
            return
        jobs = self._catalog.list_publish_jobs()
        pending = next((job for job in sorted(jobs, key=lambda item: item.get("scheduled_at") or "")
                        if job["status"] == "scheduled" and not job.get("youtube_video_id")), None)
        if not pending:
            return
        from services.live_clipper.secrets import CredentialVault
        try:
            if not CredentialVault().get("youtube.oauth"):
                return
        except Exception:
            return
        now = datetime.now().astimezone()
        uploaded = []
        for job in jobs:
            if job.get("uploaded_at"):
                try:
                    uploaded.append(datetime.fromisoformat(job["uploaded_at"]).astimezone(now.tzinfo))
                except ValueError:
                    pass
        for job in self._live_publish_jobs(config):
            value = job["data"].get("uploaded_at")
            if value:
                try:
                    uploaded.append(datetime.fromisoformat(value).astimezone(now.tzinfo))
                except (ValueError, TypeError):
                    pass
        local_hour = now.replace(minute=0, second=0, microsecond=0)
        from services.live_clipper.scheduler import DAILY_UPLOAD_LIMIT, HOURLY_UPLOAD_LIMIT, _youtube_quota_date
        if sum(item.replace(minute=0, second=0, microsecond=0) == local_hour for item in uploaded) >= HOURLY_UPLOAD_LIMIT:
            self.account_status.setText("Upload queue paused at StreamCarnia’s six-per-hour limit.")
            return
        if sum(_youtube_quota_date(item) == _youtube_quota_date(now) for item in uploaded) >= DAILY_UPLOAD_LIMIT:
            self.account_status.setText("Upload queue paused at the daily YouTube quota safeguard.")
            return
        worker = UploadApprovedStudioWorker(self._catalog.path, pending["id"], config.oauth_client_file)
        worker.signals.completed.connect(self._upload_completed)
        worker.signals.failed.connect(self._upload_failed)
        self._publish_active = True
        self.account_status.setText(f"Uploading privately: {pending['title']}")
        self._publish_pool.start(worker)
        QTimer.singleShot(300, self._refresh_publish_jobs)

    def _upload_completed(self, result: dict):
        self._publish_active = False
        video_id = result.get("video_id")
        self.account_status.setText(f"Uploaded privately. YouTube will publish at the scheduled time. Video ID: {video_id}")
        job = next((item for item in self._catalog.list_publish_jobs() if item["id"] == result.get("job_id")), None)
        thumbnail = Path((job or {}).get("metadata", {}).get("thumbnail_path", ""))
        if video_id and thumbnail.is_file():
            config = LiveClipperSettings().get()
            worker = StudioThumbnailWorker(config.oauth_client_file, video_id, thumbnail)
            self._active_thumbnail_workers.add(worker)
            worker.signals.completed.connect(lambda _id, task=worker: self._thumbnail_task_done(task, result["job_id"], None))
            worker.signals.failed.connect(lambda error, task=worker: self._thumbnail_task_done(task, result["job_id"], error))
            self._thumbnail_pool.start(worker)
        self._refresh_publish_jobs()
        QTimer.singleShot(100, self._tick_publish_queue)

    def _thumbnail_complete(self, job_id: str, error: str | None):
        job = next((item for item in self._catalog.list_publish_jobs() if item["id"] == job_id), None)
        if job:
            metadata = dict(job.get("metadata", {}))
            metadata["thumbnail_set"] = not error
            if error:
                metadata["thumbnail_error"] = error
            self._catalog.update_publish_job(job_id, job["status"], metadata=metadata)
        if error:
            self.account_status.setText(f"Video is scheduled; thumbnail could not be set yet: {error}")

    def _thumbnail_task_done(self, worker, job_id: str, error: str | None):
        self._active_thumbnail_workers.discard(worker)
        self._thumbnail_complete(job_id, error)

    def _upload_failed(self, error: str):
        self._publish_active = False
        self.account_status.setText(f"Upload did not complete: {error}")
        self._refresh_publish_jobs()
        QTimer.singleShot(1000, self._tick_publish_queue)

    def _selected_publish_job(self) -> dict | None:
        row = self.publish_table.currentRow()
        item = self.publish_table.item(row, 1) if row >= 0 else None
        job_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((job for job in self._publish_jobs if job["id"] == job_id), None)

    def _reschedule_selected(self):
        job = self._selected_publish_job()
        if not job or job["status"] not in {"scheduled", "approved"}:
            QMessageBox.information(self, "Choose a scheduled clip", "Select an unpublished scheduled clip to reschedule.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Reschedule clip")
        layout = QVBoxLayout(dialog)
        date_edit = QDateEdit(QDate.fromString(job["scheduled_at"][:10], "yyyy-MM-dd"))
        date_edit.setCalendarPopup(True)
        time_edit = QTimeEdit(QTime.fromString(job["scheduled_at"][11:16], "HH:mm"))
        form = QFormLayout()
        form.addRow("Publish date", date_edit)
        form.addRow("Publish time", time_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        scheduled = datetime.fromisoformat(date_edit.date().toString("yyyy-MM-dd") + "T" + time_edit.time().toString("HH:mm") + ":00").astimezone()
        if scheduled <= datetime.now().astimezone() + timedelta(minutes=15):
            QMessageBox.warning(self, "Invalid date", "Choose a publish time at least 15 minutes from now.")
            return
        config = LiveClipperSettings().get()
        if job.get("youtube_video_id"):
            worker = StudioScheduleUpdateWorker(config.oauth_client_file, job["youtube_video_id"],
                scheduled.isoformat(), job["id"], self._catalog.path)
            worker.signals.completed.connect(lambda _result: self._refresh_publish_jobs())
            worker.signals.failed.connect(lambda error: QMessageBox.warning(self, "Could not reschedule", error))
            self._oauth_pool.start(worker)
        else:
            self._catalog.update_publish_job(job["id"], "scheduled", scheduled_at=scheduled.isoformat())
            self._refresh_publish_jobs()

    def _cancel_schedule_selected(self):
        job = self._selected_publish_job()
        if not job or job["status"] in {"published", "cancelled"}:
            QMessageBox.information(self, "Choose an active schedule", "Select a scheduled or queued clip.")
            return
        answer = QMessageBox.question(self, "Cancel scheduled video?",
            "Cancel this local schedule and, if already uploaded, keep the YouTube video private?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if job.get("youtube_video_id"):
            config = LiveClipperSettings().get()
            worker = StudioScheduleUpdateWorker(config.oauth_client_file, job["youtube_video_id"],
                None, job["id"], self._catalog.path, cancel=True)
            worker.signals.completed.connect(lambda _result: self._refresh_publish_jobs())
            worker.signals.failed.connect(lambda error: QMessageBox.warning(self, "Could not cancel", error))
            self._oauth_pool.start(worker)
        else:
            self._catalog.update_publish_job(job["id"], "cancelled")
            self._refresh_publish_jobs()

    def _retry_upload_selected(self):
        job = self._selected_publish_job()
        if not job or job["status"] not in {"failed", "unknown"} or job.get("youtube_video_id"):
            QMessageBox.information(self, "Choose a failed upload", "Select a failed or unresolved upload without a saved YouTube ID.")
            return
        if job["status"] == "unknown":
            answer = QMessageBox.warning(self, "Upload outcome is unknown",
                "YouTube may have accepted this upload before the connection failed. Retrying could create a duplicate. Retry anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._catalog.update_publish_job(job["id"], "scheduled", error=None)
        self._refresh_publish_jobs()
        self._tick_publish_queue()

    def _refresh_publish_status(self):
        config = LiveClipperSettings().get()
        if not config.oauth_client_file or not self._catalog:
            return
        worker = RefreshStudioPublishWorker(config.oauth_client_file, self._catalog.path)
        worker.signals.completed.connect(lambda _value: self._refresh_publish_jobs())
        worker.signals.failed.connect(lambda error: self.account_status.setText(f"Could not refresh YouTube status: {error}"))
        self._oauth_pool.start(worker)

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    def shutdown(self):
        self._publish_timer.stop()
        self._project_save_timer.stop()
        self._save_project_state()
        if self._active_project_id and self._project_store and (self._active_discovery_worker or self._active_clip_worker):
            try:
                stage = "analysis_interrupted" if self._active_discovery_worker else "render_interrupted"
                self._project_store.save_project(self._active_project_id, current_stage=stage)
            except (OSError, ValueError, KeyError):
                pass
        if self._active_import_worker:
            self._active_import_worker.cancel()
        self._cancel_clip_job()
        if self._active_preview_proxy:
            self._active_preview_proxy.cancel()
        self._cancel_discovery()
        for worker in tuple(self._active_thumbnail_workers):
            worker.cancel()
        self.source_player.stop()
        self.clip_preview_player.stop()
        if self.qml_studio_page:
            self.qml_studio_page.shutdown()
        self._cancel_timeline_thumbnails()
        for pool in (self._import_pool, self._discovery_pool, self._timeline_thumbnail_pool, self._preview_pool,
                     self._oauth_pool, self._publish_pool, self._thumbnail_pool):
            pool.waitForDone(5000)

    def set_accent(self, accent_name: str):
        if self.qml_studio_page:
            self.qml_studio_page.set_accent(accent_name)
