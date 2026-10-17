"""Main window: wires devices, scanning, navigation, the 3D view and panels together."""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QDockWidget, QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressBar,
                             QPushButton, QStatusBar, QToolBar, QWidget, QVBoxLayout)

from devices.detection import DeviceMonitor
from devices.eject import can_eject, drives_removed_together, safely_remove
from devices.storage_info import DeviceInfo
from filesystem.models import FSNode
from filesystem.paths import depth_below, drive_root, norm_key, os_path, parent_path, split_ancestors
from filesystem.service import ScanService
from filesystem.threads import safe_emit
from icons.loader import IconService
from navigation.controller import History, Location, transition_mode
from navigation.selection import SelectionModel
from previews.service import PreviewService
from universe.hierarchy import cosmic_name
from universe.mapping import format_size
from universe.scene_builder import build_folder_scene, build_home_scene, layout_folder_scene, refresh_satellites

from .breadcrumb import Breadcrumb
from .properties_panel import PropertiesPanel
from .qt_images import IconPixmaps
from .search_panel import SearchPanel
from .sidebar import Sidebar
from .viewport import UniverseViewport

STYLE = """
QMainWindow, QWidget { background: #0d1321; color: #d7def0; font-family: 'Segoe UI'; font-size: 9pt; }
QToolBar { background: #121a2c; border: none; spacing: 4px; padding: 3px; }
QToolButton { padding: 4px 8px; border-radius: 4px; }
QToolButton:hover { background: #22304d; }
QToolButton:disabled { color: #4a5570; }
QListView, QListWidget { background: #0a0f1b; border: 1px solid #1e2a44; border-radius: 4px; }
QListView::item:selected, QListWidget::item:selected { background: #24406e; }
QLineEdit { background: #0a0f1b; border: 1px solid #2a3a5c; border-radius: 4px; padding: 3px 6px; }
QPushButton { background: #1d2a46; border: 1px solid #2c3f66; border-radius: 4px; padding: 4px 10px; }
QPushButton:hover { background: #26375b; }
QDockWidget::title { background: #121a2c; padding: 4px; }
QStatusBar { background: #0a0f1b; }
QProgressBar { background: #0a0f1b; border: 1px solid #2a3a5c; border-radius: 3px; text-align: center; max-height: 14px; }
QProgressBar::chunk { background: #3d7bd9; }
QScrollBar:vertical { background: #0a0f1b; width: 10px; }
QScrollBar::handle:vertical { background: #2a3a5c; border-radius: 4px; }
"""


