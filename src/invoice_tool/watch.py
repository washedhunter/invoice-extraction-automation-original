"""--watch mode: re-run the pipeline whenever a new document lands in the inbox folder."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from invoice_tool.pipeline import SUPPORTED_SUFFIXES


class _Handler(FileSystemEventHandler):
    def __init__(self, changed: threading.Event):
        self.changed = changed

    def _maybe(self, path: str) -> None:
        if Path(path).suffix.lower() in SUPPORTED_SUFFIXES:
            self.changed.set()

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._maybe(str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._maybe(str(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._maybe(str(event.src_path))


def _snapshot(folder: Path) -> dict[str, int]:
    return {
        p.name: p.stat().st_size
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    }


def watch(
    folder: Path,
    on_change: Callable[[], None],
    settle_seconds: float = 2.0,
    stop: threading.Event | None = None,
) -> None:
    """Call on_change() once at start and again after new/changed files have stopped growing."""
    folder = Path(folder)
    changed = threading.Event()
    stop = stop or threading.Event()
    observer = Observer()
    observer.schedule(_Handler(changed), str(folder), recursive=False)
    observer.start()
    try:
        on_change()
        while not stop.is_set():
            if not changed.wait(timeout=0.5):
                continue
            # wait until copies finish: file sizes unchanged for settle_seconds
            before = _snapshot(folder)
            while True:
                changed.clear()
                time.sleep(settle_seconds)
                after = _snapshot(folder)
                if after == before and not changed.is_set():
                    break
                before = after
            on_change()
    finally:
        observer.stop()
        observer.join(timeout=5)
