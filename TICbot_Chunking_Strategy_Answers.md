# TICBot – Chunking Strategy for the Sample Documents

*Updated with real, measured results from the built and Azure-validated
POC. This document originally described the planned approach before
implementation; every number below is now taken from the actual pipeline
run against the real sample documents in Azure Blob Storage, not from a
plan or an estimate.*

**Samples used:** 8 real documents from Azure Blob Storage — 5 PDFs (309
pages total) and 3 Excel workbooks (9 sheets).
- 1 FSSAI contaminants regulation (19 pages)
- 1 NABL scope of accreditation (256 pages, certificate TC-5378, SGS INDIA
  PVT. LTD., Ahmedabad) — 2,458 accredited-test rows
- 3 brochures / service catalogues (20, 12, and 2 pages)
- 3 workbooks: testing capability, key contacts, and a regulatory links
  register

**Not included in this run**: a 534MB, 2,309-page *scanned* ISO/IEC 17025
certificate document, excluded for processing-time reasons (see Section 8).
No certificate-type chunk exists in the index as a result.

---

### 1. Which chunking strategy is used?

The POC implemented and compared **four** chunking strategies side by
side against the same documents, so the benefit of a document-type-aware
approach could be measured rather than assumed. The originally-proposed
approach — hybrid, structure-aware and document-type-aware chunking — is
the **hybrid** strategy below:

| Document type | Hybrid strategy's approach |
|---|---|
| Regulation (FSSAI) | **Heading- and section-numbering-aware** chunking (e.g. `CHAPTER 2 › 2.1: METAL CONTAMINANTS`) |
| NABL scope of accreditation | **Record-aware table chunking.** Each accredited test (S.No, discipline, material, parameter, method) is kept whole; tests are grouped by discipline and material. |
| Brochures / catalogues | **Layout-aware.** Multi-column reading order is corrected first (confirmed active on all 3 real brochures — see Section 4), then split by heading, with product tables handled as tables. |
| Excel | **Block-aware.** Every table or list on a sheet is detected separately (sheet_table, sheet_lists, sheet_chart). |

The other three strategies tested were: **fixed-size** (naive token
windows), **recursive** (paragraph/sentence packing with no document-type
awareness), and **structure-aware** (generic heading/table detection,
without document-type-specific rules). All four were run against the same
8 real documents and evaluated with the same 20 questions — see Section 8.
**No single strategy is declared "the" answer here**; the measured
differences between them are reported, not ranked.

### 2. Chunk size configuration

All sizes are in tokens, measured with the text-embedding-3 tokenizer —
these are the actual configured limits in the codebase (`ticbot_chunking/config.py`), each overridable via an environment variable:

| Content | Minimum | Target | Maximum |
|---|---|---|---|
| Narrative text (regulation clauses, brochure sections) | 60 | 400 | 700 |
| Regulation / catalogue tables | – | – | 550 (a row is never split) |
| NABL scope records | – | – | 450 |
| Excel blocks | – | – | 450 |

**Observed on the real documents** (hybrid strategy, 647 chunks total; median 280, average 288 tokens):

| Chunk type | Chunks | Min | Avg | Max |
|---|---|---|---|---|
| NABL scope records | 549 | 150 | 296 | 450 |
| Regulation text | 21 | 47 | 478 | 1,226* |
| Brochure text | 49 | 19 | 146 | 599 |
| Brochure tables | 2 | 334 | 418 | 503 |
| Excel sheet tables | 21 | 42 | 271 | 449 |
| Excel sheet lists | 4 | 49 | 57 | 69 |
| Excel chart summary | 1 | 71 | 71 | 71 |

\* One real regulation chunk (section 2.3.1, "METAL CONTAMINANTS", spanning
pages 1–5) came out at 1,226 tokens — over the configured 700-token
narrative maximum. The chunker prioritizes keeping this section's content
together over strictly enforcing the limit; this is a genuine observed
exception worth reviewing if a stricter hard cap is required.

### 3. Overlap between chunks

