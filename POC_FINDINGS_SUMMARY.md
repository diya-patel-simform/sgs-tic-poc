# SGS TIC Bot & Knowledge Platform — POC Findings & Technical Summary

*Technical spike summary — sample dataset, not a production validation. All
figures below are taken directly from the project's generated reports and
test results (`experiments_blob/processing_report.json`,
`evaluation/retrieval_comparison.json`, and the automated test suite), not
estimated.*

## Executive Summary

This POC built and validated a complete, working pipeline for the SGS TIC
Bot: real documents from Azure Blob Storage are parsed, split into chunks
using four different chunking strategies, embedded, indexed in Azure AI
Search, retrieved using three different search modes, and answered through
a grounded RAG (Retrieval-Augmented Generation) layer with a Streamlit chat
UI — every step working end to end against real Azure services, not
simulated.

The goal was to test whether this architecture works reliably and to
compare four chunking strategies under identical, controlled conditions —
**not** to pick a final "winning" strategy. On the sample dataset used
here, all four strategies processed the documents successfully with zero
failures, and retrieval never returned an empty result across 240 test
queries. One real chunking defect was found and fixed during this POC (see
Section 11), which is itself a useful result: it shows the evaluation
process catches real issues before they would reach a production system.

**377 of 377 automated tests pass**, and the full pipeline was verified
against live Azure services with 5 real, manually-reviewed questions.

## 1. POC Objective

To validate, end to end and against real documents, whether the proposed
architecture — document ingestion, chunking, embedding, indexing,
retrieval, and grounded answer generation with citations — works reliably,
and to generate objective, side-by-side measurements comparing four
different chunking strategies under the same conditions (same documents,
same questions, same retrieval settings).

## 2. Sample Dataset

**8 representative documents** (5 PDFs, 3 Excel workbooks) were used —
sourced from the project's Azure Blob Storage account. This is a
**representative sample for this technical spike, not the complete
production document set.**

| File | Type | Size |
|---|---|---|
| 2708469290SGS-AFL-Molecular-Service-Catalog-EN-A4-LR-19-11.pdf | Brochure | 20 pages |
| 381854 - HN-New Camapign-21-04-A5-HR-1X1.pdf | Brochure | 12 pages |
| Contaminants_Regulations (1).pdf | FSSAI regulation | 19 pages |
| NABL Scope-TC-5378 1 (1).pdf | NABL accreditation scope | 256 pages |
| SGS-AFL-Vitamin-Testing-Leaflet-A4-EN-LR-18-11.pdf | Brochure | 2 pages |
| Food Testing capability.xlsx | Capability matrix | 5 sheets |
| HN_Food_Testing_India_Key_Contacts.xlsx | Contact directory | 2 sheets |
| TICBOT_Regulatory_Links_Register.xlsx | Reference register | 2 sheets |

Notable characteristics deliberately present in this set: multi-page
regulatory tables, deep section/heading numbering, multi-column brochure
layouts, embedded images, a large (256-page) structured accreditation-scope
table, and Excel sheets with both tabular and list-style data.

**Not included**: a 534MB, 2,309-page scanned ISO/IEC 17025 certificate
document — excluded from this POC's ingestion run for processing-time
reasons (see Limitations, Section 11).

## Architecture

### 3. Document Processing Architecture

```
Azure Blob Storage
    → PDF / Excel detection
    → PDF: text-layer detection
         text-based        → local PDF parser (pdfplumber)
         scanned/no usable text → Azure AI Document Intelligence
      Excel: local extraction (openpyxl)
    → common parsed representation (shared by every chunking strategy)
```

All 5 sample PDFs were classified **text-based** and processed by the
local parser — no document in this sample set required Azure Document
Intelligence, so that path, while implemented and available, was not
exercised on real data in this run.

### 4. Chunking Strategies Tested

