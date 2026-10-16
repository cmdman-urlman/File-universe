"""The interactive 3D viewport (QOpenGLWidget) with picking and zoom transitions."""
from __future__ import annotations

import math
import os
import time
import traceback

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from rendering import lod as lodmod
from rendering.camera import OrbitCamera
from rendering.mathutil import ray_sphere
from rendering.renderer import BACKDROP_KINDS, Renderer

ZOOM_FACTOR = 3.4        # camera distance in object radii when "standing" at an object


class UniverseViewport(QOpenGLWidget):
    item_clicked = pyqtSignal(int)          # scene index or -1
    item_activated = pyqtSignal(int)        # double-click / Enter
    hover_changed = pyqtSignal(int)
    back_requested = pyqtSignal()
    home_requested = pyqtSignal()
    transition_finished = pyqtSignal()

    def __init__(self, icon_service, preview_service, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.camera = OrbitCamera()
        self.renderer = Renderer(icon_service, preview_service)
        self.scene = None
        self.selected: int | None = None
        self.hovered: int | None = None
        self.frame = None
        self.gl_error: str | None = None
        self.label_fn = lambda item: (item.label, "")
        self.hud_title = ""
        self.hud_subtitle = ""
        self.status_text = ""
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.t = 0.0
        self.scene_t = 0.0
        self._transition: dict | None = None
        self._press_pos = None
        self._press_button = None
        self._dragged = False
        self._last_mouse = None
        self._fps = 0.0
        self.show_labels = True
        self._label_font = QFont("Segoe UI", 9)
        self._small_font = QFont("Segoe UI", 8)
        self._title_font = QFont("Segoe UI", 13, QFont.Weight.DemiBold)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)

    # ---- GL lifecycle -----------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            self.renderer.initialize()
        except Exception as exc:
            self.gl_error = f"OpenGL initialisation failed: {exc}"
            traceback.print_exc()

    def paintGL(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last, 0.1)
        self._last = now
        self.t = now - self._t0
        if dt > 0:
            self._fps = self._fps * 0.95 + (1.0 / dt) * 0.05
        self.camera.update(dt)
        self._step_transition()
        frozen = self._transition is not None and self._transition.get("phase") == 1
        if not frozen:
            self.scene_t += dt
        if self.scene is not None:
            self.scene.animate(dt)
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        if self.renderer.ready and not self.gl_error:
            try:
                self.frame = self.renderer.render(self.scene, self.camera, w, h, self.t, self.scene_t,
                                                  self.selected, self.hovered)
            except Exception as exc:
                self.gl_error = f"Rendering error: {exc}"
                traceback.print_exc()
        self._paint_overlay(dpr)
        spent = time.perf_counter() - now
        if spent > 0.25 and os.environ.get("FUE_PERF_LOG"):
            print(f"[perf] slow frame {spent * 1000:.0f} ms ({len(self.scene) if self.scene else 0} objects)", flush=True)

    # ---- scene management & transitions ---------------------------------------
    def set_scene(self, scene, mode: str = "jump", focus_index: int | None = None, child_key: str | None = None):
        """Start a transition to *scene* (which may be None = 'still loading').

        mode: 'in' (zoom into child focus_index of the current scene), 'out'
        (zoom out to the parent; child_key identifies the old focus in the new
        scene), 'jump', or 'refresh' (rebuild in place).
        """
        old = self.scene
        if mode == "refresh" and old is not None and scene is not None:
            scene.fade = 1.0
            scene.alpha[:] = 1.0
            self._swap(scene)
            return
        tr = {"mode": mode, "next": scene, "phase": 1, "focus": focus_index, "child_key": child_key}
        if old is None:
            tr["phase"] = 2
            self._transition = tr
            if scene is not None:
                self._begin_phase2()
            return
        self.selected = None
        self.hovered = None
        cam = self.camera
        if mode == "in" and focus_index is not None and 0 <= focus_index < len(old):
            p = old.world_positions(self.scene_t)[focus_index]
            r = float(old.radius[focus_index])
            old.extra["keep"] = [focus_index]
            old.fade_target = 0.0
            cam.fly_to(p, max(r * ZOOM_FACTOR, cam.min_distance * 2), 0.8)
        elif mode == "out":
            old.extra["keep"] = [0]
            old.fade_target = 0.0
            r0 = float(old.radius[0]) if len(old) else 1.0
            cam.fly_to(np.zeros(3), r0 * ZOOM_FACTOR, 0.55)
        else:
            old.fade_target = 0.0
            cam.fly_to(cam.target, cam.distance * 1.6, 0.4)
        self._transition = tr

    def provide_scene(self, scene) -> None:
        """Deliver the destination scene of a running transition."""
        if self._transition is None:
            self.set_scene(scene, "refresh" if self.scene is not None else "jump")
            return
        self._transition["next"] = scene

    @property
    def in_transition(self) -> bool:
        return self._transition is not None

    def _step_transition(self) -> None:
        tr = self._transition
        if tr is None:
            return
        if tr["phase"] == 1:
            if self.camera.animating:
                return
            if tr["next"] is None:
                self.status_text = "Scanning…"
                return
            self._begin_phase2()
        elif tr["phase"] == 2:
            if not self.camera.animating and (self.scene is None or self.scene.fade > 0.9):
                if self.scene is not None:
                    self.scene.extra.pop("keep", None)
                self._transition = None
                self.status_text = ""
                self.transition_finished.emit()

    def _begin_phase2(self) -> None:
        tr = self._transition
        new = tr["next"]
        mode = tr["mode"]
        cam = self.camera
        self.status_text = ""
        new.fade = 0.0
        new.fade_target = 1.0
        self.scene_t = 0.0
        pos0 = new.world_positions(0.0)
        if mode == "in" and len(new):
            new.extra["keep"] = [0]
            cam.set_view(np.zeros(3), float(new.radius[0]) * ZOOM_FACTOR, immediate=True)
        elif mode == "out" and tr.get("child_key") is not None:
            j = new.index_of_key(tr["child_key"])
            if j is not None:
                new.extra["keep"] = [j]
                cam.set_view(pos0[j], float(new.radius[j]) * ZOOM_FACTOR, immediate=True)
            else:
                cam.set_view(np.zeros(3), new.view_distance * 0.3, immediate=True)
        else:
            cam.set_view(np.zeros(3), new.view_distance * 2.2, immediate=True)
        if len(new):
            new.alpha[:] = 0.0
            if "keep" in new.extra:
                new.alpha[new.extra["keep"]] = 1.0
        self.scene = new
        self.camera.min_distance = max(float(new.radius[0]) * 0.02, 1e-3) if len(new) else 0.01
        cam.fly_to(np.zeros(3), new.view_distance, 1.1)
        tr["phase"] = 2

    def _swap(self, scene) -> None:
        self.scene = scene
        self._transition = None

    def reset_camera(self) -> None:
        if self.scene is not None:
            self.camera.fly_to(np.zeros(3), self.scene.view_distance, 0.8,
                               yaw=math.radians(35), pitch=math.radians(28))

    def focus_item(self, index: int) -> None:
        if self.scene is None or not (0 <= index < len(self.scene)):
            return
        pos = self.scene.world_positions(self.scene_t)[index]
        r = float(self.scene.radius[index])
        if index == 0 and self.scene.payload is not None:
            self.reset_camera()
            return
        self.camera.fly_to(pos, max(r * 6.0, 1.5), 0.8)

    # ---- picking ----------------------------------------------------------------
    def pick(self, x: float, y: float) -> int:
        f = self.frame
        sc = self.scene
        if f is None or sc is None or len(sc) == 0 or len(f.positions) != len(sc):
            return -1
        dpr = self.devicePixelRatioF()
        sx, sy = x * dpr, y * dpr
        origin, direction = self.camera.ray(sx, sy, f.width, f.height)
        vis = f.visible.copy()
        center_is_backdrop = sc.payload is not None and (sc.items[0].kind in BACKDROP_KINDS or not sc.items[0].drawn)
        if sc.payload is not None:
            vis[0] = False
        idx = np.nonzero(vis)[0]
        if len(idx):
            tt = ray_sphere(origin, direction, f.positions[idx], f.radii[idx] * 1.1)
            k = int(np.argmin(tt))
            if np.isfinite(tt[k]):
                return int(idx[k])
            # tolerant screen-space fallback for tiny objects
            d = np.linalg.norm(f.screen[idx] - [sx, sy], axis=1)
            near = d < np.maximum(f.px[idx], 10.0 * dpr)
            if near.any():
                cand = idx[near]
                return int(cand[np.argmin(d[near])])
        if sc.payload is not None and not center_is_backdrop and f.visible[0]:
            tt = ray_sphere(origin, direction, f.positions[:1], f.radii[:1])
            if np.isfinite(tt[0]):
                return 0
        return -1

    # ---- input --------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        self._press_pos = e.position()
        self._last_mouse = e.position()
        self._press_button = e.button()
        self._dragged = False
        self.setFocus()

    def mouseMoveEvent(self, e) -> None:
        p = e.position()
        if self._last_mouse is not None and e.buttons() != Qt.MouseButton.NoButton:
            dx = p.x() - self._last_mouse.x()
            dy = p.y() - self._last_mouse.y()
            if self._press_pos is not None and (abs(p.x() - self._press_pos.x()) + abs(p.y() - self._press_pos.y())) > 4:
                self._dragged = True
            if self._transition is None or self._transition.get("phase") == 2 and not self.camera.animating:
                h = max(self.height(), 1)
                if e.buttons() & Qt.MouseButton.LeftButton and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self.camera.rotate(dx * 0.008, dy * 0.008)
                elif e.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton | Qt.MouseButton.LeftButton):
                    self.camera.pan(dx / h, dy / h)
            self._last_mouse = p
            return
        idx = self.pick(p.x(), p.y())
        idx = None if idx < 0 else idx
        if idx != self.hovered:
            self.hovered = idx
            self.hover_changed.emit(-1 if idx is None else idx)
            self.setCursor(Qt.CursorShape.PointingHandCursor if idx is not None else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e) -> None:
        if not self._dragged and e.button() == Qt.MouseButton.LeftButton and self._transition is None:
            idx = self.pick(e.position().x(), e.position().y())
            self.selected = None if idx < 0 else idx
            self.item_clicked.emit(idx)
        self._press_pos = None
        self._last_mouse = None

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._transition is not None:
            return
        idx = self.pick(e.position().x(), e.position().y())
        if idx >= 0:
            self.selected = idx
            self.item_activated.emit(idx)

    def wheelEvent(self, e) -> None:
        steps = e.angleDelta().y() / 120.0
        if steps and self._transition is None:
            self.camera.zoom(0.85 ** steps)

    def keyPressEvent(self, e) -> None:
        k = e.key()
        cam = self.camera
        if k == Qt.Key.Key_Left:
            cam.rotate(-0.12, 0)
        elif k == Qt.Key.Key_Right:
            cam.rotate(0.12, 0)
        elif k == Qt.Key.Key_Up:
            cam.rotate(0, 0.08)
        elif k == Qt.Key.Key_Down:
            cam.rotate(0, -0.08)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_PageUp):
            cam.zoom(0.8)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_PageDown):
            cam.zoom(1.25)
        elif k == Qt.Key.Key_W:
            cam.pan(0, 0.05)
        elif k == Qt.Key.Key_S:
            cam.pan(0, -0.05)
        elif k == Qt.Key.Key_A:
            cam.pan(0.05, 0)
        elif k == Qt.Key.Key_D:
            cam.pan(-0.05, 0)
        elif k == Qt.Key.Key_R:
            self.reset_camera()
        elif k == Qt.Key.Key_F and self.selected is not None:
            self.focus_item(self.selected)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.selected is not None:
                self.item_activated.emit(self.selected)
        elif k == Qt.Key.Key_Backspace:
            self.back_requested.emit()
        elif k == Qt.Key.Key_Home:
            self.home_requested.emit()
        elif k == Qt.Key.Key_Escape:
            self.selected = None
            self.item_clicked.emit(-1)
        elif k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.scene is not None and len(self.scene) > 0:
            n = len(self.scene)
            start = 0 if self.scene.payload is None else 1
            if n > start:
                step = -1 if k == Qt.Key.Key_Backtab or e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                cur = self.selected if self.selected is not None else start - step
                nxt = cur + step
                if nxt >= n:
                    nxt = start
                if nxt < start:
                    nxt = n - 1
                self.selected = nxt
                self.item_clicked.emit(nxt)
                self.focus_item(nxt)
        else:
            super().keyPressEvent(e)

    def focusNextPrevChild(self, nxt: bool) -> bool:
        return False      # keep Tab for cycling objects

    # ---- 2-D overlay (labels & HUD) -------------------------------------------
    def _paint_overlay(self, dpr: float) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            if self.gl_error:
                p.setPen(QColor(255, 120, 120))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                           self.gl_error + "\nSee README → Troubleshooting.")
                return
            if self.show_labels:
                self._paint_labels(p, dpr)
            self._paint_hud(p)
        finally:
            p.end()

    def _paint_labels(self, p: QPainter, dpr: float) -> None:
        f, sc = self.frame, self.scene
        if f is None or sc is None or len(f.px) != len(sc):
            return
        mask = f.visible.copy()
        if sc.payload is not None:
            mask[0] = False
        order = list(lodmod.top_k(f.px, mask & (f.px > 1.5 * dpr), lodmod.MAX_LABELS))
        for extra in (self.hovered, self.selected):
            if extra is not None and 0 <= extra < len(sc) and f.visible[extra] and extra not in order:
                order.insert(0, extra)
        placed: list[QRectF] = []
        fm = QFontMetricsF(self._label_font)
        fm2 = QFontMetricsF(self._small_font)
        for i in order:
            item = sc.items[i]
            title, sub = self.label_fn(item)
            if len(title) > 34:
                title = title[:32] + "…"
            x = f.screen[i, 0] / dpr
            w = max(fm.horizontalAdvance(title), fm2.horizontalAdvance(sub)) + 10
            h = fm.height() + (fm2.height() if sub else 0) + 4
            if f.px[i] / dpr > 140:          # huge on screen: label its centre instead
                y = f.screen[i, 1] / dpr - h / 2
            else:
                y = (f.screen[i, 1] + f.px[i]) / dpr + 4
            y = min(max(y, 50.0), self.height() - h - 22)
            r = QRectF(x - w / 2, y, w, h)
            important = i in (self.selected, self.hovered)
            if not important and any(r.intersects(o) for o in placed):
                continue
            if not self.rect().toRectF().intersects(r):
                continue
            placed.append(r)
            a = 220 if important else 150
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 14, 28, a))
            p.drawRoundedRect(r, 4, 4)
            if item.is_dir:
                p.setPen(QColor(140, 215, 255) if not important else QColor(200, 245, 255))
            else:
                p.setPen(QColor(235, 235, 245))
            p.setFont(self._label_font)
            p.drawText(QRectF(r.x(), r.y() + 1, r.width(), fm.height()), Qt.AlignmentFlag.AlignHCenter, title)
            if sub:
                p.setPen(QColor(160, 170, 190))
                p.setFont(self._small_font)
                p.drawText(QRectF(r.x(), r.y() + fm.height(), r.width(), fm2.height() + 2),
                           Qt.AlignmentFlag.AlignHCenter, sub)

    def _paint_hud(self, p: QPainter) -> None:
        p.setPen(QColor(220, 230, 255))
        p.setFont(self._title_font)
        p.drawText(QPointF(14, 26), self.hud_title)
        p.setFont(self._small_font)
        p.setPen(QColor(150, 170, 210))
        p.drawText(QPointF(14, 44), self.hud_subtitle)
        if self.scene is not None and self.scene.hidden_count:
            p.drawText(QPointF(14, 60), f"+{self.scene.hidden_count:,} smaller items not drawn "
                                        f"(listed in the object list)")
        hint = ("Drag: rotate · Right-drag: pan · Wheel: zoom · Click: select · Double-click: enter · "
                "Backspace: back · Tab: next · F: focus · R: reset")
        p.setPen(QColor(120, 135, 170))
        p.drawText(QPointF(14, self.height() - 10), hint)
        p.drawText(QPointF(self.width() - 70, self.height() - 10), f"{self._fps:4.0f} fps")
        text = self.status_text or (self.scene.status_text if self.scene is not None else "")
        if text:
            p.setFont(self._label_font)
            fm = QFontMetricsF(self._label_font)
            w = fm.horizontalAdvance(text) + 24
            r = QRectF(self.width() / 2 - w / 2, 12, w, 26)
            p.setPen(QPen(QColor(90, 160, 255, 160)))
            p.setBrush(QColor(10, 20, 40, 200))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(200, 225, 255))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
