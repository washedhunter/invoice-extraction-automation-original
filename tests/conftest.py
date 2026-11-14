from __future__ import annotations

from pathlib import Path

import pytest

from invoice_tool.config import Settings, load_settings
from invoice_tool.gstin import checksum_char
from invoice_tool.schema import ExtractedInvoice, LineItem

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_gstin(state: str, pan: str = "ABCDE1234F", entity: str = "1") -> str:
    first14 = f"{state}{pan}{entity}Z"
    return first14 + checksum_char(first14)


SELLER_MH = make_gstin("27", "AAACT1111K")
BUYER_MH = make_gstin("27", "AAACB2222L")
SELLER_KA = make_gstin("29", "AAACK3333M")


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch):
    """Tests must never call the real API, even if a .env with a real key is present."""
    import google.genai

    def blocked(*_a, **_k):
        raise _NetworkBlocked("real Gemini client created in a test")

    monkeypatch.setattr(google.genai, "Client", blocked)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("invoice_tool.cli.load_dotenv", lambda *_a, **_k: False)


@pytest.fixture
def settings() -> Settings:
    return load_settings(REPO_ROOT / "config")


@pytest.fixture
def clean_invoice() -> ExtractedInvoice:
    """Intra-state invoice where every check passes. 2 x 500 @18% + 1 x 1000 @5%."""
    return ExtractedInvoice(
        document_type="invoice",
        vendor_name="Test Vendor Pvt Ltd",
        vendor_gstin=SELLER_MH,
        buyer_gstin=BUYER_MH,
        invoice_number="TV/2026/001",
        invoice_date="2026-03-10",
        line_items=[
            LineItem(
                description="Item A",
                hsn_sac="4820",
                quantity=2,
                unit_price=500,
                amount=1000,
                gst_rate=18,
            ),
            LineItem(
                description="Item B",
                hsn_sac="4901",
                quantity=1,
                unit_price=1000,
                amount=1000,
                gst_rate=5,
            ),
        ],
        subtotal=2000,
        cgst=115,
        sgst=115,
        igst=None,
        round_off=0,
        total=2230,
        category="Office Supplies",
    )
