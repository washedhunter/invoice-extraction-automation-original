# Design decisions

Plain-English notes on why the project is built the way it is, and what else was considered.

## 1. An LLM for reading, plain code for judging

**Choice.** Gemini turns each document into structured JSON. Everything after that (sums, tax rules, GSTIN checks, duplicates, summaries) is ordinary Python.

**Why.** Invoices come in endless layouts, and a vision LLM reads them all without a template per vendor. LLMs are bad at being *reliably* right about arithmetic, though, and you can't unit-test a prompt the way you can test a function. Splitting the job means:
- every flag has a reproducible reason ("Line items sum to ₹49,540 but subtotal is ₹50,040");
- the rules are covered by fast offline tests;
- the prompt can tell the model to **copy wrong numbers as printed**. If the model "helpfully" fixed a wrong total, the validator could never catch it. The evaluation checks for exactly that.

**Alternatives considered.**
- *OCR (Tesseract) + regex/templates* (e.g. invoice2data): cheap and offline, but needs a template per layout and breaks on photos.
- *Google Document AI Invoice Parser*: purpose-built, but needs a billing account and a GCP project.
- *LayoutLM-style models*: need labelled training data and a GPU.

## 2. Structured output, validated twice

Gemini gets a JSON schema generated from the Pydantic model (`schema.py`). The category list from `config/settings.toml` is injected as an enum. The response is then parsed again with Pydantic, because the API silently ignores some JSON-schema constraints (lengths and similar). A category outside the list becomes "Other".

The same Pydantic model is the ground-truth format for the synthetic data, so evaluation compares like with like.

I used `client.models.generate_content` with `response_json_schema` rather than the newer `client.interactions.create`. The older call has typed config and handles PDFs and images the same way through `Part.from_bytes`. Both live behind one adapter class (`extractor.py`), so switching is a one-file change.

## 3. Model choice: gemini-3.5-flash-lite

Tried in order on 2026-11-14, with a free-tier key:

