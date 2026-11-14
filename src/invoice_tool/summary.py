"""Monthly spending summaries (pandas)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import pandas as pd

from invoice_tool import gstin
from invoice_tool.duplicates import DUP_EXACT, DUP_INVOICE_NO, DUP_NEAR
from invoice_tool.schema import InvoiceRecord

DUPLICATE_CODES = {DUP_EXACT, DUP_INVOICE_NO, DUP_NEAR}


def _name_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower()) or "unknown"


def vendor_labels(records: list[InvoiceRecord]) -> dict[str, str]:
    """file name -> one display name per vendor.

    The same vendor can appear as "Konkan Cloud Systems LLP" and "KONKAN CLOUD SYSTEMS LLP"
    (different layouts). Documents are grouped by normalised name, and names that share a valid
    GSTIN are merged. The display name is the most common spelling, preferring mixed case.
    """
    by_gstin: dict[str, str] = {}
    keys: dict[str, str] = {}
    for r in records:
        if r.extracted is None:
            continue
        key = _name_key(r.extracted.vendor_name)
        g = gstin.normalise(r.extracted.vendor_gstin)
        if g and gstin.is_valid(g):
            key = by_gstin.setdefault(g, key)
        keys[r.file_name] = key
    spellings: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        if r.file_name in keys:
            spellings[keys[r.file_name]][r.extracted.vendor_name or "(unknown vendor)"] += 1
    display = {
        key: max(names.items(), key=lambda kv: (not kv[0].isupper(), kv[1], kv[0]))[0]
        for key, names in spellings.items()
    }
    return {f: display[k] for f, k in keys.items()}


def spend_frame(records: list[InvoiceRecord]) -> pd.DataFrame:
    """One row per countable document: extracted, dated, with a total, and not a duplicate."""
    labels = vendor_labels(records)
    rows = []
    for r in records:
        inv = r.extracted
        if inv is None or inv.total is None:
            continue
        d = inv.parsed_date()
        if d is None or DUPLICATE_CODES & set(r.flag_codes):
            continue
        rows.append(
            {
                "vendor": labels[r.file_name],
                "category": inv.category,
                "month": f"{d.year:04d}-{d.month:02d}",
                "total": float(inv.total),
            }
        )
    return pd.DataFrame(rows, columns=["vendor", "category", "month", "total"])


def pivot(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """`by` x month table of spend, with a Total column and a Total row."""
    if df.empty:
        return pd.DataFrame()
    table = df.pivot_table(index=by, columns="month", values="total", aggfunc="sum", fill_value=0.0)
    table = table.reindex(sorted(table.columns), axis=1)
    table["Total"] = table.sum(axis=1)
    table = table.sort_values("Total", ascending=False)
    table.loc["Total"] = table.sum(axis=0)
    table.index.name = by.capitalize()
    table.columns.name = None
    return table


def monthly_summaries(records: list[InvoiceRecord]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = spend_frame(records)
    return pivot(df, "vendor"), pivot(df, "category")
