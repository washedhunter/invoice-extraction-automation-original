# Invoice Data Extraction & Automation Tool

Reads PDF invoices and receipt photos with Gemini, pulls out vendor, GSTIN, date, line items, totals and GST into an Excel workbook, cross-checks every total and tax, flags duplicates and mismatches for review, and summarises monthly spending by vendor and category.

![CI](https://github.com/washedhunter/invoice-extraction-automation/actions/workflows/ci.yml/badge.svg)

> All documents in this repo are **synthetic**: fictional vendors, randomly generated GSTINs, and a "SYNTHETIC TEST DOCUMENT" footer on every page. On the Gemini free tier Google may use inputs to improve its products, so no real invoices were ever sent.

## What it looks like

Output workbook from the real run below, rendered with LibreOffice. Rows that need review are highlighted.

**Invoices** (one row per document, status and reason codes up front)
![Invoices sheet](docs/img/workbook-invoices.png)

**Flags for Review** (one row per issue, in plain English, with the related file for duplicates)
![Flags for Review sheet](docs/img/workbook-flags.png)

**Monthly Summary** (vendor x month, category x month and a chart; duplicates excluded)
![Monthly Summary sheet](docs/img/workbook-summary.png)

Terminal output of the live run (29 API calls; the byte-identical duplicate came from the cache):

```text
30 documents -> out\lite.xlsx  (OK 15, needs review 15, failed 0)
API calls: 29, cached: 1
  CGST_SGST_UNEQUAL           1
  DUP_EXACT                   1
  DUP_INVOICE_NO              1
  DUP_NEAR                    1
  GSTIN_INVALID               2
  GST_RATE_INVALID_FOR_DATE   2
  LINE_SUM_MISMATCH           2
  MISSING_FIELD               1
  TAX_TYPE_MISMATCH           2
  TOTAL_MISMATCH              2
```

## Architecture

```mermaid
flowchart LR
    A[Inbox folder<br/>PDF / JPG / PNG] --> B{Cache hit?<br/>SHA-256 + model}
    B -- yes --> D
    B -- no --> C[Gemini<br/>structured output<br/>Pydantic schema]
    C -->|retry with backoff on 429/5xx;<br/>stop cleanly at daily quota| C
    C --> D[ExtractedInvoice]
    D --> E[Validation rules<br/>totals, GST, GSTIN, rate by date]
    E --> F[Duplicate detection<br/>exact / invoice no. / near]
    F --> G[Excel workbook<br/>4 sheets + chart]
    F --> H[results.json]
    H --> I[Evaluation vs<br/>ground truth]
```

The model only **transcribes**. Every check is deterministic Python, so each flag has a reason you can reproduce by hand.

## Results

Run on 2026-11-14 with `gemini-3.5-flash-lite` (free tier) over the 30 synthetic documents in `samples/`: 21 text PDFs and 9 scanned-looking PDFs or photos, with 15 planted errors and duplicates. Reproduce with the quickstart below; the numbers come from `eval/results.md`.

**Flags vs planted errors: 15 of 15 caught, 0 false alarms**

| Reason code | Planted | Caught | False alarms |
|---|---|---|---|
| LINE_SUM_MISMATCH | 2 | 2 | 0 |
| TOTAL_MISMATCH | 2 | 2 | 0 |
| TAX_TYPE_MISMATCH | 2 | 2 | 0 |
| CGST_SGST_UNEQUAL | 1 | 1 | 0 |
| GSTIN_INVALID | 2 | 2 | 0 |
| GST_RATE_INVALID_FOR_DATE | 2 | 2 | 0 |
| MISSING_FIELD | 1 | 1 | 0 |
| DUP_EXACT / DUP_INVOICE_NO / DUP_NEAR | 3 | 3 | 0 |

**Field-level extraction accuracy** (exact match after normalisation; amounts within ₹0.01)

| Field | All 30 | Text PDF (21) | Scanned / photo (9) |
|---|---|---|---|
| Vendor name, GSTINs, invoice no., date | 100% | 100% | 100% |
| Subtotal, CGST, SGST, IGST, round-off, total | 100% | 100% | 100% |
| Line items: count, description, HSN/SAC, qty, price, amount, GST rate | 100% (64 lines) | 100% | 100% |
| Category (from a fixed list) | 87% (26/30) | 81% | 100% |
| Document type (invoice vs receipt) | 83% (25/30) | 100% | 44% |

Every miss is a judgement call, not a misread: all 5 `document_type` misses are thermal receipts headed "TAX INVOICE" that the model called invoices. The 4 category misses are a courier/printing shop (labelled *Other*) and an AC purchase (labelled *Repairs & Maintenance*) that the model put under *Office Supplies*. Full per-field table: [eval/results.md](eval/results.md).

Honest caveats: 30 synthetic documents is a small set, and they're cleaner than real-world scans. The planted errors test the validation logic end to end, so 100% recall here says the rules work when extraction is right, not that every real-world error will be caught.

## Quickstart

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you). The commands work in PowerShell and in macOS/Linux shells.

