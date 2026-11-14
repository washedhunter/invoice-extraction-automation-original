"""On-disk cache of extraction results, keyed by file SHA-256 + model + prompt version.

Re-running on the same files never calls (or bills) the API again. A recorded-responses folder
(samples/recorded) is the same format, used read-only with --replay.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _safe(model: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in model)


class ExtractionCache:
    def __init__(self, root: Path, prompt_version: str, read_only: bool = False):
        self.root = Path(root)
        self.prompt_version = prompt_version
        self.read_only = read_only

    def _path(self, sha256: str, model: str) -> Path:
        return self.root / f"{sha256}__{_safe(model)}__{self.prompt_version}.json"

    def get(self, sha256: str, model: str) -> dict[str, Any] | None:
        p = self._path(sha256, model)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def get_any_model(self, sha256: str) -> dict[str, Any] | None:
        """Replay mode: use whatever model the response was recorded with."""
        matches = sorted(self.root.glob(f"{sha256}__*.json"))
        if not matches:
            return None
        return json.loads(matches[-1].read_text(encoding="utf-8"))

    def put(
        self,
        sha256: str,
        model: str,
        source_file: str,
        extracted: dict[str, Any],
        raw_response: str,
    ) -> None:
        if self.read_only:
            raise RuntimeError("cache is read-only")
        self.root.mkdir(parents=True, exist_ok=True)
        entry = {
            "sha256": sha256,
            "model": model,
            "prompt_version": self.prompt_version,
            "source_file": source_file,
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "raw_response": raw_response,
            "extracted": extracted,
        }
        self._path(sha256, model).write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
