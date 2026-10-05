"""An exact, unchecked file selection; no executor runs without a second confirmation."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from pulse.cleanup.models import CleanupPlan
from pulse.desktop.widgets import label, size_text, table


class CleanupDialog(QDialog):
    def __init__(self, plan: CleanupPlan, parent=None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.selected_plan: CleanupPlan | None = None
        self.setWindowTitle("Review cache cleanup")
        self.resize(840, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Review before removing", "title"))
        layout.addWidget(label(str(plan.root), "muted"))
        layout.addWidget(
            label(
                "Only recognized pip download cache files unused for at least seven days "
                "appear here. "
                "Close pip and installers first. Removed downloads may need to be fetched again. "
                "Removal is permanent; files do not go to Trash."
            )
        )
        if plan.warnings or not plan.complete:
            layout.addWidget(label("Plan unavailable: " + "; ".join(plan.warnings), "warning"))
        self.files = table(["Select", "Size", "File relative to cache"])
        self.files.setRowCount(len(plan.files))
        for row, entry in enumerate(plan.files):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            self.files.setItem(row, 0, check)
            self.files.setItem(row, 1, QTableWidgetItem(size_text(entry.identity.size)))
            self.files.setItem(row, 2, QTableWidgetItem(str(entry.relative_path)))
        layout.addWidget(self.files)
        self.summary = label("No files selected", "muted")
        layout.addWidget(self.summary)
        layout.addWidget(
            label(
                f"{plan.skipped} entries excluded. Logical file sizes are estimates; "
                "space actually reclaimed on APFS is unknown.",
                "muted",
            )
        )
        actions = QHBoxLayout()
        select = QPushButton("Select all eligible files")
        select.clicked.connect(self.select_all)
        actions.addWidget(select)
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.remove = QPushButton("Remove selected…")
        self.remove.setProperty("role", "primary")
        self.remove.setEnabled(False)
        self.remove.clicked.connect(self.confirm_selection)
        actions.addWidget(self.remove)
        layout.addLayout(actions)
        self.files.itemChanged.connect(self.update_selection)

    def selection(self) -> CleanupPlan:
        return replace(
            self.plan,
            files=tuple(
                entry
                for row, entry in enumerate(self.plan.files)
                if self.files.item(row, 0).checkState() == Qt.CheckState.Checked
            ),
        )

    def update_selection(self) -> None:
        selected = self.selection()
        self.summary.setText(
            f"{len(selected.files)} files selected · "
            f"{size_text(selected.estimated_bytes)} logical size"
        )
        self.remove.setEnabled(bool(selected.files) and selected.complete)

    def select_all(self) -> None:
        self.files.blockSignals(True)
        for row in range(self.files.rowCount()):
            self.files.item(row, 0).setCheckState(Qt.CheckState.Checked)
        self.files.blockSignals(False)
        self.update_selection()

    def confirm_selection(self) -> None:
        selected = self.selection()
        if not selected.files or not selected.complete:
            return
        answer = QMessageBox.question(
            self,
            "Permanently remove cache files?",
            f"Remove {len(selected.files)} selected files "
            f"({size_text(selected.estimated_bytes)} logical size)?\n\n"
            "These files cannot be restored after successful deletion. "
            "Close installers before continuing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.selected_plan = selected
            self.accept()
