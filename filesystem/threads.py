"""Helpers for emitting Qt signals from worker threads."""
from __future__ import annotations


def safe_emit(signal, *args) -> None:
    """Emit from a worker thread; ignore the error raised if the QObject was
    already destroyed because the application is shutting down."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass
