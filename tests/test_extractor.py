import pytest
from google.genai import errors

from invoice_tool.extractor import (
    PROMPT,
    ExtractionError,
    GeminiExtractor,
    QuotaExhausted,
    is_daily_quota,
    retry_delay_hint,
)
from tests.fakes import FakeClient

CATEGORIES = ["Office Supplies", "Travel", "Other"]


def rate_limit(delay="7s", quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier"):
    return errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "You exceeded your current quota",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id}],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
                ],
            }
        },
    )


def make(outcomes, **kw):
    sleeps = []
    ex = GeminiExtractor(
        "gemini-test", CATEGORIES, client=FakeClient(outcomes), sleep=sleeps.append, **kw
    )
    return ex, sleeps


def good_json(clean_invoice, **update):
    return clean_invoice.model_copy(update=update).model_dump_json()


def test_sends_file_bytes_schema_and_prompt(tmp_path, clean_invoice):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    ex, _ = make([good_json(clean_invoice, category="Office Supplies")])
    inv, raw = ex.extract(pdf)
    assert inv.total == 2230 and raw.startswith("{")
    call = ex._client.models.calls[0]
    assert call["model"] == "gemini-test"
    part, prompt = call["contents"]
    assert part.inline_data.mime_type == "application/pdf"
    assert part.inline_data.data == b"%PDF-1.4 fake"
    assert prompt == PROMPT
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema["properties"]["category"]["enum"] == CATEGORIES


@pytest.mark.parametrize("name, mime", [("r.jpg", "image/jpeg"), ("r.PNG", "image/png")])
def test_image_mime_types(tmp_path, clean_invoice, name, mime):
    f = tmp_path / name
    f.write_bytes(b"img")
    ex, _ = make([good_json(clean_invoice, category="Travel")])
    ex.extract(f)
    assert ex._client.models.calls[0]["contents"][0].inline_data.mime_type == mime


def test_unsupported_type(tmp_path):
    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    ex, _ = make([])
    with pytest.raises(ExtractionError, match="unsupported"):
        ex.extract(f)


def test_retries_rate_limit_using_server_delay(tmp_path, clean_invoice):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, sleeps = make(
        [rate_limit("7s"), rate_limit("3s"), good_json(clean_invoice, category="Other")]
    )
    inv, _ = ex.extract(f)
    assert inv.vendor_name == "Test Vendor Pvt Ltd"
    assert sleeps == [8.0, 4.0]  # server hint + 1s


def test_server_retry_hint_is_not_capped(tmp_path, clean_invoice):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    outcomes = [rate_limit("120s"), good_json(clean_invoice, category="Other")]
    ex, sleeps = make(outcomes, max_backoff=90)
    ex.extract(f)
    assert sleeps == [121.0]


def test_retries_server_errors_with_backoff(tmp_path, clean_invoice):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    err = errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})
    ex, sleeps = make(
        [err, err, good_json(clean_invoice, category="Other")], initial_backoff=2, max_backoff=90
    )
    ex.extract(f)
    assert len(sleeps) == 2
    assert 2 <= sleeps[0] < 3 and 4 <= sleeps[1] < 5


def test_gives_up_after_max_attempts(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, sleeps = make([rate_limit()] * 3, max_attempts=3)
    with pytest.raises(ExtractionError, match="request failed"):
        ex.extract(f)
    assert len(sleeps) == 2


def test_daily_quota_stops_immediately(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, sleeps = make([rate_limit("40s", "GenerateRequestsPerDayPerProjectPerModel-FreeTier")])
    with pytest.raises(QuotaExhausted):
        ex.extract(f)
    assert sleeps == []


def test_client_errors_are_not_retried(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    bad = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
    ex, sleeps = make([bad])
    with pytest.raises(ExtractionError):
        ex.extract(f)
    assert sleeps == []


def test_invalid_json_is_an_extraction_error(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, _ = make(['{"vendor_name": "x"}'])  # missing required document_type/category
    with pytest.raises(ExtractionError, match="schema"):
        ex.extract(f)


def test_empty_response(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, _ = make([""])
    with pytest.raises(ExtractionError, match="no text"):
        ex.extract(f)


def test_unknown_category_becomes_other(tmp_path, clean_invoice):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    ex, _ = make([good_json(clean_invoice, category="Snacks")])
    inv, _ = ex.extract(f)
    assert inv.category == "Other"


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ExtractionError, match="GEMINI_API_KEY"):
        GeminiExtractor("m", CATEGORIES)


def test_error_helpers():
    assert retry_delay_hint(rate_limit("12s")) == 12.0
    assert not is_daily_quota(rate_limit())
    assert is_daily_quota(rate_limit(quota_id="GenerateRequestsPerDayPerProjectPerModel"))
