"""Read-only views of domain objects; action orchestration belongs to the window."""

import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pulse.core.processes import ProcessSnapshot
from pulse.desktop.widgets import Metric, label, size_text, table
from pulse.health.models import Issue
from pulse.services.engine import ComputerScan
from pulse.services.monitor import MonitorSnapshot


def heading(layout: QVBoxLayout, title: str, description: str) -> None:
    layout.addWidget(label(title, "title"))
    layout.addWidget(label(description, "muted"))


def text_view() -> QTextEdit:
    view = QTextEdit()
    view.setReadOnly(True)
    view.setAcceptRichText(False)
    return view


def next_step(issue: Issue) -> str:
    return {
        "cpu_high": "Open Processes to see busy apps. Refresh after your current task finishes.",
        "memory_high": "Sort Processes by memory and check Memory Pressure in Activity Monitor.",
        "disk_low_space": "Scan Storage and review macOS Storage settings before removing files.",
        "disk_critical": "Scan Storage and review macOS Storage settings before removing files.",
    }.get(issue.id, issue.recommendation)


class OverviewPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading(layout, "Your Mac, at a glance", "OBSERVE → UNDERSTAND → FIX")
        self.status = label("Taking your first sample…")
        layout.addWidget(self.status)
        cards = QHBoxLayout()
        self.cpu, self.memory, self.disk, self.battery = (
            Metric(name)
            for name in ("Processor", "Available memory", "Available storage", "Battery")
        )
        for card in (self.cpu, self.memory, self.disk, self.battery):
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        self.machine = label("", "muted")
        layout.addWidget(self.machine)
        layout.addWidget(label("What this sample tells us"))
        self.findings = text_view()
        layout.addWidget(self.findings, 1)
        self.limits = label("", "muted")
        layout.addWidget(self.limits)

    def display(self, snapshot: MonitorSnapshot) -> None:
        stats = snapshot.system
        self.status.setText(str(snapshot.health.status))
        self.cpu.update_value(f"{stats.cpu_percent:.0f}%", "A half-second sample")
        self.memory.update_value(
            size_text(stats.memory_available),
            f"of {size_text(stats.memory_total)} · pressure not measured",
        )
        self.disk.update_value(
            size_text(stats.disk_free) if stats.disk_free is not None else "Unavailable",
            f"of {size_text(stats.disk_total)} · APFS volume estimates",
        )
        battery = stats.battery
        self.battery.update_value(
            f"{battery.percent:.0f}%" if battery else "Unavailable",
            ("Connected to power" if battery.plugged_in else "On battery")
            if battery
            else "No accessible battery reading",
        )
        hours = stats.uptime // 3600
        self.machine.setText(
            f"{'macOS' if stats.os == 'Darwin' else stats.os} {stats.os_version} · "
            f"{stats.architecture} · "
            f"{stats.logical_cpus or 'Unknown'} logical cores · "
            f"Up {hours // 24}d {hours % 24}h · Sampled {datetime.now():%H:%M:%S}"
        )
        self.findings.setPlainText(
            "\n\n".join(
                f"{issue.severity.value.upper()} · {issue.title}\n{issue.description}\n"
                f"What you can do: {next_step(issue)}"
                for issue in snapshot.health.issues
            )
            or "No threshold alerts in this sample. Refresh later to see whether this persists."
        )
        self.limits.setText(" · ".join(snapshot.health.limitations))


class StoragePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading(
            layout, "Understand your storage", "Scan known cache locations without changing files."
        )
        self.summary = label("Storage has not been scanned yet. Choose Scan storage to begin.")
        layout.addWidget(self.summary)
        self.inventory = table(["Location", "Logical size", "Coverage", "Policy"])
        layout.addWidget(self.inventory, 1)
        self.details = text_view()
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)
        self.candidates = ()
        self.inventory.itemSelectionChanged.connect(self.show_details)
        actions = QHBoxLayout()
        self.scan = QPushButton("Scan storage")
        self.scan.setProperty("role", "primary")
        actions.addWidget(self.scan)
        actions.addStretch()
        self.category = QComboBox()
        self.category.addItem("pip downloads (current)", "pip-http")
        self.category.addItem("pip downloads (legacy)", "pip-http-legacy")
        actions.addWidget(self.category)
        self.preview = QPushButton("Review cleanup…")
        actions.addWidget(self.preview)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                "Cleanup supports old, recognized pip downloads only. "
                "Other locations are review-only. "
                "Size is not a promise of reclaimable space.",
                "muted",
            )
        )

    def display(self, scan: ComputerScan) -> None:
        self.candidates = scan.storage.candidates
        self.inventory.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            for column, text in enumerate(
                (
                    candidate.description,
                    size_text(candidate.size),
                    "Complete" if candidate.complete else "Partial",
                    candidate.safety.value.capitalize(),
                )
            ):
                self.inventory.setItem(row, column, QTableWidgetItem(text))
        self.summary.setText(
            f"{len(self.candidates)} known locations · "
            f"{len(scan.storage.problems)} access problems · Scanned {datetime.now():%H:%M:%S}"
        )
        self.details.setPlainText(
            "\n".join(f"{problem.path}: {problem.reason}" for problem in scan.storage.problems)
            or "Select a location for its path and cleanup policy."
        )

    def show_details(self) -> None:
        row = self.inventory.currentRow()
        if 0 <= row < len(self.candidates):
            entry = self.candidates[row]
            self.details.setPlainText(
                f"{entry.path}\n{entry.reason}\nExcluded entries: {entry.skipped}"
            )


class ProcessesPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot: ProcessSnapshot | None = None
        layout = QVBoxLayout(self)
        heading(
            layout, "What is using resources?", "Measured processes, with no automatic stopping."
        )
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an app or process")
        self.sort = QComboBox()
        self.sort.addItems(["Most processor use", "Most memory use"])
        controls.addWidget(self.search, 1)
        controls.addWidget(self.sort)
        layout.addLayout(controls)
        self.coverage = label("Waiting for a sample", "muted")
        layout.addWidget(self.coverage)
        self.processes = table(["App / process", "Processor", "Resident memory", "User", "PID"])
        layout.addWidget(self.processes, 1)
        layout.addWidget(
            label(
                "100% processor use equals one core. Resident memory can be shared across apps; "
                "do not add these values together. Close apps normally when possible.",
                "muted",
            )
        )
        self.search.textChanged.connect(self.render)
        self.sort.currentIndexChanged.connect(self.render)

    def display(self, snapshot: ProcessSnapshot | None) -> None:
        self.snapshot = snapshot
        self.render()

    def render(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        query = self.search.text().casefold()
        rows = [entry for entry in snapshot.processes if query in entry.name.casefold()]
        rows.sort(
            key=lambda entry: (
                entry.cpu_percent if self.sort.currentIndex() == 0 else entry.memory_rss
            ),
            reverse=True,
        )
        self.coverage.setText(
            snapshot.error or f"{len(rows)} shown · {snapshot.skipped} inaccessible or exited"
        )
        self.processes.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            for column, value in enumerate(
                (
                    entry.name,
                    f"{entry.cpu_percent:.1f}%",
                    size_text(entry.memory_rss),
                    entry.user or "Unknown",
                    str(entry.pid),
                )
            ):
                self.processes.setItem(row, column, QTableWidgetItem(value))


def history_bytes(data: dict[str, object]) -> int:
    value = data.get("bytes_removed", 0)
    return value if isinstance(value, int) and 0 <= value <= 2**63 - 1 else 0


class HistoryPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading(
            layout,
            "A record of every change",
            "Private, local history. Dry runs create no records.",
        )
        self.summary = label("Choose Reload history to read previous operations.")
        layout.addWidget(self.summary)
        self.records = table(["Time", "Result", "Logical bytes removed", "Record"])
        layout.addWidget(self.records, 1)
        self.details = text_view()
        self.details.setMaximumHeight(170)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.reload = QPushButton("Reload history")
        actions.addWidget(self.reload)
        self.recoveries = QComboBox()
        self.recoveries.setMinimumContentsLength(18)
        actions.addWidget(self.recoveries, 1)
        self.restore = QPushButton("Review recovery…")
        self.restore.setEnabled(False)
        actions.addWidget(self.restore)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                "Recovery handles files preserved after an error. "
                "Successful deletions cannot be undone. "
                "Each recovery is checked again and cannot overwrite an existing file.",
                "muted",
            )
        )
        self.history = ()
        self.records.itemSelectionChanged.connect(self.show_details)

    def display(self, records: tuple[dict[str, object], ...]) -> None:
        self.history = records
        self.records.setRowCount(len(records))
        self.recoveries.clear()
        seen = set()
        for row, record in enumerate(records):
            event = record.get("last_event") or {}
            data = event.get("data", {})
            stamp = event.get("time")
            try:
                when = datetime.fromtimestamp(stamp).strftime("%b %d, %H:%M")
            except (TypeError, ValueError, OverflowError, OSError):
                when = "Unknown"
            for column, value in enumerate(
                (
                    when,
                    record.get("error") or event.get("event", "Unknown"),
                    size_text(history_bytes(data)),
                    record["journal"],
                )
            ):
                self.records.setItem(row, column, QTableWidgetItem(str(value)))
            for item in record.get("potential_recoveries", []):
                source, destination = item.get("recovery_path"), item.get("path")
                if isinstance(source, str) and isinstance(destination, str) and source not in seen:
                    self.recoveries.addItem(destination, (source, destination))
                    seen.add(source)
        self.summary.setText(
            f"{len(records)} recent operations" if records else "No cleanup history yet."
        )
        self.restore.setEnabled(self.recoveries.count() > 0)
        self.details.setPlainText("Select a record for its audit details.")

    def show_details(self) -> None:
        row = self.records.currentRow()
        if 0 <= row < len(self.history):
            self.details.setPlainText(json.dumps(self.history[row], indent=2, default=str))

    def selected_recovery(self) -> tuple[str, str] | None:
        return self.recoveries.currentData(Qt.ItemDataRole.UserRole)