class MainWindow(QMainWindow):
    eject_finished = pyqtSignal(object, bool, str)     # DeviceInfo, success, message

    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Universe Explorer")
        self.resize(1500, 900)
        self.setStyleSheet(STYLE)
        self.icons = IconService()
        self.previews = PreviewService(self)
        self.pixmaps = IconPixmaps(self.icons)
        self.scan = ScanService(self)
        self.history = History()
        self.selection = SelectionModel(self)
        self.devices: list[DeviceInfo] = []
        self.location: Location | None = None
        self.current_node: FSNode | None = None
        self._pending_select: str | None = None
        self._relayout_due = False
        self._removed_devices: dict[str, DeviceInfo] = {}

        self.viewport = UniverseViewport(self.icons, self.previews)
        self.viewport.label_fn = self._label_for
        self.breadcrumb = Breadcrumb()
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.breadcrumb)
        cl.addWidget(self.viewport, 1)
        self.setCentralWidget(central)

        self.sidebar = Sidebar(self.pixmaps)
        dock = QDockWidget("Explorer", self)
        dock.setWidget(self.sidebar)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.props = PropertiesPanel(self.pixmaps, self.previews)
        pdock = QDockWidget("Properties", self)
        pdock.setWidget(self.props)
        pdock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, pdock)
        self.search_panel = SearchPanel(self.pixmaps)
        self.search_dock = QDockWidget("Search", self)
        self.search_dock.setWidget(self.search_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.search_dock)
        self.resizeDocks([dock, pdock], [300, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.search_dock], [150], Qt.Orientation.Vertical)

        self._build_toolbar()
        self._build_status()
        self._connect()

        self.monitor = DeviceMonitor(parent=self)
        self.monitor.devices_changed.connect(self._on_devices)
        self.navigate(Location(None))
        QTimer.singleShot(50, self.monitor.start)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setInterval(700)
        self._relayout_timer.timeout.connect(self._maybe_relayout)
        self._relayout_timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    # ---- construction ---------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Navigation")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, tip, slot, shortcut=None):
            a = QAction(text, self)
            a.setToolTip(tip + (f"  ({shortcut})" if shortcut else ""))
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            tb.addAction(a)
            return a

        self.a_back = act("◀ Back", "Back", self.go_back, "Alt+Left")
        self.a_fwd = act("Forward ▶", "Forward", self.go_forward, "Alt+Right")
        self.a_up = act("▲ Up", "Up to the parent structure", self.go_up, "Alt+Up")
        self.a_home = act("⌂ Home", "This PC (all universes)", lambda: self.navigate(Location(None)), "Alt+Home")
        tb.addSeparator()
        act("⟳ Refresh", "Rescan the current location", self.refresh, "F5")
        act("◎ Reset camera", "Reset the camera", self.viewport.reset_camera, "Ctrl+R")
        self.a_labels = act("Labels", "Toggle labels", self._toggle_labels, "Ctrl+T")
        act("Go to path…", "Type a path to fly to", self._goto_path, "Ctrl+L")
        act("Search", "Search below the current location", self._focus_search, "Ctrl+F")
        tb.addSeparator()
        act("⏏ Safely remove", "Safely remove the selected device, or the one you are browsing", self._eject_current,
            "Ctrl+E")
        tb.addSeparator()
        act("?", "About / help", self._about)

    def _build_status(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("")
        sb.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.hide()
        sb.addPermanentWidget(self.progress)
        self.cancel_btn = QPushButton("Cancel scan")
        self.cancel_btn.clicked.connect(self.scan.cancel_all)
        self.cancel_btn.hide()
        sb.addPermanentWidget(self.cancel_btn)

    def _connect(self) -> None:
        self.scan.listing_ready.connect(self._on_listing)
        self.scan.previews_ready.connect(self._on_previews)
        self.scan.sizes_updated.connect(self._on_sizes)
        self.scan.progress.connect(self._on_progress)
        self.scan.search_batch.connect(self._on_search_batch)
        self.scan.search_done.connect(self._on_search_done)
        self.viewport.item_clicked.connect(self._on_view_click)
        self.viewport.item_activated.connect(self._on_view_activate)
        self.viewport.back_requested.connect(self.go_back_or_up)
        self.viewport.home_requested.connect(lambda: self.navigate(Location(None)))
        self.sidebar.device_activated.connect(self._on_device_activated)
        self.sidebar.object_selected.connect(self._on_list_select)
        self.sidebar.object_activated.connect(self._on_list_activate)
        self.sidebar.eject_requested.connect(self.safely_remove)
        self.eject_finished.connect(self._on_eject_finished)
        self.breadcrumb.path_clicked.connect(self._on_crumb)
        self.search_panel.search_requested.connect(self._start_search)
        self.search_panel.stop_requested.connect(self.scan.cancel_search)
        self.search_panel.hit_activated.connect(self._on_hit)
        self.icons.icon_ready.connect(self._on_icon_ready)

    # ---- helpers -------------------------------------------------------------------
    def device_for(self, path: str) -> DeviceInfo | None:
        root = norm_key(drive_root(path))
        for d in self.devices:
            if norm_key(d.mount) == root:
                return d
        return None

    def _depth_of(self, path: str) -> int:
        return depth_below(drive_root(path), path)

    def _label_for(self, item):
        p = item.payload
        if isinstance(p, FSNode):
            if p.is_dir and p.total_size is None:
                return item.label, "measuring…" if not p.is_link else "link"
            est = "≈" if p.is_dir and not p.size_complete else ""
            return item.label, f"{est}{format_size(p.effective_size())}"
        if isinstance(p, DeviceInfo):
            if p.ready and p.total:
                return p.title, f"{p.kind_label} · {format_size(p.used)} used / {format_size(p.total)}"
            return p.title, p.error or "not ready"
        return item.label, ""

    # ---- navigation -----------------------------------------------------------------
    def navigate(self, loc: Location, push: bool = True, select_key: str | None = None) -> None:
        if loc.path is not None:
            if not os.path.isdir(os_path(loc.path)):
                self.status_label.setText(f"Cannot open {loc.path}: not available")
                return
            if loc.mount is None:
                loc = Location(loc.path, drive_root(loc.path))
        old = self.location
        mode = transition_mode(old, loc)
        sc = self.viewport.scene
        focus = child_key = None
        if mode == "in" and sc is not None:
            focus = sc.index_of_key(loc.key)
            if focus is None:
                mode = "jump"
        elif mode == "out" and old is not None:
            child_key = old.key
        self.location = loc
        self._pending_select = select_key
        if push:
            self.history.push(loc)
        self.scan.cancel_sizes()
        self.selection.clear()
        self._update_nav_actions()
        if loc.is_home:
            self.current_node = None
            self.breadcrumb.set_path(None)
            self.viewport.set_scene(None, mode if old is not None else "jump", focus, child_key)
            scene = build_home_scene(self.devices)
            self.viewport.provide_scene(scene)
            self._after_scene(scene)
        else:
            dev = self.device_for(loc.path)
            self.breadcrumb.set_path(loc.path, dev.title if dev else None)
            self.scan.set_protected(split_ancestors(loc.path))
            self.viewport.set_scene(None, mode, focus, child_key)
            self.current_node = self.scan.request_listing(loc.path)
        self._update_hud()

    def _build_current_scene(self):
        node = self.current_node
        dev = self.device_for(node.path)
        return build_folder_scene(node, self._depth_of(node.path), dev.kind if dev else "unknown")

    def _on_listing(self, key: str) -> None:
        if self.location is None or self.location.is_home or key != self.location.key:
            return
        node = self.scan.model.get(self.location.path)
        if node is None:
            return
        self.current_node = node
        scene = self._build_current_scene()
        if node.error:
            scene.status_text = node.error
        self.viewport.provide_scene(scene)
        self._after_scene(scene)
        self.scan.request_sizes(node)

    def _after_scene(self, scene) -> None:
        extra = []
        if self.current_node is not None and scene.hidden_count:
            extra = (self.current_node.children or [])[len(scene.items) - 1:]
        self.sidebar.set_scene(scene, extra)
        cur = self.location.path if self.location else None
        self.sidebar.set_devices(self.devices, drive_root(cur) if cur else None)
        self._show_current_properties()
        self._update_hud()
        if self._pending_select:
            idx = scene.index_of_key(self._pending_select)
            self._pending_select = None
            if idx is not None:
                QTimer.singleShot(1300, lambda i=idx: self._select_index(i, focus=True))

    def _on_previews(self, key: str) -> None:
        sc = self.viewport.scene
        if sc is not None and self.location is not None and key == self.location.key and sc.payload is self.current_node:
            refresh_satellites(sc)

    def _on_sizes(self, keys: list) -> None:
        if self.current_node is None:
            return
        self._relayout_due = True
        sel = self.selection.payload
        if isinstance(sel, FSNode) and sel.key in keys:
            self.props.refresh()
        elif sel is None and self.current_node.key in keys:
            self._show_current_properties()

    def _maybe_relayout(self) -> None:
        if not self._relayout_due:
            return
        sc = self.viewport.scene
        if sc is None or sc.payload is not self.current_node or self.viewport.in_transition:
            return
        self._relayout_due = False
        if sc.payload is None:      # home scene: devices, not folders - nothing to relayout
            return
        layout_folder_scene(sc)
        self.sidebar.model.refresh()
        self._update_hud()

    def go_back(self) -> None:
        loc = self.history.back()
        if loc is not None:
            self.navigate(loc, push=False)

    def go_forward(self) -> None:
        loc = self.history.forward()
        if loc is not None:
            self.navigate(loc, push=False)

    def go_up(self) -> None:
        if self.location is None or self.location.is_home:
            return
        parent = parent_path(self.location.path)
        self.navigate(Location(parent) if parent else Location(None))

    def go_back_or_up(self) -> None:
        if self.history.can_back():
            self.go_back()
        else:
            self.go_up()

    def refresh(self) -> None:
        self.monitor.refresh()
        if self.location is None or self.location.is_home:
            scene = build_home_scene(self.devices)
            self.viewport.set_scene(scene, "refresh")
            self._after_scene(scene)
            return
        self.scan.invalidate(self.location.path)
        self.scan.request_listing(self.location.path, force=True)
        self.status_label.setText(f"Rescanning {self.location.path}…")

    def _update_nav_actions(self) -> None:
        self.a_back.setEnabled(self.history.can_back())
        self.a_fwd.setEnabled(self.history.can_forward())
        self.a_up.setEnabled(self.location is not None and not self.location.is_home)

    def _update_hud(self) -> None:
        loc = self.location
        if loc is None or loc.is_home:
            self.viewport.hud_title = "This PC — the multiverse"
            n = sum(1 for d in self.devices if d.ready)
            self.viewport.hud_subtitle = f"{n} universe(s) · each storage device is shaped like its hardware"
            self.setWindowTitle("File Universe Explorer — This PC")
            return
        node = self.current_node
        depth = self._depth_of(loc.path)
        self.viewport.hud_title = f"{cosmic_name(depth)}: {node.name if node else loc.path}"
        sub = loc.path
        if node is not None and node.children is not None:
            f, d = node.direct_counts()
            est = "" if node.size_complete else "≈"
            sub += f"   ·   {d:,} folders, {f:,} files   ·   {est}{format_size(node.effective_size())}"
        self.viewport.hud_subtitle = sub
        self.setWindowTitle(f"File Universe Explorer — {loc.path}")

    # ---- selection ---------------------------------------------------------------------
    def _scene_depth(self) -> int:
        if self.location is None or self.location.is_home:
            return 0
        return self._depth_of(self.location.path)

    def _show_current_properties(self) -> None:
        if self.location is None or self.location.is_home:
            self.props.show_payload(None)
        elif self.current_node is not None:
            depth = self._depth_of(self.current_node.path)
            if depth == 0:
                dev = self.device_for(self.current_node.path)
                if dev is not None:
                    self.props.show_payload(dev, 0, True, "drive:" + dev.mount)
                    return
            self.props.show_payload(self.current_node, depth, True, "dir:" + self.current_node.path)

    def _select_index(self, idx: int, focus: bool = False) -> None:
        sc = self.viewport.scene
        if sc is None or not (0 <= idx < len(sc)):
            return
        self.viewport.selected = idx
        item = sc.items[idx]
        self.selection.set(item.payload)
        self.sidebar.select_index(idx)
        if item.is_center:
            self._show_current_properties()
        else:
            self.props.show_payload(item.payload, self._scene_depth(), False, item.icon_key)
        if focus:
            self.viewport.focus_item(idx)

    def _on_view_click(self, idx: int) -> None:
        if idx < 0:
            self.viewport.selected = None
            self.selection.clear()
            self.sidebar.select_index(None)
            self._show_current_properties()
            return
        self._select_index(idx)

    def _activate_payload(self, payload, idx: int | None) -> None:
        if isinstance(payload, DeviceInfo):
            if payload.ready:
                self.navigate(Location(payload.mount, payload.mount))
            else:
                self.status_label.setText(f"{payload.title}: {payload.error or 'not ready'}")
        elif isinstance(payload, FSNode):
            if idx == 0:
                self.viewport.reset_camera()
            elif payload.is_dir:
                self.navigate(Location(payload.path))
            else:
                if idx is not None and idx > 0:
                    self._select_index(idx, focus=True)
                self._open_file(payload)

    def _open_file(self, node: FSNode) -> None:
        """Hand the file to Windows to open with its associated application, like Explorer does."""
        try:
            os.startfile(os_path(node.path))
        except OSError as exc:
            self.status_label.setText(f"{node.name}: could not open ({exc.strerror or exc})")
        else:
            self.status_label.setText(f"Opened {node.name}")

    def _on_view_activate(self, idx: int) -> None:
        sc = self.viewport.scene
        if sc is not None and 0 <= idx < len(sc):
            self._activate_payload(sc.items[idx].payload, idx)

    def _on_list_select(self, idx: int, payload) -> None:
        if idx >= 0:
            self._select_index(idx, focus=True)
        else:
            self.selection.set(payload)
            self.props.show_payload(payload, self._scene_depth(), False,
                                    ("dir:" if payload.is_dir else "file:") + payload.path)

    def _on_list_activate(self, idx: int, payload) -> None:
        self._activate_payload(payload, idx if idx >= 0 else None)

    def _on_device_activated(self, dev) -> None:
        if dev is None:
            self.navigate(Location(None))
        else:
            self._activate_payload(dev, None)

    def _on_crumb(self, path) -> None:
        self.navigate(Location(path) if path else Location(None))

    # ---- devices -------------------------------------------------------------------------
    def _on_devices(self, devices: list) -> None:
        old_mounts = {d.mount.upper() for d in self.devices if d.ready}
        new_mounts = {d.mount.upper() for d in devices if d.ready}
        removed = old_mounts - new_mounts
        added = new_mounts - old_mounts
        self.devices = devices
        self.icons.drive_kinds = {d.mount: d.kind for d in devices}
        cur = self.location
        if cur is not None and not cur.is_home and cur.mount and cur.mount.upper() in removed:
            self._drive_lost(cur.mount)
        elif cur is not None and cur.is_home and (removed or added or self.viewport.scene is None
                                                  or len(self.viewport.scene) != len(devices)):
            self._rebuild_home(removed)
        else:
            self.sidebar.set_devices(devices, drive_root(cur.path) if cur and cur.path else None)
            if cur is not None and cur.is_home:
                self._update_hud()
        self.history.replace_missing(new_mounts)
        self._update_nav_actions()
        if removed:
            self.status_label.setText("Disconnected: " + ", ".join(sorted(removed)))
        elif added and old_mounts:
            self.status_label.setText("Connected: " + ", ".join(sorted(added)))

    def _eject_current(self) -> None:
        sel = self.selection.payload
        if isinstance(sel, DeviceInfo):
            dev = sel
        elif self.location is not None and self.location.path:
            dev = self.device_for(self.location.path)
        else:
            dev = None
        if dev is None:
            self.status_label.setText("Select a device first (or right-click one in the Universes list).")
        else:
            self.safely_remove(dev)

    def safely_remove(self, dev: DeviceInfo) -> None:
        if not can_eject(dev):
            self.status_label.setText(f"{dev.title} is not a removable device.")
            return
        if getattr(self, "_ejecting", False):
            return
        together = drives_removed_together(dev, self.devices)
        if len(together) > 1:
            names = "\n".join("  • " + d.title for d in together)
            answer = QMessageBox.question(
                self, "Safely remove",
                f"{dev.title} shares one device with other drives (for example the slots of a card reader).\n"
                f"Removing it removes all of these together:\n\n{names}\n\nContinue?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._ejecting = True
        # release our own handles on the drive first: running listings, size walks and searches
        self.scan.cancel_all()
        self.status_label.setText(f"Preparing {dev.title} for safe removal…")
        threading.Thread(target=lambda: safe_emit(self.eject_finished, dev, *safely_remove(dev)),
                         daemon=True, name="eject").start()

    def _on_eject_finished(self, dev: DeviceInfo, ok: bool, message: str) -> None:
        self._ejecting = False
        if ok:
            self.monitor.refresh()     # the drive disappears through the normal hot-plug path
            QTimer.singleShot(600, lambda: self.status_label.setText(message))
        else:
            QMessageBox.warning(self, "Safely remove", message)
        self.status_label.setText(message)

    def _rebuild_home(self, removed: set[str]) -> None:
        old = self.viewport.scene
        if old is not None and removed and old.payload is None:
            # let the vanished universes fade away before rebuilding
            for i, it in enumerate(old.items):
                if isinstance(it.payload, DeviceInfo) and it.payload.mount.upper() in removed:
                    old.alpha_target[i] = 0.0
            QTimer.singleShot(1600, lambda: self._rebuild_home(set()))
            return
        scene = build_home_scene(self.devices)
        prev = {it.payload.mount.upper() for it in old.items} if old is not None and old.payload is None else set()
        for i, it in enumerate(scene.items):
            scene.alpha[i] = 1.0 if it.payload.mount.upper() in prev else 0.0
        scene.fade = 1.0
        self.viewport.set_scene(scene, "refresh")
        self.viewport.scene.alpha[:] = [1.0 if it.payload.mount.upper() in prev else 0.0 for it in scene.items]
        self._after_scene(scene)

    def _drive_lost(self, mount: str) -> None:
        sc = self.viewport.scene
        self.scan.cancel_all()
        if sc is not None:
            sc.dissolving = True
            sc.fade_target = 0.0
            sc.extra.pop("keep", None)
            sc.status_text = f"Drive {mount} was disconnected — its universe is fading away"
        QTimer.singleShot(1800, lambda: self.navigate(Location(None)))

    # ---- search ------------------------------------------------------------------------
    def _focus_search(self) -> None:
        self.search_dock.show()
        self.search_panel.query.setFocus()
        self.search_panel.query.selectAll()

    def _start_search(self, query: str) -> None:
        if self.location is None or self.location.is_home:
            roots = [d.mount for d in self.devices if d.ready]
            scope = "all drives"
        else:
            roots = [self.location.path]
            scope = self.location.path
        if not roots:
            return
        self.search_panel.set_running(scope)
        self._search_token = self.scan.search(roots, query)

    def _on_search_batch(self, token: int, hits: list) -> None:
        if token == getattr(self, "_search_token", None):
            self.search_panel.add_hits(hits)

    def _on_search_done(self, token: int, count: int, cancelled: bool) -> None:
        if token == getattr(self, "_search_token", None):
            self.search_panel.finished(count, cancelled)

    def _on_hit(self, hit) -> None:
        if hit.is_dir:
            self.navigate(Location(hit.path))
        else:
            parent = parent_path(hit.path)
            if parent:
                self.navigate(Location(parent), select_key=norm_key(hit.path))

    # ---- misc --------------------------------------------------------------------------
    def _on_progress(self, text: str, done: int, total: int) -> None:
        if text:
            self.status_label.setText(text)
        elif self.status_label.text().startswith(("Scanning", "Searching", "Rescanning")):
            self.status_label.setText("Ready")
        busy = bool(text) and not text.endswith("complete") and text != "Cancelled"
        if total > 0 and busy:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress.show()
        elif busy:
            self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.hide()
        self.cancel_btn.setVisible(busy)

    def _on_icon_ready(self, _key: str) -> None:
        if not hasattr(self, "_icon_refresh_pending"):
            self._icon_refresh_pending = False
        if not self._icon_refresh_pending:
            self._icon_refresh_pending = True
            QTimer.singleShot(300, self._refresh_icons)

    def _refresh_icons(self) -> None:
        self._icon_refresh_pending = False
        self.sidebar.model.refresh()
        self.search_panel.model.layoutChanged.emit()

    def _toggle_labels(self) -> None:
        self.viewport.show_labels = not self.viewport.show_labels

    def _goto_path(self) -> None:
        start = self.location.path if self.location and self.location.path else ""
        text, ok = QInputDialog.getText(self, "Go to path", "Folder path:", text=start)
        if ok and text.strip():
            path = os.path.abspath(os.path.expandvars(text.strip().strip('"')))
            self.navigate(Location(path))

    def _about(self) -> None:
        QMessageBox.information(self, "File Universe Explorer", (
            "Your storage devices as navigable 3D universes.\n\n"
            "Drive → universe → galaxy → nebula region → star cluster → planetary system → planet → moon → "
            "crater → rock → sand grain → microscopic worlds (endless).\n\n"
            "Mouse: left-drag rotate · right/middle-drag (or Shift+drag) pan · wheel zoom · click select · "
            "double-click enter / open file.\nKeys: arrows rotate · W/A/S/D pan · +/- zoom · Tab next object · F focus · "
            "Enter open folder · Backspace back · Home · R reset · F5 refresh · Ctrl+F search · Ctrl+L go to path.\n\n"
            "Browsing is read-only: nothing is ever modified. Double-clicking a file opens it in its default app."))

    def shutdown(self) -> None:
        if getattr(self, "_shut", False):
            return
        self._shut = True
        self.scan.shutdown()
        self.icons.shutdown()
        self.previews.shutdown()

    def closeEvent(self, e) -> None:
        self.shutdown()
        super().closeEvent(e)
