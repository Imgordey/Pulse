"""Build a local, standalone .app; never modify Applications or macOS security settings."""

import json
import os
import platform
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def make_icon() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(ROOT / "packaging/icon.svg"))
    iconset = ROOT / "build/Pulse.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            dimension = size * scale
            image = QImage(dimension, dimension, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter, QRectF(0, 0, dimension, dimension))
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            if not image.save(str(iconset / f"icon_{size}x{size}{suffix}.png")):
                raise RuntimeError("Could not write icon")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "build/Pulse.icns")], check=True
    )
    app.quit()


def runtime_notices() -> None:
    target = ROOT / "dist/Pulse.app/Contents/Resources/runtime-notices"
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"Python": platform.python_version()}
    for name in ("PySide6-Essentials", "shiboken6", "psutil", "pyinstaller"):
        package = distribution(name)
        manifest[name] = package.version
        for file in package.files or ():
            if "license" in file.name.lower() or "copying" in file.name.lower():
                source = package.locate_file(file)
                if source.is_file():
                    (target / f"{name}-{file.name}").write_bytes(source.read_bytes())
    (target / "versions.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Build the macOS application on macOS.")
    make_icon()
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(ROOT / "build/pyinstaller-cache"))
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "packaging/Pulse.spec")],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    runtime_notices()
    # Notices are added after bundling, so seal the final local build again.
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(ROOT / "dist/Pulse.app")], check=True
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(ROOT / "dist/Pulse.app")], check=True
    )
    archive = ROOT / f"dist/Pulse-0.4.0-macos-{platform.machine()}.zip"
    subprocess.run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(ROOT / "dist/Pulse.app"),
            str(archive),
        ],
        check=True,
    )
    print(f"Built {ROOT / 'dist/Pulse.app'}\nArchive: {archive}")


if __name__ == "__main__":
    main()