| Strategy | Approach |
|---|---|
| **Fixed-size** | Naive fixed-size token windows with overlap — a simple baseline. |
| **Recursive** | Recursive/semantic paragraph and sentence packing. |
| **Structure-aware** | Uses generic document structure (headings, tables, blocks) without document-type-specific rules. |
| **Hybrid** (document-type-aware) | Applies a specialized chunker per document type (e.g. a dedicated NABL scope-table chunker, a regulation section-numbering chunker) instead of generic windowing. |

## Experiments & Results

### 5. Chunking Results

Actual chunk counts produced from the real sample dataset:

| Strategy | Total chunks | Brochure | Regulation | NABL scope | Capability matrix | Contact directory | Reference register |
|---|---|---|---|---|---|---|---|
| Fixed | 1,518 | 24 | 27 | 1,454 | 6 | 4 | 3 |
| Recursive | 1,493 | 24 | 35 | 1,421 | 6 | 4 | 3 |
| Structure-aware | 1,108 | 67 | 40 | 983 | 8 | 7 | 3 |
| Hybrid | 647 | 51 | 21 | 549 | 12 | 9 | 5 |

**Metadata preservation observations** (from the actual processing report):
- The FSSAI regulation's tolerance-limit table has no ruling lines in the
  source PDF; the local table parser only detects ruling-line tables, so
  this content came through as plain text rather than a table-type chunk —
  the content itself was preserved, just not tagged as a table.
- 555 images were detected across the 5 PDFs; 0 became figure-type chunks.
  The local parser doesn't detect captions, so undecorated images are
  correctly treated as decorative and dropped — not a loss of captioned
  content.
- Brochure multi-column reading-order correction changed paragraph order
  on all 3 real brochures tested (199, 57, and 62 paragraphs respectively),
  confirming this correction is active and necessary on real layouts.
- 3 Excel workbooks / 9 sheets were processed, producing 26 Excel-derived
  chunks (hybrid strategy) across sheet-table, sheet-list, and sheet-chart
  types.
- A real metadata-extraction defect was found in the hybrid strategy's
  specialized NABL chunker and fixed during this POC — see Section 11.

### 6. Azure AI Search

Four separate indexes were created, one per chunking strategy, so results
are never mixed between strategies:

| Index | Live document count |
|---|---|
| ticbot-chunks-fixed | 1,518 |
| ticbot-chunks-recursive | 1,493 |
| ticbot-chunks-structure | 1,108 |
| ticbot-chunks-hybrid | 647 |

All four live counts match their source chunk files exactly (verified).

- **Embedding model**: `text-embedding-3-large` (Azure OpenAI), **3,072-dimension** vectors, HNSW algorithm with cosine similarity.
- **Metadata/filter fields**: 19 fields including chunking strategy, document type, chunk type, parser used, source file/blob path, page numbers, section path/number, sheet, cell range, authority, lab location, certificate number, discipline, material, facility, and access class.
- **Retrieval modes supported**: keyword (BM25-style), vector (embedding similarity), and hybrid (both, fused by Azure AI Search).

### 7. Retrieval Evaluation

**Scope**: 20 evaluation questions (grounded in verified real document
content, spanning 10 question categories — prose, headings, tables, NABL
scope, certificate/lab info, Excel contacts, Excel structured blocks,
page-specific, metadata-filter, and long-context) × 4 chunking strategies
× 3 retrieval modes × top_k=5 = **240 total retrieval evaluations**.

19 of the 20 questions have verifiable ground truth; the 20th (about the
excluded certificate) is run and recorded but excluded from scoring since
no strategy could answer it correctly (see Section 11).

**Measured metrics** (Hit@1, Hit@3, Hit@5, source recall, citation
precision, average score, average latency, empty-retrieval count) —
full tables in `evaluation/retrieval_comparison.md`:

- **Empty retrievals: 0 of 240** — no query returned zero results.
- **Hit@5 ranged from 0.842 to 1.000** across all 12 (strategy, mode) combinations.
- Vector and hybrid retrieval modes reached Hit@5 = 1.000 for every one of the 4 chunking strategies (8 of 8 combinations); keyword mode reached 1.000 for only 1 of the 4 strategies (recursive) and was lower for the other three (0.842–0.947).
- **Category-specific observation**: for the 2 NABL-scope questions specifically, keyword-mode retrieval scored Hit@5 = 0.000 for the structure-aware and hybrid strategies, while vector and hybrid retrieval modes scored 1.000 for every strategy on those same questions.

No overall winner is declared anywhere in the evaluation tooling or output — every number above is a measurement, not a ranking.

## RAG + UI

### 8. RAG Implementation

```
question → existing retrieval client (search/keyword/vector/hybrid)
        → top-K chunks → numbered context (with full source metadata)
        → Azure OpenAI chat model (gpt-4.1), grounded by an explicit prompt
        → answer + structured citations
```

- **Model**: Azure OpenAI `gpt-4.1` chat deployment.
- **Grounding**: the prompt instructs the model to answer only from the supplied sources, never fabricate facts or citations, preserve exact numbers/names/certificate numbers, and explicitly say when the context is insufficient.
- **Citation generation**: citations are built from the actual retrieved chunk's metadata (source file, page, sheet, cell range, section, certificate number, lab, discipline, material) — never from the model's own text. A citation to a source number the model was never given is dropped, not fabricated.
- **No-context handling**: when retrieval returns zero results, the system returns a fixed "not enough information" response without calling the language model at all.

### 9. Streamlit Demo

A chat interface (`ticbot_chunking/app.py`) on top of the RAG service above, calling it directly with no duplicated retrieval or Azure OpenAI logic:

- Chat-style question input and grounded answer display.
- Retrieval mode selector: **Hybrid** (default) / Vector / Keyword.
- Top-K selector (default 5).
- Citations shown per answer, with filename, document type, page/sheet/cell range/section, and certificate/lab/discipline/material metadata when available.
- An expandable "Retrieved Sources" section listing every chunk retrieved for the question, cited or not.
- "Clear Chat" control; chat history kept only in the browser session (no database).