- **Between sections: none.** Chunk boundaries follow the document's own sections, so each chunk is self-contained.
- **Inside a long section split into parts: up to 60 tokens** (~10–15% of the 400-token target).
- **Tables and scope records: no row overlap.** Each chunk instead repeats the column header/table intro and any carried-forward row label.
- **Every chunk starts with a context header:** document title and section path, plus lab, certificate number and validity for NABL chunks — confirmed present on every real NABL chunk (e.g. `Lab: SGS INDIA PVT. LTD., ... | Certificate TC-5378 | ISO/IEC 17025: 2017 | Valid 01/04/2024 to 31/03/2026`).

### 4. How document hierarchy is preserved

- **Headings and sub-headings:** the full heading path is stored as `section_path`. Real example: `MINISTRY OF HEALTH AND FAMILY WELFARE (Food Safety and Standards Authority of India) Notification › CHAPTER 2 › 2.1: METAL CONTAMINANTS`.
- **Section numbering:** read from the text and stored as `section_number` (e.g. `2.3.1`, or `CHAPTER 2` for an unnumbered chapter heading).
- **Tables:**
  - A table that runs across pages is joined into one logical block — confirmed on the real regulation content (pages 1–5 joined under one section).
  - Row-spanning labels and sub-group labels are carried forward — confirmed in the real NABL output (the lab/certificate/discipline/material header is repeated identically on every one of the 549 real scope-record chunks).
- **Page headers and footers:** removed from chunk text.
- **Excel:** the path is workbook › sheet › block (e.g. `HN_Food_Testing_India_Key_Contacts.xlsx › Sheet: Key Contacts › HNIndiaContacts`), with the exact cell range recorded on every chunk.
- **Note on annexures:** none of the real sample documents contain an explicit Annexure/Appendix/Schedule heading, so this specific rule has code support but is unverified against a real sample in this run.

### 5. Sample chunk output

These are real chunks taken directly from this POC's actual output (`experiments_blob/hybrid/chunks.jsonl`), shortened where marked (…).

**A. Regulation chunk** (heading-only; the tolerance-limit table itself has no ruling lines in the source PDF, so it comes through as plain text — see Section 6):
```
[Regulation] MINISTRY OF HEALTH AND FAMILY WELFARE
(Food Safety and Standards Authority of India)
Notification › CHAPTER 2.
CONTAMINANTS, TOXINS AND RESIDUES
```
`{"chunk_type":"text","doc_type":"regulation","source_file":"sample-pdf-data/Contaminants_Regulations (1).pdf","tokens":47,"pages":[1],"section_number":"CHAPTER 2","authority":"FSSAI","access_class":"public"}`

**B. NABL scope chunk** — real certificate/lab header repeated verbatim on every chunk from this document:
```
[NABL Scope of Accreditation] sample-pdf-data/NABL Scope-TC-5378 1 (1).pdf
Lab: SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA | Certificate TC-5378 | ISO/IEC 17025: 2017 | Valid 01/04/2024 to 31/03/2026 | Last amended 30/05/2025
Facility: — | Discipline/Group: BIOLOGICAL- ANIMAL FOOD & FEED | Material/Product: Corn gluten, Soybean, Ground nut, Rape seed & pet food. Poultry stuffing, Guar meal, Soya bean Meal.
Accredited tests:
S.No 1: Bacillus cereus (Enumeration) — Method: IS 5887-6:2012
S.No 2: Bacillus cereus (Enumeration) — Method: ISO 7932:2004
S.No 3: Clostridium perfringens (Detection) — Method: IS 5887-4:1999
…
```
`{"chunk_type":"scope_records","doc_type":"accreditation_scope","certificate_no":"TC-5378","lab_location":"SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA","discipline":"BIOLOGICAL- ANIMAL FOOD & FEED","material":"Corn gluten, Soybean, Ground nut, Rape seed & pet food...","sno_range":"1–11","row_count":11,"pages":[1],"tokens":435}`

