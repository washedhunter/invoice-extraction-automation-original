"""Write the review workbook with openpyxl.

Sheets: Invoices, Line Items, Flags for Review, Monthly Summary.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from invoice_tool.duplicates import DUP_DESCRIPTIONS
from invoice_tool.rules import REASON_DESCRIPTIONS
from invoice_tool.schema import InvoiceRecord
from invoice_tool.summary import monthly_summaries

MONEY = '"₹"#,##0.00'
DATE = "dd-mmm-yyyy"
PCT = '0.##"%"'
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
REVIEW_FILL = PatternFill(bgColor="F8D7DA")  # conditional formats use bgColor
FAILED_FILL = PatternFill(bgColor="F1A9A0")
ALL_REASONS = {**REASON_DESCRIPTIONS, **DUP_DESCRIPTIONS}

INVOICE_COLUMNS = [
    ("File", 16, None),
    ("Status", 9, None),
    ("Flags", 34, None),
    ("Type", 9, None),
    ("Vendor", 30, None),
    ("Vendor GSTIN", 18, None),
    ("Buyer GSTIN", 18, None),
    ("Invoice No", 20, None),
    ("Invoice Date", 13, DATE),
    ("Category", 20, None),
    ("Currency", 9, None),
    ("Subtotal", 14, MONEY),
    ("CGST", 12, MONEY),
    ("SGST", 12, MONEY),
    ("IGST", 12, MONEY),
    ("Round Off", 10, MONEY),
    ("Total", 14, MONEY),
    ("Line Items", 10, "0"),
]


def _status(r: InvoiceRecord) -> str:
    if r.extracted is None:
        return "Failed"
    return "Review" if r.flags else "OK"


def _date_value(r: InvoiceRecord):
    if r.extracted is None:
        return None
    return r.extracted.parsed_date() or r.extracted.invoice_date


def _write_table(ws: Worksheet, columns, rows: list[list], start_row: int = 1) -> None:
    for c, (name, width, _fmt) in enumerate(columns, 1):
        cell = ws.cell(row=start_row, column=c, value=name)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    for r_i, row in enumerate(rows, start_row + 1):
        for c, value in enumerate(row, 1):
            cell = ws.cell(row=r_i, column=c, value=value)
            fmt = columns[c - 1][2]
            if fmt and value is not None and not isinstance(value, str):
                cell.number_format = fmt
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    last_col = get_column_letter(len(columns))
    ws.auto_filter.ref = f"A{start_row}:{last_col}{max(start_row + 1, start_row + len(rows))}"


def _invoices_sheet(ws: Worksheet, records: list[InvoiceRecord]) -> None:
    rows = []
    for r in records:
        inv = r.extracted
        rows.append(
            [
                r.file_name,
                _status(r),
                ", ".join(r.flag_codes),
                inv.document_type if inv else None,
                inv.vendor_name if inv else None,
                inv.vendor_gstin if inv else None,
                inv.buyer_gstin if inv else None,
                inv.invoice_number if inv else None,
                _date_value(r),
                inv.category if inv else None,
                inv.currency if inv else None,
                inv.subtotal if inv else None,
                inv.cgst if inv else None,
                inv.sgst if inv else None,
                inv.igst if inv else None,
                inv.round_off if inv else None,
                inv.total if inv else None,
                len(inv.line_items) if inv else None,
            ]
        )
    _write_table(ws, INVOICE_COLUMNS, rows)
    n = len(rows) + 1
    last_col = get_column_letter(len(INVOICE_COLUMNS))
    rng = f"A2:{last_col}{max(n, 2)}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=['$B2="Failed"'], fill=FAILED_FILL))
    ws.conditional_formatting.add(rng, FormulaRule(formula=['$B2="Review"'], fill=REVIEW_FILL))


def _line_items_sheet(ws: Worksheet, records: list[InvoiceRecord]) -> None:
    columns = [
        ("File", 16, None),
        ("Vendor", 30, None),
        ("Invoice No", 20, None),
        ("Invoice Date", 13, DATE),
        ("#", 5, "0"),
        ("Description", 46, None),
        ("HSN/SAC", 10, None),
        ("Qty", 7, "0.##"),
        ("Unit Price", 13, MONEY),
        ("Amount", 14, MONEY),
        ("GST %", 8, PCT),
        ("GST Amount", 13, MONEY),
    ]
    rows = []
    for r in records:
        inv = r.extracted
        if inv is None:
            continue
        for i, li in enumerate(inv.line_items, 1):
            gst = (
                round(li.amount * li.gst_rate / 100, 2)
                if li.amount is not None and li.gst_rate is not None
                else None
            )
            rows.append(
                [
                    r.file_name,
                    inv.vendor_name,
                    inv.invoice_number,
                    _date_value(r),
                    i,
                    li.description,
                    li.hsn_sac,
                    li.quantity,
                    li.unit_price,
                    li.amount,
                    li.gst_rate,
                    gst,
                ]
            )
    _write_table(ws, columns, rows)


def _flags_sheet(ws: Worksheet, records: list[InvoiceRecord]) -> None:
    columns = [
        ("File", 16, None),
        ("Vendor", 30, None),
        ("Invoice No", 20, None),
        ("Invoice Date", 13, DATE),
        ("Total", 14, MONEY),
        ("Reason Code", 26, None),
        ("Reason", 44, None),
        ("Detail", 60, None),
        ("Related File", 16, None),
        ("Reviewer Notes", 30, None),
    ]
    rows = []
    for r in records:
        inv = r.extracted
        for f in r.flags:
            rows.append(
                [
                    r.file_name,
                    inv.vendor_name if inv else None,
                    inv.invoice_number if inv else None,
                    _date_value(r),
                    inv.total if inv else None,
                    f.code,
                    ALL_REASONS.get(f.code, f.code),
                    f.detail,
                    f.related_file,
                    None,
                ]
            )
    _write_table(ws, columns, rows)


def _pivot_block(ws: Worksheet, table: pd.DataFrame, top: int, title: str) -> tuple[int, int, int]:
    """Write a pivot table starting at row `top`. Returns (header_row, last_data_row, n_cols)."""
    ws.cell(row=top, column=1, value=title).font = Font(bold=True, size=12)
    header = top + 1
    cols = [table.index.name or "", *[str(c) for c in table.columns]]
    for c, name in enumerate(cols, 1):
        cell = ws.cell(row=header, column=c, value=name)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
    for r_i, (label, values) in enumerate(table.iterrows(), header + 1):
        ws.cell(row=r_i, column=1, value=str(label))
        for c, v in enumerate(values, 2):
            ws.cell(row=r_i, column=c, value=float(v)).number_format = MONEY
        if label == "Total":
            for c in range(1, len(cols) + 1):
                ws.cell(row=r_i, column=c).font = Font(bold=True)
    return header, header + len(table), len(cols)


def _summary_sheet(ws: Worksheet, records: list[InvoiceRecord]) -> None:
    by_vendor, by_category = monthly_summaries(records)
    ws["A1"] = "Monthly spending summary (INR). Duplicates and unreadable documents are excluded."
    ws["A1"].font = Font(italic=True)
    ws.column_dimensions["A"].width = 34
    if by_vendor.empty:
        ws["A3"] = "No documents with a date and total yet."
        return
    for c in range(2, len(by_vendor.columns) + 2):
        ws.column_dimensions[get_column_letter(c)].width = 13
    v_header, v_last, v_cols = _pivot_block(ws, by_vendor, 3, "Spend by vendor x month")
    ws.freeze_panes = ws.cell(row=v_header + 1, column=2)
    ws.auto_filter.ref = f"A{v_header}:{get_column_letter(v_cols)}{v_last}"
    c_top = v_last + 3
    c_header, c_last, c_cols = _pivot_block(ws, by_category, c_top, "Spend by category x month")

    # stacked column chart: months on the x axis, one series per category (excl. Total row/col)
    chart = BarChart()
    chart.type, chart.grouping, chart.overlap = "col", "stacked", 100
    chart.title = "Monthly spend by category"
    chart.y_axis.title = "INR"
    chart.y_axis.numFmt = "#,##0"
    chart.height, chart.width = 9, 22
    month_cols = c_cols - 2  # minus label column and Total column
    data = Reference(
        ws, min_col=1, max_col=1 + month_cols, min_row=c_header + 1, max_row=c_last - 1
    )
    cats = Reference(ws, min_col=2, max_col=1 + month_cols, min_row=c_header, max_row=c_header)
    chart.add_data(data, from_rows=True, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, f"A{c_last + 3}")


def write_workbook(records: list[InvoiceRecord], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    _invoices_sheet(ws, records)
    _line_items_sheet(wb.create_sheet("Line Items"), records)
    _flags_sheet(wb.create_sheet("Flags for Review"), records)
    _summary_sheet(wb.create_sheet("Monthly Summary"), records)
    wb.save(path)
    return path
