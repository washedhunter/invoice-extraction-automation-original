"""The synthetic set must be reproducible, and its planted errors must be exactly what the
validators flag when they are given the ground truth (the "oracle" run, no LLM involved)."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from invoice_tool import duplicates, rules
from invoice_tool.schema import ExtractedInvoice, InvoiceRecord
from invoice_tool.synth.generate import PLAN, generate
from tests.conftest import REPO_ROOT

SAMPLES = REPO_ROOT / "samples"


def oracle(sample_dir: Path, settings) -> dict[str, tuple[list[str], list[str]]]:
    out, records, truth = {}, [], {}
    for p in sorted((sample_dir / "ground_truth").glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        truth[t["file"]] = t
        inv = ExtractedInvoice.model_validate(t["invoice"])
        sha = hashlib.sha256((sample_dir / t["file"]).read_bytes()).hexdigest()
        records.append(
            InvoiceRecord(
                file_name=t["file"],
                file_sha256=sha,
                extracted=inv,
                flags=rules.validate_invoice(inv, settings),
            )
        )
    duplicates.find_duplicates(records, settings.near_duplicate_days)
    for r in records:
        out[r.file_name] = (truth[r.file_name]["expected_flags"], r.flag_codes)
    return out


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    d = tmp_path_factory.mktemp("synth")
    generate(d, seed=7)
    return d


def test_generates_planned_files(generated):
    files = sorted(p.name for p in generated.iterdir() if p.is_file())
    assert files == sorted(s.file_name for s in PLAN)
    assert len(files) == 30


def test_oracle_flags_match_planted_errors(generated, settings):
    for name, (expected, got) in oracle(generated, settings).items():
        assert got == expected, name


def test_committed_samples_match_their_ground_truth(settings):
    for name, (expected, got) in oracle(SAMPLES, settings).items():
        assert got == expected, name


def test_plant_coverage():
    counts = Counter(s.plant or s.dup_kind for s in PLAN)
    assert counts[None] == 15  # clean documents
    for plant in ["line_sum", "total", "tax_type", "bad_gstin", "rate_date"]:
        assert counts[plant] == 2
    assert counts["cgst_sgst"] == counts["missing_number"] == 1
    assert counts["exact"] == counts["reissue"] == counts["near"] == 1
    assert sum(1 for s in PLAN if s.form != "pdf") >= 8  # scanned-looking documents


def test_ground_truth_is_deterministic(generated, tmp_path):
    generate(tmp_path, seed=7)
    for p in (generated / "ground_truth").glob("*.json"):
        assert p.read_text(encoding="utf-8") == (tmp_path / "ground_truth" / p.name).read_text(
            encoding="utf-8"
        )
    # text PDFs are byte-identical (reportlab invariant mode), so cached hashes stay valid
    for p in generated.glob("inv_*.pdf"):
        assert p.read_bytes() == (tmp_path / p.name).read_bytes()


def test_exact_duplicate_is_byte_identical(generated):
    assert (generated / "inv_030.pdf").read_bytes() == (generated / "inv_005.pdf").read_bytes()