**C. Brochure table chunk** — a real product/reaction-count table (ruling lines detected):
```
[Brochure / Service catalog] EXPERTISE › PRODUCT LIST
Table context: 17/20
| ID | PRODUCT | NUMBER OF REACTIONS (RXN) | BARCODING |
| A38452 | MEAT DNA Analyser kit I | 96 | B1.1 to B1.24 |
| A38453 | MEAT DNA Analyser kit II | 96 | B1.25 to B1.48 |
…
```
`{"chunk_type":"table","doc_type":"brochure","pages":[18],"section_path":"EXPERTISE › PRODUCT LIST","row_count":15,"tokens":503}`

**D. Excel chunk** — a real contact-directory record table (internal access, contains PII):
```
[Contact Directory] sample-xlsx-data/HN_Food_Testing_India_Key_Contacts.xlsx › Sheet: Key Contacts › HNIndiaContacts
| S. No. | Name | Role / Designation | Contact Category | Business Scope | Location | Email ID | Notes |
Row 5 — S. No.: 1 | Name: Contact 001 | Role / Designation: Quality Manager | ... | Location: Chennai | Email ID: contact001@example.com | Notes: Chennai Lab
…
```
`{"chunk_type":"sheet_table","doc_type":"contact_directory","sheet":"Key Contacts","cell_range":"A5:H10","excel_table":"HNIndiaContacts","access_class":"internal","contains_pii":true,"row_count":6,"tokens":431}`

**Note on figures**: unlike the original plan, this real sample set produced **zero** figure-type chunks. 555 images were detected across the 5 PDFs, but the local parser doesn't detect captions, and the brochure chunker correctly treats an uncaptioned image as decorative rather than fabricating a caption — so this is expected behavior on this sample set, not data loss.

### 6. How tables are handled

