"""Left sidebar: storage devices (universes) and an accessible list of objects in view."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, QSize, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QAbstractItemView, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu,
                             QSplitter, QVBoxLayout, QWidget)

from devices.eject import can_eject

from universe.mapping import format_size

ROLE_INDEX = Qt.ItemDataRole.UserRole + 1


class ObjectListModel(QAbstractListModel):
    """Virtualised list of the scene's items (handles 100k+ entries)."""

    def __init__(self, pixmaps, parent=None):
        super().__init__(parent)
        self.pixmaps = pixmaps
        self.items = []          # list[SceneItem]
        self.offset = 1
        self.extra_nodes = []    # children not rendered in 3D (huge folders)

    def set_scene(self, scene, extra_nodes=None) -> None:
        self.beginResetModel()
        if scene is None:
            self.items, self.offset = [], 0
        else:
            self.offset = 0 if scene.payload is None else 1
            self.items = scene.items[self.offset:]
        self.extra_nodes = list(extra_nodes or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items) + len(self.extra_nodes)

    def _entry(self, row: int):
        if row < len(self.items):
            it = self.items[row]
            return it.payload, it.label, it.is_dir, it.icon_key, row + self.offset
        node = self.extra_nodes[row - len(self.items)]
        key = ("dir:" if node.is_dir else "file:") + node.path
        return node, node.name, node.is_dir, key, -1 - (row - len(self.items))

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        payload, label, is_dir, icon_key, scene_index = self._entry(index.row())
        if role == Qt.ItemDataRole.DisplayRole:
            size = getattr(payload, "effective_size", None)
            if is_dir and size is not None and getattr(payload, "total_size", 0) is None:
                return f"{label}    {'(link)' if payload.is_link else 'measuring…'}"
            if size is not None:
                est = "" if (not is_dir or getattr(payload, "size_complete", True)) else "≈"
                return f"{label}    {est}{format_size(size())}"
            total = getattr(payload, "total", None)
            return f"{label}    {format_size(total)}" if total else label
        if role == Qt.ItemDataRole.ToolTipRole:
            return getattr(payload, "path", None) or getattr(payload, "mount", label)
        if role == Qt.ItemDataRole.DecorationRole and icon_key:
            return self.pixmaps.icon(icon_key, request=index.row() < 400)
        if role == Qt.ItemDataRole.ForegroundRole and is_dir:
            return QColor(130, 200, 255)
        if role == ROLE_INDEX:
            return scene_index
        if role == Qt.ItemDataRole.UserRole + 2:
            return label
        return None

    def payload_at(self, row: int):
        return self._entry(row)[0]

    def refresh(self) -> None:
        if self.rowCount():
            self.dataChanged.emit(self.index(0), self.index(self.rowCount() - 1))


