"""Duplicate detection across a batch of processed documents.

Three kinds, strongest first. For each pair only the strongest match is reported, and the flag
goes on the later document (by invoice date, then file name) pointing at the earlier one.
  DUP_EXACT       same file bytes (SHA-256)
  DUP_INVOICE_NO  same vendor GSTIN + invoice number
  DUP_NEAR        same vendor + same total, dates within N days
"""

from __future__ import annotations

import re
from datetime import date

from invoice_tool import gstin
from invoice_tool.schema import Flag, InvoiceRecord

DUP_EXACT = "DUP_EXACT"
DUP_INVOICE_NO = "DUP_INVOICE_NO"
DUP_NEAR = "DUP_NEAR"

DUP_DESCRIPTIONS = {
    DUP_EXACT: "Same file submitted twice",
    DUP_INVOICE_NO: "Same vendor GSTIN and invoice number as another document",
    DUP_NEAR: "Same vendor and total as another document within a few days",
}


def _norm_text(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"[^a-z0-9]", "", s.lower()) or None


def _same_vendor(a: InvoiceRecord, b: InvoiceRecord) -> bool:
    """Compare GSTINs when both documents have one; otherwise compare normalised names."""
    ia, ib = a.extracted, b.extracted
    if ia is None or ib is None:
        return False
    ga, gb = gstin.normalise(ia.vendor_gstin), gstin.normalise(ib.vendor_gstin)
    if ga and gb:
        return ga == gb
    na, nb = _norm_text(ia.vendor_name), _norm_text(ib.vendor_name)
    return bool(na) and na == nb


def _sort_key(r: InvoiceRecord) -> tuple[date, str]:
    d = r.extracted.parsed_date() if r.extracted else None
    return (d or date.max, r.file_name)


def find_duplicates(records: list[InvoiceRecord], near_days: int) -> None:
    """Append duplicate flags to records in place."""
    strength = {DUP_EXACT: 0, DUP_INVOICE_NO: 1, DUP_NEAR: 2}
    ordered = sorted(records, key=_sort_key)
    for i, later in enumerate(ordered):
        best: tuple[int, int, str, str, str] | None = (
            None  # (strength, position, code, detail, file)
        )
        for j, earlier in enumerate(ordered[:i]):
            code, detail = _match(earlier, later, near_days)
            if code:
                candidate = (strength[code], j, code, detail, earlier.file_name)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
        if best:
            # one duplicate flag per document: its strongest match, earliest document on ties
            later.flags.append(Flag(code=best[2], detail=best[3], related_file=best[4]))


def _match(a: InvoiceRecord, b: InvoiceRecord, near_days: int) -> tuple[str | None, str]:
    if a.file_sha256 == b.file_sha256:
        return DUP_EXACT, f"Identical file to {a.file_name}"
    ia, ib = a.extracted, b.extracted
    if ia is None or ib is None:
        return None, ""
    ga, gb = gstin.normalise(ia.vendor_gstin), gstin.normalise(ib.vendor_gstin)
    na, nb = _norm_text(ia.invoice_number), _norm_text(ib.invoice_number)
    if ga and ga == gb and na and na == nb:
        return (
            DUP_INVOICE_NO,
            f"Same GSTIN {ga} and invoice no. {ib.invoice_number} as {a.file_name}",
        )
    da, db = ia.parsed_date(), ib.parsed_date()
    if (
        _same_vendor(a, b)
        and ia.total is not None
        and ib.total is not None
        and abs(ia.total - ib.total) < 0.005
        and da
        and db
        and abs((db - da).days) <= near_days
    ):
        return (
            DUP_NEAR,
            f"Same vendor and total ₹{ib.total:,.2f} as {a.file_name} "
            f"({abs((db - da).days)} days apart)",
        )
    return None, ""