```bash
git clone https://github.com/washedhunter/invoice-extraction-automation.git
cd invoice-extraction-automation
uv sync
cp .env.example .env        # then put your key from https://aistudio.google.com in .env
uv run invoice-tool process samples --out out/out.xlsx --json-out out/results.json
uv run invoice-eval --results out/results.json
```

**No API key?** Replay the recorded real responses from the run above:

```bash
uv run invoice-tool process samples --replay samples/recorded --out out/demo.xlsx
```

**Watch an inbox folder** (reprocesses when files arrive; already-seen files come from the cache):

```bash
uv run invoice-tool process inbox --out out/inbox.xlsx --watch
```

Other commands: `uv run invoice-synth --out samples --clean` regenerates the synthetic set (byte-identical), and `uv run pytest` runs the offline tests. If the daily free-tier quota runs out mid-run, the tool writes what it has, exits with code 3, and resumes from the cache on the next run.

## Project structure

```
config/settings.toml      model, tolerances, categories, required fields (env-overridable: INVOICE_*)
config/gst_rates.toml     GST slabs by date (pre / post GST 2.0, 22 Sep 2025)
src/invoice_tool/
  cli.py                  `invoice-tool process` (+ --watch, --replay, --json-out)
  extractor.py            the only module that calls Gemini: schema, prompt, retries, quota handling
  cache.py                SHA-256 keyed result cache; same format as samples/recorded
  schema.py               Pydantic models (Gemini response schema = ground-truth format)
  rules.py  gstin.py      validation rules with reason codes; GSTIN checksum
  duplicates.py           exact / same invoice no. / near-duplicate detection
  summary.py  excel.py    pandas pivots; openpyxl workbook with formats, filters, chart
  pipeline.py  watch.py   orchestration; inbox watcher
  evaluate.py             field accuracy + flag precision/recall vs ground truth
  synth/                  synthetic invoice generator (5 layouts, scan effects, planted errors)
samples/                  30 synthetic documents, ground_truth/*.json, recorded/ Gemini responses
eval/results.md           evaluation report from the live run
tests/                    78 offline tests (Gemini is mocked, network blocked)
docs/DECISIONS.md         why each choice was made, and what else was considered
```

## Design decisions and trade-offs

Details in [docs/DECISIONS.md](docs/DECISIONS.md). In short:

- **LLM transcribes, Python judges.** The prompt tells Gemini to copy printed values even when they're wrong. Arithmetic, GST rules and duplicates are deterministic code, so they're testable, explainable and free.
- **Structured output plus Pydantic re-validation.** The API ignores some schema constraints, so every response is validated again, and the category list from config is injected as an enum.
- **Synthetic data with planted errors.** It gives exact ground truth and keeps real invoices off a free tier that may train on inputs. An "oracle" test runs the validators on the ground truth to separate rule bugs from extraction errors.
- **Cache by file hash.** Re-runs and duplicate files never re-bill; a run interrupted by the daily quota resumes the next day.
- **Model: `gemini-3.5-flash-lite`.** `gemini-3.8-flash` timed out on every request from a free-tier key on the day of the run. `gemini-3.6-flash` allows only 20 requests a day on the free tier, so it can't cover the 29-file set in one day. The model is one line in config.

## Limitations and next steps

- The GST rate check is **slab-level** (was this rate a GST slab on that date?), not HSN-specific, and it doesn't model item-specific exceptions.
- Intra- vs inter-state is decided from the GSTIN state codes, so it needs both GSTINs. Place-of-supply special cases (hotels, events) aren't modelled.
- `document_type` is ambiguous for bills headed "Tax Invoice". Category is a judgement call; a few labelled examples in the prompt, or a per-vendor category memory, would help.
- Synthetic scans are mild (small skew, noise, blur). Real phone photos with shadows, folds and handwriting need their own test set.
- Next: multi-page invoices with continuation tables, a per-vendor rules file, a reviewer workflow that reads "Reviewer Notes" back in, and a comparison across models when quota allows.

## License

MIT, see [LICENSE](LICENSE).
