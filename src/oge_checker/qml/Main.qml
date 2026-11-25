import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    width: 1320; height: 900
    minimumWidth: 1000; minimumHeight: 700
    visible: true
    title: "ОГЭ · Проверка работ · Beta-0.8.0" + (backend.state.dirty ? " *" : "")
    color: window.backgroundColor
    font.family: "Segoe UI"
    font.pixelSize: 14
    palette.highlight: window.accentColor
    palette.window: window.backgroundColor
    palette.base: window.inputColor
    palette.text: window.textColor
    palette.windowText: window.textColor
    palette.button: window.selectionColor
    palette.buttonText: window.textColor
    palette.mid: window.borderColor
    palette.dark: window.inputColor
    palette.light: window.borderColor
    palette.placeholderText: window.mutedColor
    palette.disabled.text: window.mutedColor
    palette.disabled.buttonText: window.mutedColor
    palette.highlightedText: "#ffffff"
    readonly property color backgroundColor: backend.darkTheme ? "#101014" : "#f4f1f9"
    readonly property color surfaceColor: backend.darkTheme ? "#1c1a23" : "#ffffff"
    readonly property color inputColor: backend.darkTheme ? "#141218" : "#faf8fd"
    readonly property color textColor: backend.darkTheme ? "#eeeaf5" : "#292033"
    readonly property color mutedColor: backend.darkTheme ? "#b2a9c1" : "#6e607c"
    readonly property color accentColor: backend.darkTheme ? "#7848d8" : "#713dc5"
    readonly property color accentHoverColor: backend.darkTheme ? "#8e5bea" : "#5f2bad"
    readonly property color accentTextColor: backend.darkTheme ? "#d5bbff" : "#572995"
    readonly property color selectionColor: backend.darkTheme ? "#392650" : "#eaddf9"
    readonly property color borderColor: backend.darkTheme ? "#41374e" : "#d9cce5"
    readonly property color disabledColor: backend.darkTheme ? "#302b38" : "#e7e1ec"
    readonly property color warningColor: backend.darkTheme ? "#342a32" : "#fff1d7"
    readonly property color warningTextColor: backend.darkTheme ? "#f0c895" : "#825715"
    property int section: 0
    onClosing: function(close) { close.accepted = backend.canLeave() }

    component ActionButton: Button {
        property bool primary: false
        padding: 12
        background: Rectangle { radius: 4; color: !parent.enabled ? window.disabledColor : parent.primary ? (parent.hovered ? window.accentHoverColor : window.accentColor) : (parent.hovered ? window.selectionColor : window.surfaceColor); border.color: parent.primary ? "transparent" : window.borderColor }
        contentItem: Text { text: parent.text; color: parent.primary ? "#ffffff" : window.textColor; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    }

    component Input: TextField {
        color: window.textColor
        placeholderTextColor: window.mutedColor
        selectionColor: window.accentColor
        padding: 10
        background: Rectangle { color: window.inputColor; radius: 4; border.color: parent.activeFocus ? window.accentHoverColor : window.borderColor }
    }
    component NavTab: TabButton {
        padding: 12
        contentItem: Text { text: parent.text; font: parent.font; color: parent.checked ? window.accentTextColor : window.mutedColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle {
            color: parent.checked ? window.selectionColor : window.surfaceColor
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: parent.parent.checked ? window.accentHoverColor : window.borderColor }
        }
    }

    header: ToolBar {
        background: Rectangle { color: window.surfaceColor; border.color: window.borderColor }
        contentItem: ColumnLayout {
            spacing: 12
            RowLayout {
                Layout.margins: 18
                Label { text: "ОГЭ"; color: window.accentColor; font.pixelSize: 30; font.bold: true }
                ColumnLayout {
                    Label { text: "Проверка работ"; color: window.textColor; font.pixelSize: 22; font.bold: true }
                    Label { text: "Сканы → ключи → результаты"; color: window.mutedColor }
                }
                Item { Layout.fillWidth: true }
                ActionButton { text: "+ Загрузить PDF"; primary: true; enabled: !backend.busy; onClicked: backend.choosePdf() }
                ActionButton { text: "Открыть"; enabled: !backend.busy; onClicked: backend.openProject() }
                ActionButton { text: "Сохранить"; enabled: backend.state.hasProject && !backend.busy; onClicked: backend.saveProject() }
                ActionButton { text: "Excel"; enabled: backend.state.hasProject && !backend.busy; onClicked: backend.exportExcel() }
            }
            RowLayout {
                Layout.leftMargin: 18; Layout.rightMargin: 18; Layout.bottomMargin: 14
                ActionButton { text: "Загрузить ключи"; enabled: !backend.busy; onClicked: backend.importFile("keys") }
                ActionButton { text: "Редактор ключей"; enabled: !backend.busy; onClicked: { backend.beginKeys(); keyDialog.open() } }
                Label { text: backend.state.keyTitle || ""; color: window.mutedColor; Layout.fillWidth: true; elide: Text.ElideRight }
                ActionButton { objectName: "themeToggle"; text: backend.darkTheme ? "Светлая тема" : "Тёмная тема"; onClicked: backend.setDarkTheme(!backend.darkTheme) }
                ActionButton { text: "Импорт правок"; enabled: backend.state.hasProject && !backend.busy; onClicked: backend.importFile("corrections") }
            }
        }
    }
    footer: ToolBar {
        implicitHeight: 44
        background: Rectangle { color: window.surfaceColor; border.color: window.borderColor }
        RowLayout {
            anchors.fill: parent; anchors.margins: 10
            Label { text: backend.status; color: window.mutedColor; Layout.fillWidth: true; elide: Text.ElideMiddle }
            Label { text: backend.state.summary || ""; color: window.mutedColor }
            BusyIndicator { running: backend.busy; visible: running; Layout.preferredHeight: 26; Layout.preferredWidth: 26 }
        }
    }
    RowLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 18
        enabled: !backend.busy
        Rectangle {
            Layout.preferredWidth: 265; Layout.fillHeight: true; radius: 5; color: window.surfaceColor; border.color: window.borderColor
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 12
                Label { text: "Работы учеников"; font.bold: true; font.pixelSize: 18; color: window.textColor }
                Input { id: search; placeholderText: "Имя или страница"; Layout.fillWidth: true }
                ListView {
                    id: pages; objectName: "pagesList"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5
                    model: backend.state.pages || []
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        required property var modelData
                        width: ListView.view.width; height: visible ? 65 : 0
                        visible: (modelData.name + " " + modelData.number).toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                        enabled: !backend.busy
                        background: Rectangle { radius: 4; color: modelData.number === backend.state.pageNumber ? window.selectionColor : "transparent" }
                        contentItem: Column {
                            spacing: 5
                            Label { text: modelData.name; width: parent.width; elide: Text.ElideRight; color: window.textColor }
                            Label { text: "Страница " + modelData.number + (modelData.prepared ? "" : " · ошибка подготовки"); color: window.mutedColor; font.pixelSize: 12 }
                        }
                        onClicked: backend.selectPage(modelData.number)
                    }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            Rectangle {
                Layout.fillWidth: true; implicitHeight: banner.implicitHeight + 24; radius: 4; color: window.selectionColor
                Label { id: banner; anchors.fill: parent; anchors.margins: 12; wrapMode: Text.WordWrap; color: window.accentTextColor; text: backend.state.demo ? "ДЕМО: случайные ключи. Баллы не являются результатом ОГЭ." : backend.state.pageError || "Ответы проверяются автоматически. Сомнительные поля выделены цветом." }
            }
            TabBar {
                id: tabs; Layout.fillWidth: true
                NavTab { text: "Ответы" }
                NavTab { text: "Замены и вариант" }
                NavTab { text: "Результаты" }
                NavTab { text: "Точность" }
            }
            StackLayout {
                currentIndex: tabs.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
                ColumnLayout {
                    CheckBox { id: suspect; text: "Только сомнительные поля" }
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; color: window.surfaceColor; radius: 5
                        ListView {
                            objectName: "fieldsList"; anchors.fill: parent; anchors.margins: 6; clip: true
                            model: backend.state.fields || []
                            ScrollBar.vertical: ScrollBar {}
                            delegate: ItemDelegate {
                                required property var modelData
                                width: ListView.view.width; height: suspect.checked && !modelData.suspect ? 0 : 46
                                visible: height > 0; enabled: !backend.busy
                                background: Rectangle { radius: 5; color: modelData.id === backend.state.selected.id ? window.selectionColor : modelData.suspect ? window.warningColor : window.surfaceColor }
                                contentItem: RowLayout {
                                    Label { text: modelData.label; Layout.preferredWidth: 100; color: window.textColor }
                                    Label { text: modelData.candidate; Layout.fillWidth: true; elide: Text.ElideRight; color: window.mutedColor }
                                    Label { text: modelData.value; Layout.fillWidth: true; elide: Text.ElideRight; color: window.textColor }
                                    Label { text: modelData.confidence; Layout.preferredWidth: 50; color: window.mutedColor }
                                }
                                onClicked: backend.selectField(modelData.id)
                            }
                            Label { anchors.centerIn: parent; visible: !backend.state.hasProject; text: "Загрузите PDF для начала работы"; color: window.mutedColor }
                        }
                    }
                    Label { text: backend.state.selected.label || "Выберите поле"; font.bold: true; color: window.textColor }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 110; radius: 4; color: window.surfaceColor; border.color: window.borderColor
                        Image { objectName: "fieldImage"; anchors.fill: parent; anchors.margins: 8; source: backend.state.image || ""; fillMode: Image.PreserveAspectFit }
                    }
                    RowLayout {
                        Input { objectName: "answerEditor"; Layout.fillWidth: true; text: backend.state.selected.value || ""; enabled: !!backend.state.selected.id && !backend.busy; font.pixelSize: 20; onTextEdited: backend.editField(text); onAccepted: backend.nextField() }
                        ActionButton { text: "Следующее →"; enabled: !backend.busy; onClicked: backend.nextField() }
                        ActionButton { text: "Скан"; onClicked: backend.showImage("original") }
                    }
                    ActionButton { text: "Уточнить OCR по форматам ключа"; enabled: backend.state.hasProject && !backend.busy; onClicked: backend.recheckOCR() }
                    Label { text: backend.state.selected.warning || "Правки применяются сразу. Enter — следующее поле."; color: window.mutedColor; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                }
                ColumnLayout {
                    Label { text: "Вариант работы"; font.bold: true }
                    Label { text: backend.state.subjectName || ""; color: window.accentTextColor }
                    ComboBox { id: variant; model: backend.state.variants || []; currentIndex: Math.max(0, model.indexOf(backend.state.variant)); onActivated: backend.setVariant(currentText, false); enabled: !backend.busy }
                    ActionButton { text: "Назначить всем работам"; enabled: !backend.busy; onClicked: backend.setVariant(variant.currentText, true) }
                    ActionButton { text: "Показать блок замен"; onClicked: backend.showImage("replacements") }
                    Label { text: "Блок замен считывается и применяется автоматически. Ниже — необязательные ручные исправления."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    RowLayout {
                        visible: backend.state.subject === "russian"
                        Label { text: "Грамотность ГК1–ГК4 (русский): −1 = неизвестно" }
                        SpinBox { from: -1; to: 12; value: backend.state.literacy === undefined ? -1 : backend.state.literacy; onValueModified: backend.setLiteracy(value) }
                    }
                    Label { text: "Замены: по одной строке номер=ответ, например 12=3."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { id: draft; text: backend.state.draft || ""; font.pixelSize: 18; enabled: !backend.busy; onTextChanged: if (activeFocus) backend.setDraft(text) } }
                    ActionButton { text: "Применить замены"; primary: true; enabled: !backend.busy; onClicked: backend.applyReplacements(draft.text) }
                    Label { text: backend.state.replacementWarnings || ""; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: window.warningTextColor }
                }
                ListView {
                    objectName: "resultsList"; clip: true; spacing: 6
                    model: backend.state.results || []
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width; height: 80; radius: 4; color: window.surfaceColor
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 12
                            Label { text: modelData.page; Layout.preferredWidth: 35 }
                            ColumnLayout { Layout.fillWidth: true; Label { text: modelData.name; font.bold: true } Label { text: modelData.status; color: window.mutedColor; Layout.fillWidth: true; elide: Text.ElideRight } }
                            Label { text: modelData.total; font.pixelSize: 24; color: window.accentColor }
                            Label { text: "Оценка: " + modelData.grade; color: window.textColor }
                        }
                    }
                }
                ColumnLayout {
                    Label { text: "Измерение по эталонной расшифровке. Уверенность OCR не равна точности."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Flow {
                        Layout.fillWidth: true; spacing: 8
                        ActionButton { text: "Загрузить эталон"; enabled: !backend.busy; onClicked: backend.importFile("reference") }
                        ActionButton { text: "Шаблон CSV"; onClicked: backend.saveTemplate("reference") }
                        ActionButton { text: "Сохранить отчёт"; onClicked: backend.saveMetrics() }
                    }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: backend.state.metrics || ""; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true } }
                }
            }
        }
    }
    Dialog {
        id: errorDialog; title: "Сообщение"; anchors.centerIn: parent; modal: true; width: Math.min(540, window.width - 50); standardButtons: Dialog.Ok
        property string message: ""
        Label { text: errorDialog.message; width: parent.width; wrapMode: Text.WordWrap }
    }
    Dialog {
        id: pdfDialog; title: "Обработка PDF"; anchors.centerIn: parent; modal: true; width: 520; standardButtons: Dialog.Ok | Dialog.Cancel
        property string path: ""
        ColumnLayout { width: parent.width; Label { text: pdfDialog.path; elide: Text.ElideMiddle; Layout.fillWidth: true } Input { id: pdfPages; placeholderText: "Страницы: 1-3,44 или пусто — все"; Layout.fillWidth: true } }
        onAccepted: backend.startPdf(path, pdfPages.text)
    }
    Dialog {
        id: keyDialog; title: "Редактор ключей"; anchors.centerIn: parent; modal: true; width: Math.min(1050, window.width - 60); height: Math.min(800, window.height - 80)
        contentItem: ColumnLayout {
            RowLayout {
                Label { text: "Предмет" }
                ComboBox { model: backend.subjects; textRole: "name"; valueRole: "id"; currentIndex: indexOfValue(backend.keySubject); onActivated: backend.selectKeySubject(currentValue); Layout.fillWidth: true }
                Label { text: "Вариант" }
                ComboBox { model: backend.keyVariants; currentIndex: Math.max(0, model.indexOf(backend.keyVariant)); onActivated: backend.selectKeyVariant(currentText) }
                Label { text: "Заданий" }
                SpinBox { from: 1; to: backend.keySummary.limit || 19; value: backend.keySummary.count || 1; onValueModified: backend.setTaskCount(value) }
            }
            RowLayout {
                Input { id: newVariant; placeholderText: "Номер варианта"; Layout.fillWidth: true }
                ActionButton { text: "+ Вариант"; onClicked: backend.addVariant(newVariant.text) }
                ActionButton { text: "Удалить вариант"; enabled: backend.keyVariants.length > 1; onClicked: backend.removeVariant(backend.keyVariant) }
                ActionButton { text: "Шаблон"; onClicked: backend.saveTemplate("keys") }
            }
            Label { text: "Проверяемый максимум: " + backend.keySummary.maximum + " / полный ОГЭ: " + backend.keySummary.fullMaximum + ". Оценки: " + backend.keySummary.scale; color: window.accentTextColor }
            Label { text: backend.keySummary.note; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: window.mutedColor }
            Label { text: "Предмет задаёт задания, баллы и форматы. Ответы с совпадающими номерами сохраняются. Длина: 0 — без ограничения."; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: window.mutedColor }
            Label { text: "Задание · Ответ (альтернативы: |) · Баллы · Формат · Длина" }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: backend.keyVisibleRows; spacing: 5
                ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    Label { text: modelData.number; Layout.preferredWidth: 45 }
                    Input { text: modelData.answer; Layout.fillWidth: true; onTextEdited: backend.editKeyCell(modelData.rowIndex, "answer", text) }
                    Input { text: modelData.points; Layout.preferredWidth: 55; onTextEdited: backend.editKeyCell(modelData.rowIndex, "points", text); onEditingFinished: backend.refreshKeys() }
                    ComboBox { model: backend.answerTypes; textRole: "name"; valueRole: "id"; currentIndex: indexOfValue(modelData.type); Layout.preferredWidth: 190; onActivated: backend.editKeyCell(modelData.rowIndex, "type", currentValue) }
                    SpinBox { from: 0; to: 256; value: modelData.minLength; Layout.preferredWidth: 95; onValueModified: backend.editKeyCell(modelData.rowIndex, "minLength", value.toString()) }
                    SpinBox { from: 0; to: 256; value: modelData.maxLength; Layout.preferredWidth: 95; onValueModified: backend.editKeyCell(modelData.rowIndex, "maxLength", value.toString()) }
                }
            }
            RowLayout {
                ActionButton { text: "Сохранить JSON"; onClicked: backend.applyKeys(true) }
                Item { Layout.fillWidth: true }
                ActionButton { text: "Отмена"; onClicked: keyDialog.close() }
                ActionButton { text: "Применить"; primary: true; onClicked: if (backend.applyKeys(false)) keyDialog.close() }
            }
        }
    }
    Window {
        id: progressWindow
        objectName: "progressWindow"
        width: 440; height: 220
        x: window.x + (window.width - width) / 2
        y: window.y + (window.height - height) / 2
        minimumWidth: width; maximumWidth: width
        minimumHeight: height; maximumHeight: height
        transientParent: window
        flags: Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        title: "Выполняется операция"
        color: window.surfaceColor
        visible: backend.busy
        onClosing: function(close) { close.accepted = !backend.busy }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 14
            BusyIndicator { Layout.alignment: Qt.AlignHCenter; running: backend.busy; palette.highlight: window.accentColor; palette.windowText: window.accentColor }
            Label { text: backend.status; color: window.textColor; wrapMode: Text.WordWrap; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
            ProgressBar { indeterminate: true; Layout.fillWidth: true; palette.highlight: window.accentColor }
            Label { text: "Дождитесь завершения. Повторный запуск заблокирован."; color: window.mutedColor; wrapMode: Text.WordWrap; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
        }
    }
    Connections {
        target: backend
        function onError(message) { errorDialog.message = message; errorDialog.open() }
        function onPdfChosen(path) { pdfDialog.path = path; pdfPages.text = ""; pdfDialog.open() }
    }
    Shortcut { sequence: "Ctrl+O"; onActivated: backend.openProject() }
    Shortcut { sequence: "Ctrl+S"; onActivated: backend.saveProject() }
}
