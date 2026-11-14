"""Data models.

`ExtractedInvoice` is both the structured-output schema sent to Gemini and the shape of the
ground-truth JSON produced by the synthetic generator, so the two can be compared field by field.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(description="Item or service description exactly as printed.")
    hsn_sac: str | None = Field(
        default=None, description="HSN (goods) or SAC (services) code as printed, else null."
    )
    quantity: float | None = Field(default=None, description="Quantity as printed.")
    unit_price: float | None = Field(
        default=None, description="Price per unit before GST, as printed."
    )
    amount: float | None = Field(
        default=None, description="Taxable value of this line before GST, as printed."
    )
    gst_rate: float | None = Field(
        default=None,
        description="Total GST rate for this line in percent (e.g. 18 for 9% CGST + 9% SGST).",
    )


class ExtractedInvoice(BaseModel):
    document_type: Literal["invoice", "receipt"] = Field(
        description=(
            "'receipt' for a point-of-sale bill (thermal/till slip, cash memo, restaurant, cafe, "
            "cab or shop bill), even if headed 'TAX INVOICE'; 'invoice' for a full-page business "
            "invoice with a billed-to party"
        )
    )
    vendor_name: str | None = Field(default=None, description="Seller / supplier name.")
    vendor_gstin: str | None = Field(
        default=None, description="Seller's 15-character GSTIN exactly as printed, else null."
    )
    buyer_gstin: str | None = Field(
        default=None, description="Buyer's (billed-to) GSTIN exactly as printed, else null."
    )
    invoice_number: str | None = Field(
        default=None, description="Invoice / bill number as printed, else null."
    )
    invoice_date: str | None = Field(
        default=None, description="Invoice date converted to ISO format YYYY-MM-DD."
    )
    currency: str = Field(default="INR", description="ISO 4217 currency code, usually INR.")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = Field(
        default=None, description="Printed taxable value / subtotal before GST."
    )
    cgst: float | None = Field(default=None, description="Total CGST amount printed, else null.")
    sgst: float | None = Field(
        default=None, description="Total SGST / UTGST amount printed, else null."
    )
    igst: float | None = Field(default=None, description="Total IGST amount printed, else null.")
    round_off: float | None = Field(
        default=None, description="Round-off adjustment printed (may be negative), else null."
    )
    total: float | None = Field(default=None, description="Grand total payable, as printed.")
    category: str = Field(description="Spending category, chosen from the allowed list.")

    def parsed_date(self) -> date | None:
        if not self.invoice_date:
            return None
        try:
            return date.fromisoformat(self.invoice_date.strip())
        except ValueError:
            return None


def gemini_response_schema(categories: list[str]) -> dict[str, Any]:
    """JSON schema for Gemini structured output, with the category list as an enum."""
    schema = copy.deepcopy(ExtractedInvoice.model_json_schema())
    schema["properties"]["category"]["enum"] = list(categories)
    return schema


class Flag(BaseModel):
    code: str
    detail: str
    related_file: str | None = None


class InvoiceRecord(BaseModel):
    """One processed input file."""

    file_name: str
    file_sha256: str
    extracted: ExtractedInvoice | None = None
    error: str | None = None
    flags: list[Flag] = Field(default_factory=list)

    @property
    def flag_codes(self) -> list[str]:
        return sorted({f.code for f in self.flags})

    @property
    def needs_review(self) -> bool:
        return bool(self.flags)
