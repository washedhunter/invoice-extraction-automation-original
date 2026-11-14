"""Score a run against the synthetic ground truth.

    uv run invoice-eval --results out/results.json --truth samples/ground_truth --report eval/results.md

Reports field-level extraction accuracy (overall, and text PDFs vs scanned/photographed documents)
and flag precision / recall per reason code against the planted errors, listing every miss.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

HEADER_FIELDS = [
    "document_type",
    "vendor_name",
    "vendor_gstin",
    "buyer_gstin",
    "invoice_number",
    "invoice_date",
    "category",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "round_off",
    "total",
]
NUMERIC = {"subtotal", "cgst", "sgst", "igst", "round_off", "total"}
ZERO_IS_NULL = {"cgst", "sgst", "igst", "round_off"}
LINE_FIELDS = ["description", "hsn_sac", "quantity", "unit_price", "amount", "gst_rate"]
LINE_NUMERIC = {"quantity", "unit_price", "amount", "gst_rate"}
# "no GST printed" and "0% GST" mean the same thing for a tax or a line rate
ZERO_IS_NULL_LINE = {"gst_rate"}


def _norm_str(field_name: str, v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    if field_name in {"vendor_name", "description"}:
        s = re.sub(r"[^a-z0-9]", "", s.lower())
    else:
        s = re.sub(r"\s", "", s).upper()
    return s or None


def field_equal(name: str, truth: Any, pred: Any, numeric: bool) -> bool:
    if numeric:
        if name in ZERO_IS_NULL or name in ZERO_IS_NULL_LINE:
            truth, pred = truth or 0.0, pred or 0.0
        if truth is None or pred is None:
            return truth is None and pred is None
        return abs(float(truth) - float(pred)) <= 0.01
    return _norm_str(name, truth) == _norm_str(name, pred)


def match_lines(truth: list[dict], pred: list[dict]) -> list[tuple[dict, dict | None]]:
    """Greedy match of predicted line items to true ones by description similarity."""
    remaining = list(pred)
    pairs = []
    for t in truth:
        best, best_score = None, 0.0
        for p in remaining:
            score = SequenceMatcher(
                None,
                _norm_str("description", t["description"]) or "",
                _norm_str("description", p.get("description")) or "",
            ).ratio()
            if score > best_score:
                best, best_score = p, score
        if best is not None and best_score >= 0.5:
            remaining.remove(best)
            pairs.append((t, best))
        else:
            pairs.append((t, None))
    return pairs


@dataclass
class Tally:
    correct: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.correct += ok
        self.total += 1

    @property
    def pct(self) -> float:
        return 100.0 * self.correct / self.total if self.total else 0.0


@dataclass
class Report:
    n_docs: int = 0
    n_scanned: int = 0
    processed: int = 0
    failed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    fields: dict[str, dict[str, Tally]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Tally))
    )
    docs_all_header_correct: Tally = field(default_factory=Tally)
    flag_tp: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flag_fp: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flag_fn: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    misses: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)


def evaluate(results: dict, truth_dir: Path) -> Report:
    rep = Report(models=results.get("models", []))
    records = {r["file_name"]: r for r in results["records"]}
    rep.pending = list(results.get("pending", []))
    for tp in sorted(Path(truth_dir).glob("*.json")):
        t = json.loads(tp.read_text(encoding="utf-8"))
        name, true_inv = t["file"], t["invoice"]
        group = "scanned / photo" if t["scanned"] else "text PDF"
        rep.n_docs += 1
        rep.n_scanned += t["scanned"]
        rec = records.get(name)
        pred = (rec or {}).get("extracted") or {}
        if rec is None:
            if name not in rep.pending:
                rep.pending.append(name)
        elif not pred:
            rep.failed.append(name)
        else:
            rep.processed += 1

        wrong_fields = []
        for f in HEADER_FIELDS:
            ok = bool(pred) and field_equal(f, true_inv.get(f), pred.get(f), f in NUMERIC)
            rep.fields[group][f].add(ok)
            rep.fields["all"][f].add(ok)
            if not ok:
                wrong_fields.append(f)
        rep.docs_all_header_correct.add(not wrong_fields)
        t_lines, p_lines = true_inv["line_items"], pred.get("line_items") or []
        count_ok = bool(pred) and len(t_lines) == len(p_lines)
        rep.fields[group]["line_item_count"].add(count_ok)
        rep.fields["all"]["line_item_count"].add(count_ok)
        for tl, pl in match_lines(t_lines, p_lines):
            for f in LINE_FIELDS:
                ok = pl is not None and field_equal(f, tl.get(f), pl.get(f), f in LINE_NUMERIC)
                rep.fields[group][f"line.{f}"].add(ok)
                rep.fields["all"][f"line.{f}"].add(ok)

        expected = set(t["expected_flags"])
        got = {f["code"] for f in (rec or {}).get("flags", [])} if rec else set()
        why = f" (fields differing from truth: {', '.join(wrong_fields)})" if wrong_fields else ""
        if rec is None:
            why = " (not processed)"
        for code in expected & got:
            rep.flag_tp[code] += 1
        for code in expected - got:
            rep.flag_fn[code] += 1
            rep.misses.append(f"{name}: expected {code}, got {sorted(got) or 'no flags'}{why}")
        for code in got - expected:
            rep.flag_fp[code] += 1
            rep.false_alarms.append(f"{name}: unexpected {code}{why}")
    return rep


def _pr(tp: int, fp: int, fn: int) -> tuple[str, str]:
    p = f"{100 * tp / (tp + fp):.0f}%" if tp + fp else "n/a"
    r = f"{100 * tp / (tp + fn):.0f}%" if tp + fn else "n/a"
    return p, r


def to_markdown(rep: Report) -> str:
    out = []
    models = ", ".join(rep.models) or "unknown"
    out.append(
        f"Model: `{models}` · documents: {rep.n_docs} ({rep.n_scanned} scanned/photo) · "
        f"processed: {rep.processed} · failed: {len(rep.failed)} · "
        f"not processed: {len(rep.pending)}"
    )
    out.append("")
    out.append(
        "**Field-level extraction accuracy** (exact match after normalisation; "
        "amounts within ₹0.01)"
    )
    out.append("")
    groups = [g for g in ("all", "text PDF", "scanned / photo") if g in rep.fields]
    out.append("| Field | " + " | ".join(groups) + " |")
    out.append("|---|" + "---|" * len(groups))
    names = list(rep.fields["all"].keys())
    for f in names:
        cells = []
        for g in groups:
            t = rep.fields[g].get(f)
            cells.append(f"{t.pct:.0f}% ({t.correct}/{t.total})" if t and t.total else "-")
        out.append(f"| {f} | " + " | ".join(cells) + " |")
    d = rep.docs_all_header_correct
    out.append("")
    out.append(f"Documents with every header field correct: {d.pct:.0f}% ({d.correct}/{d.total})")
    out.append("")
    out.append("**Flags vs planted errors**")
    out.append("")
    out.append("| Reason code | Planted | Caught | False alarms | Precision | Recall |")
    out.append("|---|---|---|---|---|---|")
    codes = sorted(set(rep.flag_tp) | set(rep.flag_fn) | set(rep.flag_fp))
    for c in codes:
        tp, fp, fn = rep.flag_tp[c], rep.flag_fp[c], rep.flag_fn[c]
        p, r = _pr(tp, fp, fn)
        out.append(f"| {c} | {tp + fn} | {tp} | {fp} | {p} | {r} |")
    tp, fp, fn = sum(rep.flag_tp.values()), sum(rep.flag_fp.values()), sum(rep.flag_fn.values())
    p, r = _pr(tp, fp, fn)
    out.append(f"| **All** | {tp + fn} | {tp} | {fp} | {p} | {r} |")
    out.append("")
    out.append("Missed planted errors:" if rep.misses else "Missed planted errors: none")
    out += [f"- {m}" for m in rep.misses]
    out.append("")
    out.append("False alarms:" if rep.false_alarms else "False alarms: none")
    out += [f"- {m}" for m in rep.false_alarms]
    if rep.failed:
        out += ["", "Failed extractions: " + ", ".join(rep.failed)]
    if rep.pending:
        out += ["", "Not processed (quota): " + ", ".join(rep.pending)]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Evaluate a run against synthetic ground truth.")
    ap.add_argument("--results", type=Path, required=True, help="JSON written by --json-out")
    ap.add_argument("--truth", type=Path, default=Path("samples/ground_truth"))
    ap.add_argument("--report", type=Path, help="also write the markdown report here")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any planted error is missed, any false alarm, or any file failed/pending",
    )
    args = ap.parse_args(argv)
    results = json.loads(args.results.read_text(encoding="utf-8"))
    rep = evaluate(results, args.truth)
    md = to_markdown(rep)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md, encoding="utf-8", newline="\n")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 (no ₹)
    print(md)
    if args.strict and (rep.misses or rep.false_alarms or rep.failed or rep.pending):
        print(
            "STRICT: evaluation found misses, false alarms, or unprocessed files", file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
