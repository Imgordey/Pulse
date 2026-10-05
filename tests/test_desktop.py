"""Desktop safety and async behavior, using offscreen Qt and disposable caches only."""

import os
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from pulse.cleanup.executor import execute_cleanup  # noqa: E402
from pulse.cleanup.planner import create_cleanup_plan  # noqa: E402
from pulse.core.processes import ProcessSnapshot, ProcessStats  # noqa: E402
from pulse.core.system import SystemStats  # noqa: E402
from pulse.desktop.cleanup_dialog import CleanupDialog  # noqa: E402
from pulse.desktop.pages import HistoryPage, OverviewPage, ProcessesPage  # noqa: E402
from pulse.desktop.tasks import Task  # noqa: E402
from pulse.desktop.window import PulseWindow  # noqa: E402
from pulse.health.engine import analyze_health  # noqa: E402
from pulse.services.monitor import MonitorSnapshot  # noqa: E402


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(qt, condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.005)
    assert condition(), "Qt operation did not finish"


@pytest.fixture
def window(qt):
    widget = PulseWindow()
    widget.timer.stop()
    yield widget
    wait_until(qt, lambda: widget.task is None)
    widget.close()
    widget.deleteLater()
    qt.processEvents()


def test_launch_does_not_scan_or_clean(window, monkeypatch):
    from pulse.desktop import window as module

    scan = Mock()
    clean = Mock()
    monkeypatch.setattr(module, "scan_computer", scan)
    monkeypatch.setattr(module, "execute_cleanup", clean)
    assert window.task is None
    assert window.storage.inventory.rowCount() == 0
    assert not window.history.restore.isEnabled()
    scan.assert_not_called()
    clean.assert_not_called()


def test_selection_starts_empty_and_cancel_does_not_delete(qt, cache_file, monkeypatch):
    home, file = cache_file
    dialog = CleanupDialog(create_cleanup_plan(home))
    assert not dialog.selection().files
    assert not dialog.remove.isEnabled()
    dialog.select_all()
    assert dialog.remove.isEnabled()
    assert dialog.selection().estimated_bytes == file.stat().st_size
    question = Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.confirm_selection()
    assert dialog.selected_plan is None
    assert file.exists()
    assert question.call_args.args[-1] == QMessageBox.StandardButton.No
    dialog.close()


