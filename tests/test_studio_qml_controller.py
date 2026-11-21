"""Smoke tests for the QML-to-Python Studio contract."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from ui.studio_qml import StudioQmlPage
from ui.pages.studio_page import StudioPage


_APP = QApplication.instance() or QApplication([])


def test_qml_studio_loads_and_render_boundary_sends_real_ranges():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        source = Path(temp) / "source.mp4"
        source.write_bytes(b"test fixture; no decoder is started while the page is hidden")
        page = StudioQmlPage()
        _APP.processEvents()
        try:
            assert page.view.status() == page.view.Status.Ready
            assert not page.view.errors()
            assert page.controller.ranges == []  # Never silently select the entire source.

            page.set_sources([{"path": str(source), "title": "Local source"}])
            assert page.open_source(str(source))
            page.controller.set_duration(12_000)
            page.set_ranges([(2.25, 6.5), (8.0, 10.0)])
            page.set_editor_settings("stack", "karaoke", "large-v3")

            emitted = []
            page.render_requested.connect(lambda path, ranges: emitted.append((path, ranges)))
            page.set_renderer_available(True)
            page.request_render()

            assert emitted == [(str(source.resolve()), [(2.25, 6.5), (8.0, 10.0)])]
            assert page.controller.sourceInLibrary
            assert page.view.rootObject().property("outputLayout") == "stack"
            previewed = []
            page.preview_requested.connect(lambda path, start, end: previewed.append((path, start, end)))
            page.request_preview()
            assert previewed == [(str(source.resolve()), 8.0, 10.0)]
            page.controller.add_range(1.0, 2.0)
            before_drag = list(page.controller.ranges)
            page.controller.begin_range_edit()
            page.controller.set_range_edge(0, 1.5, 0)
            page.controller.end_range_edit()
            page.controller.undo()
            assert page.controller.ranges == before_drag
            page.controller.redo()
            assert page.controller.ranges[0] == {"startMs": 1500, "endMs": 6500}
        finally:
            page.shutdown()
            _APP.processEvents()


def test_qml_candidate_selection_creates_range_and_emits_review_identity():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        source = Path(temp) / "source.mp4"
        source.write_bytes(b"fixture")
        page = StudioQmlPage()
        try:
            page.controller.set_source(str(source))
            page.controller.set_duration(15_000)
            page.set_candidates([{
                "id": "candidate-7",
                "payload": {"rank": 7, "start": 3.5, "end": 8.0,
                            "score": 0.91, "reasons": ["audio_spike"]},
                "review_state": "pending",
            }])
            chosen, reviewed = [], []
            page.controller.candidate_chosen.connect(chosen.append)
            page.candidate_review_requested.connect(lambda identity, state: reviewed.append((identity, state)))

            page.controller.choose_candidate(0)
            page.controller.set_candidate_review(0, "favorite")

            assert chosen == ["candidate-7"]
            assert reviewed == [("candidate-7", "favorite")]
            assert page.controller.ranges == [{"startMs": 3500, "endMs": 8000}]
            assert page.controller.positionMs == 3500
        finally:
            page.shutdown()
            _APP.processEvents()


def test_studio_page_keeps_widgets_fallback_as_default_and_loads_qml_tab():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        workspace = Path(temp) / "media"

        class Settings:
            def __init__(self):
                self.value = SimpleNamespace(
                    studio_workspace_dir=str(workspace), clip_output_dir=str(workspace),
                    download_dir=str(workspace), accent="violet", transcription_model="medium",
                    caption_style="pop", clip_layout="blur", clip_facecam="",
                    clip_stack_facecam_percent=35,
                )
                self.ffmpeg_path = None

            def get(self):
                return self.value

            def update(self, **changes):
                for key, value in changes.items():
                    setattr(self.value, key, value)

        page = StudioPage(Settings())
        _APP.processEvents()
        try:
            labels = [page.tabs.tabText(index) for index in range(page.tabs.count())]
            assert labels == ["Clip Studio", "Timeline editor", "Library & metadata", "Publish calendar"]
            assert page.tabs.tabText(page.tabs.currentIndex()) == "Clip Studio"
            assert page.qml_studio_page is not None
            assert page.qml_studio_page.view.status() == page.qml_studio_page.view.Status.Ready
            assert page._project_store is not None
        finally:
            page.shutdown()
            _APP.processEvents()
