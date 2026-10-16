"""File Universe Explorer - entry point.

    py main.py                       start the application
    py main.py --path "C:\\Users"     start inside a folder
    py main.py --selftest OUT_DIR    scripted tour that saves screenshots, then exits
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# PyOpenGL error checking costs a lot per call; enable with FUE_GL_DEBUG=1
import OpenGL  # noqa: E402

OpenGL.ERROR_CHECKING = os.environ.get("FUE_GL_DEBUG") == "1"

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QSurfaceFormat  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


def configure_gl() -> None:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)


def run_selftest(win, out_dir: str, tour: list[str]) -> None:
    """Scripted tour that waits for each transition to finish and saves screenshots.

    Tour steps: a folder path, '@in' (double-click the largest sub-folder),
    '@back', '@up', '@home' or '@select' (select the largest object).
    """
    import time as _time
    from navigation.controller import Location
    os.makedirs(out_dir, exist_ok=True)
    steps = list(tour)
    state = {"i": 0, "phase": "wait", "t": _time.monotonic() + 3.0}

    def largest(dirs_only: bool):
        sc = win.viewport.scene
        if sc is None:
            return None
        best, best_r = None, -1.0
        start = 0 if sc.payload is None else 1
        for k in range(start, len(sc)):
            it = sc.items[k]
            if dirs_only and not it.is_dir:
                continue
            if getattr(it.payload, "ready", True) and sc.radius_target[k] > best_r:
                best, best_r = k, float(sc.radius_target[k])
        return best

    def shoot(name: str) -> None:
        win.viewport.grabFramebuffer().save(os.path.join(out_dir, f"{name}_view.png"))
        win.grab().save(os.path.join(out_dir, f"{name}_window.png"))
        print(f"[selftest] {name}: {win.viewport.hud_title} | fps {win.viewport._fps:.0f}", flush=True)

    def tick() -> None:
        now = _time.monotonic()
        busy = win.viewport.in_transition or win.viewport.scene is None
        if state["phase"] == "wait":
            if busy or now < state["t"]:
                return
            idx = state["i"]
            shoot(f"{idx:02d}")
            if idx >= len(steps):
                QApplication.instance().quit()
                return
            step = steps[idx]
            state["i"] += 1
            print(f"[selftest] step {idx + 1}: {step}", flush=True)
            if step == "@in":
                k = largest(True)
                if k is not None:
                    win._on_view_activate(k)
            elif step == "@select":
                k = largest(False)
                if k is not None:
                    win._select_index(k, focus=True)
            elif step in ("@click", "@dclick"):
                # real mouse events at the projected position of the largest folder
                from PyQt6.QtCore import QPoint
                from PyQt6.QtTest import QTest
                k = largest(True)
                f = win.viewport.frame
                if k is not None and f is not None:
                    dpr = win.viewport.devicePixelRatioF()
                    pt = QPoint(int(f.screen[k, 0] / dpr), int(f.screen[k, 1] / dpr))
                    print(f"[selftest]   {step} at {pt.x()},{pt.y()} on '{win.viewport.scene.items[k].label}'"
                          f" -> pick={win.viewport.pick(pt.x(), pt.y())}", flush=True)
                    if step == "@click":
                        QTest.mouseClick(win.viewport, Qt.MouseButton.LeftButton, pos=pt)
                    else:
                        QTest.mouseDClick(win.viewport, Qt.MouseButton.LeftButton, pos=pt)
            elif step.startswith("@search:"):
                win.search_panel.query.setText(step[8:])
                win.search_panel._go()
                state["t"] = now + 6.0
                return
            elif step == "@hit":
                if win.search_panel.model.hits:
                    win._on_hit(win.search_panel.model.hits[0])
                    print(f"[selftest]   activating hit {win.search_panel.model.hits[0].path}", flush=True)
            elif step == "@back":
                win.go_back()
            elif step == "@up":
                win.go_up()
            elif step == "@home":
                win.navigate(Location(None))
            elif step == "@unplug":
                # simulate the current drive disappearing, then coming back
                real = list(win.devices)
                mount = (win.location.mount or "") if win.location else ""
                win._on_devices([d for d in real if d.mount.upper() != mount.upper()])
                QTimer.singleShot(1000, lambda: shoot(f"{idx:02d}b_unplugging"))
                QTimer.singleShot(5000, lambda: win._on_devices(real))
                state["t"] = now + 7.0
                return
            else:
                win.navigate(Location(step))
            state["t"] = now + 2.2
    timer = QTimer(win)
    timer.timeout.connect(tick)
    timer.start(100)
    QTimer.singleShot(240_000, QApplication.instance().quit)   # hard stop


def main() -> int:
    ap = argparse.ArgumentParser(description="File Universe Explorer")
    ap.add_argument("--path", help="start inside this folder")
    ap.add_argument("--selftest", metavar="OUT_DIR", help="run a scripted tour and save screenshots")
    ap.add_argument("--tour", nargs="*", default=None, help="folders visited by --selftest")
    args = ap.parse_args()

    configure_gl()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("File Universe Explorer")
    from ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    if args.path:
        from navigation.controller import Location
        QTimer.singleShot(1200, lambda: win.navigate(Location(os.path.abspath(args.path))))
    if args.selftest:
        run_selftest(win, args.selftest, args.tour or ["C:\\", "C:\\Windows"])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
