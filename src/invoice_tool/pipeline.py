"""Process a folder: extract (or reuse cached results), validate, find duplicates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from invoice_tool.cache import ExtractionCache
from invoice_tool.config import Settings
from invoice_tool.duplicates import find_duplicates
from invoice_tool.extractor import ExtractionError, QuotaExhausted
from invoice_tool.rules import EXTRACTION_FAILED, validate_invoice
from invoice_tool.schema import ExtractedInvoice, Flag, InvoiceRecord

SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}


class Extractor(Protocol):  # GeminiExtractor or a test fake
    model: str

    def extract(self, path: Path, data: bytes | None = None) -> tuple[ExtractedInvoice, str]: ...


@dataclass
class RunResult:
    records: list[InvoiceRecord]
    pending: list[str] = field(default_factory=list)  # not processed (daily quota reached)
    live_calls: int = 0
    cache_hits: int = 0
    models: set[str] = field(default_factory=set)

    @property
    def quota_reached(self) -> bool:
        return bool(self.pending)


def discover(input_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in Path(input_dir).iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _failed(name: str, sha: str, message: str) -> InvoiceRecord:
    return InvoiceRecord(
        file_name=name,
        file_sha256=sha,
        error=message,
        flags=[Flag(code=EXTRACTION_FAILED, detail=message)],
    )


def run(
    input_dir: Path,
    settings: Settings,
    cache: ExtractionCache,
    extractor: Extractor | None = None,
    replay: bool = False,
    log: Callable[[str], None] = lambda _msg: None,
) -> RunResult:
    files = discover(input_dir)
    result = RunResult(records=[])
    quota_hit = False
    model = extractor.model if extractor is not None else settings.model
    for i, path in enumerate(files, 1):
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        entry = cache.get_any_model(sha) if replay else cache.get(sha, model)
        if entry is not None:
            invoice = ExtractedInvoice.model_validate(entry["extracted"])
            result.cache_hits += 1
            result.models.add(entry["model"])
            log(f"[{i}/{len(files)}] {path.name}: cached ({entry['model']})")
        elif replay:
            result.records.append(_failed(path.name, sha, "no recorded response for this file"))
            log(f"[{i}/{len(files)}] {path.name}: no recorded response")
            continue
        elif quota_hit or extractor is None:
            result.pending.append(path.name)
            continue
        else:
            try:
                invoice, raw = extractor.extract(path, data)
            except QuotaExhausted:
                quota_hit = True
                result.pending.append(path.name)
                log(f"[{i}/{len(files)}] {path.name}: daily quota reached, stopping API calls")
                continue
            except ExtractionError as exc:
                result.records.append(_failed(path.name, sha, str(exc)))
                log(f"[{i}/{len(files)}] {path.name}: FAILED {exc}")
                continue
            cache.put(sha, extractor.model, path.name, invoice.model_dump(mode="json"), raw)
            result.live_calls += 1
            result.models.add(extractor.model)
            log(f"[{i}/{len(files)}] {path.name}: extracted with {extractor.model}")
        record = InvoiceRecord(file_name=path.name, file_sha256=sha, extracted=invoice)
        record.flags = validate_invoice(invoice, settings)
        result.records.append(record)
    find_duplicates(result.records, settings.near_duplicate_days)
    result.records.sort(key=lambda r: r.file_name)
    return result


def write_json(result: RunResult, path: Path, input_dir: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "models": sorted(result.models),
        "live_calls": result.live_calls,
        "cache_hits": result.cache_hits,
        "pending": result.pending,
        "records": [r.model_dump(mode="json") for r in result.records],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return path
