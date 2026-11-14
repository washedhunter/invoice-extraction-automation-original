"""Monthly spending summaries (pandas)."""

from __future__ import annotations

import pandas as pd

from invoice_tool.duplicates import DUP_EXACT, DUP_INVOICE_NO, DUP_NEAR
from invoice_tool.schema import InvoiceRecord

DUPLICATE_CODES = {DUP_EXACT, DUP_INVOICE_NO, DUP_NEAR}


def spend_frame(records: list[InvoiceRecord]) -> pd.DataFrame:
    """One row per countable document: extracted, dated, with a total, and not a duplicate."""
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
                "vendor": inv.vendor_name or "(unknown vendor)",
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