| Model | What happened |
|---|---|
| `gemini-3.8-flash` (latest stable Flash) | Every request, even "Reply OK", timed out (504 after ~60 s, or no response in 100 s). Other models answered in ~1–2 s on the same connection, so it wasn't the network. |
| `gemini-3.6-flash` | Worked (one invoice extracted in ~10 s), but the free tier allows **20 requests per day** for this model (from the API's own 429 message), and the sample set needs 30. |
| `gemini-3.5-flash-lite` | Processed every unique document in one run, twice (29, then 30 after a sample was added). A few 503s and per-minute 429s were absorbed by the retry logic. |

Accuracy was high enough on the lite model (100% on every amount, GSTIN, date and line item) that a bigger model wasn't needed for this data. The model is one line in config (or `--model`, or `INVOICE_MODEL`).

## 4. Rate limits and the daily quota

- **Per-minute 429s and 5xx errors** are retried with exponential backoff. If the server says how long to wait (`RetryInfo.retryDelay`), the tool waits that long plus 1 second. Client-side timeouts are retried too. Each retry is logged, so a slow API never looks like a hang.
- **Daily quota (429 with a `...PerDay...` quota id)** is *not* retried: waiting minutes won't help. The run stops calling the API, writes the workbook for what's done, lists the files still pending, and exits with code 3. Because results are cached, the next day's run picks up where it stopped.
- The SDK's own retries are turned off, so there's exactly one retry policy.

## 5. Cache by file hash

Results are stored as `.cache/extractions/<sha256>__<model>__<prompt-version>.json`, together with the raw model response. Re-running never re-bills. A byte-identical duplicate file is served from the cache. Changing the model or the prompt (bump `PROMPT_VERSION`) invalidates the cache naturally.

`samples/recorded/` holds the same files from the real run. `--replay samples/recorded` reproduces the demo (and CI) without a key. It's the actual responses, not hand-made fixtures, and the README says so.

## 6. Validation rules (`rules.py`)

| Code | Check |
|---|---|
| `LINE_SUM_MISMATCH` | Σ line amounts vs subtotal |
| `TOTAL_MISMATCH` | subtotal + CGST + SGST + IGST + round-off vs total |
| `TAX_AMOUNT_MISMATCH` | Σ (line amount × line GST rate) vs total GST charged |
| `CGST_SGST_UNEQUAL` | CGST must equal SGST |
| `TAX_TYPE_MISMATCH` | both IGST and CGST/SGST charged; or, when both GSTINs are present, IGST on an intra-state supply or CGST/SGST on an inter-state supply (state = first 2 GSTIN digits) |
| `GSTIN_INVALID` | format regex, valid state code, base-36 check character |
| `GST_RATE_INVALID_FOR_DATE` | line rate isn't a GST slab on the invoice date (`config/gst_rates.toml`) |
| `MISSING_FIELD` | required fields per document type (receipts don't need a GSTIN or invoice number) |
| `EXTRACTION_FAILED` | the API or schema validation failed |

- **Tolerance** is ₹1 (configurable), because invoices round per line and print a round-off. The round-off is extracted as its own field instead of being hidden in the tolerance.
- **GST 2.0:** from 22 Sep 2025 the 12% and 28% slabs were folded into 5% and 18%, and 40% was added for luxury/"sin" goods. So a 12% invoice dated October 2025 is flagged, while the same rate in August 2025 is fine. This is a slab-level check; it doesn't know which HSN code belongs in which slab.
- **The GSTIN checksum** was verified against two GSTINs published as examples in public GST documentation, plus tampered variants.

## 7. Duplicates

Three levels, strongest first: same file bytes → same vendor GSTIN + invoice number (ignoring case and punctuation) → same vendor + same total within 7 days. Each document gets at most one duplicate flag: its strongest match, on the later document by invoice date, pointing at the earlier file. Duplicates are excluded from the spending summary so money isn't double-counted. Other flagged documents still count, because a wrong total is still spend that needs review.

## 8. Synthetic data instead of real invoices

- The free tier may use inputs to improve Google's products, so real invoices must not be sent.
- Synthetic data gives **exact ground truth** and lets errors be planted on purpose.
- 31 documents: 11 fictional vendors in 4 states (one unregistered shop with no GSTIN), 4 invoice layouts plus a thermal-receipt layout, varied date and number formats (`14-03-2026`, `14 Mar 2026`, `14.03.2026`, `14/03/26`; `1,23,456.00`, `Rs.`, `INR`). 10 are rasterised and given skew, noise, blur and JPEG artefacts, then saved as image-only PDFs, JPGs or PNGs, so there's no text layer to cheat with.
- 16 clean documents and 15 with exactly one planted issue each. They cover every reason code except `TAX_AMOUNT_MISMATCH` and `EXTRACTION_FAILED`, which are covered by unit tests only.
- Generation is seeded. Text PDFs and ground truth are byte-identical between runs (reportlab "invariant" mode), so cached hashes and recorded responses stay valid. The scanned images are deterministic on the same library versions but can change with other Pillow/pdfium builds; CI replays the committed files rather than regenerating them.
- **Oracle test:** the validators run on the ground truth itself, and must produce exactly the planted flags, no more and no less. If that fails, the bug is in the rules or the generator, not the model.

**A ground-truth bug the evaluation found.** The thermal receipts print item names cut to 20 characters and no HSN/SAC column, but the first version of the ground truth had the full names and codes. The model read the receipts correctly and was marked wrong. The fix made the ground truth match what's printed (and added a test for it); the documents didn't change. **A prompt change after the first run.** In the first run, the model called every thermal receipt headed "TAX INVOICE" an invoice (document_type 25/30). That matters: receipts have looser required fields, so a real receipt with no GSTIN would get a false `MISSING_FIELD`. The prompt and schema now define a receipt as any point-of-sale bill, whatever its heading (prompt v2). A cash-memo receipt with no GSTIN, no number and no GST was added to test exactly that case. The second run got document_type right on all 31. This was tuned on the evaluation set, and the README says so. The 4 category misses were left alone.

## 9. Evaluation (`evaluate.py`)

- Field-level accuracy, split into text PDFs vs scanned/photo documents. Strings are compared after normalising case and spacing, amounts within ₹0.01. A missing tax is treated as 0.
- Line items are matched to the truth by description similarity, so an extra or missing line doesn't shift every comparison.
- Flag precision and recall per reason code against the planted set. Every miss and false alarm is listed, with the fields that differed from the truth, so you can tell an extraction error from a rule error.

## 10. Excel output

- Four sheets: **Invoices**, **Line Items**, **Flags for Review**, **Monthly Summary**.
- Formatting: real Excel dates and ₹ number formats (not text), frozen headers, autofilters, conditional formatting on the status column (a reviewer can change "Review" to "OK" and the highlight goes away), a "Reviewer Notes" column, and landscape fit-to-width printing.
- Summary: pandas pivots by vendor × month and category × month, plus a stacked column chart. Vendor names are merged across spellings (the same vendor appears in capitals on some layouts) using the normalised name and the GSTIN.

## 11. Making CI meaningful

The CI "demo" step replays the recorded responses and then evaluates them. On its own that could never fail: a changed sample just becomes an extraction failure. So `process --replay` exits 4 if any file has no recorded response, and `invoice-eval --strict` exits 1 on any missed planted error, false alarm, or failed or unprocessed file. A regression in rules, duplicates or samples breaks the build.

## 12. Testing without the network

- 87 offline tests cover rules, GSTIN, duplicates, generator determinism, the oracle, the extractor (fake client: retries, daily quota, bad JSON, MIME types), the pipeline, the workbook structure, the CLI and watch mode.
- A pytest fixture replaces `google.genai.Client` and clears API keys for every test.
- That fixture exists because of a real mistake during development. `load_dotenv()` looks for `.env` relative to the calling module, not the working directory, so one CLI test found the repo's real `.env` and sent the synthetic samples to Gemini, using up a day's free quota for one model. The CLI now reads `.env` only from the working directory, and tests cannot reach the API.