1. **Detection:** PDF tables are detected by ruling lines (the local parser's approach); Excel tables use defined Excel table objects where present, otherwise blank-row/column boundaries.
2. **Joining across pages:** confirmed on the real regulation content — a multi-page content block (pages 1–5) is kept together under its section.
3. **Every chunk stands alone:** column headers, table intro text, and carried-forward row labels are repeated per chunk — confirmed on all 549 real NABL chunks (identical Lab/Certificate/Discipline/Material header on each).
4. **Row integrity:** a row is never split.
5. **Format by table type:** regulation/catalogue tables as markdown rows; NABL scopes as "S.No — Parameter — Method" records; Excel record tables as "Header: value" rows; Excel formulas indexed as cached values and flagged `computed_values` (confirmed: 2 real chunks in the contacts workbook's Summary sheet carry this flag).
6. **Real quality findings from this sample set:**
   - The FSSAI regulation's tolerance-limit table has **no ruling lines** in the source PDF. Since the local parser only detects ruling-line tables, this content came through as plain text rather than a `table`-type chunk (see Sample A above) — the content itself is preserved, just not tagged as a table.
   - 555 images were detected across the 5 real PDFs; the local parser correctly excluded all of them as decorative (no captions detected) — 0 became figure chunks.
   - **A real defect was found and fixed during this POC**: the NABL scope chunker's column-header matching didn't recognize this real document's actual (long, real-world-phrased) column headers, so every one of its 256 original chunks came out with blank discipline/material/method fields, and the lab name was never extracted at all. Fixed — now 549 of 549 corrected chunks carry real, non-blank discipline, material, and lab-location data (see the project's evaluation report for the full root-cause writeup).
7. **Generic vs. specialized table handling**: the generic **structure-aware** strategy (no document-type rules) tags 469 chunks as generic `table` type from the same documents, but does not extract structured fields like discipline/material/certificate number — that structured extraction is specific to the hybrid strategy's dedicated NABL/regulation chunkers.

### 7. Metadata classification

**Document-level** (`DocumentMetadata`):
`doc_type`, `source_file`, `authority`, `business_area`, `geography`, `lab_location`, `certificate_no`, `accreditation_standard`, `validity`, `last_amended`, `issued`, `effective`, `access_class`, `contains_pii`, `language`.
*(`business_area`, `geography`, and `issued` exist in the schema but have no automatic extraction rule wired up yet on this sample set — currently always empty.)*

**Chunk-level** (`ChunkMetadata`):
`chunk_type` (text, table, scope_records, figure, certificate, sheet_table, sheet_lists, sheet_kv, sheet_chart), `section_path`, `section_number`, `pages`/`sheet`/`cell_range`, `table_header`, `entities`, `row_count`, `discipline`, `material`, `facility`, `sno_range`, `part`, `quality_flags`, `excel_table`, plus (added during this POC) `strategy` and `parser` — which of the four strategies produced the chunk, and which parser (local PDF / Document Intelligence / Excel) read the source.

**How metadata is actually assigned** (verified against real output):
- **Rules**: filename keywords (`guess_doc_type_from_filename`) and regex patterns on page-1 text for certificate number, validity dates, "Last Amended on", and the ISO/IEC 17025 standard string — all confirmed working on the real NABL document (`TC-5378`, `01/04/2024 to 31/03/2026`, `30/05/2025`, `ISO/IEC 17025: 2017`). A new pattern (`extract_lab_location`) was added during this POC to also capture the lab's name/address from a real `"Laboratory Name : ..."` line.
- **LLM classifier**: available as an optional fallback for business area/topic (requires an Azure OpenAI chat deployment), not exercised as part of this run.
- **Access control**: confirmed on the real contact-directory workbook — its chunks are tagged `access_class: "internal"` and `contains_pii: true`.

### 8. Retrieval and citation accuracy test

This is the real, Azure-based test the original version of this document said would come "next" — it has now been run.

**Setup:**
- **20 questions**, each written from and manually verified against the actual real document content (never invented), covering prose, headings, tables, NABL scope, certificate/lab info, Excel contacts, Excel structured blocks, page-specific facts, metadata-filtered queries, and long-context summaries.
- **Retrieval**: all three modes — keyword, vector, and hybrid (Azure AI Search's built-in fusion) — tested separately.
- **Embeddings**: Azure OpenAI `text-embedding-3-large` (3,072 dimensions) — the real Azure service, not a stand-in.
- **Scale**: 20 questions × 4 chunking strategies × 3 retrieval modes = **240 total retrieval evaluations**, top_k=5.

**Results** (full per-strategy/mode tables in `evaluation/retrieval_comparison.md`):
- **0 of 240 queries returned zero results.**
- **Hit@5 ranged from 0.842 to 1.000** across the 12 (strategy, mode) combinations.
- Vector and hybrid retrieval modes reached **Hit@5 = 1.000 for all 4 chunking strategies**. Keyword-only retrieval reached 1.000 for only 1 of the 4 strategies (recursive), and was measurably weaker — specifically on the 2 NABL-scope questions, where keyword mode scored **Hit@5 = 0.000** for two of the four strategies (structure-aware and hybrid) while vector/hybrid modes scored 1.000 for every strategy on those same questions.
- **Citation accuracy**: citations are built directly from the actual retrieved chunk's metadata (never from the language model's own text), and a hallucinated or out-of-range source reference is dropped rather than shown. This was verified with 5 real, manually-reviewed end-to-end questions through the RAG backend and the Streamlit UI (2 via CLI, 3 via the UI, one per retrieval mode) — every one produced a correctly-cited, grounded answer.

**Weak spot identified**: keyword-only search is measurably less reliable than vector/hybrid search specifically for NABL-scope questions on two of the four strategies. **Recommendation for follow-up**: this is exactly the kind of gap semantic re-ranking (already supported by the Azure AI Search index schema, not yet enabled) is designed to close — worth testing as a next step.

**Scope of this test**: real Azure services end to end (Azure AI Search + Azure OpenAI embeddings + GPT-4.1 for the RAG questions), on the 8-document real sample set described above. This is a controlled, small-scale test (20 questions) — not a production-scale accuracy or load validation, and several categories (e.g. multi-page tables, certificate/lab info) are represented by only 1 question each.
