"""Scrollable in-app guide for the C-SCRuB workflow."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QTextBrowser, QWidget

from dmcscrub_app.ui.tutorial_content import TUTORIAL_MARKDOWN


def _apply_block_spacing(document: QTextDocument) -> None:
    """Apply a clear heading hierarchy and readable Markdown spacing."""
    heading_styles = {
        1: (24.0, "#172033", 0.0, 22.0),
        2: (19.0, "#1f2329", 32.0, 16.0),
        3: (15.0, "#2b2f36", 24.0, 12.0),
        4: (12.0, "#4b515b", 18.0, 9.0),
    }
    block = document.begin()
    while block.isValid():
        block_format = block.blockFormat()
        heading_level = block_format.headingLevel()
        if heading_level:
            size, color, top, bottom = heading_styles.get(
                heading_level, heading_styles[4]
            )
            block_format.setTopMargin(top)
            block_format.setBottomMargin(bottom)
        elif block.textList() is None:
            block_format.setTopMargin(0)
            block_format.setBottomMargin(18)
        else:
            block_format.setTopMargin(3)
            block_format.setBottomMargin(7)

        cursor = QTextCursor(block)
        cursor.setBlockFormat(block_format)
        if heading_level:
            heading_format = QTextCharFormat()
            heading_format.setFontPointSize(size)
            heading_format.setFontWeight(QFont.Weight.Bold)
            heading_format.setForeground(QColor(color))
            cursor.setPosition(block.position())
            cursor.setPosition(
                block.position() + block.length() - 1,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(heading_format)
        block = block.next()


class TutorialView(QWidget):
    """Text-only tutorial shown from the top toolbar."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tutorialView")

        document_view = QTextBrowser()
        document_view.setObjectName("tutorialDocument")
        document_view.setFrameShape(QFrame.NoFrame)
        document_view.setOpenExternalLinks(True)
        document_view.setMaximumWidth(860)
        document_view.viewport().setAutoFillBackground(False)
        document_view.document().setDocumentMargin(0)
        document_view.document().setDefaultStyleSheet(
            """
            h1 { color: #1f2329; font-size: 26px; margin-bottom: 20px; }
            h2 { color: #1f2329; font-size: 19px; margin-top: 24px; }
            h3 { color: #2b2f36; font-size: 15px; margin-top: 20px; }
            p, li { color: #4b515b; font-size: 13px; }
            strong { color: #2b2f36; font-weight: 600; }
            a { color: #2f6fd0; }
            """
        )
        document_view.setMarkdown(TUTORIAL_MARKDOWN)
        _apply_block_spacing(document_view.document())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 40)
        layout.addStretch(1)
        layout.addWidget(document_view, 8)
        layout.addStretch(1)
