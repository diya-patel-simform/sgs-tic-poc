# TICBot Pipeline — Known Issues, Fixes, and Limitations

*A consolidated, honest list of every real issue found across this project
— from document ingestion through the Streamlit UI. Each item is marked
**Fixed**, **Open**, or **Known limitation (by design)**. Nothing here is
invented; every item traces to a real finding during development,
validation, or evaluation. Dataset referred to below is the primary
sample set (`sample-pdf-data` + `sample-xlsx-data`) unless stated
otherwise.*

---

## 1. Document parsing / ingestion

| Issue | Status | Detail |
|---|---|---|
| Mixed text/scanned PDFs route as a whole document, not per page | **Fixed** | `parsers/page_classifier.py` classifies every page (TEXT/SCANNED/AMBIGUOUS, via char/word count, text density, image coverage and extraction quality — not `text_length == 0` alone) and `parsers/page_router.py` sends TEXT pages to the local parser and SCANNED/AMBIGUOUS pages to Document Intelligence's `pages=` selection (e.g. `"41,81-82"`), never the whole document. Results are merged back into one `LayoutDocument`, ordered by original page number. Wired into both real ingestion entry points: `pipeline.process_pdf` (used by `run_pipeline.py`/`ingest_from_blob.py`) and `ingestion.orchestrator.ingest_document` (used by `run_ingestion.py`; a mixed document is now reported with `parser="mixed_local_and_document_intelligence"`). `parsers/router.py`'s original whole-document `parse_pdf_auto`/`describe_routing` is unchanged and still used by `experiments/common.py`'s chunking-strategy comparison harness (out of scope for this fix). See `parsers/page_router.py`'s module docstring, `tests/test_page_router.py`/`tests/test_page_classifier.py`, and `tests/test_ingestion_page_routing_integration.py` for the wired-in integration tests. |
| Local table detection only finds ruling-line tables | **Known limitation** | The real FSSAI regulation's tolerance-limit table has no ruling lines, so it comes through as plain text, not a `table`-type chunk. Content is preserved, just not tagged as a table. |
| Local parser doesn't detect figure captions | **Known limitation** | All 555 images across the sample PDFs are treated as decorative and dropped (no caption detected nearby). Zero figure-type chunks were produced on this corpus. |
| Local parser's heading/title detection struggles on heavily graphic-design brochures | **Known limitation** | Found during early chunk-quality validation; some brochure pages yield little/no detected heading structure. |
| Brochure reading-order correction breaks for a full-width title above 2-column content | **Open** | Found via the edge-case validation framework against the local sample corpus; not reverified against the current real Blob corpus. `fix_reading_order()` in `chunkers/brochure.py` has not been revisited since. |
| The 534MB, 2,309-page scanned ISO/IEC 17025 certificate is excluded from ingestion | **Known limitation** | Excluded for processing-time reasons. As a direct consequence, **the Azure Document Intelligence (scanned-PDF) path has never been exercised end-to-end on real data anywhere in this project** — every real PDF processed so far has been text-based and used the local parser. |
| `AZURE_STORAGE_ACCOUNT_URL` originally held a full connection string, not the expected bare endpoint | **Fixed** | `blob_store.py` now detects and accepts either format. |
| `AZURE_STORAGE_CONTAINER_NAME` originally pointed at a non-existent container | **Fixed** | The real data was split across `sample-pdf-data`/`sample-xlsx-data`; multi-container support was added (comma-separated list, or a one-off `--container` override). |
| `chunk_regulation()` leaked the local temp file path into `source_file` metadata instead of the real blob path | **Fixed** | Corrected at the orchestration layer (`run_ingestion.py` force-sets `source_file`/`parser` after every strategy call) rather than inside the chunker, to avoid changing chunking-strategy behavior. |

## 2. Chunking

