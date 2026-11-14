from datetime import date

import pytest

from invoice_tool import rules
from invoice_tool.schema import LineItem
from tests.conftest import SELLER_KA


def codes(inv, settings):
    return sorted({f.code for f in rules.validate_invoice(inv, settings)})


def test_clean_invoice_has_no_flags(clean_invoice, settings):
    assert codes(clean_invoice, settings) == []


def test_line_sum_mismatch(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"subtotal": 2100, "total": 2330})
    assert codes(inv, settings) == [rules.LINE_SUM_MISMATCH]


def test_total_mismatch(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"total": 2330})
    assert codes(inv, settings) == [rules.TOTAL_MISMATCH]


def test_total_within_tolerance_is_ok(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"total": 2230.6})
    assert codes(inv, settings) == []


def test_round_off_is_counted(clean_invoice, settings):
    inv = clean_invoice.model_copy(
        update={"cgst": 115.4, "sgst": 115.4, "round_off": 0.2, "total": 2231}
    )
    # 2000 + 230.8 + 0.2 = 2231; tax 230.8 vs expected 230 is within ₹1
    assert codes(inv, settings) == []


def test_cgst_sgst_unequal(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"cgst": 165, "sgst": 65})
    assert codes(inv, settings) == [rules.CGST_SGST_UNEQUAL]


def test_tax_amount_mismatch(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"cgst": 165, "sgst": 165, "total": 2330})
    assert codes(inv, settings) == [rules.TAX_AMOUNT_MISMATCH]


def test_intra_state_with_igst(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"cgst": None, "sgst": None, "igst": 230})
    assert codes(inv, settings) == [rules.TAX_TYPE_MISMATCH]


def test_inter_state_with_cgst_sgst(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"vendor_gstin": SELLER_KA})
    assert codes(inv, settings) == [rules.TAX_TYPE_MISMATCH]


def test_inter_state_with_igst_is_ok(clean_invoice, settings):
    inv = clean_invoice.model_copy(
        update={"vendor_gstin": SELLER_KA, "cgst": None, "sgst": None, "igst": 230}
    )
    assert codes(inv, settings) == []


def test_both_igst_and_cgst(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"igst": 10, "cgst": 110, "sgst": 110})
    assert rules.TAX_TYPE_MISMATCH in codes(inv, settings)


def test_tax_type_needs_both_gstins(clean_invoice, settings):
    inv = clean_invoice.model_copy(
        update={"buyer_gstin": None, "cgst": None, "sgst": None, "igst": 230}
    )
    assert rules.TAX_TYPE_MISMATCH not in codes(inv, settings)


def test_invalid_vendor_gstin(clean_invoice, settings):
    g = clean_invoice.vendor_gstin
    bad = g[:14] + ("A" if g[14] != "A" else "B")
    inv = clean_invoice.model_copy(update={"vendor_gstin": bad})
    flags = rules.validate_invoice(inv, settings)
    assert [f.code for f in flags] == [rules.GSTIN_INVALID]
    assert "Vendor" in flags[0].detail and "checksum" in flags[0].detail


def test_twelve_percent_after_gst_2_0(clean_invoice, settings):
    items = [LineItem(description="X", quantity=1, unit_price=1000, amount=1000, gst_rate=12)]
    inv = clean_invoice.model_copy(
        update={
            "invoice_date": "2025-10-01",
            "line_items": items,
            "subtotal": 1000,
            "cgst": 60,
            "sgst": 60,
            "total": 1120,
        }
    )
    assert codes(inv, settings) == [rules.GST_RATE_INVALID_FOR_DATE]


def test_twelve_percent_before_gst_2_0_is_ok(clean_invoice, settings):
    items = [LineItem(description="X", quantity=1, unit_price=1000, amount=1000, gst_rate=12)]
    inv = clean_invoice.model_copy(
        update={
            "invoice_date": "2025-09-21",
            "line_items": items,
            "subtotal": 1000,
            "cgst": 60,
            "sgst": 60,
            "total": 1120,
        }
    )
    assert codes(inv, settings) == []


@pytest.mark.parametrize(
    "d, rate, ok",
    [
        (date(2025, 9, 21), 28, True),
        (date(2025, 9, 22), 28, False),
        (date(2025, 9, 22), 40, True),
        (date(2025, 9, 21), 40, False),
        (date(2026, 1, 1), 5, True),
    ],
)
def test_rate_table_boundaries(settings, d, rate, ok):
    assert (rate in settings.valid_rates_on(d)) is ok


def test_missing_fields_invoice(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"invoice_number": None, "vendor_gstin": " "})
    flags = rules.validate_invoice(inv, settings)
    missing = [f for f in flags if f.code == rules.MISSING_FIELD]
    assert len(missing) == 1
    assert "invoice_number" in missing[0].detail and "vendor_gstin" in missing[0].detail


def test_receipt_does_not_need_gstin_or_number(clean_invoice, settings):
    inv = clean_invoice.model_copy(
        update={
            "document_type": "receipt",
            "invoice_number": None,
            "vendor_gstin": None,
            "buyer_gstin": None,
        }
    )
    assert codes(inv, settings) == []


def test_bad_date_reported(clean_invoice, settings):
    inv = clean_invoice.model_copy(update={"invoice_date": "10/03/2026"})
    flags = rules.validate_invoice(inv, settings)
    assert [f.code for f in flags] == [rules.MISSING_FIELD]
    assert "ISO" in flags[0].detail
