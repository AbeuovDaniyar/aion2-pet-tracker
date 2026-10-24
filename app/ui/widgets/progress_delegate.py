"""Paints a small progress bar + label in a tree column."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

FRACTION_ROLE = Qt.UserRole + 10   # float 0..1 or None
LABEL_ROLE = Qt.UserRole + 11      # str
COLOR_ROLE = Qt.UserRole + 12      # str hex


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#2a3c63"))
        if index.data(LABEL_ROLE) is None:  # group header rows
            return
        frac = index.data(FRACTION_ROLE)
        label = index.data(LABEL_ROLE) or ""
        color = QColor(index.data(COLOR_ROLE) or "#ffb36a")
        r = option.rect.adjusted(6, 0, -6, 0)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        bar = QRectF(r.x(), r.center().y() - 3, r.width() * 0.45, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#22314f"))
        painter.drawRoundedRect(bar, 3, 3)
        if frac:
            fill = QRectF(bar.x(), bar.y(), bar.width() * max(0.0, min(frac, 1.0)), bar.height())
            painter.setBrush(color)
            painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor("#f1f4f8" if label == "MAX" else "#9eafc8"))
        tr = r.adjusted(int(bar.width()) + 8, 0, 0, 0)
        painter.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.restore()
