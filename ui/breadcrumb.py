"""Clickable breadcrumb path bar."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from filesystem.paths import display_name, split_ancestors


class Breadcrumb(QWidget):
    path_clicked = pyqtSignal(object)      # path str or None for home

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(4, 0, 4, 0)
        self.lay.setSpacing(0)

    def set_path(self, path: str | None, drive_title: str | None = None) -> None:
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._add("This PC", None)
        if path:
            parts = split_ancestors(path)
            # keep the bar compact for very deep paths
            if len(parts) > 9:
                head, tail = parts[:1], parts[-7:]
                self._sep()
                self._add(drive_title or display_name(head[0]), head[0])
                self._sep()
                self.lay.addWidget(QLabel(" … "))
                parts = tail
                for p in parts:
                    self._sep()
                    self._add(display_name(p), p)
            else:
                for i, p in enumerate(parts):
                    self._sep()
                    self._add(drive_title if i == 0 and drive_title else display_name(p), p)
        self.lay.addStretch(1)

    def _sep(self) -> None:
        lbl = QLabel(" › ")
        lbl.setStyleSheet("color:#6c7a99;")
        self.lay.addWidget(lbl)

    def _add(self, text: str, path) -> None:
        b = QToolButton()
        b.setText(text if len(text) < 40 else text[:38] + "…")
        b.setToolTip(path or "This PC")
        b.setAutoRaise(True)
        b.clicked.connect(lambda _=False, p=path: self.path_clicked.emit(p))
        self.lay.addWidget(b)
