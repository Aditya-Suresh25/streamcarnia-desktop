import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Rectangle {
    id: root
    color: studioController.theme.bg
    property int requestedPosition: -1
    property bool playing: false
    property bool rendering: false
    property bool analyzing: false
    property bool active: false
    property bool renderedPreview: false
    property string outputLayout: "blur"
    property string captionStyle: "pop"
    property string speechModel: "medium"

    function formatTime(ms) {
        var s = Math.floor(Math.max(0, ms) / 1000)
        var h = Math.floor(s / 3600)
        var m = Math.floor((s % 3600) / 60)
        var sec = s % 60
        function two(n) { return n < 10 ? "0" + n : "" + n }
        return h > 0 ? h + ":" + two(m) + ":" + two(sec) : two(m) + ":" + two(sec)
    }
    function seekTo(ms) { player.position = Math.max(0, Math.min(ms, player.duration)); studioController.set_position(player.position) }
    function stopPreview() { player.pause(); player.stop() }
    function showRenderedPreview() { root.playing = false; root.renderedPreview = true; player.position = 0; player.play() }

    MediaPlayer {
        id: player
        source: root.active ? (root.renderedPreview ? studioController.previewUrl : studioController.sourceUrl) : ""
        videoOutput: videoOutput
        audioOutput: AudioOutput {}
        onDurationChanged: if (!root.renderedPreview) studioController.set_duration(duration)
        onPositionChanged: if (!root.renderedPreview) studioController.set_position(position)
        onPlaybackStateChanged: root.playing = playbackState === MediaPlayer.PlayingState
        onMediaStatusChanged: {
            if (mediaStatus === MediaPlayer.Loaded || mediaStatus === MediaPlayer.Buffered)
                studioController.set_status("Media ready · previewing the original source")
            else if (mediaStatus === MediaPlayer.EndOfMedia)
                studioController.set_status("Playback complete")
        }
        onErrorOccurred: function(error, errorString) {
            if (error !== MediaPlayer.NoError)
                studioController.set_status("Playback unavailable: " + errorString)
        }
    }
    onRequestedPositionChanged: {
        if (requestedPosition >= 0) { seekTo(requestedPosition); requestedPosition = -1 }
    }
    onActiveChanged: {
        if (!active) { player.pause(); player.stop() }
    }
    ScrollView {
        id: pageScroll
        anchors.fill: parent
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        ColumnLayout {
        x: 24
        width: Math.max(1, pageScroll.availableWidth - 48)
        spacing: 14
        Item { Layout.preferredHeight: 4 }

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            ColumnLayout {
                spacing: 3
                Label { text: "CLIP STUDIO"; color: studioController.theme.accent_hover; font.family: studioController.displayFont; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.4 }
                Label { text: "Edit a moment"; color: studioController.theme.text; font.family: studioController.displayFont; font.pixelSize: 25; font.bold: true }
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "Choose video…"
                enabled: !root.rendering && !root.analyzing
                Accessible.name: "Choose a local video"
                onClicked: studioPage.choose_source()
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            ComboBox {
                id: sourcePicker
                enabled: !root.rendering && !root.analyzing
                Layout.preferredWidth: 280
                visible: studioController.sources.length > 0
                model: studioController.sources
                textRole: "title"
                currentIndex: {
                    for (var i = 0; i < studioController.sources.length; ++i)
                        if (studioController.sources[i].path === studioController.sourcePath) return i
                    return -1
                }
                Accessible.name: "Choose from catalog sources"
                onActivated: function(index) {
                    if (index >= 0 && index < studioController.sources.length)
                        studioController.open_source(studioController.sources[index].path)
                }
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Label { text: "Output"; color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 11 }
            ComboBox {
                id: layoutPicker
                enabled: !root.rendering && !root.analyzing
                Layout.fillWidth: true
                textRole: "label"
                valueRole: "value"
                model: [
                    { label: "Portrait · 9:16", value: "blur" },
                    { label: "Facecam above gameplay", value: "stack" },
                    { label: "Landscape · 16:9", value: "landscape" },
                    { label: "Square · 1:1", value: "square" }
                ]
                currentIndex: Math.max(0, indexOfValue(root.outputLayout))
                Accessible.name: "Clip layout"
                onActivated: studioPage.set_output_settings(currentValue, captionPicker.currentValue, modelPicker.currentValue)
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
            }
            ComboBox {
                id: captionPicker
                enabled: !root.rendering && !root.analyzing
                Layout.fillWidth: true
                textRole: "label"
                valueRole: "value"
                model: [
                    { label: "Pop captions", value: "pop" },
                    { label: "Bounce captions", value: "bounce" },
                    { label: "Word captions", value: "word" },
                    { label: "Karaoke captions", value: "karaoke" }
                ]
                currentIndex: Math.max(0, indexOfValue(root.captionStyle))
                Accessible.name: "Animated caption style"
                onActivated: studioPage.set_output_settings(layoutPicker.currentValue, currentValue, modelPicker.currentValue)
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
            }
            ComboBox {
                id: modelPicker
                enabled: !root.rendering && !root.analyzing
                Layout.fillWidth: true
                textRole: "label"
                valueRole: "value"
                model: [
                    { label: "Speech · small", value: "small" },
                    { label: "Speech · medium", value: "medium" },
                    { label: "Speech · large-v3", value: "large-v3" }
                ]
                currentIndex: Math.max(0, indexOfValue(root.speechModel))
                Accessible.name: "Speech recognition model"
                onActivated: studioPage.set_output_settings(layoutPicker.currentValue, captionPicker.currentValue, currentValue)
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            SpinBox {
                id: candidateLimit
                from: 1; to: 30; value: 8
                enabled: !root.rendering && !root.analyzing
                Accessible.name: "Number of highlights to find"
            }
            Button {
                text: "Find highlight moments"
                enabled: studioController.sourceInLibrary && studioController.sourcePath.length > 0 && !root.analyzing && !root.rendering
                onClicked: studioPage.find_highlights(candidateLimit.value)
                background: Rectangle { color: parent.enabled ? studioController.theme.panel_alt : studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            BusyIndicator { running: root.analyzing; visible: running; implicitWidth: 26; implicitHeight: 26 }
            Button {
                text: "Cancel analysis"
                visible: root.analyzing
                onClicked: studioPage.cancel_highlight_search()
                background: Rectangle { color: studioController.theme.panel_alt; border.color: studioController.theme.border; radius: 8 }
            }
            Item { Layout.fillWidth: true }
            Label {
                text: studioController.sourceInLibrary ? "Analysis reuses StreamCarnia's local highlight detector" : "Importing source into the project library…"
                color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.preferredHeight: studioController.candidates.length > 0 ? Math.min(150, studioController.candidates.length * 48) : 0
            visible: studioController.candidates.length > 0
            clip: true
            model: studioController.candidates
            spacing: 4
            delegate: Rectangle {
                required property int index
                required property var modelData
                width: ListView.view.width
                height: 44
                color: studioController.theme.panel
                border.color: studioController.theme.border_hair
                radius: 8
                property var clipCandidate: modelData.payload || modelData
                RowLayout {
                    anchors.fill: parent; anchors.margins: 6; spacing: 8
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 1
                        Label {
                            text: "#" + (clipCandidate.rank || "?") + "  " + (clipCandidate.label || "Highlight") + (clipCandidate.score !== undefined && clipCandidate.score !== null ? " · score " + Number(clipCandidate.score).toFixed(2) : "")
                            color: studioController.theme.text; font.family: studioController.bodyFont; font.pixelSize: 11; elide: Text.ElideRight
                        }
                        Label {
                            text: (clipCandidate.reasons || []).join(" · ")
                            color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 9; elide: Text.ElideRight
                        }
                    }
                    ToolButton {
                        text: "Use"
                            enabled: !root.rendering && !root.analyzing
                        Accessible.name: "Use this detected highlight"
                        onClicked: studioController.choose_candidate(index)
                    }
                    ToolButton {
                        text: "★"
                            enabled: !root.rendering && !root.analyzing
                        Accessible.name: "Favorite this highlight"
                        onClicked: studioController.set_candidate_review(index, "favorite")
                    }
                    ToolButton {
                        text: "×"
                            enabled: !root.rendering && !root.analyzing
                        Accessible.name: "Reject this highlight"
                        onClicked: studioController.set_candidate_review(index, "rejected")
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 280
            Layout.minimumHeight: 190
            color: studioController.theme.card
            border.color: studioController.theme.border_hair
            radius: 14
            VideoOutput {
                id: videoOutput
                anchors.fill: parent
                anchors.margins: 1
                fillMode: VideoOutput.PreserveAspectFit
            }
            Column {
                anchors.centerIn: parent
                spacing: 7
                visible: studioController.sourcePath.length === 0
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Choose a local video"; color: studioController.theme.text; font.family: studioController.displayFont; font.pixelSize: 20; font.bold: true }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Choose a source to preview and edit"; color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 12 }
                Button {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Browse videos"
                    enabled: !root.rendering && !root.analyzing
                    Accessible.name: "Browse for a local video"
                    onClicked: studioPage.choose_source()
                    background: Rectangle { color: studioController.theme.accent; radius: 8 }
                    contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.bold: true; horizontalAlignment: Text.AlignHCenter }
                }
            }
            Label {
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 12
                width: parent.width - 24; elide: Text.ElideMiddle
                text: studioController.sourcePath
                color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 11
                visible: studioController.sourcePath.length > 0
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: root.renderedPreview ? "Rendered output preview" : "Source preview"
                color: studioController.theme.accent_hover
                font.family: studioController.displayFont
                font.pixelSize: 11
                font.bold: true
            }
            Item { Layout.fillWidth: true }
            Button {
                visible: studioController.previewUrl.length > 0 && !root.renderedPreview
                text: "View rendered preview"
                onClicked: root.showRenderedPreview()
            }
            Button {
                visible: root.renderedPreview
                text: "Back to source"
                onClicked: { root.playing = false; root.renderedPreview = false; player.pause() }
            }
            ToolButton {
                text: root.playing ? "Ⅱ" : "▶"
                enabled: studioController.sourcePath.length > 0
                onClicked: root.playing ? player.pause() : player.play()
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.pixelSize: 19; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: studioController.theme.panel; border.color: studioController.theme.border; radius: 8 }
            }
            Label { text: root.formatTime(studioController.positionMs); color: studioController.theme.text; font.family: studioController.bodyFont; font.pixelSize: 12 }
            Slider {
                Layout.fillWidth: true
                from: 0; to: Math.max(1, studioController.durationMs)
                value: studioController.positionMs
                onMoved: root.seekTo(value)
            }
            Label { text: root.formatTime(studioController.durationMs); color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 12 }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            color: studioController.theme.panel
            border.color: studioController.theme.border_hair
            radius: 12
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "CLIP RANGES"; color: studioController.theme.text_dim; font.family: studioController.displayFont; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.2 }
                    Item { Layout.fillWidth: true }
                    ToolButton {
                        text: "Undo"
                        Accessible.name: "Undo timeline edit"
                        enabled: studioController.canUndo
                        onClicked: studioController.undo()
                    }
                    ToolButton {
                        text: "Redo"
                        Accessible.name: "Redo timeline edit"
                        enabled: studioController.canRedo
                        onClicked: studioController.redo()
                    }
                    Label { text: studioController.durationMs > 0 ? root.formatTime(studioController.durationMs) : "--:--"; color: studioController.theme.text_faint; font.pixelSize: 10 }
                }
                Item {
                    id: timeline
                    Layout.fillWidth: true; Layout.fillHeight: true
                        enabled: !root.rendering && !root.analyzing
                    focus: true
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Slider
                    Accessible.name: "Clip timeline. Use left and right arrows to seek one second; Shift plus arrows seeks five seconds."
                    Keys.onPressed: function(event) {
                        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_Z) {
                            if (event.modifiers & Qt.ShiftModifier) studioController.redo()
                            else studioController.undo()
                            event.accepted = true
                            return
                        }
                        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_Y) {
                            studioController.redo(); event.accepted = true; return
                        }
                        if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
                            var step = event.modifiers & Qt.ShiftModifier ? 5000 : 1000
                            var direction = event.key === Qt.Key_Left ? -1 : 1
                            studioController.seek_to(Math.max(0, Math.min(studioController.durationMs, studioController.positionMs + direction * step)))
                            event.accepted = true
                        } else if (event.key === Qt.Key_Home) {
                            studioController.seek_to(0); event.accepted = true
                        } else if (event.key === Qt.Key_End) {
                            studioController.seek_to(studioController.durationMs); event.accepted = true
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.color: timeline.activeFocus ? studioController.theme.accent_hover : "transparent"
                        radius: 4
                        z: 5
                    }
                    Repeater {
                        model: studioController.thumbnails
                        delegate: Image {
                            required property int index
                            required property var modelData
                            width: timeline.width / Math.max(1, studioController.thumbnails.length)
                            height: timeline.height
                            x: index * width
                            source: modelData.url
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: true
                            opacity: 0.55
                        }
                    }
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 8; radius: 4; color: studioController.theme.bg_alt }
                    Repeater {
                        model: studioController.ranges
                        delegate: Rectangle {
                            required property int index
                            required property var modelData
                            property real scale: timeline.width / Math.max(1, studioController.durationMs)
                            z: 1
                            x: modelData.startMs * scale
                            width: Math.max(12, (modelData.endMs - modelData.startMs) * scale)
                            anchors.verticalCenter: parent.verticalCenter
                            height: studioController.activeRange === index ? 18 : 13
                            radius: 5
                            color: studioController.theme.accent
                            opacity: studioController.activeRange === index ? 0.95 : 0.52
                            MouseArea {
                                anchors.fill: parent
                                onClicked: studioController.select_range(index)
                                onPressed: studioController.select_range(index)
                            }
                            Rectangle {
                                id: inHandle; x: -4; width: 10; height: 24; radius: 4; anchors.verticalCenter: parent.verticalCenter
                                color: studioController.theme.text
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Slider
                                Accessible.name: "Clip " + (index + 1) + " in point. Use arrow keys to adjust by one second."
                                Keys.onLeftPressed: studioController.set_range_edge(index, Math.max(0, modelData.startMs / 1000 - 1), 0)
                                Keys.onRightPressed: studioController.set_range_edge(index, Math.min(modelData.endMs / 1000 - 0.1, modelData.startMs / 1000 + 1), 0)
                                MouseArea {
                                    anchors.fill: parent; cursorShape: Qt.SizeHorCursor
                                    Accessible.name: "Drag clip in point"
                                    property real originX: 0
                                    onReleased: studioController.end_range_edit()
                                    onPressed: function(mouse) {
                                        studioController.begin_range_edit()
                                        originX = mapToItem(timeline, mouse.x, mouse.y).x
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (!pressed || studioController.durationMs <= 0) return
                                        var localX = mapToItem(timeline, mouse.x, mouse.y).x
                                        studioController.set_range_edge(index, Math.max(0, localX / timeline.width * studioController.durationMs) / 1000, 0)
                                    }
                                }
                            }
                            Rectangle {
                                x: parent.width - 6; width: 10; height: 24; radius: 4; anchors.verticalCenter: parent.verticalCenter
                                color: studioController.theme.text
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Slider
                                Accessible.name: "Clip " + (index + 1) + " out point. Use arrow keys to adjust by one second."
                                Keys.onLeftPressed: studioController.set_range_edge(index, Math.max(modelData.startMs / 1000 + 0.1, modelData.endMs / 1000 - 1), 1)
                                Keys.onRightPressed: studioController.set_range_edge(index, Math.min(studioController.durationMs / 1000, modelData.endMs / 1000 + 1), 1)
                                MouseArea {
                                    anchors.fill: parent; cursorShape: Qt.SizeHorCursor
                                    Accessible.name: "Drag clip out point"
                                    onPressed: studioController.begin_range_edit()
                                    onReleased: studioController.end_range_edit()
                                    onPositionChanged: function(mouse) {
                                        if (!pressed || studioController.durationMs <= 0) return
                                        var localX = mapToItem(timeline, mouse.x, mouse.y).x
                                        studioController.set_range_edge(index, Math.max(0, localX / timeline.width * studioController.durationMs) / 1000, 1)
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        z: 2
                        visible: studioController.durationMs > 0
                        x: studioController.positionMs / Math.max(1, studioController.durationMs) * timeline.width - 1
                        y: 0; width: 2; height: parent.height
                        color: studioController.theme.warning
                    }
                    MouseArea {
                        anchors.fill: parent; z: 0
                        onClicked: function(mouse) {
                            timeline.forceActiveFocus()
                            if (studioController.durationMs > 0)
                                studioController.seek_to(mouse.x / width * studioController.durationMs)
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: studioController.statusText; color: studioController.theme.text_dim; font.family: studioController.bodyFont; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
            Button {
                text: "+ Add range"
                Accessible.name: "Add a clip range at the playhead"
                enabled: studioController.durationMs > 0 && !root.rendering && !root.analyzing
                onClicked: {
                    var p = studioController.positionMs / 1000
                    studioController.add_range(p, Math.min(studioController.durationMs / 1000, p + 30))
                }
                background: Rectangle { color: studioController.theme.panel_alt; border.color: studioController.theme.border; radius: 8 }
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            Button {
                text: "Remove range"
                Accessible.name: "Remove selected clip range"
                enabled: studioController.activeRange >= 0 && !root.rendering && !root.analyzing
                onClicked: studioController.remove_range(studioController.activeRange)
                background: Rectangle { color: studioController.theme.panel_alt; border.color: studioController.theme.border; radius: 8 }
                contentItem: Label { text: parent.text; color: parent.enabled ? studioController.theme.text : studioController.theme.text_faint; font.family: studioController.bodyFont; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            Button {
                text: "Render preview"
                Accessible.name: "Render a preview of the selected range with the current layout and captions"
                enabled: studioController.renderAvailable && studioController.sourceInLibrary && studioController.activeRange >= 0 && !root.rendering && !root.analyzing
                onClicked: studioPage.request_preview()
                background: Rectangle { color: studioController.theme.panel_alt; border.color: studioController.theme.border; radius: 8 }
                contentItem: Label { text: parent.text; color: parent.enabled ? studioController.theme.text : studioController.theme.text_faint; font.family: studioController.bodyFont; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            Button {
                text: "Render clips"
                Accessible.name: "Render selected clip ranges"
                visible: !root.rendering
                enabled: studioController.renderAvailable && studioController.sourceInLibrary && studioController.sourcePath.length > 0 && studioController.ranges.length > 0 && !root.analyzing
                onClicked: studioPage.request_render()
                background: Rectangle { color: parent.enabled ? studioController.theme.accent : studioController.theme.panel_alt; radius: 8 }
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.bold: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
            Button {
                text: "Cancel render"
                Accessible.name: "Cancel clip rendering"
                visible: root.rendering
                onClicked: studioPage.cancel_render()
                background: Rectangle { color: studioController.theme.danger_dim; border.color: studioController.theme.danger; radius: 8 }
                contentItem: Label { text: parent.text; color: studioController.theme.text; font.family: studioController.bodyFont; font.bold: true; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
            }
        }
        Item { Layout.preferredHeight: 8 }
        }
    }
}