| Issue | Status | Detail |
|---|---|---|
| NABL scope chunker's column-header matching failed on the real document | **Fixed** | Real column headers are long, real-world phrasing that didn't match the hardcoded exact-match synonym list — every one of the original 256 chunks came out with blank discipline/material/method and no lab name. Fixed with keyword/substring fallback matching + a new `extract_lab_location()`. Verified: 549 of 549 corrected chunks now carry real data. |
| NABL chunker fabricated `"Permanent Facility"` when facility was genuinely unknown | **Fixed** | Replaced with an honest `"—"`, consistent with how discipline/material already behave when unresolved. `metadata.facility` itself was always correctly `None` — only the display text was wrong. |
| One real regulation chunk exceeds the configured 700-token narrative maximum | **Open** | A section (2.3.1, "METAL CONTAMINANTS", pages 1–5) comes out at 1,226 tokens. The chunker prioritizes keeping the section together over strictly enforcing the limit — worth reviewing if a hard cap is required. |
| Generic strategies (fixed/recursive/structure-aware) don't extract structured NABL fields | **Known limitation (by design)** | Only the hybrid strategy's specialized chunker extracts discipline/material/certificate_no into metadata; the generic strategies produce plain text or generic `table` chunks without that structure. |
| No multi-page `table`-type chunk exists anywhere in the tested corpus | **Known coverage gap** | The one real table-spanning-pages case (the regulation's metal-contaminants section) is chunked as `text`, not `table` (see the ruling-lines issue above), so this specific citation/retrieval scenario has never been validated. |

## 3. Metadata classification

| Issue | Status | Detail |
|---|---|---|
| `business_area`, `geography`, `issued` fields exist in the schema but have no extraction rule wired up | **Open** | Always empty on real output — no code path populates them yet. |
| The optional LLM classifier fallback (business area/topic) has never been exercised on real data | **Untested** | Requires `AZURE_OPENAI_CHAT_DEPLOYMENT`, which wasn't configured until late in this project; the rule-based classifier handled every real case tested so far without needing it. |
| `facility` genuinely can't be extracted for the real NABL document | **Known limitation** | The real table has no Facility column and no "Facility:" banner row — there's nothing to extract, not a bug. Correctly reported as absent (post-fix) rather than guessed. |

## 4. Azure AI Search / indexing

| Issue | Status | Detail |
|---|---|---|
| Semantic re-ranking is not implemented | **Known limitation** | The index schema already has a semantic configuration defined and ready; none of the three retrieval modes evaluated use it. `reranker_score` is always `None` in every result. |
| `chunk_id` shifts when earlier content in the same file changes | **Known limitation (by design)** | `chunk_id` is a hash of (strategy, source_file, position-in-file, text). Fixing the NABL chunker changed chunk boundaries, which shifted the position of every later chunk in that file too — requiring 287 stale documents to be explicitly identified and deleted after reindexing. This is inherent to the id scheme; any future chunker fix that changes chunk count/order will need the same stale-cleanup step. |
| No automated check that a live index matches its current `chunks.jsonl` | **Open** | Every consistency check done in this project (document counts, chunk_id set-differences) was run manually, on demand — there's no ongoing/automated staleness detection. |

## 5. Retrieval

| Issue | Status | Detail |
|---|---|---|
| Keyword-only retrieval is measurably weaker for NABL-scope questions | **Open (measured)** | Hit@5 = 0.000 for the structure-aware and hybrid strategies on the 2 real NABL questions, in keyword mode specifically — vector and hybrid retrieval modes scored 1.000 for every strategy on the same questions. Semantic re-ranking (not implemented) is the likely fix candidate. |
| Only 20 evaluation questions total; several categories have just 1 question | **Known limitation** | Multi-page tables and certificate/lab-info categories are each represented by a single question — thin statistical coverage. |
| No confidence/relevance threshold on retrieval before it's handed to the LLM | **Known limitation (by design)** | Even a poor/irrelevant retrieval is passed to the RAG prompt; there's no hard score cutoff — the "insufficient information" behavior relies entirely on the prompt instructing the model to say so. |

## 6. RAG

| Issue | Status | Detail |
|---|---|---|
| "Insufficient context" detection uses a soft substring match on the answer text | **Known limitation** | `_looks_like_no_context_answer()` checks for `"couldn't find enough information"` in the model's response — robust to minor formatting differences, but if the model phrases a refusal completely differently, it could go undetected as a refusal. |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` was unset for a long stretch of this project | **Resolved (config, not code)** | Blocked all real RAG testing until it was added; not a code defect. |

## 7. Streamlit UI

| Issue | Status | Detail |
|---|---|---|
| `streamlit run` failed with `ModuleNotFoundError: No module named 'ticbot_chunking'` | **Fixed** | `streamlit run` only adds the launched script's own directory to `sys.path`, not the project root — so `app.py`'s absolute `ticbot_chunking.*` imports failed even though the identical code path works fine under `pytest`. Fixed with a `sys.path` bootstrap at the top of `app.py`. |
| No dataset/index selector in the UI | **Open** | Switching between the sample dataset and the `updated-pdf-data` test set currently requires editing a hardcoded constant (`INDEX_NAME_OVERRIDE`) in `app.py`, not a UI control. |
| No response streaming | **Known limitation** | The answer only appears once fully generated. |
| No inline page-level preview/anchor for citations | **Known limitation** | Citations are text-only (filename, page, section, etc.) — no link or preview into the actual source content. |
| Top-K capped at 20 | **Known limitation (arbitrary)** | A POC-time limit, not a technical constraint. |
| No authentication | **Known limitation (by design, out of POC scope)** | Anyone with the running URL can use it; no login or per-user access control. |
| Chat history is session-only | **Known limitation (by design)** | Lost on refresh or restart; no persistence layer, per the POC's explicit scope. |

## 8. Testing / operations

| Issue | Status | Detail |
|---|---|---|
| `monkeypatch.delenv()` didn't actually simulate "credentials missing" once real credentials existed in `.env` | **Fixed** | `python-dotenv`'s `load_dotenv()` refills any env var that's absent (but not one that's merely empty) on module reload — so a test that deleted a var and reloaded config would get it silently refilled from the real `.env`. This caused one test to make an unintended **real** Azure call before being caught and fixed (switched affected tests to `monkeypatch.setenv(key, "")` instead of `delenv`). Any new test using this pattern should use the same fix. |
| No CI/automated pipeline | **Open** | All test runs and pipeline executions in this project were done manually from the terminal; no GitHub Actions or equivalent has been verified. |
| No production-scale load testing | **Known limitation** | Everything validated at small scale: 8–9 real documents, 20 evaluation questions, 240 retrieval evaluations. |
| No monitoring/observability | **Known limitation (out of POC scope)** | No logging/metrics for retrieval quality, latency, cost, or errors in a running deployment. |
| No cost controls or rate limiting on Azure OpenAI calls | **Known limitation (out of POC scope)** | Direct, uncontrolled calls — a bug or traffic spike could generate unexpected cost. |

## 9. Data / document coverage

| Issue | Status | Detail |
|---|---|---|
| The 2,309-page scanned certificate is completely absent from every stage of the pipeline | **Known limitation** | Never ingested, chunked, embedded, or indexed. The one evaluation question that depends on it (Q008) has no possible correct answer in the current index — by design, not a defect, but a real coverage gap. |
| Only one real NABL scope document in the corpus | **Known limitation** | Limits confidence that the NABL-specific chunking/metadata logic generalizes across labs, certificate formats, or geographies. |
| Sample dataset (8 documents) is not representative of full production scale or diversity | **Known limitation** | Explicitly a technical spike, not a production validation. |

---

**Fixed, verified issues**: 7 (Blob Storage config × 2, source_file leak, NABL column-matching + fabricated facility default, streamlit path bug, test-hygiene dotenv issue).
**Open issues**: 8.
**Known limitations (by design or scope)**: remainder.

None of the "Open" items are blocking for the current POC's stated goals — they're the concrete, evidence-based punch list for whoever picks this up next.
