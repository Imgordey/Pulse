import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from pulse.desktop.window import PulseWindow
    except ModuleNotFoundError as exc:
        if exc.name is not None and exc.name.startswith("PySide6"):
            print(
                "Install the desktop extra: python -m pip install -e '.[desktop]'", file=sys.stderr
            )
            return 1
        raise
    application = QApplication(sys.argv)
    application.setApplicationName("Pulse")
    application.setApplicationVersion("0.4.0")
    application.setOrganizationName("Pulse")
    window = PulseWindow()
    window.show()
    window.refresh()
    return application.exec()