def test_confirmed_preview_binds_exact_selected_files(qt, cache_file, monkeypatch):
    home, file = cache_file
    plan = create_cleanup_plan(home)
    other = file.with_suffix("")
    other.write_bytes(b"another cache file")
    os.utime(other, (time.time() - 8 * 86400,) * 2)
    plan = create_cleanup_plan(home)
    dialog = CleanupDialog(plan)
    dialog.files.item(0, 0).setCheckState(Qt.CheckState.Checked)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.confirm_selection()
    selected = dialog.selected_plan
    assert selected is not None and len(selected.files) == 1
    assert selected.root == plan.root and selected.root_inode == plan.root_inode
    report = execute_cleanup(selected, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "deleted"
    remaining = [entry for entry in (file, other) if entry.exists()]
    assert len(remaining) == 1
    dialog.close()


def test_incomplete_preview_cannot_confirm(qt, cache_file, monkeypatch):
    home, _ = cache_file
    dialog = CleanupDialog(replace(create_cleanup_plan(home), complete=False))
    dialog.select_all()
    assert not dialog.remove.isEnabled()
    question = Mock()
    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.confirm_selection()
    question.assert_not_called()
    dialog.close()


def test_background_operation_keeps_event_loop_responsive(qt, window):
    ticks = []
    received = []
    pulse = QTimer()
    pulse.setInterval(5)
    pulse.timeout.connect(lambda: ticks.append(True))
    pulse.start()
    assert window.start_task("Working", lambda: (time.sleep(0.08), "done")[1], received.append)
    assert not window.start_task("Duplicate", lambda: None, received.append)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    wait_until(qt, lambda: window.task is None)
    pulse.stop()
    assert received == ["done"]
    assert len(ticks) >= 2
    assert window.refresh_button.isEnabled()


def test_failed_worker_reports_error_and_can_be_reused(qt, window, monkeypatch):
    warning = Mock(return_value=QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", warning)

    def fail():
        raise PermissionError("Access denied")

    window.start_task("Reading", fail, lambda result: None)
    wait_until(qt, lambda: window.task is None)
    assert "Access denied" in warning.call_args.args[2]
    received = []
    window.start_task("Retry", lambda: 42, received.append)
    wait_until(qt, lambda: window.task is None)
    assert received == [42]


def test_process_search_and_numeric_sort(qt):
    page = ProcessesPage()
    page.display(
        ProcessSnapshot(
            (ProcessStats(1, "Alpha", 2, 100), ProcessStats(2, "Beta", 10, 20)), skipped=3
        )
    )
    assert page.processes.item(0, 0).text() == "Beta"
    page.sort.setCurrentIndex(1)
    assert page.processes.item(0, 0).text() == "Alpha"
    page.search.setText("BET")
    assert page.processes.rowCount() == 1
    assert page.processes.item(0, 0).text() == "Beta"
    assert "3 inaccessible" in page.coverage.text()
    page.close()


def test_overview_uses_available_space_and_unknown_battery(qt):
    stats = SystemStats(
        "Darwin",
        12,
        3,
        10,
        30,
        2,
        100,
        2,
        3600,
        memory_available=7,
        disk_free=8,
        os_version="15.0",
        architecture="arm64",
    )
    page = OverviewPage()
    page.display(MonitorSnapshot(stats, None, analyze_health(stats)))
    assert page.disk.value.text() == "8.0 B"
    assert page.battery.value.text() == "Unavailable"
    assert "Needs attention" in page.status.text()
    page.close()


def test_history_handles_invalid_time_and_size(qt):
    page = HistoryPage()
    page.display(
        (
            {
                "journal": "record.jsonl",
                "last_event": {
                    "time": "bad",
                    "event": "finished",
                    "data": {"bytes_removed": "invalid"},
                },
                "potential_recoveries": [],
            },
        )
    )
    assert page.records.item(0, 0).text() == "Unknown"
    assert page.records.item(0, 2).text() == "0.0 B"
    assert not page.restore.isEnabled()
    page.close()


def test_task_converts_exception_to_signal(qt):
    errors = []

    def fail():
        raise ValueError("Invalid input")

    task = Task(fail)
    task.failed.connect(errors.append)
    task.start()
    wait_until(qt, lambda: not task.isRunning() and bool(errors))
    assert errors == ["ValueError: Invalid input"]
    task.wait()


def test_navigation_responds_to_accessibility_toggle(window):
    window.navigation.button(1).setChecked(True)
    assert window.pages.currentWidget() is window.storage
    window.navigation.button(2).click()
    assert window.pages.currentWidget() is window.processes
    window.navigation.button(3).setChecked(True)
    assert window.pages.currentWidget() is window.history


def test_recovery_cancel_never_starts_mutation(window, preserved_file, monkeypatch):
    from pulse.cleanup.recovery import prepare_recovery

    home, source, destination = preserved_file
    question = Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "question", question)
    start = Mock()
    monkeypatch.setattr(window, "start_task", start)
    window.review_recovery(prepare_recovery(source, destination, home=home))
    start.assert_not_called()
    assert source.exists() and not destination.exists()
    assert question.call_args.args[-1] == QMessageBox.StandardButton.No


def test_refresh_never_traverses_storage(qt, window, monkeypatch):
    from pulse.desktop import window as module

    stats = SystemStats("Darwin", 10, 2, 10, 20, 20, 100, 20, 3600, disk_free=80)
    snapshot = MonitorSnapshot(stats, ProcessSnapshot((), 0), analyze_health(stats))
    collect = Mock(return_value=snapshot)
    scan = Mock()
    clean = Mock()
    monkeypatch.setattr(module, "collect_snapshot", collect)
    monkeypatch.setattr(module, "scan_computer", scan)
    monkeypatch.setattr(module, "execute_cleanup", clean)
    window.refresh()
    wait_until(qt, lambda: window.task is None)
    collect.assert_called_once_with(include_processes=True)
    scan.assert_not_called()
    clean.assert_not_called()
