# Pulse desktop runtime

Pulse uses unmodified, dynamically loaded open-source dependencies. This local
build includes Python, psutil, Qt 6, PySide6 and Shiboken. PyInstaller packages the
application; its bootloader has an exception allowing application bundling.

- Python: PSF license, https://docs.python.org/3/license.html
- psutil: BSD-3-Clause, https://github.com/giampaolo/psutil
- Qt Core/GUI/Widgets: LGPL-3.0, https://code.qt.io/cgit/qt/qtbase.git/
- PySide6 and Shiboken: LGPL-3.0, https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt's incorporated third-party code: https://doc.qt.io/qt-6/licenses-used-in-qt.html
- PySide6's incorporated third-party code: https://doc.qt.io/qtforpython-6/licenses.html
- PyInstaller: GPL-2.0 with bootloader exception, https://pyinstaller.org/en/stable/license.html

The corresponding upstream source, license texts and versioned tags are available
from these projects. The build includes a runtime version manifest and installed
package license files in `runtime-notices`. Qt libraries remain separate from the
Pulse executable and may be replaced with compatible builds. The Pulse source and
build instructions are at https://github.com/Imgordey/Pulse.

This is a local development build. A public binary release needs a complete
third-party notice/source review and Apple signing/notarization preparation.
