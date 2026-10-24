"""One Qt application for the whole test run.

Some tests only need Qt's event loop and others open windows; a plain QCoreApplication
created first would make window tests abort, so create a full (offscreen) QApplication up front.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])
