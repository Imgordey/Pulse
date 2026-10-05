"""Confirmation text always stays literal, including untrusted filenames."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget


def question(
    parent: QWidget,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton,
    default: QMessageBox.StandardButton,
) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    box.setStandardButtons(buttons)
    box.setDefaultButton(default)
    answer = QMessageBox.StandardButton(box.exec())
    box.deleteLater()
    return answer
