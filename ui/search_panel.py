"""Search dock: finds files/folders by name below the current location."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton, QVBoxLayout, QWidget

from universe.mapping import format_size


class HitModel(QAbstractListModel):
    def __init__(self, pixmaps, parent=None):
        super().__init__(parent)
        self.hits = []
        self.pixmaps = pixmaps

    def clear(self) -> None:
        self.beginResetModel()
        self.hits = []
        self.endResetModel()

    def add(self, hits) -> None:
        if not hits:
            return
        n = len(self.hits)
        self.beginInsertRows(QModelIndex(), n, n + len(hits) - 1)
        self.hits.extend(hits)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.hits)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        h = self.hits[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            size = "folder" if h.is_dir else format_size(h.size)
            return f"{h.name}    —    {h.path}    ({size})"
        if role == Qt.ItemDataRole.ToolTipRole:
            return h.path
        if role == Qt.ItemDataRole.DecorationRole:
            return self.pixmaps.icon(("dir:" if h.is_dir else "file:") + h.path, request=index.row() < 200)
        if role == Qt.ItemDataRole.ForegroundRole and h.is_dir:
            return QColor(130, 200, 255)
        return None


class SearchPanel(QWidget):
    search_requested = pyqtSignal(str)
    stop_requested = pyqtSignal()
    hit_activated = pyqtSignal(object)      # SearchHit

    def __init__(self, pixmaps, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search names below the current location (supports * and ?)…")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._go)
        row.addWidget(self.query, 1)
        self.go_btn = QPushButton("Search")
        self.go_btn.clicked.connect(self._go)
        row.addWidget(self.go_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#9aa7c0;")
        lay.addWidget(self.status)
        self.model = HitModel(pixmaps, self)
        self.list = QListView()
        self.list.setUniformItemSizes(True)
        self.list.setModel(self.model)
        self.list.activated.connect(self._activate)
        self.list.doubleClicked.connect(self._activate)
        lay.addWidget(self.list, 1)

    def _go(self) -> None:
        q = self.query.text().strip()
        if q:
            self.model.clear()
            self.search_requested.emit(q)
            self.stop_btn.setEnabled(True)

    def _activate(self, index) -> None:
        if index.isValid():
            self.hit_activated.emit(self.model.hits[index.row()])

    def set_running(self, scope: str) -> None:
        self.status.setText(f"Searching in {scope}…")

    def add_hits(self, hits) -> None:
        self.model.add(hits)
        self.status.setText(f"{self.model.rowCount():,} matches so far… (double-click a result to fly there)")

    def finished(self, count: int, cancelled: bool) -> None:
        self.stop_btn.setEnabled(False)
        tail = " (stopped)" if cancelled else ""
        self.status.setText(f"{count:,} matches{tail}. Double-click a result to fly to it.")
