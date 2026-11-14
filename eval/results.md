Model: `gemini-3.5-flash-lite` · documents: 30 (9 scanned/photo) · processed: 30 · failed: 0 · not processed: 0

**Field-level extraction accuracy** (exact match after normalisation; amounts within ₹0.01)

| Field | all | text PDF | scanned / photo |
|---|---|---|---|
| document_type | 83% (25/30) | 100% (21/21) | 44% (4/9) |
| vendor_name | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| vendor_gstin | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| buyer_gstin | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| invoice_number | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| invoice_date | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| category | 87% (26/30) | 81% (17/21) | 100% (9/9) |
| subtotal | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| cgst | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| sgst | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| igst | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| round_off | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| total | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| line_item_count | 100% (30/30) | 100% (21/21) | 100% (9/9) |
| line.description | 100% (64/64) | 100% (41/41) | 100% (23/23) |
| line.hsn_sac | 100% (64/64) | 100% (41/41) | 100% (23/23) |
| line.quantity | 100% (64/64) | 100% (41/41) | 100% (23/23) |
| line.unit_price | 100% (64/64) | 100% (41/41) | 100% (23/23) |
| line.amount | 100% (64/64) | 100% (41/41) | 100% (23/23) |
| line.gst_rate | 100% (64/64) | 100% (41/41) | 100% (23/23) |

Documents with every header field correct: 70% (21/30)

**Flags vs planted errors**

| Reason code | Planted | Caught | False alarms | Precision | Recall |
|---|---|---|---|---|---|
| CGST_SGST_UNEQUAL | 1 | 1 | 0 | 100% | 100% |
| DUP_EXACT | 1 | 1 | 0 | 100% | 100% |
| DUP_INVOICE_NO | 1 | 1 | 0 | 100% | 100% |
| DUP_NEAR | 1 | 1 | 0 | 100% | 100% |
| GSTIN_INVALID | 2 | 2 | 0 | 100% | 100% |
| GST_RATE_INVALID_FOR_DATE | 2 | 2 | 0 | 100% | 100% |
| LINE_SUM_MISMATCH | 2 | 2 | 0 | 100% | 100% |
| MISSING_FIELD | 1 | 1 | 0 | 100% | 100% |
| TAX_TYPE_MISMATCH | 2 | 2 | 0 | 100% | 100% |
| TOTAL_MISMATCH | 2 | 2 | 0 | 100% | 100% |
| **All** | 15 | 15 | 0 | 100% | 100% |

Missed planted errors: none

False alarms: none
