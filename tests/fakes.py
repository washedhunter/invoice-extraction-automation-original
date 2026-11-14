"""Test doubles: no network calls anywhere in the test suite."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from invoice_tool.extractor import QuotaExhausted
from invoice_tool.schema import ExtractedInvoice


class FakeModels:
    """Stands in for genai.Client().models. Pops scripted outcomes in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


class TruthExtractor:
    """Returns the ground truth for each sample file, like a perfect model would."""

    def __init__(self, truth_dir: Path, model: str = "fake-model", quota_after: int | None = None):
        self.model = model
        self.calls = 0
        self.quota_after = quota_after
        self.truth = {}
        for p in Path(truth_dir).glob("*.json"):
            t = json.loads(p.read_text(encoding="utf-8"))
            self.truth[t["file"]] = t["invoice"]

    def extract(self, path: Path, data: bytes | None = None):
        if self.quota_after is not None and self.calls >= self.quota_after:
            raise QuotaExhausted("RPD exhausted")
        self.calls += 1
        inv = ExtractedInvoice.model_validate(self.truth[Path(path).name])
        return inv, inv.model_dump_json()
