"""Regression: ticking 'maxed' used to delete the clicked row inside its own click handler and crash."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PETS = ROOT / "data" / "pets.json"
pytestmark = pytest.mark.skipif(not PETS.exists(), reason="run tools/parse_pdf.py first")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    from app.core.store import Store
    from app.ui.theme import StoreSignals
    from app.ui.tracker_window import MainWindow

    store = Store(pets_json=PETS, db_path=tmp_path / "p.db", overrides_path=tmp_path / "o.json")
    w = MainWindow(store, StoreSignals(store))
    w.show()
    app.processEvents()
    yield w
    w.close()
    store.close()


def pump(app, n=20):
    for _ in range(n):
        app.processEvents()


def click_check(app, tree, item):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from app.ui.tracker_window import COL_MAX

    rect = tree.visualItemRect(item)
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(tree.header().sectionPosition(COL_MAX) + 12,
                                                              rect.center().y()))
    pump(app)


def test_ticking_rows_does_not_crash(app, win):
    tree = win.tracker.tree
    n = tree.topLevelItemCount()
    for row in (3, 3, 0):
        tree.setCurrentItem(tree.topLevelItem(row))
        click_check(app, tree, tree.topLevelItem(row))
    assert tree.topLevelItemCount() == n - 3            # maxed pets leave the "Not maxed" list
    assert sum(win.store.progress(p).maxed for p in win.store.pets) == 3


def test_route_card_checkbox_does_not_crash(app, win):
    from PySide6.QtWidgets import QCheckBox

    win.tabs.setCurrentWidget(win.route)
    pump(app)
    boxes = [b for b in win.route.scroll.widget().findChildren(QCheckBox) if b.text() == "Maxed"]
    assert boxes
    boxes[0].click()
    pump(app)
    boxes = [b for b in win.route.scroll.widget().findChildren(QCheckBox) if b.text() == "Maxed"]
    boxes[0].click()
    pump(app)
    assert sum(win.store.progress(p).maxed for p in win.store.pets) == 2
