from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "packaging/desktop_entry.py")],
    pathex=[str(root / "src")],
    datas=[(str(root / "packaging/THIRD_PARTY_NOTICES.md"), ".")],
    excludes=["tkinter", "pytest", "ruff", "PySide6.QtQml", "PySide6.QtQuick"],
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="Pulse", console=False, icon=str(root / "build/Pulse.icns"),
    target_arch=None, codesign_identity=None,
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name="Pulse")
app = BUNDLE(
    collection, name="Pulse.app", icon=str(root / "build/Pulse.icns"),
    bundle_identifier="io.github.imgordey.pulse", version="0.2.0",
    info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "13.0"},
)
