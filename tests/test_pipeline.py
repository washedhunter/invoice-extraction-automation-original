"""End-to-end over the committed samples with a perfect fake extractor (no network)."""

import json
import shutil

import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from invoice_tool import evaluate
from invoice_tool.cache import ExtractionCache, cache_version
from invoice_tool.cli import EXIT_MISSING_RECORDING, EXIT_QUOTA, app
from invoice_tool.excel import write_workbook
from invoice_tool.extractor import PROMPT_VERSION
from invoice_tool.pipeline import run, write_json
from tests.conftest import REPO_ROOT
from tests.fakes import TruthExtractor

SAMPLES = REPO_ROOT / "samples"
TRUTH = SAMPLES / "ground_truth"


@pytest.fixture
def inbox(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    for p in SAMPLES.iterdir():
        if p.is_file():
            shutil.copy(p, d / p.name)
    return d


@pytest.fixture
def cache(tmp_path):
    return ExtractionCache(tmp_path / "cache", PROMPT_VERSION)


def test_full_run_matches_planted_flags(inbox, cache, settings):
    ex = TruthExtractor(TRUTH)
    result = run(inbox, settings, cache, ex)
    assert len(result.records) == 31
    # the exact duplicate is served from the cache, not sent to the API again
    assert ex.calls == 30 and result.live_calls == 30 and result.cache_hits == 1
    truth = {
        json.loads(p.read_text())["file"]: json.loads(p.read_text()) for p in TRUTH.glob("*.json")
    }
    for r in result.records:
        assert r.flag_codes == truth[r.file_name]["expected_flags"], r.file_name


def test_rerun_uses_cache_only(inbox, cache, settings):
    run(inbox, settings, cache, TruthExtractor(TRUTH))
    ex2 = TruthExtractor(TRUTH)
    result = run(inbox, settings, cache, ex2)
    assert ex2.calls == 0 and result.cache_hits == 31


def test_quota_stops_and_resumes(inbox, cache, settings):
    first = run(inbox, settings, cache, TruthExtractor(TRUTH, quota_after=10))
    assert first.quota_reached and len(first.records) + len(first.pending) == 31
    second = run(inbox, settings, cache, TruthExtractor(TRUTH))
    assert not second.quota_reached and len(second.records) == 31


def test_replay_missing_response_is_flagged(inbox, tmp_path, settings):
    empty = ExtractionCache(tmp_path / "nothing", PROMPT_VERSION, read_only=True)
    result = run(inbox, settings, empty, None, replay=True)
    codes = {r.file_name: r.flag_codes for r in result.records}
    assert len(codes) == 31
    assert codes.pop("inv_030.pdf") == ["DUP_EXACT", "EXTRACTION_FAILED"]  # byte copy still found
    assert all(c == ["EXTRACTION_FAILED"] for c in codes.values())


def test_workbook_structure(inbox, cache, settings, tmp_path):
    result = run(inbox, settings, cache, TruthExtractor(TRUTH))
    out = write_workbook(result.records, tmp_path / "out.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames == ["Invoices", "Line Items", "Flags for Review", "Monthly Summary"]
    inv = wb["Invoices"]
    assert inv.max_row == 32 and inv.freeze_panes == "A2" and inv.auto_filter.ref
    headers = [c.value for c in inv[1]]
    assert headers[:3] == ["File", "Status", "Flags"]
    total_col = headers.index("Total") + 1
    date_col = headers.index("Invoice Date") + 1
    assert inv.cell(2, total_col).number_format == '"₹"#,##0.00'
    assert inv.cell(2, date_col).number_format == "dd-mmm-yyyy"
    rules = [r for cf in inv.conditional_formatting for r in cf.rules]
    assert any('"Review"' in r.formula[0] for r in rules)
    statuses = [inv.cell(r, 2).value for r in range(2, 33)]
    assert statuses.count("Review") == 15 and statuses.count("OK") == 16
    li = wb["Line Items"]
    li_headers = [c.value for c in li[1]]
    assert li.cell(2, li_headers.index("Qty") + 1).number_format == "General"
    assert li.cell(2, li_headers.index("GST %") + 1).number_format == 'General"%"'

    flags = wb["Flags for Review"]
    assert flags.max_row == 16  # 15 planted issues, one flag each
    assert flags.freeze_panes == "A2"
    assert sum(1 for _ in wb["Line Items"].iter_rows(min_row=2)) == sum(
        len(r.extracted.line_items) for r in result.records
    )
    summary = wb["Monthly Summary"]
    assert len(summary._charts) == 1
    assert summary["A4"].value is not None  # vendor table starts


def test_summary_excludes_duplicates(inbox, cache, settings):
    from invoice_tool.summary import monthly_summaries

    result = run(inbox, settings, cache, TruthExtractor(TRUTH))
    by_vendor, by_category = monthly_summaries(result.records)
    countable = [r for r in result.records if not any(c.startswith("DUP_") for c in r.flag_codes)]
    expected = sum(r.extracted.total for r in countable)
    assert by_vendor.loc["Total", "Total"] == pytest.approx(expected)
    assert by_category.loc["Total", "Total"] == pytest.approx(expected)


def test_vendor_spellings_are_merged(clean_invoice):
    from invoice_tool.schema import InvoiceRecord
    from invoice_tool.summary import monthly_summaries, vendor_labels

    a = InvoiceRecord(file_name="a.pdf", file_sha256="1", extracted=clean_invoice)
    upper = clean_invoice.model_copy(
        update={"vendor_name": "TEST VENDOR PVT. LTD.", "invoice_number": "X2", "total": 999}
    )
    b = InvoiceRecord(file_name="b.pdf", file_sha256="2", extracted=upper)
    bad_gstin = clean_invoice.model_copy(
        update={"vendor_gstin": "27AAAAA0000A1ZZ", "invoice_number": "X3", "total": 5}
    )
    c = InvoiceRecord(file_name="c.pdf", file_sha256="3", extracted=bad_gstin)
    labels = vendor_labels([a, b, c])
    assert set(labels.values()) == {"Test Vendor Pvt Ltd"}
    by_vendor, _ = monthly_summaries([a, b, c])
    assert list(by_vendor.index) == ["Test Vendor Pvt Ltd", "Total"]


def test_evaluation_of_perfect_run(inbox, cache, settings, tmp_path):
    result = run(inbox, settings, cache, TruthExtractor(TRUTH))
    path = write_json(result, tmp_path / "r.json", inbox)
    rep = evaluate.evaluate(json.loads(path.read_text(encoding="utf-8")), TRUTH)
    assert rep.processed == 31 and not rep.misses and not rep.false_alarms
    assert all(t.pct == 100 for t in rep.fields["all"].values())
    md = evaluate.to_markdown(rep)
    assert "| **All** | 15 | 15 | 0 | 100% | 100% |" in md


def test_evaluation_counts_a_wrong_field(inbox, cache, settings, tmp_path):
    result = run(inbox, settings, cache, TruthExtractor(TRUTH))
    data = json.loads(write_json(result, tmp_path / "r.json", inbox).read_text(encoding="utf-8"))
    rec = next(r for r in data["records"] if r["file_name"] == "inv_008.pdf")
    rec["extracted"]["total"] -= 1000  # model "fixed" the planted total error
    rec["flags"] = []
    rep = evaluate.evaluate(data, TRUTH)
    assert rep.fields["all"]["total"].correct == 30
    assert rep.flag_fn["TOTAL_MISMATCH"] == 1
    assert "inv_008.pdf: expected TOTAL_MISMATCH" in rep.misses[0]
    assert "total" in rep.misses[0]


def _record_responses(inbox, folder, settings):
    rec_cache = ExtractionCache(folder, cache_version(PROMPT_VERSION, settings.categories))
    run(inbox, settings, rec_cache, TruthExtractor(TRUTH))


def test_cli_replay(inbox, tmp_path, settings, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    recorded = tmp_path / "recorded"
    _record_responses(inbox, recorded, settings)
    out, js = tmp_path / "o.xlsx", tmp_path / "o.json"
    res = CliRunner().invoke(
        app,
        [
            "process",
            str(inbox),
            "--out",
            str(out),
            "--replay",
            str(recorded),
            "--json-out",
            str(js),
        ],
    )
    assert res.exit_code == 0, res.output
    assert out.exists() and json.loads(js.read_text(encoding="utf-8"))["cache_hits"] == 31
    assert "needs review 15" in res.output


def test_cli_without_key(inbox, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("INVOICE_CONFIG_DIR", str(REPO_ROOT / "config"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res = CliRunner().invoke(app, ["process", str(inbox), "--out", str(tmp_path / "o.xlsx")])
    assert res.exit_code == 2
    assert "GEMINI_API_KEY" in res.output


def test_cli_quota_exit_code(inbox, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INVOICE_CONFIG_DIR", str(REPO_ROOT / "config"))
    monkeypatch.setenv("INVOICE_CACHE_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(
        "invoice_tool.cli.GeminiExtractor",
        lambda *a, **k: TruthExtractor(TRUTH, quota_after=5),
    )
    res = CliRunner().invoke(app, ["process", str(inbox), "--out", str(tmp_path / "o.xlsx")])
    assert res.exit_code == EXIT_QUOTA
    assert "Daily Gemini quota reached" in res.output


def test_cli_replay_fails_when_a_recording_is_missing(inbox, tmp_path, settings, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    recorded = tmp_path / "recorded"
    _record_responses(inbox, recorded, settings)
    (inbox / "new.pdf").write_bytes(b"%PDF-1.4 not recorded")
    res = CliRunner().invoke(
        app, ["process", str(inbox), "--out", str(tmp_path / "o.xlsx"), "--replay", str(recorded)]
    )
    assert res.exit_code == EXIT_MISSING_RECORDING
    assert "1 file(s) have no recorded response: new.pdf" in res.output


def test_eval_strict_exit_code(inbox, cache, settings, tmp_path):
    result = run(inbox, settings, cache, TruthExtractor(TRUTH))
    path = write_json(result, tmp_path / "r.json", inbox)
    evaluate.main(["--results", str(path), "--truth", str(TRUTH), "--strict"])  # perfect: no exit
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][0]["flags"].append({"code": "TOTAL_MISMATCH", "detail": "x"})
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        evaluate.main(["--results", str(path), "--truth", str(TRUTH), "--strict"])
    assert e.value.code == 1


def test_cached_category_outside_current_list_becomes_other(inbox, cache, settings):
    run(inbox, settings, cache, TruthExtractor(TRUTH))
    narrowed = settings.model_copy(update={"categories": ["Travel", "Other"]})
    result = run(inbox, narrowed, cache, TruthExtractor(TRUTH))
    assert {r.extracted.category for r in result.records} == {"Travel", "Other"}


def test_cache_version_depends_on_categories():
    assert cache_version("v2", ["A", "B"]) != cache_version("v2", ["A", "C"])
    assert cache_version("v2", ["A", "B"]).startswith("v2-")
