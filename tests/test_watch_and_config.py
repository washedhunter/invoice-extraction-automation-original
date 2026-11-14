import shutil
import threading
import time

from invoice_tool.config import load_settings
from invoice_tool.watch import watch
from tests.conftest import REPO_ROOT


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("INVOICE_MODEL", "gemini-other")
    monkeypatch.setenv("INVOICE_AMOUNT_TOLERANCE", "2.5")
    monkeypatch.setenv("INVOICE_CATEGORIES", '["A", "Other"]')
    s = load_settings(REPO_ROOT / "config")
    assert (
        s.model == "gemini-other" and s.amount_tolerance == 2.5 and s.categories == ["A", "Other"]
    )


def test_cli_override_beats_env(monkeypatch):
    monkeypatch.setenv("INVOICE_MODEL", "from-env")
    assert load_settings(REPO_ROOT / "config", model="from-cli").model == "from-cli"


def test_watch_survives_an_error(tmp_path):
    calls, logs = [], []
    stop = threading.Event()

    def on_change():
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("out.xlsx is open in Excel")
        stop.set()

    t = threading.Thread(
        target=watch,
        args=(tmp_path, on_change),
        kwargs={"settle_seconds": 0.3, "stop": stop, "log": logs.append},
    )
    t.start()
    time.sleep(0.5)
    shutil.copy(REPO_ROOT / "samples" / "inv_001.pdf", tmp_path / "new.pdf")
    t.join(timeout=15)
    stop.set()
    assert len(calls) == 2 and "PermissionError" in logs[0]


def test_watch_reruns_when_a_file_arrives(tmp_path):
    calls = []
    stop = threading.Event()

    def on_change():
        calls.append(sorted(p.name for p in tmp_path.iterdir()))
        if len(calls) == 2:
            stop.set()

    t = threading.Thread(
        target=watch, args=(tmp_path, on_change), kwargs={"settle_seconds": 0.3, "stop": stop}
    )
    t.start()
    time.sleep(0.5)
    shutil.copy(REPO_ROOT / "samples" / "inv_001.pdf", tmp_path / "new.pdf")
    t.join(timeout=15)
    stop.set()
    assert calls[0] == [] and calls[1] == ["new.pdf"]
