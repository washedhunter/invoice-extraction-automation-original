"""Deterministic validation rules. Each failure becomes a reason-coded Flag.

The LLM only transcribes; every check here is plain arithmetic or a lookup, so each flag can
be explained and reproduced.
"""

from __future__ import annotations

from collections.abc import Callable

from invoice_tool import gstin
from invoice_tool.config import Settings
from invoice_tool.schema import ExtractedInvoice, Flag

# Reason codes
MISSING_FIELD = "MISSING_FIELD"
LINE_SUM_MISMATCH = "LINE_SUM_MISMATCH"
TOTAL_MISMATCH = "TOTAL_MISMATCH"
TAX_AMOUNT_MISMATCH = "TAX_AMOUNT_MISMATCH"
CGST_SGST_UNEQUAL = "CGST_SGST_UNEQUAL"
TAX_TYPE_MISMATCH = "TAX_TYPE_MISMATCH"
GSTIN_INVALID = "GSTIN_INVALID"
GST_RATE_INVALID_FOR_DATE = "GST_RATE_INVALID_FOR_DATE"
EXTRACTION_FAILED = "EXTRACTION_FAILED"

REASON_DESCRIPTIONS = {
    MISSING_FIELD: "A required field is missing or unreadable",
    LINE_SUM_MISMATCH: "Line items do not add up to the subtotal",
    TOTAL_MISMATCH: "Subtotal + taxes + round-off does not equal the total",
    TAX_AMOUNT_MISMATCH: "GST charged does not match line amounts x GST rates",
    CGST_SGST_UNEQUAL: "CGST and SGST should be equal for an intra-state supply",
    TAX_TYPE_MISMATCH: "Wrong tax type for the supply (IGST vs CGST+SGST)",
    GSTIN_INVALID: "GSTIN fails the format or checksum test",
    GST_RATE_INVALID_FOR_DATE: "GST rate was not a valid slab on the invoice date",
    EXTRACTION_FAILED: "The document could not be read",
}


def _v(x: float | None) -> float:
    return float(x) if x is not None else 0.0


def _money(x: float) -> str:
    return f"₹{x:,.2f}"


def check_required(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    required = (
        s.required_fields_receipt if inv.document_type == "receipt" else s.required_fields_invoice
    )
    missing = []
    for name in required:
        value = getattr(inv, name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(name)
    if inv.invoice_date and inv.parsed_date() is None and "invoice_date" not in missing:
        missing.append("invoice_date (not a valid ISO date)")
    if not inv.line_items:
        missing.append("line_items")
    if missing:
        return [Flag(code=MISSING_FIELD, detail="Missing: " + ", ".join(missing))]
    return []


def check_line_sum(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    amounts = [li.amount for li in inv.line_items]
    if inv.subtotal is None or not amounts or any(a is None for a in amounts):
        return []
    line_sum = sum(_v(a) for a in amounts)
    if abs(line_sum - inv.subtotal) > s.amount_tolerance:
        return [
            Flag(
                code=LINE_SUM_MISMATCH,
                detail=(
                    f"Line items sum to {_money(line_sum)} but subtotal is {_money(inv.subtotal)}"
                ),
            )
        ]
    return []


def check_total(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    if inv.subtotal is None or inv.total is None:
        return []
    expected = inv.subtotal + _v(inv.cgst) + _v(inv.sgst) + _v(inv.igst) + _v(inv.round_off)
    if abs(expected - inv.total) > s.amount_tolerance:
        return [
            Flag(
                code=TOTAL_MISMATCH,
                detail=(
                    f"Subtotal + taxes + round-off = {_money(expected)} "
                    f"but total is {_money(inv.total)}"
                ),
            )
        ]
    return []


def check_tax_amount(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    lines = inv.line_items
    if not lines or any(li.amount is None or li.gst_rate is None for li in lines):
        return []
    expected = sum(_v(li.amount) * _v(li.gst_rate) / 100 for li in lines)
    charged = _v(inv.cgst) + _v(inv.sgst) + _v(inv.igst)
    if abs(expected - charged) > s.amount_tolerance:
        return [
            Flag(
                code=TAX_AMOUNT_MISMATCH,
                detail=(
                    f"GST at line rates = {_money(expected)} but GST charged = {_money(charged)}"
                ),
            )
        ]
    return []


def check_cgst_sgst(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    c, g = _v(inv.cgst), _v(inv.sgst)
    if c == 0 and g == 0:
        return []
    if abs(c - g) > s.amount_tolerance:
        return [
            Flag(
                code=CGST_SGST_UNEQUAL,
                detail=f"CGST {_money(c)} and SGST {_money(g)} should be equal",
            )
        ]
    return []


def check_tax_type(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    has_cs = _v(inv.cgst) > 0 or _v(inv.sgst) > 0
    has_i = _v(inv.igst) > 0
    if has_cs and has_i:
        return [Flag(code=TAX_TYPE_MISMATCH, detail="Both IGST and CGST/SGST charged")]
    seller_state = gstin.state_code(inv.vendor_gstin)
    buyer_state = gstin.state_code(inv.buyer_gstin)
    if not (seller_state and buyer_state):
        return []  # can only decide intra/inter-state when both GSTINs are present
    intra = seller_state == buyer_state
    if intra and has_i:
        return [
            Flag(
                code=TAX_TYPE_MISMATCH,
                detail=f"Intra-state supply (both in state {seller_state}) but IGST charged",
            )
        ]
    if not intra and has_cs:
        return [
            Flag(
                code=TAX_TYPE_MISMATCH,
                detail=(
                    f"Inter-state supply (state {seller_state} to {buyer_state}) "
                    "but CGST/SGST charged"
                ),
            )
        ]
    return []


def check_gstins(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    flags = []
    for label, value in (("Vendor", inv.vendor_gstin), ("Buyer", inv.buyer_gstin)):
        if value is None or not value.strip():
            continue  # absence is handled by check_required
        reason = gstin.validate(value)
        if reason:
            flags.append(Flag(code=GSTIN_INVALID, detail=f"{label} GSTIN {value}: {reason}"))
    return flags


def check_rates(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    d = inv.parsed_date()
    if d is None:
        return []
    valid = s.valid_rates_on(d)
    if valid is None:
        return []
    bad = sorted(
        {
            li.gst_rate
            for li in inv.line_items
            if li.gst_rate is not None and not any(abs(li.gst_rate - r) < 1e-6 for r in valid)
        }
    )
    if bad:
        shown = ", ".join(f"{r:g}%" for r in bad)
        return [
            Flag(
                code=GST_RATE_INVALID_FOR_DATE,
                detail=f"Rate(s) {shown} not a GST slab on {d.isoformat()}",
            )
        ]
    return []


CHECKS: list[Callable[[ExtractedInvoice, Settings], list[Flag]]] = [
    check_required,
    check_line_sum,
    check_total,
    check_tax_amount,
    check_cgst_sgst,
    check_tax_type,
    check_gstins,
    check_rates,
]


def validate_invoice(inv: ExtractedInvoice, s: Settings) -> list[Flag]:
    flags: list[Flag] = []
    for check in CHECKS:
        flags.extend(check(inv, s))
    return flags