class Sidebar(QWidget):
    device_activated = pyqtSignal(object)        # DeviceInfo or None (home)
    object_selected = pyqtSignal(int, object)    # scene index (or negative), payload
    object_activated = pyqtSignal(int, object)
    eject_requested = pyqtSignal(object)         # DeviceInfo

    def __init__(self, pixmaps, parent=None):
        super().__init__(parent)
        self.pixmaps = pixmaps
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        split = QSplitter(Qt.Orientation.Vertical)
        lay.addWidget(split)

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Universes (storage devices)")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        tl.addWidget(title)
        self.devices = QListWidget()
        self.devices.setIconSize(QSize(28, 28))
        self.devices.itemClicked.connect(self._device_clicked)
        self.devices.itemActivated.connect(self._device_clicked)
        self.devices.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.devices.customContextMenuRequested.connect(self._device_menu)
        tl.addWidget(self.devices)
        split.addWidget(top)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self.objects_title = QLabel("Objects in view")
        self.objects_title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        bl.addWidget(self.objects_title)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter objects in this view…")
        self.filter.setClearButtonEnabled(True)
        bl.addWidget(self.filter)
        self.model = ObjectListModel(pixmaps, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterRole(Qt.ItemDataRole.UserRole + 2)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.list = QListView()
        self.list.setModel(self.proxy)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.clicked.connect(self._obj_clicked)
        self.list.activated.connect(self._obj_activated)
        self.list.doubleClicked.connect(self._obj_activated)
        self.list.selectionModel().currentChanged.connect(lambda cur, _prev: self._obj_clicked(cur))
        bl.addWidget(self.list)
        split.addWidget(bottom)
        split.setSizes([180, 500])
        self._device_list = []
        self._suppress = False

    # ---- devices --------------------------------------------------------------
    def set_devices(self, devices, current_mount: str | None) -> None:
        self._device_list = devices
        self.devices.blockSignals(True)
        self.devices.clear()
        home = QListWidgetItem(self.pixmaps.icon("gen:drive:unknown", request=False), "This PC — multiverse")
        home.setData(Qt.ItemDataRole.UserRole, None)
        self.devices.addItem(home)
        for d in devices:
            if d.ready and d.total:
                sub = f"{d.kind_label} · {format_size(d.free)} free of {format_size(d.total)}"
            else:
                sub = f"{d.kind_label} · {d.error or 'not ready'}"
            item = QListWidgetItem(self.pixmaps.icon("drive:" + d.mount), f"{d.title}\n{sub}")
            item.setData(Qt.ItemDataRole.UserRole, d)
            tip = f"{d.mount}  {d.fstype}  {d.bus} {d.media}".strip()
            item.setToolTip(tip + ("\nRight-click to safely remove" if can_eject(d) else ""))
            if not d.ready:
                item.setForeground(QColor(120, 120, 130))
            self.devices.addItem(item)
            if current_mount and d.mount.upper() == current_mount.upper():
                item.setSelected(True)
        if not current_mount:
            home.setSelected(True)
        self.devices.blockSignals(False)

    def _device_clicked(self, item) -> None:
        d = item.data(Qt.ItemDataRole.UserRole)
        self.device_activated.emit(d)

    def _device_menu(self, pos) -> None:
        item = self.devices.itemAt(pos)
        d = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if d is None:
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.device_activated.emit(d))
        eject = menu.addAction("⏏ Eject disc" if d.kind == "disc" else "⏏ Safely remove",
                               lambda: self.eject_requested.emit(d))
        eject.setEnabled(can_eject(d))
        menu.exec(self.devices.viewport().mapToGlobal(pos))

    # ---- objects -------------------------------------------------------------
    def set_scene(self, scene, extra_nodes=None) -> None:
        self._suppress = True
        self.model.set_scene(scene, extra_nodes)
        n = self.model.rowCount()
        self.objects_title.setText(f"Objects in view ({n:,})")
        self._suppress = False

    def select_index(self, scene_index: int | None) -> None:
        self._suppress = True
        self.list.clearSelection()
        if scene_index is not None and scene_index >= self.model.offset:
            row = scene_index - self.model.offset
            if 0 <= row < self.model.rowCount():
                pidx = self.proxy.mapFromSource(self.model.index(row))
                if pidx.isValid():
                    self.list.setCurrentIndex(pidx)
                    self.list.scrollTo(pidx)
        self._suppress = False

    def _source(self, proxy_index):
        src = self.proxy.mapToSource(proxy_index)
        if not src.isValid():
            return None, None
        return self.model.data(src, ROLE_INDEX), self.model.payload_at(src.row())

    def _obj_clicked(self, proxy_index) -> None:
        if self._suppress or not proxy_index.isValid():
            return
        idx, payload = self._source(proxy_index)
        if payload is not None:
            self.object_selected.emit(idx, payload)

    def _obj_activated(self, proxy_index) -> None:
        idx, payload = self._source(proxy_index)
        if payload is not None:
            self.object_activated.emit(idx, payload)
