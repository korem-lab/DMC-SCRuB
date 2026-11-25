"""Left column: the Input Summary panel (metrics + input files)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from dmcscrub_app.ui.models import InputFile, InputSummaryVM, MetricRow
from dmcscrub_app.ui.search_index import (
    KIND_LABEL,
    KIND_MISS,
    KIND_PLACEHOLDER,
    KIND_ROW,
    KINDS,
    SearchIndex,
)


@dataclass(frozen=True)
class _CardColor:
    fill: str
    border: str


# Muted, desaturated tints for a professional SnapGene-like feel.
_FILES_COLOR = _CardColor("#eef1f6", "#dde3ec")
_FEATURES_COLOR = _CardColor("#f0eef6", "#e1dbee")
_SAMPLES_COLOR = _CardColor("#eaf2ec", "#d3e3d7")
_CONTROLS_COLOR = _CardColor("#f5f0e7", "#e6dcc8")

# Enough to scroll through; past this the text is too vague to be worth listing.
_MAX_RESULTS = 100
_MAX_LIST_HEIGHT = 180

# Suggestions are drawn by hand, so they carry their own padding and text colour
# instead of inheriting the stylesheet's.
_ITEM_PADDING = 6
_ITEM_TEXT = "#1f2329"
_MUTED_TEXT = "#94a3b8"

# The Find box and the panel title sit above the cards.
_FIRST_CARD_INDEX = 2

_ENTRY_ROLE = Qt.UserRole


def _apply_card_color(card: QFrame, color: _CardColor) -> None:
    card.setStyleSheet(
        f"QFrame#summaryCard {{ background: {color.fill}; border: 1px solid {color.border}; }}"
    )


class _RichTextDelegate(QStyledItemDelegate):
    """Draws suggestions as rich text, which is how a batch name gets its bold."""

    def paint(self, painter, option, index) -> None:  # noqa: N802 (Qt override)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        document = self._document(styled)
        # The row's own background and hover state still come from the stylesheet;
        # only the text is ours to draw.
        styled.text = ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        painter.save()
        painter.translate(styled.rect.left() + _ITEM_PADDING, styled.rect.top() + 2)
        document.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt override)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        document = self._document(styled)
        return QSize(
            int(document.idealWidth()) + _ITEM_PADDING * 2,
            int(document.size().height()) + 4,
        )

    def _document(self, styled: QStyleOptionViewItem) -> QTextDocument:
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(styled.font)
        document.setDefaultStyleSheet(f"body {{ color: {_ITEM_TEXT}; }}")
        document.setHtml(f"<body>{styled.text}</body>")
        return document


class FindBox(QWidget):
    """Find a sample, a control, a step or a batch, and point the diagram at it.

    Emits `cleared` on every keystroke before anything else: a highlight is only ever
    true for one exact target, so the moment the text stops being that target the
    colour has to go, which is also what makes deleting a character undo it. Changing
    kind leaves the colour alone, since nothing about the search was retyped.
    """

    selected = Signal(str, str)
    cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._index = SearchIndex()

        header = QLabel("Find")
        header.setObjectName("panelTitle")
        self.kind_box = QComboBox()
        self.kind_box.setObjectName("findKind")
        for kind in KINDS:
            self.kind_box.addItem(KIND_LABEL[kind], kind)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(header)
        top.addStretch(1)
        top.addWidget(self.kind_box)

        self.field = QLineEdit()
        self.field.setPlaceholderText(KIND_PLACEHOLDER[KIND_ROW])
        self.field.setClearButtonEnabled(True)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("dagToolbarButton")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.field, 1)
        row.addWidget(self.search_button)

        self.results = QListWidget()
        self.results.setObjectName("searchResults")
        self.results.setItemDelegate(_RichTextDelegate(self.results))
        self.results.setMaximumHeight(_MAX_LIST_HEIGHT)
        self.results.hide()

        self.hint = QLabel()
        self.hint.setObjectName("metricLabel")
        self.hint.setWordWrap(True)
        self.hint.hide()

        # No margins and no tint: this block is a sibling of the "Input Summary"
        # heading, not one of the cards under it, so it lines up with the heading.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addLayout(row)
        layout.addWidget(self.results)
        layout.addWidget(self.hint)

        self.field.textChanged.connect(self._on_text_changed)
        self.field.returnPressed.connect(self._on_search_clicked)
        self.search_button.clicked.connect(self._on_search_clicked)
        self.results.itemClicked.connect(self._on_item_clicked)
        self.kind_box.currentIndexChanged.connect(self._on_kind_changed)

    @property
    def kind(self) -> str:
        return str(self.kind_box.currentData())

    def set_index(self, index: SearchIndex) -> None:
        """Swap in a new set of findable names, leaving any live search alone.

        Called again on every graph rebuild, where the diagram keeps its highlight, so
        clearing the field here would leave the colour on screen with nothing typed.
        """
        self._index = index
        self._fill_results(self.field.text().strip())

    def reset(self) -> None:
        self.field.blockSignals(True)
        self.field.clear()
        self.field.blockSignals(False)
        self.results.clear()
        self.results.hide()
        self.set_hint("")

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def _on_text_changed(self, text: str) -> None:
        self.cleared.emit()
        self.set_hint("")
        self._fill_results(text.strip())

    def _on_kind_changed(self) -> None:
        self.field.setPlaceholderText(KIND_PLACEHOLDER[self.kind])
        self.set_hint("")
        self._fill_results(self.field.text().strip())

    def _fill_results(self, text: str) -> None:
        self.results.clear()
        if not text:
            self.results.hide()
            return
        matches = self._index.matches(self.kind, text)
        if not matches:
            self.results.hide()
            self.set_hint(KIND_MISS[self.kind])
            return
        for match in matches[:_MAX_RESULTS]:
            item = QListWidgetItem(match.html)
            item.setData(_ENTRY_ROLE, match.value)
            self.results.addItem(item)
        if len(matches) > _MAX_RESULTS:
            overflow = QListWidgetItem(
                f"<span style='color:{_MUTED_TEXT}'>\u2026 and "
                f"{len(matches) - _MAX_RESULTS} more</span>"
            )
            overflow.setFlags(Qt.NoItemFlags)
            self.results.addItem(overflow)
        # Sized to its contents: left to the layout, a list inside a scrolling panel
        # of cards collapses to a couple of rows however many matches there are.
        row_height = self.results.sizeHintForRow(0)
        self.results.setFixedHeight(
            min(_MAX_LIST_HEIGHT, self.results.count() * row_height + 8)
        )
        self.results.show()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        value = item.data(_ENTRY_ROLE)
        if value:
            self._choose(str(value))

    def _on_search_clicked(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        value = self._index.resolve(self.kind, text)
        if value is None:
            self.set_hint("No exact match. Pick one from the list above.")
            return
        self._choose(value)

    def _choose(self, value: str) -> None:
        self.field.blockSignals(True)
        self.field.setText(value)
        self.field.blockSignals(False)
        self.results.hide()
        self.set_hint("")
        self.selected.emit(self.kind, value)


class _MetricCard(QFrame):
    """A titled, tinted card listing label/value metric rows."""

    def __init__(self, title: str, rows: list[MetricRow], color: _CardColor) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        _apply_card_color(self, color)

        header = QLabel(title)
        header.setObjectName("summaryCardTitle")

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        for row_index, row in enumerate(rows):
            label = QLabel(row.label)
            label.setObjectName("metricLabel")
            value = QLabel(row.value)
            value.setObjectName("metricValue")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(header)
        layout.addLayout(grid)


class _FilesCard(QFrame):
    """A tinted card listing input files with a validity indicator."""

    def __init__(self, files: list[InputFile], color: _CardColor) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        _apply_card_color(self, color)

        header = QLabel("Input Files")
        header.setObjectName("summaryCardTitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(header)

        for file in files:
            row = QWidget()
            row_layout = QGridLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setColumnStretch(0, 1)
            name = QLabel(file.name)
            name.setObjectName("fileName")
            status = QLabel("\u2713" if file.ok else "\u2717")
            status.setObjectName("fileOk" if file.ok else "fileBad")
            status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_layout.addWidget(name, 0, 0)
            row_layout.addWidget(status, 0, 1)
            layout.addWidget(row)


class InputSummaryPanel(QScrollArea):
    """Scrollable stack of summary cards for one dataset."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("summaryPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(16)
        self.setWidget(self._content)

        self.find = FindBox()
        self._layout.addWidget(self.find)

        self._title = QLabel("Input Summary")
        self._title.setObjectName("panelTitle")
        self._layout.addWidget(self._title)
        self._layout.addStretch(1)

    def set_summary(self, summary: InputSummaryVM) -> None:
        self._clear_cards()
        # Order requested by the user: Input Files -> Features -> Samples -> Controls.
        cards = [
            _FilesCard(summary.files, _FILES_COLOR),
            _MetricCard("Features", summary.features, _FEATURES_COLOR),
            _MetricCard("Samples", summary.samples, _SAMPLES_COLOR),
            _MetricCard("Controls", summary.controls, _CONTROLS_COLOR),
        ]
        for index, card in enumerate(cards):
            self._layout.insertWidget(_FIRST_CARD_INDEX + index, card)

    def _clear_cards(self) -> None:
        while self._layout.count() > _FIRST_CARD_INDEX + 1:
            item = self._layout.takeAt(_FIRST_CARD_INDEX)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
