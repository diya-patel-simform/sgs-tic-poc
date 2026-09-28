# TICBot POC — Final Retrieval Evaluation Summary

This is the closing document for the retrieval-evaluation phase of the
TICBot chunking-strategy POC: real documents, real embeddings, real Azure
AI Search indexes, real retrieval queries. It reports measurements only —
it does not recommend or select a chunking strategy.

## Dataset used

Real files from the project's Azure Blob Storage account (`sample-pdf-data`
and `sample-xlsx-data` containers) — the same corpus used throughout this
project's real-data validation:

| File | Type | Pages / Sheets |
|---|---|---|
| 2708469290SGS-AFL-Molecular-Service-Catalog-EN-A4-LR-19-11.pdf | brochure | 20 pages |
| 381854 - HN-New Camapign-21-04-A5-HR-1X1.pdf | brochure | 12 pages |
| Contaminants_Regulations (1).pdf | regulation | 19 pages |
| NABL Scope-TC-5378 1 (1).pdf | accreditation_scope | 256 pages |
| SGS-AFL-Vitamin-Testing-Leaflet-A4-EN-LR-18-11.pdf | brochure | 2 pages |
| Food Testing capability.xlsx | capability_matrix | 5 sheets |
| HN_Food_Testing_India_Key_Contacts.xlsx | contact_directory | 2 sheets |
| TICBOT_Regulatory_Links_Register.xlsx | reference_register | 2 sheets |

**Excluded: `ISOIEC 17025 Certiificate and Scope of Accreditation- Validity
up to 19-11-2027.pdf`** — a genuinely scanned, 534MB, 2,309-page document.
It was intentionally left out of the real ingestion run (see
`experiments_blob/processing_report.md`) because processing it would have
taken an impractically long time for this POC pass. It has never been
parsed, chunked, embedded, or indexed at any point in this project. This is
the one deliberate gap in the dataset, and it is called out explicitly
wherever it affects a result (see "Limitations" below) rather than left
implicit.

## Scope of this evaluation

- **20 evaluation questions** (`evaluation/questions.jsonl`), each grounded
  in real, manually-verified content from the corpus above — never
  fabricated ground truth. Categories: normal prose (A), headings/sections
  (B), tables (C), NABL scope (D), certificate/lab info (E), Excel contacts
  (F), Excel structured blocks (G), page-specific (H), metadata-filter (I),
  and long-context (J).
- **4 chunking strategies**: fixed, recursive, structure_aware, hybrid —
  each in its own Azure AI Search index (`ticbot-chunks-fixed/recursive/structure/hybrid`).
- **3 retrieval modes**: keyword, vector, hybrid (keyword + vector fused by
  Azure AI Search).
