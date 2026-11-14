Model: `gemini-3.5-flash-lite` · documents: 31 (10 scanned/photo) · processed: 31 · failed: 0 · not processed: 0

**Field-level extraction accuracy** (exact match after normalisation; amounts within ₹0.01)

| Field | all | text PDF | scanned / photo |
|---|---|---|---|
| document_type | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| vendor_name | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| vendor_gstin | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| buyer_gstin | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| invoice_number | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| invoice_date | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| category | 87% (27/31) | 81% (17/21) | 100% (10/10) |
| subtotal | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| cgst | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| sgst | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| igst | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| round_off | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| total | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| line_item_count | 100% (31/31) | 100% (21/21) | 100% (10/10) |
| line.description | 100% (67/67) | 100% (41/41) | 100% (26/26) |
| line.hsn_sac | 100% (67/67) | 100% (41/41) | 100% (26/26) |
| line.quantity | 100% (67/67) | 100% (41/41) | 100% (26/26) |
| line.unit_price | 100% (67/67) | 100% (41/41) | 100% (26/26) |
| line.amount | 100% (67/67) | 100% (41/41) | 100% (26/26) |
| line.gst_rate | 100% (67/67) | 100% (41/41) | 100% (26/26) |

Documents with every header field correct: 87% (27/31)

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
