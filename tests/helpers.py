"""Shared test helpers: temporary directory trees."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def make_tree(base: str, spec: dict) -> None:
    """spec: {name: int (file size) | dict (sub-folder)}"""
    for name, val in spec.items():
        p = os.path.join(base, name)
        if isinstance(val, dict):
            os.makedirs(p, exist_ok=True)
            make_tree(p, val)
        else:
            with open(p, "wb") as f:
                f.write(b"x" * val)


class TempTree:
    def __init__(self, spec: dict):
        self.spec = spec

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix="fue_test_")
        make_tree(self.path, self.spec)
        return self.path

    def __exit__(self, *exc) -> None:
        # the long-path prefix lets rmtree delete trees deeper than MAX_PATH
        target = "\\\\?\\" + os.path.abspath(self.path) if sys.platform == "win32" else self.path
        shutil.rmtree(target)
