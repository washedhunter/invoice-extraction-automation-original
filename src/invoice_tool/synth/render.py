"""Render a synthetic document to PDF in one of five layouts.

A  classic boxed tax invoice      dates 14-03-2026, amounts 1,23,456.00
B  modern invoice + GST summary   dates 14 Mar 2026, amounts Rs. 1,23,456.00
C  dot-matrix style (Courier)     dates 14.03.2026, amounts 123456.00
D  professional services          dates 14/03/2026, amounts INR 1,23,456.00
R  80 mm thermal receipt          dates 14/03/26 13:45, amounts 123456.00
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from invoice_tool.synth.catalog import Party

rl_config.invariant = 1  # byte-identical PDFs for identical input (stable file hashes)

FOOTER = "SYNTHETIC TEST DOCUMENT - generated for software testing, not a real invoice."
# Receipts print item names cut to this width and no HSN/SAC column; ground truth must match.
RECEIPT_DESC_WIDTH = 20


@dataclass
class Line:
    description: str
    code: str | None
    qty: float
    unit_price: float
    amount: float
    rate: float


@dataclass
class DocData:
    doc_type: str  # "invoice" | "receipt"
    vendor: Party
    vendor_gstin: str  # as printed
    buyer: Party | None
    number: str | None
    issued: datetime
    lines: list[Line]
    subtotal: float
    cgst: float | None
    sgst: float | None
    igst: float | None
    round_off: float
    total: float
    extras: dict = field(default_factory=dict)

    @property
    def day(self) -> date:
        return self.issued.date()


# ---------------------------------------------------------------- formatting helpers


def indian(x: float) -> str:
    """1234567.5 -> '12,34,567.50' (Indian digit grouping)."""
    neg = x < 0
    whole, dec = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return ("-" if neg else "") + whole + "." + dec


def qty_str(q: float) -> str:
    return f"{q:g}"


def rate_str(r: float) -> str:
    return f"{r:g}%"


STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["Normal"], fontSize=8.5, leading=11)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7, leading=9, textColor=colors.grey)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)
CENTER = ParagraphStyle("center", parent=BODY, alignment=TA_CENTER)
TITLE = ParagraphStyle("title", parent=BODY, fontSize=15, leading=19, alignment=TA_CENTER)
MONO = ParagraphStyle("mono", parent=BODY, fontName="Courier", fontSize=8.5, leading=10.5)
MONO_C = ParagraphStyle("monoc", parent=MONO, alignment=TA_CENTER)


def _template(path: Path, pagesize=A4, margin: float = 14 * mm) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="Synthetic test document",
        author="invoice-synth",
        invariant=1,
    )


def _tax_rows(d: DocData, fmt) -> list[tuple[str, str]]:
    rows = []
    if d.cgst is not None:
        rows.append(("CGST", fmt(d.cgst)))
    if d.sgst is not None:
        rows.append(("SGST", fmt(d.sgst)))
    if d.igst is not None:
        rows.append(("IGST", fmt(d.igst)))
    return rows


def _party_block(p: Party, gstin: str, bold_name: bool = True) -> str:
    name = f"<b>{p.name}</b>" if bold_name else p.name
    return f"{name}<br/>{p.address}<br/>GSTIN: {gstin}<br/>State: {p.state_name} ({p.state})"


# ---------------------------------------------------------------- layout A


def render_a(d: DocData, path: Path) -> None:
    fmt = indian
    story = [Paragraph("<b>TAX INVOICE</b>", TITLE), Spacer(1, 4 * mm)]
    meta = []
    if d.number:
        meta.append(f"Invoice No: <b>{d.number}</b>")
    meta.append(f"Invoice Date: {d.day.strftime('%d-%m-%Y')}")
    if d.buyer:
        meta.append(f"Place of Supply: {d.buyer.state_name} ({d.buyer.state})")
    head = Table(
        [
            [
                Paragraph(_party_block(d.vendor, d.vendor_gstin), BODY),
                Paragraph("<br/>".join(meta), BODY),
            ]
        ],
        colWidths=[110 * mm, 72 * mm],
    )
    head.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [head, Spacer(1, 3 * mm)]
    if d.buyer:
        bill = Table(
            [
                [
                    Paragraph(
                        "<b>Bill To</b><br/>" + _party_block(d.buyer, d.buyer.gstin, False), BODY
                    )
                ]
            ],
            colWidths=[182 * mm],
        )
        bill.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.black)]))
        story += [bill, Spacer(1, 4 * mm)]
    rows = [["#", "Description", "HSN/SAC", "Qty", "Rate", "Taxable Value", "GST %"]]
    for i, ln in enumerate(d.lines, 1):
        rows.append(
            [
                str(i),
                Paragraph(ln.description, BODY),
                ln.code or "",
                qty_str(ln.qty),
                fmt(ln.unit_price),
                fmt(ln.amount),
                rate_str(ln.rate),
            ]
        )
    items = Table(
        rows, colWidths=[8 * mm, 74 * mm, 20 * mm, 12 * mm, 22 * mm, 28 * mm, 18 * mm], repeatRows=1
    )
    items.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [items, Spacer(1, 4 * mm)]
    trows = [
        ("Taxable Value", fmt(d.subtotal)),
        *_tax_rows(d, fmt),
        ("Round Off", fmt(d.round_off)),
        ("Grand Total", fmt(d.total)),
    ]
    totals = Table([list(r) for r in trows], colWidths=[40 * mm, 32 * mm], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story += [
        totals,
        Spacer(1, 10 * mm),
        Paragraph("For " + d.vendor.name, RIGHT),
        Spacer(1, 12 * mm),
        Paragraph("Authorised Signatory", RIGHT),
        Spacer(1, 8 * mm),
        Paragraph(FOOTER, SMALL),
    ]
    _template(path).build(story)


# ---------------------------------------------------------------- layout B


def render_b(d: DocData, path: Path) -> None:
    def fmt(x: float) -> str:
        return "Rs. " + indian(x)

    accent = colors.HexColor("#1f4e79")
    name_style = ParagraphStyle("nm", parent=BODY, fontSize=16, leading=20, textColor=accent)
    inv_style = ParagraphStyle("inv", parent=RIGHT, fontSize=20, leading=24, textColor=accent)
    top = Table(
        [
            [
                Paragraph(f"<b>{d.vendor.name}</b>", name_style),
                Paragraph("<b>INVOICE</b>", inv_style),
            ],
            [Paragraph(f"{d.vendor.address}<br/>GSTIN {d.vendor_gstin}", BODY), ""],
        ],
        colWidths=[120 * mm, 62 * mm],
    )
    story = [top, Spacer(1, 5 * mm)]
    meta_cells = [
        ["Invoice number", "Date of issue", "Supplier state"],
        [d.number or "", d.day.strftime("%d %b %Y"), f"{d.vendor.state_name} ({d.vendor.state})"],
    ]
    meta = Table(meta_cells, colWidths=[60 * mm, 60 * mm, 62 * mm])
    meta.setStyle(
        TableStyle(
            [
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey),
                ("FONTSIZE", (0, 0), (-1, 0), 7.5),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ]
        )
    )
    story += [meta, Spacer(1, 4 * mm)]
    if d.buyer:
        story += [
            Paragraph(
                f"<font color='grey'>BILLED TO</font><br/><b>{d.buyer.name}</b><br/>"
                f"{d.buyer.address}<br/>GSTIN {d.buyer.gstin}",
                BODY,
            ),
            Spacer(1, 5 * mm),
        ]
    rows = [["Item", "HSN/SAC", "Qty", "Unit price", "GST", "Amount"]]
    for ln in d.lines:
        rows.append(
            [
                Paragraph(ln.description, BODY),
                ln.code or "",
                qty_str(ln.qty),
                fmt(ln.unit_price),
                rate_str(ln.rate),
                fmt(ln.amount),
            ]
        )
    items = Table(rows, colWidths=[72 * mm, 20 * mm, 12 * mm, 28 * mm, 14 * mm, 36 * mm])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, accent),
    ]
    for r in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#eef3f8")))
    items.setStyle(TableStyle(style))
    story += [items, Spacer(1, 5 * mm)]
    # rate-wise GST summary
    by_rate: dict[float, float] = {}
    for ln in d.lines:
        by_rate[ln.rate] = by_rate.get(ln.rate, 0.0) + ln.amount
    intra = d.cgst is not None
    hdr = ["GST rate", "Taxable"] + (["CGST", "SGST"] if intra else ["IGST"])
    srows = [hdr]
    for rate, taxable in sorted(by_rate.items()):
        tax = taxable * rate / 100
        srows.append(
            [rate_str(rate), indian(taxable)]
            + ([indian(tax / 2), indian(tax / 2)] if intra else [indian(tax)])
        )
    summary = Table(srows, hAlign="LEFT")
    summary.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.grey),
            ]
        )
    )
    trows = [["Subtotal", fmt(d.subtotal)]] + [[f"Total {k}", v] for k, v in _tax_rows(d, fmt)]
    trows += [["Round off", fmt(d.round_off)], ["Amount due", fmt(d.total)]]
    totals = Table(trows, colWidths=[30 * mm, 36 * mm])
    totals.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent),
            ]
        )
    )
    story += [
        Table(
            [[summary, totals]],
            colWidths=[110 * mm, 72 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
        Spacer(1, 14 * mm),
        Paragraph("Thank you for your business.", BODY),
        Spacer(1, 6 * mm),
        Paragraph(FOOTER, SMALL),
    ]
    _template(path).build(story)


# ---------------------------------------------------------------- layout C


def render_c(d: DocData, path: Path) -> None:
    def fmt(x: float) -> str:
        return f"{x:.2f}"

    sep = "-" * 92
    lines = [
        d.vendor.name.upper(),
        d.vendor.address.upper(),
        f"GSTIN : {d.vendor_gstin}",
        sep,
        "TAX INVOICE".center(92),
        sep,
    ]
    if d.number:
        lines.append(f"INVOICE NO : {d.number:<30} DATE : {d.day.strftime('%d.%m.%Y')}")
    else:
        lines.append(f"{'':43} DATE : {d.day.strftime('%d.%m.%Y')}")
    if d.buyer:
        lines += [
            f"BUYER      : {d.buyer.name.upper()}",
            f"             {d.buyer.address.upper()}",
            f"BUYER GSTIN: {d.buyer.gstin}",
        ]
    lines += [
        sep,
        f"{'SR':<3}{'PARTICULARS':<40}{'HSN/SAC':>9}{'QTY':>6}{'RATE':>11}{'GST%':>6}{'AMOUNT':>13}",
        sep,
    ]
    for i, ln in enumerate(d.lines, 1):
        desc = ln.description[:38]
        lines.append(
            f"{i:<3}{desc:<40}{ln.code or '':>9}{qty_str(ln.qty):>6}{fmt(ln.unit_price):>11}"
            f"{ln.rate:>5g}%{fmt(ln.amount):>13}"
        )
        if len(ln.description) > 38:
            lines.append(f"{'':3}{ln.description[38:78]}")
    lines.append(sep)
    tail = [("TAXABLE VALUE", d.subtotal)] + [(k, float(v)) for k, v in _tax_rows(d, fmt)]
    tail += [("ROUND OFF", d.round_off), ("NET AMOUNT", d.total)]
    for label, val in tail:
        lines.append(f"{label:>70} : {fmt(val):>15}")
    lines += [sep, "", "E. & O.E.", "", FOOTER]
    story = [Paragraph(ln.replace(" ", "&nbsp;") or "&nbsp;", MONO) for ln in lines]
    _template(path, margin=10 * mm).build(story)


# ---------------------------------------------------------------- layout D


def render_d(d: DocData, path: Path) -> None:
    def fmt(x: float) -> str:
        return "INR " + indian(x)

    story = [
        Table(
            [
                [
                    Paragraph(
                        f"<b>{d.vendor.name}</b><br/><font size=7.5>{d.vendor.address} | GSTIN: "
                        f"{d.vendor_gstin}</font>",
                        ParagraphStyle("h", parent=BODY, fontSize=13, leading=16),
                    )
                ]
            ],
            colWidths=[182 * mm],
            style=[("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#7a3e00"))],
        ),
        Spacer(1, 6 * mm),
    ]
    left = "<b>Tax Invoice</b><br/>"
    if d.buyer:
        left += f"To: {d.buyer.name}<br/>{d.buyer.address}<br/>Client GSTIN: {d.buyer.gstin}"
    right = []
    if d.number:
        right.append(f"Invoice #: {d.number}")
    right.append(f"Dated: {d.day.strftime('%d/%m/%Y')}")
    right.append(f"Place of supply: {(d.buyer or d.vendor).state_name}")
    story += [
        Table(
            [[Paragraph(left, BODY), Paragraph("<br/>".join(right), RIGHT)]],
            colWidths=[110 * mm, 72 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
        Spacer(1, 6 * mm),
    ]
    rows = [["Description of service / goods", "SAC/HSN", "Units", "Rate", "GST %", "Amount"]]
    for ln in d.lines:
        rows.append(
            [
                Paragraph(ln.description, BODY),
                ln.code or "",
                qty_str(ln.qty),
                fmt(ln.unit_price),
                rate_str(ln.rate),
                fmt(ln.amount),
            ]
        )
    items = Table(rows, colWidths=[70 * mm, 20 * mm, 12 * mm, 30 * mm, 14 * mm, 36 * mm])
    items.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    trows = [["Taxable amount", fmt(d.subtotal)]]
    for k, v in _tax_rows(d, fmt):
        trows.append([f"{k} (total)", v])
    trows += [["Rounding", fmt(d.round_off)], ["Total payable", fmt(d.total)]]
    totals = Table(trows, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
            ]
        )
    )
    story += [
        items,
        Spacer(1, 4 * mm),
        totals,
        Spacer(1, 10 * mm),
        Paragraph("Payment due within 15 days. Bank details on request.", BODY),
        Spacer(1, 6 * mm),
        Paragraph(FOOTER, SMALL),
    ]
    _template(path).build(story)


# ---------------------------------------------------------------- receipt


def render_receipt(d: DocData, path: Path) -> None:
    def fmt(x: float) -> str:
        return f"{x:.2f}"

    width = 42
    out = [d.vendor.name.upper().center(width)]
    addr = d.vendor.address
    while addr:
        out.append(addr[:width].center(width))
        addr = addr[width:]
    out += [f"GSTIN: {d.vendor_gstin}".center(width), "TAX INVOICE".center(width), "-" * width]
    if d.number:
        out.append(f"Bill No: {d.number}")
    out.append(f"Date: {d.issued.strftime('%d/%m/%y %H:%M')}")
    out += ["-" * width, f"{'Item':<20}{'Qty':>4}{'Rate':>8}{'Amt':>10}", "-" * width]
    for ln in d.lines:
        out.append(
            f"{ln.description[:RECEIPT_DESC_WIDTH]:<20}{qty_str(ln.qty):>4}"
            f"{fmt(ln.unit_price):>8}{fmt(ln.amount):>10}"
        )
    out.append("-" * width)
    rate = d.lines[0].rate if d.lines else 0
    out.append(f"{'Sub Total':<30}{fmt(d.subtotal):>12}")
    if d.cgst is not None:
        out.append(f"{f'CGST @ {rate / 2:g}%':<30}{fmt(d.cgst):>12}")
    if d.sgst is not None:
        out.append(f"{f'SGST @ {rate / 2:g}%':<30}{fmt(d.sgst):>12}")
    if d.igst is not None:
        out.append(f"{f'IGST @ {rate:g}%':<30}{fmt(d.igst):>12}")
    out.append(f"{'Round Off':<30}{fmt(d.round_off):>12}")
    out += [
        "=" * width,
        f"{'TOTAL':<30}{fmt(d.total):>12}",
        "=" * width,
        "",
        "Thank you! Visit again.".center(width),
        "",
        "SYNTHETIC TEST DOCUMENT".center(width),
        "not a real bill".center(width),
    ]
    style = ParagraphStyle("rcpt", parent=MONO, fontSize=7.5, leading=9.5)
    height = (len(out) * 3.4 + 14) * mm
    story = [Paragraph(s.replace(" ", "&nbsp;") or "&nbsp;", style) for s in out]
    tmpl = _template(path, pagesize=(80 * mm, height), margin=4 * mm)
    tmpl.build(story)


RENDERERS = {"A": render_a, "B": render_b, "C": render_c, "D": render_d, "R": render_receipt}


def render(layout: str, d: DocData, path: Path) -> None:
    RENDERERS[layout](d, path)
