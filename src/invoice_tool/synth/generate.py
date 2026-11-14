"""Generate the synthetic sample set: documents + ground-truth JSON with planted errors.

    uv run invoice-synth --out samples --clean

Ground truth for each file is samples/ground_truth/<file stem>.json:
    {"file", "layout", "form", "scanned", "planted", "expected_flags", "related_file", "invoice"}
where "invoice" has exactly the fields of invoice_tool.schema.ExtractedInvoice, as printed on the
document (including the planted errors).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from invoice_tool import duplicates, rules
from invoice_tool.schema import ExtractedInvoice, LineItem
from invoice_tool.synth import scan
from invoice_tool.synth.catalog import BUYER, VENDORS, Item, Party
from invoice_tool.synth.render import RECEIPT_DESC_WIDTH, DocData, Line, render

GST2_START = date(2025, 9, 22)

# planted error -> expected reason code
PLANTS = {
    "line_sum": rules.LINE_SUM_MISMATCH,
    "total": rules.TOTAL_MISMATCH,
    "tax_type": rules.TAX_TYPE_MISMATCH,
    "cgst_sgst": rules.CGST_SGST_UNEQUAL,
    "bad_gstin": rules.GSTIN_INVALID,
    "rate_date": rules.GST_RATE_INVALID_FOR_DATE,
    "missing_number": rules.MISSING_FIELD,
}

FORM_EXT = {
    "pdf": ("inv", ".pdf"),
    "scan_pdf": ("scan", ".pdf"),
    "scan_jpg": ("scan", ".jpg"),
    "scan_png": ("scan", ".png"),
    "receipt_jpg": ("rcpt", ".jpg"),
    "receipt_png": ("rcpt", ".png"),
}


@dataclass(frozen=True)
class Spec:
    num: int
    vendor: str
    layout: str
    form: str
    day: date
    n_items: int
    plant: str | None = None
    # duplicates
    dup_of: int | None = None
    dup_kind: str | None = None  # "exact" | "reissue" | "near"

    @property
    def file_name(self) -> str:
        prefix, ext = FORM_EXT[self.form]
        return f"{prefix}_{self.num:03d}{ext}"


D = date
PLAN: list[Spec] = [
    Spec(1, "stationery", "A", "pdf", D(2025, 6, 5), 3),
    Spec(2, "cloud", "B", "pdf", D(2025, 6, 18), 2),
    Spec(3, "cooling", "C", "pdf", D(2025, 7, 2), 2),
    Spec(4, "bistro", "R", "receipt_jpg", D(2025, 7, 11), 4),
    Spec(5, "legal", "D", "pdf", D(2025, 7, 25), 2),
    Spec(6, "hotel", "A", "pdf", D(2025, 8, 9), 2),
    Spec(7, "furniture", "B", "scan_pdf", D(2025, 8, 21), 2, plant="line_sum"),
    Spec(8, "courier", "C", "pdf", D(2025, 9, 3), 3, plant="total"),
    Spec(9, "stationery", "D", "pdf", D(2025, 9, 15), 3),
    Spec(10, "cabs", "R", "receipt_png", D(2025, 9, 30), 1),
    Spec(11, "cloud", "A", "pdf", D(2025, 10, 8), 2, plant="cgst_sgst"),
    Spec(12, "hotel", "B", "pdf", D(2025, 10, 20), 1, plant="rate_date"),
    Spec(13, "legal", "C", "pdf", D(2025, 11, 4), 1, plant="tax_type"),
    Spec(14, "stationery", "D", "scan_jpg", D(2025, 11, 17), 4),
    Spec(15, "cooling", "A", "pdf", D(2025, 12, 2), 2, plant="rate_date"),
    Spec(16, "bakery", "R", "receipt_jpg", D(2025, 12, 12), 3),
    Spec(17, "courier", "B", "pdf", D(2026, 1, 9), 2, plant="bad_gstin"),
    Spec(18, "cloud", "C", "pdf", D(2026, 1, 22), 1),
    Spec(19, "furniture", "D", "pdf", D(2026, 2, 5), 2),
    Spec(20, "legal", "A", "pdf", D(2026, 2, 19), 1, plant="missing_number"),
    Spec(21, "stationery", "B", "scan_png", D(2026, 3, 6), 3, plant="total"),
    Spec(22, "cloud", "D", "pdf", D(2026, 3, 20), 2, plant="tax_type"),
    Spec(23, "cabs", "R", "receipt_jpg", D(2026, 4, 8), 1),
    Spec(24, "cooling", "B", "pdf", D(2026, 5, 14), 2, plant="line_sum"),
    Spec(25, "hotel", "C", "scan_pdf", D(2026, 6, 26), 2),
    Spec(26, "bistro", "R", "receipt_png", D(2026, 7, 31), 3, plant="bad_gstin"),
    Spec(27, "courier", "A", "pdf", D(2026, 9, 10), 2),
    # duplicates
    Spec(28, "stationery", "B", "pdf", D(2025, 9, 15), 3, dup_of=9, dup_kind="reissue"),
    Spec(29, "cloud", "A", "pdf", D(2026, 1, 25), 1, dup_of=18, dup_kind="near"),
    Spec(30, "legal", "D", "pdf", D(2025, 7, 25), 2, dup_of=5, dup_kind="exact"),
    # unregistered shop: cash memo with no GSTIN, no bill number and no GST (added after review)
    Spec(31, "kiosk", "R", "receipt_jpg", D(2026, 8, 14), 3),
]

DUP_CODES = {
    "exact": duplicates.DUP_EXACT,
    "reissue": duplicates.DUP_INVOICE_NO,
    "near": duplicates.DUP_NEAR,
}


# ---------------------------------------------------------------- money


def r2(x: Decimal | float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r0(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _price(rng: random.Random, item: Item) -> float:
    step = 100 if item.price_max >= 10000 else 10 if item.price_max >= 200 else 5
    return round(rng.uniform(item.price_min, item.price_max) / step) * step


def _number(v: Party, d: date, rng: random.Random) -> str:
    fy_start = d.year if d.month >= 4 else d.year - 1
    prefix = v.number_prefix.format(
        fy=f"{fy_start % 100:02d}-{(fy_start + 1) % 100:02d}",
        year=d.year,
        yy=f"{d.year % 100:02d}",
        yymm=d.strftime("%y%m"),
    )
    width = 5 if v.key in {"bistro", "bakery", "cabs"} else 4
    return f"{prefix}{rng.randint(10 ** (width - 2), 10 ** (width - 1) * 9):0{width}d}"


def build(spec: Spec, rng: random.Random) -> DocData:
    v = VENDORS[spec.vendor]
    receipt = spec.layout == "R"
    post = spec.day >= GST2_START
    if spec.plant == "rate_date":
        # the item whose slab changed, billed at its old (pre GST 2.0) rate after the change
        chosen = [v.items[0], *rng.sample(v.items[1:], k=spec.n_items - 1)]
    else:
        chosen = rng.sample(list(v.items), k=min(spec.n_items, len(v.items)))
    lines: list[Line] = []
    for idx, it in enumerate(chosen):
        qty = rng.randint(1, it.qty_max)
        price = _price(rng, it)
        rate = it.rate_post if post else it.rate_pre
        if spec.plant == "rate_date" and idx == 0:
            rate = it.rate_pre
        lines.append(Line(it.description, it.code, qty, price, float(r2(qty * price)), rate))

    intra = receipt or v.state == BUYER.state
    if spec.plant == "tax_type":
        intra = not intra  # wrong tax type for the supply
    subtotal = sum(r2(ln.amount) for ln in lines)
    tax = sum(r2(ln.amount) * Decimal(str(ln.rate)) / 100 for ln in lines)
    cgst = sgst = igst = None
    if not v.registered:
        pass  # no GST charged
    elif intra:
        cgst = sgst = r2(tax / 2)
    else:
        igst = r2(tax)
    if spec.plant == "cgst_sgst":
        cgst, sgst = cgst + 75, sgst - 75
    printed_subtotal = subtotal + 500 if spec.plant == "line_sum" else subtotal
    raw = printed_subtotal + (cgst or 0) + (sgst or 0) + (igst or 0)
    total = r0(raw)
    round_off = r2(total - raw)
    if spec.plant == "total":
        total += 1000

    gstin = v.gstin
    if spec.plant == "bad_gstin":
        wrong = "ABCDEFGHJK"[(int(gstin[-1], 36) + 3) % 10]
        gstin = gstin[:14] + (wrong if wrong != gstin[14] else "Q")

    hour = rng.randint(9, 21) if receipt else 11
    issued = datetime.combine(spec.day, time(hour, rng.choice([5, 17, 32, 48])))
    return DocData(
        doc_type="receipt" if receipt else "invoice",
        vendor=v,
        vendor_gstin=gstin,
        buyer=None if receipt else BUYER,
        number=(
            None
            if spec.plant == "missing_number" or not v.registered
            else _number(v, spec.day, rng)
        ),
        issued=issued,
        lines=lines,
        subtotal=float(printed_subtotal),
        cgst=float(cgst) if cgst is not None else None,
        sgst=float(sgst) if sgst is not None else None,
        igst=float(igst) if igst is not None else None,
        round_off=float(round_off),
        total=float(total),
    )


def to_truth(d: DocData) -> ExtractedInvoice:
    """Ground truth = what is printed on the document."""
    receipt = d.doc_type == "receipt"
    return ExtractedInvoice(
        document_type=d.doc_type,
        vendor_name=d.vendor.name,
        vendor_gstin=d.vendor_gstin,
        buyer_gstin=d.buyer.gstin if d.buyer else None,
        invoice_number=d.number,
        invoice_date=d.day.isoformat(),
        currency="INR",
        line_items=[
            LineItem(
                description=ln.description[:RECEIPT_DESC_WIDTH] if receipt else ln.description,
                hsn_sac=None if receipt else ln.code,
                quantity=ln.qty,
                unit_price=ln.unit_price,
                amount=ln.amount,
                gst_rate=ln.rate if d.vendor.registered else None,  # no rate printed
            )
            for ln in d.lines
        ],
        subtotal=d.subtotal,
        cgst=d.cgst,
        sgst=d.sgst,
        igst=d.igst,
        round_off=d.round_off,
        total=d.total,
        category=d.vendor.category,
    )


def _write_document(spec: Spec, data: DocData, out: Path, seed: int) -> None:
    target = out / spec.file_name
    if spec.form == "pdf":
        render(spec.layout, data, target)
        return
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "page.pdf"
        render(spec.layout, data, pdf)
        dpi = 200 if spec.layout == "R" else 150
        img = scan.rasterize(pdf, dpi)
    img = scan.scanify(img, seed=seed * 1000 + spec.num, strength=1.0)
    scan.save(img, target, dpi)


def generate(out: Path, seed: int = 7, clean: bool = False) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    truth_dir = out / "ground_truth"
    truth_dir.mkdir(exist_ok=True)
    if clean:
        for p in [
            *out.glob("*.pdf"),
            *out.glob("*.jpg"),
            *out.glob("*.png"),
            *truth_dir.glob("*.json"),
        ]:
            p.unlink()

    built: dict[int, DocData] = {}
    by_num = {s.num: s for s in PLAN}
    manifest = []
    for spec in PLAN:
        rng = random.Random(seed * 100_003 + spec.num)
        if spec.dup_kind == "exact":
            shutil.copyfile(out / by_num[spec.dup_of].file_name, out / spec.file_name)
            data = built[spec.dup_of]
        elif spec.dup_kind == "reissue":
            data = built[spec.dup_of]  # same invoice, re-rendered in another layout
            _write_document(spec, data, out, seed)
        elif spec.dup_kind == "near":
            base = built[spec.dup_of]
            data = DocData(
                **{
                    **base.__dict__,
                    "number": _number(base.vendor, spec.day, rng),
                    "issued": datetime.combine(spec.day, base.issued.time()),
                }
            )
            _write_document(spec, data, out, seed)
        else:
            data = build(spec, rng)
            _write_document(spec, data, out, seed)
        built[spec.num] = data

        expected = []
        if spec.plant:
            expected.append(PLANTS[spec.plant])
        if spec.dup_kind:
            expected.append(DUP_CODES[spec.dup_kind])
        record = {
            "file": spec.file_name,
            "layout": spec.layout,
            "form": spec.form,
            "scanned": spec.form != "pdf",
            "planted": spec.plant or (f"dup_{spec.dup_kind}" if spec.dup_kind else None),
            "expected_flags": sorted(expected),
            "related_file": by_num[spec.dup_of].file_name if spec.dup_of else None,
            "invoice": to_truth(data).model_dump(mode="json"),
        }
        (truth_dir / f"{Path(spec.file_name).stem}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        manifest.append(record)
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic GST invoices with ground truth.")
    ap.add_argument("--out", type=Path, default=Path("samples"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clean", action="store_true", help="delete existing documents first")
    args = ap.parse_args(argv)
    manifest = generate(args.out, args.seed, args.clean)
    planted = sum(1 for m in manifest if m["expected_flags"])
    print(
        f"Wrote {len(manifest)} documents to {args.out} ({planted} with planted errors/duplicates)"
    )


if __name__ == "__main__":
    main()
