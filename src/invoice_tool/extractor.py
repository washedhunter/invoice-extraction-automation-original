"""Gemini extraction adapter: the only module that talks to the Gemini API.

One request per document: the file bytes (PDF, JPG or PNG) plus instructions, with a JSON schema
for structured output. The response is re-validated with Pydantic, because the API ignores some
schema constraints.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from invoice_tool.schema import ExtractedInvoice, gemini_response_schema

PROMPT_VERSION = "v1"
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

PROMPT = """\
Transcribe this Indian GST tax invoice or shop receipt into the JSON schema.

Rules:
- Copy values exactly as printed. Do NOT correct, recompute or fill in amounts, even if they look
  wrong: totals and taxes are cross-checked later, so a wrong printed value must stay wrong.
- Amounts are plain numbers: no currency symbols (Rs., INR, ₹) and no thousands separators.
  A negative round-off stays negative.
- invoice_date must be YYYY-MM-DD. Indian dates put the day first (05/07/2025 is 5 July 2025).
  Two-digit years mean 20xx.
- vendor = the seller who issued the document. buyer_gstin = the billed-to party's GSTIN.
- line_items: one entry per item row. amount = the row's taxable value before GST.
  gst_rate = the total GST percent for that row (CGST% + SGST%, or IGST%). If the rate is only
  printed in the tax lines (e.g. "CGST @ 2.5%" and "SGST @ 2.5%"), use the combined rate (5).
- cgst, sgst, igst = the total amounts of each tax for the whole document, or null if that tax
  is not charged.
- If a field is not printed, use null. Never invent invoice numbers or GSTINs.
- category: pick the closest match from the allowed values.
"""


class ExtractionError(Exception):
    """The document could not be turned into a valid ExtractedInvoice."""


class QuotaExhausted(Exception):
    """The daily request quota is used up; retrying today will not help."""


def _error_payload(exc: Exception) -> str:
    details = getattr(exc, "details", None)
    try:
        return json.dumps(details) if details is not None else str(exc)
    except TypeError:
        return str(exc)


def is_daily_quota(exc: Exception) -> bool:
    return (
        getattr(exc, "code", None) == 429
        and re.search(r"per ?day|PerDay", _error_payload(exc), re.IGNORECASE) is not None
    )


def is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if not isinstance(code, int) or is_daily_quota(exc):
        return False
    return code == 429 or code >= 500


def retry_delay_hint(exc: Exception) -> float | None:
    """Seconds from the server's RetryInfo ("retryDelay": "37s"), if any."""
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', _error_payload(exc))
    return float(m.group(1)) if m else None


class GeminiExtractor:
    def __init__(
        self,
        model: str,
        categories: list[str],
        *,
        client: Any = None,
        api_key: str | None = None,
        max_retries: int = 6,
        initial_backoff: float = 4.0,
        max_backoff: float = 90.0,
        timeout_seconds: float = 180.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model = model
        self.categories = categories
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self._sleep = sleep
        self._schema = gemini_response_schema(categories)
        self._client = client or self._make_client(api_key, timeout_seconds)

    @staticmethod
    def _make_client(api_key: str | None, timeout_seconds: float) -> Any:
        from google import genai
        from google.genai import types

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ExtractionError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key, "
                "or use --replay samples/recorded to run on recorded responses."
            )
        return genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),  # we retry ourselves
            ),
        )

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        hint = retry_delay_hint(exc) if exc else None
        backoff = self.initial_backoff * 2 ** (state.attempt_number - 1)
        delay = hint + 1.0 if hint is not None else backoff + random.uniform(0, 1)
        return min(delay, self.max_backoff)

    def _call(self, data: bytes, mime_type: str) -> Any:
        from google.genai import types

        return self._client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=data, mime_type=mime_type), PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=self._schema,
            ),
        )

    def extract(self, path: Path, data: bytes | None = None) -> tuple[ExtractedInvoice, str]:
        """Return the parsed invoice and the raw JSON text from the model."""
        path = Path(path)
        mime = MIME_TYPES.get(path.suffix.lower())
        if mime is None:
            raise ExtractionError(f"unsupported file type: {path.suffix}")
        data = path.read_bytes() if data is None else data

        retrying = Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=self._wait,
            retry=retry_if_exception(is_retryable),
            sleep=self._sleep,
            reraise=True,
        )
        try:
            response = retrying(self._call, data, mime)
        except Exception as exc:
            if is_daily_quota(exc):
                raise QuotaExhausted(str(exc)) from exc
            raise ExtractionError(f"Gemini request failed: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            raise ExtractionError("Gemini returned no text (blocked or empty response)")
        try:
            invoice = ExtractedInvoice.model_validate_json(text)
        except ValidationError as exc:
            raise ExtractionError(f"response did not match the schema: {exc}") from exc
        if invoice.category not in self.categories:
            invoice.category = "Other" if "Other" in self.categories else self.categories[-1]
        return invoice, text
