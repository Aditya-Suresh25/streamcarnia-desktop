# Qt Quick Studio proof of concept

This isolated surface is loaded by `ui.studio_qml.StudioQmlPage`; it is not
connected to navigation and does not replace the existing Widgets Studio.

## Manual smoke check

From `desktop/`, run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -c "from PySide6.QtWidgets import QApplication; from ui.studio_qml import StudioQmlPage; app=QApplication([]); page=StudioQmlPage(); print(page.view.status(), page.view.errors()); page.open_source(r'C:\path\to\sample.mp4'); page.show(); app.processEvents()"
```

Confirm the QML status is `Ready`, the Browse buttons open the native file
picker, catalog source selection opens the selected path, and the local video
plays and seeks. Drag the in/out handles or focus a handle and use arrow keys
to adjust it; focus the timeline and use arrows to seek (Shift+arrows moves
five seconds; Home/End seeks to the boundaries). Add/remove ranges and confirm
the Python range model updates. The Render button remains disabled until a
host calls `set_renderer_available(True)`. Connecting
`render_requested(path, ranges)` is the explicit handoff boundary; rendering,
progress and completion must come from the host's real worker. A missing
Qt Multimedia codec/backend is surfaced in the status line while the timeline
and local source controls remain available.

Smoke assertion used during development: an offscreen QApplication loads the
QML, verifies `choose_source` exists, opens a temporary two-second local MP4,
creates two ranges, checks rendering is gated until enabled, and asserts the
emitted seconds are exactly `[(0.25, 1.0), (1.1, 1.8)]`. The temporary file is
removed afterward.

The strip intentionally has no frame thumbnails yet. There is no real frame
extraction/thumbnail service in this isolated surface, and the page does not
run FFmpeg or present decorative placeholders as actual frames.

`Studio.qml` is loaded through `core.paths.resource_path` in development and
frozen builds. Packaging must include the QML
directory and Qt Quick/Controls/QML/Multimedia plugins before this page can be
used in a frozen build.
