from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pulse.cleanup.executor import execute_cleanup
from pulse.cleanup.journal import read_history
from pulse.cleanup.models import CleanupPlan, CleanupReport
from pulse.cleanup.planner import create_cleanup_plan
from pulse.cleanup.recovery import RecoveryPlan, RecoveryResult, prepare_recovery, recover_file
from pulse.desktop.cleanup_dialog import CleanupDialog
from pulse.desktop.pages import HistoryPage, OverviewPage, ProcessesPage, StoragePage
from pulse.desktop.style import stylesheet
from pulse.desktop.tasks import Task
from pulse.desktop.widgets import label, size_text
from pulse.services.engine import ComputerScan, scan_computer
from pulse.services.monitor import MonitorSnapshot, collect_snapshot


class PulseWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.task: Task | None = None
        self.setWindowTitle("Pulse — System health, without the noise")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(stylesheet(self.palette()))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        sidebar = QVBoxLayout()
        brand = label("PULSE", "title")
        brand.setContentsMargins(22, 24, 12, 12)
        sidebar.addWidget(brand)
        self.navigation = QButtonGroup(self)
        for index, title in enumerate(("Overview", "Storage", "Processes", "History")):
            button = QPushButton(title)
            button.setProperty("role", "navigation")
            button.setCheckable(True)
            button.setFixedWidth(180)
            button.setAccessibleName(title)
            self.navigation.addButton(button, index)
            sidebar.addWidget(button)
        sidebar.addStretch()
        layout.addLayout(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(24, 24, 24, 20)
        self.pages = QStackedWidget()
        self.overview = OverviewPage()
        self.storage = StoragePage()
        self.processes = ProcessesPage()
        self.history = HistoryPage()
        for page in (self.overview, self.storage, self.processes, self.history):
            self.pages.addWidget(page)
        content.addWidget(self.pages, 1)
        self.navigation.idToggled.connect(self.navigate)
        self.navigation.button(0).setChecked(True)
        footer = QHBoxLayout()
        self.message = label("Ready", "muted")
        footer.addWidget(self.message, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.hide()
        footer.addWidget(self.progress)
        self.refresh_button = QPushButton("Refresh sample")
        footer.addWidget(self.refresh_button)
        content.addLayout(footer)
        layout.addLayout(content, 1)
        self.refresh_button.clicked.connect(self.refresh)
        self.storage.scan.clicked.connect(self.scan)
        self.storage.preview.clicked.connect(self.preview_cleanup)
        self.history.reload.clicked.connect(self.reload_history)
        self.history.restore.clicked.connect(self.preview_recovery)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.auto_refresh)
        self.timer.start()

    def navigate(self, index: int, checked: bool) -> None:
        if checked:
            self.pages.setCurrentIndex(index)

    def start_task(
        self, message: str, operation: Callable[[], object], receive: Callable[[object], None]
    ) -> bool:
        if self.task is not None:
            return False
        task = Task(operation, self)
        self.task = task
        self.message.setText(message)
        self.progress.show()
        self.set_busy(True)
        task.succeeded.connect(receive)
        task.failed.connect(self.show_error)
        task.finished.connect(self.task_finished)
        task.start()
        return True

    def set_busy(self, busy: bool) -> None:
        for button in (
            self.refresh_button,
            self.storage.scan,
            self.storage.preview,
            self.history.reload,
            self.history.restore,
        ):
            button.setEnabled(not busy)
        if not busy:
            self.history.restore.setEnabled(self.history.recoveries.count() > 0)

    def task_finished(self) -> None:
        task = self.task
        self.task = None
        self.progress.hide()
        self.set_busy(False)
        if task is not None:
            task.deleteLater()

    def show_error(self, message: str) -> None:
        self.message.setText("Operation could not finish. See details and try again.")
        QMessageBox.warning(self, "Pulse could not finish", message)

    def refresh(self) -> None:
        self.start_task(
            "Taking a resource sample…",
            lambda: collect_snapshot(include_processes=True),
            self.display_snapshot,
        )

    def auto_refresh(self) -> None:
        if self.isVisible() and self.isActiveWindow() and self.task is None:
            self.refresh()

    def display_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self.overview.display(snapshot)
        self.processes.display(snapshot.processes)
        self.message.setText("Sample updated. Storage scanning is separate and read-only.")

    def scan(self) -> None:
        self.start_task("Scanning known cache locations…", scan_computer, self.display_scan)

    def display_scan(self, scan: ComputerScan) -> None:
        self.overview.display(scan.monitor)
        self.processes.display(scan.monitor.processes)
        self.storage.display(scan)
        self.message.setText("Scan complete. No files changed.")

    def preview_cleanup(self) -> None:
        category = self.storage.category.currentData()
        self.start_task(
            "Building an exact cleanup preview…",
            lambda: create_cleanup_plan(category=category),
            self.show_cleanup,
        )

    def show_cleanup(self, plan: CleanupPlan) -> None:
        # Run after the worker has finished: modal dialogs run a nested event loop.
        QTimer.singleShot(0, lambda: self.review_cleanup(plan))

    def review_cleanup(self, plan: CleanupPlan) -> None:
        dialog = CleanupDialog(plan, self)
        self.timer.stop()
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_plan is not None:
                selected = dialog.selected_plan
                self.start_task(
                    "Removing selected cache files…",
                    lambda: execute_cleanup(selected, dry_run=False, confirmed=True),
                    self.show_cleanup_result,
                )
            else:
                self.message.setText("Cleanup cancelled. No files changed.")
        finally:
            self.timer.start()
            dialog.deleteLater()

    def show_cleanup_result(self, report: CleanupReport) -> None:
        self.message.setText(
            f"Cleanup finished · {size_text(report.bytes_removed)} logical bytes removed"
        )
        lines = [
            f"Logical size removed: {size_text(report.bytes_removed)}",
            "Space actually reclaimed on APFS: unknown.",
        ]
        if report.blocked_reason:
            lines.append(f"Cleanup refused: {report.blocked_reason}")
        if report.journal_path:
            lines.append(f"Local audit record: {report.journal_path}")
        if report.audit_error:
            lines.append(f"Audit error: {report.audit_error}")
        lines.extend(
            f"{entry.status}: {entry.path}\n{entry.reason}"
            + (f"\nPreserved file: {entry.recovery_path}" if entry.recovery_path else "")
            for entry in report.results
        )
        self.show_report("Cleanup results", "\n".join(lines))

    def show_report(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText("\n".join(text.splitlines()[:3]))
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        box.deleteLater()

    def reload_history(self) -> None:
        self.start_task("Reading local history…", read_history, self.display_history)

    def display_history(self, records: tuple[dict[str, object], ...]) -> None:
        self.history.display(records)
        self.message.setText("Local history updated.")

    def preview_recovery(self) -> None:
        paths = self.history.selected_recovery()
        if paths:
            source, destination = map(Path, paths)
            self.start_task(
                "Validating preserved file…",
                lambda: prepare_recovery(source, destination),
                self.show_recovery,
            )

    def show_recovery(self, plan: RecoveryPlan) -> None:
        QTimer.singleShot(0, lambda: self.review_recovery(plan))

    def review_recovery(self, plan: RecoveryPlan) -> None:
        self.timer.stop()
        try:
            answer = QMessageBox.question(
                self,
                "Restore preserved cache file?",
                f"Preserved file:\n{plan.source}\n\nRestore to:\n{plan.destination}\n\n"
                "An existing destination will never be overwritten.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.start_task(
                    "Restoring preserved file…",
                    lambda: recover_file(plan, dry_run=False, confirmed=True),
                    self.show_recovery_result,
                )
            else:
                self.message.setText("Recovery cancelled. No files changed.")
        finally:
            self.timer.start()

    def show_recovery_result(self, result: RecoveryResult) -> None:
        self.message.setText(f"Recovery: {result.status}")
        self.show_report(
            "Recovery result",
            f"{result.status}: {result.reason}\n"
            f"{result.destination}\nJournal: {result.journal_path}\n"
            f"Audit error: {result.audit_error or 'None'}",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.task is not None:
            self.message.setText("Wait for the current operation to finish before closing Pulse.")
            event.ignore()
        else:
            self.timer.stop()
            event.accept()
