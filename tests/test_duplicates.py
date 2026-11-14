from invoice_tool.duplicates import DUP_EXACT, DUP_INVOICE_NO, DUP_NEAR, find_duplicates
from invoice_tool.schema import InvoiceRecord


def rec(name, sha, inv):
    return InvoiceRecord(file_name=name, file_sha256=sha, extracted=inv)


def dup_flags(records):
    return {r.file_name: [(f.code, f.related_file) for f in r.flags] for r in records}


def test_exact_duplicate_flags_later_file(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice)
    b = rec("b.pdf", "h1", clean_invoice)
    find_duplicates([b, a], near_days=7)
    assert dup_flags([a, b]) == {"a.pdf": [], "b.pdf": [(DUP_EXACT, "a.pdf")]}


def test_same_gstin_and_number(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice)
    b = rec("b.pdf", "h2", clean_invoice.model_copy(update={"invoice_number": "tv-2026-001 "}))
    c = rec("c.pdf", "h3", clean_invoice.model_copy(update={"invoice_number": "TV/2026/001"}))
    find_duplicates([a, b, c], near_days=7)
    # punctuation/case-insensitive number match; the earliest document is referenced
    assert dup_flags([a, b, c])["c.pdf"] == [(DUP_INVOICE_NO, "a.pdf")]
    assert dup_flags([a, b, c])["b.pdf"] == [(DUP_INVOICE_NO, "a.pdf")]


def test_near_duplicate_within_window(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice)
    b = rec(
        "b.pdf",
        "h2",
        clean_invoice.model_copy(
            update={"invoice_number": "TV/2026/009", "invoice_date": "2026-03-15"}
        ),
    )
    find_duplicates([a, b], near_days=7)
    flags = dup_flags([a, b])
    assert flags["b.pdf"] == [(DUP_NEAR, "a.pdf")]


def test_near_duplicate_outside_window_is_ignored(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice)
    b = rec(
        "b.pdf",
        "h2",
        clean_invoice.model_copy(
            update={"invoice_number": "TV/2026/009", "invoice_date": "2026-03-25"}
        ),
    )
    find_duplicates([a, b], near_days=7)
    assert dup_flags([a, b]) == {"a.pdf": [], "b.pdf": []}


def test_different_total_not_near_duplicate(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice)
    b = rec(
        "b.pdf",
        "h2",
        clean_invoice.model_copy(update={"invoice_number": "TV/2026/009", "total": 2231}),
    )
    find_duplicates([a, b], near_days=7)
    assert dup_flags([a, b])["b.pdf"] == []


def test_later_date_is_flagged_even_if_name_sorts_first(clean_invoice):
    early = rec("z.pdf", "h1", clean_invoice)
    late = rec(
        "a.pdf",
        "h2",
        clean_invoice.model_copy(
            update={"invoice_number": "TV/2026/009", "invoice_date": "2026-03-12"}
        ),
    )
    find_duplicates([early, late], near_days=7)
    assert dup_flags([early, late]) == {"z.pdf": [], "a.pdf": [(DUP_NEAR, "z.pdf")]}


def test_strongest_match_wins(clean_invoice):
    a = rec("a.pdf", "h1", clean_invoice.model_copy(update={"invoice_number": "OTHER"}))
    b = rec("b.pdf", "h2", clean_invoice)
    c = rec("c.pdf", "h2", clean_invoice)
    find_duplicates([a, b, c], near_days=7)
    # c is near-dup of a but an exact copy of b: exact wins
    assert dup_flags([a, b, c])["c.pdf"] == [(DUP_EXACT, "b.pdf")]


def test_failed_extraction_only_matches_exact(clean_invoice):
    a = InvoiceRecord(file_name="a.pdf", file_sha256="h1", error="boom")
    b = InvoiceRecord(file_name="b.pdf", file_sha256="h1", error="boom")
    find_duplicates([a, b], near_days=7)
    assert dup_flags([a, b])["b.pdf"] == [(DUP_EXACT, "a.pdf")]
