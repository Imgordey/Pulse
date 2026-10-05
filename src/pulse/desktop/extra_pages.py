"""Storage exploration, measured system details, and symptom-specific maintenance."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pulse.core.drives import DriveSnapshot
from pulse.core.system import SystemStats
from pulse.core.volumes import VolumeStats
from pulse.desktop.pages import heading, text_view
from pulse.desktop.widgets import label, size_text, table
from pulse.optimization.actions import ACTIONS
from pulse.storage.analyzer import DirectoryAnalysis, StorageEntry
from pulse.storage.trash import personal_file_scope


class ExplorerPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.analysis: DirectoryAnalysis | None = None
        self.entries: tuple[StorageEntry, ...] = ()
        layout = QVBoxLayout(self)
        heading(layout, "Where did the space go?", "Choose a folder to inspect its file metadata.")
        controls = QHBoxLayout()
        self.root = QLineEdit(str(Path.home()))
        self.root.setAccessibleName("Folder to analyze")
        self.choose = QPushButton("Choose folder…")
        self.scan = QPushButton("Analyze folder")
        self.scan.setProperty("role", "primary")
        self.cancel = QPushButton("Stop scan")
        self.cancel.setEnabled(False)
        for widget in (self.root, self.choose, self.scan, self.cancel):
            controls.addWidget(widget, 1 if widget is self.root else 0)
        layout.addLayout(controls)
        self.summary = label("No folder analyzed yet.")
        layout.addWidget(self.summary)
        filters = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Immediate children", "Largest files (top 100)"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or path")
        filters.addWidget(self.mode)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)
        self.results = table(["File / folder", "Logical size", "Allocated blocks", "Files"])
        self.results.horizontalHeader().setStretchLastSection(False)
        self.results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results, 1)
        self.details = text_view()
        self.details.setMaximumHeight(125)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.open_folder = QPushButton("Analyze selected folder")
        self.trash = QPushButton("Review moving file to Trash…")
        self.open_folder.setEnabled(False)
        self.trash.setEnabled(False)
        actions.addWidget(self.open_folder)
        actions.addStretch()
        actions.addWidget(self.trash)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                "Sizes include only inspected files. APFS clones and snapshots may share blocks. "
                "Trash still occupies space. Visible files in personal folders can be reviewed; "
                "nothing is selected automatically.",
                "muted",
            )
        )
        self.mode.currentIndexChanged.connect(self.render)
        self.search.textChanged.connect(self.render)
        self.results.itemSelectionChanged.connect(self.show_details)

    def display(self, analysis: DirectoryAnalysis) -> None:
        self.analysis = analysis
        self.root.setText(str(analysis.root))
        state = "Stopped" if analysis.cancelled else "Complete" if analysis.complete else "Partial"
        self.summary.setText(
            f"{state} · {analysis.files:,} files · {size_text(analysis.logical_bytes)} logical · "
            f"{size_text(analysis.allocated_bytes)} allocated · {analysis.elapsed_seconds:.1f}s"
        )
        self.render()

    def render(self) -> None:
        rows = (
            ()
            if self.analysis is None
            else (
                self.analysis.children
                if self.mode.currentIndex() == 0
                else self.analysis.largest_files
            )
        )
        needle = self.search.text().casefold()
        self.entries = tuple(item for item in rows if needle in str(item.path).casefold())[:1000]
        self.results.setRowCount(0)
        self.results.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            name = (
                str(entry.path.relative_to(self.analysis.root))
                if self.mode.currentIndex() == 1
                else entry.path.name
            )
            partial = "≥ " if entry.directory and not self.analysis.complete else ""
            for column, text in enumerate(
                (
                    name + (" /" if entry.directory else ""),
                    partial + size_text(entry.logical_bytes),
                    partial + size_text(entry.allocated_bytes),
                    str(entry.files),
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(str(entry.path))
                self.results.setItem(row, column, item)
        self.show_details()

    def selected(self) -> StorageEntry | None:
        row = self.results.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def show_details(self) -> None:
        entry = self.selected()
        self.open_folder.setEnabled(bool(entry and entry.directory))
        eligible = bool(
            entry and not entry.directory and personal_file_scope(entry.path, Path.home())
        )
        self.trash.setEnabled(eligible)
        lines = (
            [str(entry.path)]
            if entry
            else ["Select a row to inspect its full path. Up to 1,000 matching rows shown."]
        )
        if self.analysis:
            lines.extend(
                f"Excluded: {count:,} {reason}"
                for reason, count in self.analysis.exclusions.items()
            )
            lines.extend(self.analysis.problems)
            lines.append(
                "Hard-linked content is counted once, under its first encountered path. "
                "Allocated blocks are not a reclaimable-space estimate. "
                "On partial scans, directory totals show only a lower bound (≥)."
            )
        self.details.setPlainText("\n".join(lines))


class SystemPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading(layout, "Measured system details", "Unavailable readings are shown explicitly.")
        self.metrics = text_view()
        self.metrics.setMaximumHeight(210)
        layout.addWidget(self.metrics)
        layout.addWidget(label("Mounted volumes"))
        self.volumes = table(["Mount point", "Filesystem", "Capacity", "Used", "Available"])
        self.volumes.horizontalHeader().setStretchLastSection(False)
        self.volumes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tabs = QTabWidget()
        tabs.addTab(self.volumes, "Mounted volumes")
        self.drives = text_view()
        self.drives.setPlainText(
            "Choose Read physical drives to inspect hardware reported by macOS."
        )
        tabs.addTab(self.drives, "Physical drives / SMART")
        layout.addWidget(tabs, 1)
        self.coverage = label("Choose Read volumes to inspect accessible mounted volumes.", "muted")
        layout.addWidget(self.coverage)
        self.read_volumes = QPushButton("Read volumes")
        layout.addWidget(self.read_volumes)
        self.read_drives = QPushButton("Read physical drives")
        layout.addWidget(self.read_drives)
        layout.addWidget(
            label(
                "APFS volumes share container space; do not add their capacities or free space. "
                "SMART is reported by macOS when available. Temperatures, memory pressure "
                "and battery wear are not normalized in this version.",
                "muted",
            )
        )

    def display(self, stats: SystemStats) -> None:
        load = (
            " / ".join(f"{v:.2f}" for v in stats.load_average)
            if stats.load_average
            else "Unavailable"
        )
        network = (
            (
                f"Sent {size_text(stats.network.bytes_sent)} · "
                f"Received {size_text(stats.network.bytes_received)} (cumulative counters)"
            )
            if stats.network
            else "Unavailable"
        )
        self.metrics.setPlainText(
            f"OS: {stats.os} {stats.os_version} · {stats.architecture}\n"
            f"CPU: {stats.cpu_percent:.1f}% · {stats.logical_cpus or '?'} logical / "
            f"{stats.physical_cpus or '?'} physical cores\n"
            f"Load average (1 / 5 / 15 min): {load}\n"
            f"RAM: {size_text(stats.memory_used)} used · {size_text(stats.memory_available)} "
            f"available / {size_text(stats.memory_total)} total\n"
            f"Swap: {size_text(stats.swap_used)} / {size_text(stats.swap_total)}\n"
            f"Network: {network}\nUptime: {stats.uptime // 86400}d "
            f"{stats.uptime // 3600 % 24}h {stats.uptime // 60 % 60}m\n"
            "Network counters can include overlapping virtual interfaces; they are not speed."
        )

    def display_drives(self, snapshot: DriveSnapshot) -> None:
        lines = []
        for drive in snapshot.drives:
            capacity = (
                size_text(drive.total_bytes) if drive.total_bytes is not None else "Unavailable"
            )
            location = (
                "Internal"
                if drive.internal
                else "External"
                if drive.internal is False
                else "Unknown"
            )
            lines.append(
                f"{drive.model or 'Unknown model'} ({drive.identifier})\n"
                f"{location} · {drive.protocol or 'Unknown connection'} · {capacity}\n"
                f"SMART reported by macOS: {drive.smart_status or 'Unavailable'}"
            )
            if drive.smart_status and drive.smart_status.lower() == "failing":
                lines.append("Back up important data now and arrange drive service.")
        lines.extend(snapshot.problems)
        lines.append(
            "A reported SMART status is not a complete drive test. "
            "Some USB enclosures do not expose SMART. Missing readings are not healthy readings."
        )
        self.drives.setPlainText("\n\n".join(lines))

    def display_volumes(self, volumes: tuple[VolumeStats, ...]) -> None:
        self.volumes.setRowCount(len(volumes))
        for row, volume in enumerate(volumes):
            for column, value in enumerate(
                (volume.mountpoint, volume.filesystem, volume.total, volume.used, volume.free)
            ):
                text = (
                    ("Unavailable" if value is None else size_text(value))
                    if column >= 2
                    else str(value)
                )
                item = QTableWidgetItem(text)
                item.setToolTip(f"{volume.device}\n{volume.options}\n{volume.error or ''}")
                self.volumes.setItem(row, column, item)
        self.coverage.setText(
            f"{len(volumes)} mounted volumes · "
            f"{sum(v.error is not None for v in volumes)} unavailable"
        )


class MaintenancePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading(layout, "Fix a specific symptom", "Choose an action only when its purpose fits.")
        self.action = QComboBox()
        for action in ACTIONS:
            self.action.addItem(action.title, action.id)
        layout.addWidget(self.action)
        self.description = label("")
        layout.addWidget(self.description)
        self.review = QPushButton("Review maintenance…")
        layout.addWidget(self.review)
        self.result = text_view()
        layout.addWidget(self.result, 1)
        layout.addWidget(
            label(
                "No automatic process termination or administrator privileges. "
                "For CPU or memory concerns, inspect Processes "
                "and close unnecessary apps normally. "
                "Every confirmed maintenance attempt is written to local History.",
                "muted",
            )
        )
        self.action.currentIndexChanged.connect(self.describe)
        self.describe()

    def describe(self) -> None:
        action = ACTIONS[self.action.currentIndex()]
        self.description.setText(f"{action.purpose}\n\n{action.consequences}")