**Note on current UI target**: the running app is temporarily pointed at a
separate, smaller test index (`ticbot-chunks-hybrid-updated`, built from a
different 3-document set — see the note at the end of Section 10) rather
than the `ticbot-chunks-hybrid` index this document's results are based on.
This is a one-line configuration change (`app.py`'s `INDEX_NAME_OVERRIDE`)
to switch back.

### 10. Validation / Smoke Tests

**5 real questions** were tested end to end against live Azure services (not mocked) across two verification passes:

| # | Question | Mode | Interface | Result |
|---|---|---|---|---|
| 1 | "What services are provided by SGS Molecular?" | Hybrid | RAG CLI | Correct, cited answer |
| 2 | "What is the certificate number and laboratory for the NABL scope of accreditation document?" | Hybrid | RAG CLI | Correct certificate/lab, cited |
| 3 | "What services are provided by SGS Molecular?" | Hybrid | Streamlit UI | Correct, cited answer |
| 4 | "What is the certificate number and laboratory for the NABL scope of accreditation document?" | Vector | Streamlit UI | Correct certificate/lab, cited; confirmed mode switch |
| 5 | "According to the vitamin testing leaflet, which water-soluble vitamins are analyzed?" | Keyword | Streamlit UI | Correct vitamin list, cited; confirmed mode switch |

All 5 produced grounded, correctly-cited answers with no errors, and
confirmed that changing the retrieval mode selector changes what is
actually passed to the retrieval layer.

**377 of 377 automated tests pass** (all mocked/offline — the automated
suite makes no real Azure calls; the 5 questions above are the separate,
real-Azure verification).

**Note on dataset flexibility**: after the above, the same pipeline
(ingestion → 4 chunking strategies → embedding → indexing → retrieval →
RAG) was also run end to end against a separate, different 3-document PDF
set (`updated-pdf-data`), producing 4 new, separate indexes
(`ticbot-chunks-*-updated`) so this test data never mixed with the
evaluated corpus above. This confirms the architecture generalizes to a
different document set, but — unlike the 5 questions above — it was
checked with only 2 manually-reviewed real questions, not the formal
20-question evaluation, so no Hit@K/recall/precision numbers exist for it.

## 11. Limitations

- **The 534MB, 2,309-page scanned ISO/IEC 17025 certificate PDF is excluded** from the current ingestion and evaluation run, due to the processing time it would require. No certificate-type chunk exists in any index; the one evaluation question depending on it is recorded as unscored, not answered incorrectly.
- **No semantic/reranker scoring is implemented.** The Azure AI Search index schema has a semantic configuration defined and ready, but none of the three retrieval modes tested use it.
- **Current UI limitations**: no streaming of the answer as it's generated, no inline page-level preview for citations, and the Top-K selector is capped at 20 (an arbitrary POC limit).
- **The sample dataset (8 documents) is not the complete production document set.** Results here characterize behavior on this sample only.
- **The 240-query evaluation is a controlled, small-scale test, not a production-scale accuracy or load validation.** Several question categories (e.g. multi-page tables, certificate/lab information) have only 1 question each.
- A real defect in the hybrid strategy's specialized NABL chunker (metadata extraction failing silently) was found and fixed **during** this POC's evaluation phase, not before — a reminder that similar latent issues could exist for document types not yet represented in the sample set.

## 12. Key Findings

Factual observations from the experiments — no strategy is declared a
winner, and none of the measured differences here were large enough, or
tested at large enough scale, to justify one:

- All four chunking strategies processed the real sample dataset successfully, with zero ingestion failures.
- Retrieval never returned zero results for any of the 20 questions, across any of the 12 strategy/mode combinations (240 queries total).
- Vector and hybrid retrieval modes reached Hit@5 = 1.000 for all 4 chunking strategies; keyword-only retrieval reached 1.000 for only 1 of the 4 strategies (recursive) and was notably weaker specifically for NABL-scope questions on two of the four strategies (see below).
- The hybrid (document-type-aware) strategy produces substantially fewer, more semantically grouped chunks for the NABL scope document specifically (549 chunks vs. 983–1,454 for the other three strategies) by design — it groups accredited tests by discipline and material rather than splitting on token windows.
- A real, previously-hidden data-loss defect in the hybrid strategy's specialized NABL chunker was caught by this POC's real-document evaluation process and fixed, restoring full metadata coverage (verified: 549 of 549 corrected chunks now carry real discipline, material, and lab-location data).
- Every one of the 5 real end-to-end RAG questions tested (across the CLI and the Streamlit UI) produced a grounded, correctly-cited answer.

## 13. Next Steps

**Recommended POC follow-up experiments** (still within POC scope):
- Process the excluded 2,309-page certificate document (with a longer or optimized ingestion run) to close the one dataset gap and re-run its one dependent evaluation question.
- Expand the evaluation set beyond 20 questions, particularly for categories currently represented by only 1 question, for more statistically meaningful per-category results.
- Evaluate semantic/reranker scoring (the index schema already supports it) to see whether it addresses the keyword-mode weakness observed on NABL-scope questions.
- Run the already-supported top_k=10 configuration to see whether it changes results for the lower-scoring combinations.

**Production considerations** (beyond this POC's scope):
- The full production document corpus (volume and format diversity) has not been tested — all results here are from the 8-document sample set.
- Authentication, deployment infrastructure, monitoring, and cost management for Azure OpenAI/Azure AI Search at production scale are not addressed by this POC.
- Any decision to standardize on a specific chunking strategy should be informed by a larger, production-representative evaluation rather than this POC's 20-question sample.
- Multi-turn conversation/chat history, if required by the product, would need a persistence layer — this POC intentionally keeps chat history in-session only.
