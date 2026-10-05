from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QVBoxLayout,
)

from pulse.presentation.formatting import format_size as size_text

__all__ = ["Metric", "label", "size_text", "table"]


def label(text: str = "", role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(True)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class Metric(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.addWidget(label(title, "muted"))
        self.value = label("—", "metric")
        self.detail = label("Waiting for a sample", "muted")
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def update_value(self, value: str, detail: str) -> None:
        self.value.setText(value)
        self.detail.setText(detail)