- **top_k = 5** for this evaluation pass (top_k=10 is supported via
  `--top-k` but wasn't run as part of this pass).
- **240 total retrieval evaluations** (20 questions × 4 strategies × 3
  modes), the same 20 questions used unchanged across every strategy.

## Metrics

Computed per (strategy, mode) combination, and again per (strategy, mode,
question category): Hit@1, Hit@3, Hit@5, source recall, citation
precision, average retrieved score, average result count, empty-retrieval
count, and average latency. **No overall winner, ranking, or composite
score is computed anywhere in this evaluation** — see
`evaluation/retrieval_comparison.md` / `.json` for the full tables.

Headline numbers across all 12 (strategy, mode) combinations:
- **Empty retrievals: 0 of 240** — no query returned zero results.
- **Hit@5 ranged from 0.84 to 1.00** across combinations (computed over the
  19 of 20 questions with verifiable ground truth).
- Hit@K, source recall, and citation precision are computed only over
  questions with `ground_truth_status` of `available` or `partial` (19 of
  20) — Q008 (the excluded certificate) is run and its raw results saved,
  but excluded from these metrics since no strategy could possibly answer
  it correctly.

## The NABL data-loss issue and its fix

During the first full evaluation pass, manual inspection of NABL-scope
questions (Q006/Q007) revealed that the `hybrid` strategy's specialized
NABL chunker (`chunkers/nabl_scope.py`) was silently producing chunks with
**0% real discipline/material coverage** across all 256 original chunks
from `NABL Scope-TC-5378 1 (1).pdf` — every accredited-test record came out
blank, and `lab_location` was never populated at all, while the generic
`fixed` strategy's plain-text chunks (chunking the same document) retained
this content correctly.

**Root cause**: the chunker matched table column headers by exact string
lookup against a hardcoded synonym list. The real document's actual column
headers are long, real-world regulatory phrasing (e.g. `"Test Method
Specification against which tests are performed and / or the techniques /
equipment used"`), which never matched. Separately, no extraction function
for the lab's name/address existed anywhere in the codebase.

**Fix**: column matching now falls back to keyword/substring matching
(after whitespace normalization) when no exact synonym matches; a new
`extract_lab_location()` was added and wired into document-metadata
building for accreditation_scope PDFs. A fabricated `"Permanent Facility"`
display default (used when facility was genuinely unresolvable) was also
replaced with an honest `"—"` marker, matching how discipline/material
already behave when unknown.

**Result**: NABL discipline, material, and lab-location coverage went from
**0/256 (0%) to 549/549 (100%)** of the corrected hybrid chunks. The
`hybrid` strategy's chunk count for this document changed from 354 to 647
total chunks (more, smaller, correctly-grouped chunks, since real
discipline/material grouping now actually happens instead of one
undifferentiated block per page). `fixed`/`recursive`/`structure_aware`
outputs were verified byte-for-byte unchanged by this fix (they never used
the specialized NABL chunker). `ticbot-chunks-hybrid` was re-embedded and
reindexed: 647 corrected documents uploaded, 287 stale old-chunk-id
documents explicitly identified and deleted, live document count now
exactly 647. 10 new regression tests, built from the real header/row/page
data reproduced during the investigation (not a synthetic fixture), cover
this fix.

## Current index state (read-only verified, not modified in this phase)

| Index | Local chunks.jsonl | Live Azure AI Search document count |
|---|---|---|
| ticbot-chunks-fixed | 1,518 | 1,518 |
| ticbot-chunks-recursive | 1,493 | 1,493 |
| ticbot-chunks-structure | 1,108 | 1,108 |
| ticbot-chunks-hybrid | 647 | 647 |

All four match exactly — no stale or missing documents in any index.

## Retrieval observations (measurements, not conclusions)

These are observations from the data, offered for the POC record — not a
recommendation:

- Across all 12 combinations, **vector and hybrid retrieval modes achieved
  Hit@5 = 1.000** for every strategy except `structure_aware` (0.947 in
  hybrid mode); **keyword mode was the most variable**, ranging from 0.842
  (`structure_aware`) to 1.000 (`recursive`).
- **Category D (NABL scope)**: `structure_aware` and `hybrid` strategies
  scored **Hit@1/3/5 = 0.000 in keyword mode** for the 2 NABL questions,
  while vector and hybrid modes scored **1.000** for every strategy on the
  same questions — the correct document was always retrievable, just not
  via lexical keyword matching alone for these two strategies' NABL chunk
  phrasing.
- **Category E (certificate/lab info, Q008 — no ground truth)**: every
  strategy/mode still returned results (never empty) for this question —
  typically NABL scope chunks (the closest real content in the corpus,
  since the actual excluded certificate shares some header phrasing with
  the NABL scope document) — but this was not counted as a hit anywhere,
  since no chunk from the actual requested document exists.
- Manual inspection (see `evaluation/results/hybrid/hybrid.jsonl` and the
  other 11 raw-result files) confirmed real, correct content for
  representative questions in every category checked: NABL scope (Q006 —
  real lab name, certificate number, discipline in the top result), PDF
  prose (Q001 — exact "SGS Molecular is located in Lisbon..." text at rank
  1), a real table (Q014 — the exact MEAT DNA Analyser product/reaction
  table at ranks 2–3), an Excel contact record (Q009 — correct sheet and
  cell range), and an Excel structured block (Q011 — correct capability
  matrix sheet and content).

Full per-category tables (all 10 categories × 4 strategies × 3 modes) are
in `evaluation/retrieval_comparison.md`.

## Limitations

- **The 2,309-page scanned certificate PDF remains excluded** from the
  entire pipeline — not ingested, chunked, embedded, or indexed. Q008 is
  the one evaluation question with `ground_truth_status: not_available`
  for this reason, and is excluded from all Hit@K / recall / precision
  metrics (its raw retrieval behavior was still recorded and reviewed).
  Including this document in a future pass would require accepting a much
  longer ingestion run (or splitting/optimizing that specific document's
  processing) — not attempted in this POC.
- No semantic (reranker) scoring is used by any of the three retrieval
  modes evaluated here — `reranker_score` is `None` throughout, even
  though the index schema already has a semantic configuration ready for
  it (see `ticbot_chunking/search/schema.py`).
- Metrics here reflect `top_k=5` only; `top_k=10` behavior is supported by
  the tooling but wasn't run as part of this evaluation pass.

## Files produced by this evaluation

- `evaluation/questions.jsonl` — the 20 evaluation questions and their
  verified (or explicitly `not_available`) ground truth.
- `evaluation/results/<strategy>/<mode>.jsonl` — all 240 raw retrieval
  results (12 files × 20 questions), preserving every citation/metadata
  field for later inspection.
- `evaluation/retrieval_comparison.json` / `.md` — the full measurement
  tables, overall and per category.
- `evaluation/final_poc_retrieval_summary.md` — this document.
