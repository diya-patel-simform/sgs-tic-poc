# TICbot Chunking Pipeline

Implementation of the chunking strategy described in
`TICbot_Chunking_Strategy_Answers.md`: a hybrid, document-type-aware pipeline
that routes each file to one of four chunkers (regulation, NABL scope of
accreditation, brochure/catalogue, Excel) rather than using one fixed
splitter, plus an Azure AI Search hybrid-retrieval eval harness.

## Layout

```
ticbot_chunking/
  config.py                  chunk-size limits (section 2) + Azure config from env
  tokenizer.py                token counting (text-embedding-3 tokenizer)
  storage/
    blob_store.py             Azure Blob Storage client (list / identify / download blobs)
  ingestion/
    source.py                  lists/fetches source files: Blob Storage, or a labeled local stand-in
    orchestrator.py             per-document parser classification + provenance (ingest_document)
    representative_checks.py    targeted validation: FSSAI tables, NABL scopes, brochures, figures, Excel blocks
    report.py                   processing_report.md / .json builders
  experiments/
    common.py                  shared parsing-once + token-windowing/provenance toolkit
    fixed_size.py               strategy 1: naive fixed-size token windows
    recursive.py                 strategy 2: recursive/semantic paragraph+sentence packing
    structure_aware.py           strategy 3: generic heading/table/block structure, no doc-type rules
    hybrid.py                    strategy 4: reuses chunkers/* as-is, just tags `strategy`
    stats.py                     per-strategy statistics + cross-strategy comparison report
  validation/
    edge_cases.py                 EdgeCaseResult: shared Edge Case/Expected/Actual/Pass-Fail row type
    generic_checks.py             7 checks scanning an existing chunks.jsonl corpus
    fixture_checks.py             5 checks that build known scenarios and run every strategy fresh
    report.py                     renders the edge-case table + the human-readable chunk inspection report
  parsers/
    ir.py                     normalized layout representation every chunker reads
    local_pdf.py               local (pdfplumber) parser for text-based PDFs + text-layer detection
    azure_docintel.py         Azure AI Document Intelligence adapter -> ir.LayoutDocument (scanned PDFs only)
    router.py                  parse_pdf_auto(): picks local_pdf vs azure_docintel automatically
  chunkers/
    section_numbering.py      CHAPTER / x.y / x.y.z / Annexure heading-path tracker
    table_utils.py            rowspan carry-forward, sub-group labels, row-integrity chunking
    text_utils.py             sentence-boundary splitting with 1-sentence overlap
    regulation.py             heading + section-numbering + table-aware chunker
    nabl_scope.py              record-aware scope-of-accreditation chunker
    brochure.py                layout-aware (reading order, headings, tables, figures)
    excel_blocks.py            block-aware Excel chunker (openpyxl, no Azure needed)
  metadata/
    schema.py                  DocumentMetadata / ChunkMetadata / Chunk (section 7)
    classifier.py               regex rules + optional LLM fallback for doc metadata
  retrieval/
    embeddings.py               Azure OpenAI embeddings
    azure_search_index.py       single-index schema + upload for the QA eval (hybrid keyword+vector)
    qa_eval.py                  section 8 retrieval/citation accuracy harness
  search/
    schema.py                    per-strategy Azure AI Search index schema (4 indexes, no embeddings/upload)
    index_manager.py             create / exists / recreate / fetch an index
    validate.py                  structural validation of a built or live index
    chunk_id.py                  stable document key (sha256 of strategy+source_file+position+text)
    document_mapper.py            chunks.jsonl row + vector -> Azure AI Search document
    embedding_client.py           batched Azure OpenAI embeddings, retried on transient errors
    indexer.py                    embed + upload one strategy's chunks.jsonl to its index
    index_content_validation.py   live document count/vector/text/metadata population checks
    retrieval_client.py           common keyword/vector/hybrid retrieval interface (search())
    eval_metrics.py               Hit@K / source recall / citation precision, per (strategy, mode[, category])
    eval_runner.py                runs or recomputes the full evaluation matrix
    eval_report.py                retrieval_comparison.json/.md builders (no winner, ever)
  rag/
    chat_client.py                Azure OpenAI chat completion, retried like embedding_client.py
    context_builder.py            RetrievalResult list -> numbered LLM context block
    prompt.py                     the grounded-answering system prompt (10 rules) + NO_CONTEXT_ANSWER
    response.py                   Citation / RagResponse — the typed answer() return value
    rag_service.py                question -> retrieval_client.search() -> context -> chat -> RagResponse
  pipeline.py                   routes files -> parser -> chunker -> chunks.jsonl
  app.py                        Streamlit chat UI on top of rag_service.answer() — see below
  scripts/                      CLIs: run_pipeline, ingest_from_blob, run_chunking_experiments,
                                 run_validation, run_ingestion, create_search_index, index_chunks,
                                 search_chunks, run_retrieval_eval, evaluate_retrieval, ask_rag,
                                 chunk_stats, inspect_chunk, build_index, run_eval
  tests/                        offline unit/integration tests (no Azure needed)
```

Everything under `chunkers/`, `metadata/`, and `parsers/ir.py` is pure Python
operating on the `LayoutDocument` IR, so it's fully unit-tested without any
Azure credentials (`ticbot_chunking/tests/`). `storage/blob_store.py` is
unit-tested with the Azure SDK mocked (no real storage account needed).
Only `parsers/azure_docintel.py` and `retrieval/` make live Azure calls that
can't be exercised offline.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in Azure Blob Storage / Document Intelligence / Search / OpenAI values
```

## Running the tests (no credentials needed)

```bash
.venv/bin/python -m pytest ticbot_chunking/tests -q
```

## Running the pipeline

PDFs are parsed automatically — text-based PDFs locally (no Azure call),
scanned/image-only PDFs via Azure Document Intelligence (credentials needed
only for those). Excel workbooks are handled entirely locally via
`openpyxl` and never need Azure credentials. See "PDF parsing" below.

```bash
.venv/bin/python -m ticbot_chunking.scripts.run_pipeline upadated_data_sgs output/chunks.jsonl
```

## PDF parsing: automatic local-vs-Azure routing

Azure Document Intelligence is **not** called for every PDF. Each PDF is
inspected first; only ones with no usable text layer (i.e. actually
scanned/image-based) go to Document Intelligence:

```
PDF -> inspect_text_layer() -> usable text layer? --yes--> local_pdf.parse_pdf_local()   -\
                                                \--no---> azure_docintel.parse_pdf()      -+-> same LayoutDocument IR -> chunking
                                                                                           -/
```

**Library: [`pdfplumber`](https://github.com/jsvine/pdfplumber) (MIT
license)**, chosen over `PyMuPDF` (AGPL/commercial dual license — avoided
for a client POC) and plain `pypdf` (text-only, no bounding boxes or table
extraction). `pdfplumber` gives per-character bounding boxes and font
info (needed for reading-order and heading heuristics — the same kind of
signal the brochure chunker's `fix_reading_order` already depends on) and
native ruling-line table extraction, in one dependency, with no system-level
binaries.

**Detection** (`parsers/local_pdf.py::inspect_text_layer`): every page's
text is extracted (`page.extract_text()`); a page counts as having a
"usable text layer" if it yields at least `MIN_CHARS_PER_PAGE` (20)
non-whitespace characters. The PDF as a whole is treated as text-based if
**at least 10%** of its pages have one (`MIN_TEXT_FRACTION`) — deliberately
a low bar, not a majority vote: a document that's overwhelmingly text-based
with a handful of scanned inserts (e.g. one scanned certificate page in an
otherwise text-based multi-page NABL scope document) should still get the
free, fast local parse, while a document with mostly no real text (e.g. a
scan with one OCR'd cover page) still correctly routes to Document
Intelligence. This is a document-level decision — see "remaining
limitations" below for what that means for the individual pages on the
minority side of the cut. No manual scanned-page flag is involved anywhere;
`parsers/router.py::parse_pdf_auto` is the single entry point, and it's
what `pipeline.process_pdf` and `experiments.common.parse_input_dir` both
call.

When a PDF *does* route to Document Intelligence, which of its pages are
tagged `is_scanned=True` in the resulting IR is also automatic — computed
from the same per-page text-layer check, passed into
`azure_docintel.parse_pdf(file_path, text_layer_stats=...)` — not a manually
supplied flag either (this replaces the `scanned_page_numbers` parameter
that existed before this step).

**Common representation:** both parsers return the exact same
`parsers.ir.LayoutDocument` (pages, paragraphs with role + bounding boxes,
tables with cells, figures) — see "Layout" above. No chunker changed; the
four chunking strategies and `chunkers/*.py` don't know or care which
parser produced the document they're given.

**What each path preserves:**

| | Local parser (`local_pdf.py`) | Document Intelligence (`azure_docintel.py`) |
|---|---|---|
| Source filename, page numbers, text | yes | yes |
| Tables | ruling-line tables only (see below) | ML-based layout, incl. un-ruled tables, rowspan/colspan |
| Headings/structure | text-convention signal (CHAPTER/dotted numbering/Annexure, reusing `chunkers/section_numbering.py`'s regexes) + a font-size/bold fallback | ML-based role classification |
| Figures | position only, no caption/inline text | caption + inline-text-overlap detection |

Table detection deliberately uses only pdfplumber's ruling-line strategy,
not its text-alignment strategy — the latter badly mis-segments ordinary
paragraph text into garbled fake table cells on whitespace-aligned,
non-ruled tables (confirmed against the real FSSAI regulation sample, which
has exactly that shape). An un-ruled table therefore comes through as plain
paragraph text locally, not a `Table` — a real trade-off against Document
Intelligence's ML layout model, and deliberately preferred over fabricating
a table structure that isn't really there.

## Azure Blob Storage (source document store)

**Azure Blob Storage is the sole ingestion source for the end-to-end
ingestion pipeline (`scripts/run_ingestion.py`) — there is no
local-directory fallback.** If it isn't configured, inaccessible, or
returns no files, ingestion fails clearly with an actionable error instead
of silently reading local files.

Set the three storage variables in `.env` (no credentials are ever
hardcoded):

```bash
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net
AZURE_STORAGE_ACCOUNT_KEY=<account key>
AZURE_STORAGE_CONTAINER_NAME=<container name>
```

`ticbot_chunking/storage/blob_store.py` is the client: `list_blobs()` /
`list_pdf_blobs()` / `list_excel_blobs()` (optionally with a `prefix=`
folder filter), `download_blob_bytes()`, and `download_blob_to_file()`. Each
listed blob is a `BlobInfo` with `.name` (the full blob path), `.size`,
`.is_pdf`, `.is_excel`. Any of these raise a clear `RuntimeError` if the
three env vars above aren't set.

`ticbot_chunking/scripts/ingest_from_blob.py` is a **separate command** from
`run_pipeline.py`: it lists blobs, downloads each one, and hands it to the
*same, unmodified* `pipeline.process_pdf` / `pipeline.process_excel` used by
the local-directory pipeline — then overwrites each resulting chunk's
`source_file` metadata with the blob's full path (not the local temp
filename it was downloaded to), so citations point back to blob storage.
Embeddings and indexing are explicitly out of scope here — that's
`build_index.py`, a later step.

```bash
# See what would be ingested, without downloading or parsing anything
.venv/bin/python -m ticbot_chunking.scripts.ingest_from_blob --list-only

# Only look under a folder prefix
.venv/bin/python -m ticbot_chunking.scripts.ingest_from_blob --list-only --prefix "FSSAI Regulation/"

# Ingest everything in the container through the existing chunking pipeline
.venv/bin/python -m ticbot_chunking.scripts.ingest_from_blob output/chunks_from_blob.jsonl

# Ingest only a folder, and/or cap how many blobs are processed
.venv/bin/python -m ticbot_chunking.scripts.ingest_from_blob output/chunks_from_blob.jsonl --prefix "Brochures/" --limit 5
```

Blobs that fail to parse (e.g. a PDF blob when Document Intelligence isn't
configured) are skipped with the error printed, rather than aborting the
whole run — useful when a container has a mix of file types.

## Chunk size / overlap configuration

Every limit in section 2 of the strategy doc is a default that can be
overridden with an environment variable — see the commented-out block near
the bottom of `.env.example` (`CHUNK_NARRATIVE_MIN_TOKENS`,
`CHUNK_NARRATIVE_TARGET_TOKENS`, `CHUNK_NARRATIVE_MAX_TOKENS`,
`CHUNK_NARRATIVE_OVERLAP_MAX_TOKENS`, `CHUNK_TABLE_MAX_TOKENS`,
`CHUNK_NABL_MAX_TOKENS`, `CHUNK_EXCEL_MAX_TOKENS`). No code changes needed to
retune chunk sizes.

## Chunk statistics report

```bash
.venv/bin/python -m ticbot_chunking.scripts.chunk_stats output/chunks.jsonl
```

Prints (and writes `chunk_stats.json` with) document/chunk counts, a
breakdown by `doc_type` and `chunk_type`, min/avg/max token count, chunks
that exceed their type's configured limit, tiny narrative chunks (below
`NARRATIVE.min_tokens`), and empty/near-empty chunks.

## Inspecting individual chunks

```bash
# One chunk by line index, full text + metadata
.venv/bin/python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --index 42

# Filter by chunk_type / doc_type / source_file, or full-text search
.venv/bin/python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --chunk-type table
.venv/bin/python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --contains Carbaryl

# Summary lines only (index, type, tokens, location) instead of full text
.venv/bin/python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --chunk-type figure --list
```

## Chunking-strategy experiments

Compares four chunking strategies on **exactly the same parsed documents**
(each PDF is parsed once via the existing Document Intelligence adapter and
every strategy runs against that same parse; Excel files are read locally,
no Azure dependency):

| Strategy | What it does |
|---|---|
| `fixed` | Naive fixed-size token-window slicing. Ignores headings, tables, sentence/paragraph boundaries entirely — the baseline. |
| `recursive` | Recursive/semantic packing: whole paragraphs/rows packed up to the target size; an oversized single unit is recursively split at paragraph → line → sentence → word boundaries. Never cuts mid-sentence unless forced to. |
| `structure_aware` | Uses the document's own headings/tables (PDF) or blank-row/column blocks (Excel) as boundaries — the same *generic* signals the hybrid strategy is built on — but with none of hybrid's per-doc-type specialization (no NABL grouping, no Excel block-type classification, no entity/method-code extraction). |
| `hybrid` | **Reuses the existing document-type-aware pipeline as-is** (`chunkers/regulation.py`, `nabl_scope.py`, `brochure.py`, `excel_blocks.py` — no new logic), just tags each chunk's `strategy` metadata. |

```bash
# All four strategies, default sizing (chunk_size=400, overlap=60, max_chunk_size=700)
.venv/bin/python -m ticbot_chunking.scripts.run_chunking_experiments --input upadated_data_sgs

# One strategy only
.venv/bin/python -m ticbot_chunking.scripts.run_chunking_experiments \
    --input upadated_data_sgs --strategy hybrid

# Different token limits — writes to a separate output dir so both configurations are kept
.venv/bin/python -m ticbot_chunking.scripts.run_chunking_experiments \
    --input upadated_data_sgs --output-dir experiments_800 \
    --chunk-size 800 --overlap 100 --max-chunk-size 1200
```

Selectable: `--input` (scanned recursively for `.pdf`/`.xlsx`/`.xlsm`),
`--strategy` (`fixed` / `recursive` / `structure_aware` / `hybrid` / `all`,
default `all`), `--output-dir` (default `experiments`), `--chunk-size`,
`--overlap`, `--max-chunk-size`.

Output layout (matches the task's example):
```
experiments/
  fixed/chunks.jsonl            fixed/stats.json
  recursive/chunks.jsonl        recursive/stats.json
  structure_aware/chunks.jsonl  structure_aware/stats.json
  hybrid/chunks.jsonl           hybrid/stats.json
  comparison_report.json        regenerated from every stats.json currently in --output-dir,
                                 so it's accurate whether strategies were run together or
                                 across several separate invocations
```

Every chunk (regardless of strategy) uses the same `ChunkMetadata` schema —
`doc_type`, `chunk_type`, `source_file`, `tokens`, `pages`/`sheet`/`cell_range`,
and a `strategy` tag — so the four JSONL outputs are directly comparable.
Each strategy's `stats.json` reports: total chunks, avg/min/max tokens,
chunks by `doc_type`, chunks by `chunk_type`, pages/sheets covered, tiny
chunks (< 25% of `chunk_size`), and oversized chunks (> `max_chunk_size`).
`comparison_report.json` lays every strategy's stats side by side — **it
does not judge or recommend a strategy**, by design.

**On `--chunk-size`/`--overlap`/`--max-chunk-size` and the hybrid strategy:**
the existing hybrid chunkers read their limits from
`ticbot_chunking.config` (`NARRATIVE`/`REGULATION_TABLE`/`NABL_SCOPE`/`EXCEL_BLOCK`,
themselves env-var-overridable — see "Chunk size / overlap configuration"
above). `run_chunking_experiments.py` sets those `CHUNK_*_TOKENS`
environment variables at the very top of the script, before any
`ticbot_chunking` import, so a single invocation's chunk-size flags apply
uniformly to every strategy selected in that invocation, hybrid included,
without modifying the existing hybrid chunkers at all. To compare multiple
token-limit configurations, run the script again with different values and
a different `--output-dir` (as in the third example above).

## Chunk-quality / edge-case validation

Checks the chunks produced by every strategy for 12 things:

1. Table rows being split
2. Multi-page table continuity
3. Rowspan/merged-label carry-forward
4. Missing table headers
5. Missing section hierarchy
6. Missing source/page metadata
7. Incorrect NABL discipline/material grouping
8. Incorrect brochure reading order
9. Incorrect Excel block separation
10. Empty/tiny chunks
11. Excessive duplication
12. Token-limit violations

Two kinds of checks, both run by the same command:
- **Generic checks** (6, 10, 11, 12, plus 4/5/2) scan whatever
  `<experiments-dir>/<strategy>/chunks.jsonl` files already exist (from
  `run_chunking_experiments.py`).
- **Fixture-based checks** (1, 3, 7, 8, 9) build small, known-correct
  synthetic scenarios (the same kind of fixture the unit tests use) and run
  every strategy against them fresh — there's no ground truth to compare
  arbitrary real chunk text against for these, so a known scenario with a
  known-correct answer is used instead. These always run, need no Azure
  credentials, and don't depend on `--experiments-dir` having anything in it.

```bash
.venv/bin/python -m ticbot_chunking.scripts.run_validation --experiments-dir experiments
```

Writes:
- `<experiments-dir>/edge_case_report.md` — one `Edge Case | Expected | Actual | Pass/Fail`
  table per strategy (+ `.json`). **Does not declare a best strategy** —
  some rows are legitimately `N/A` where a strategy has no concept of a
  given capability by design (e.g. `fixed`/`recursive` have no section
  hierarchy or NABL grouping at all), which is reported as such rather than
  as a failure.
- `<experiments-dir>/<strategy>/inspection_report.md` — a human-readable,
  per-strategy chunk inspection report, grouped by source document, showing
  for every chunk: source document, page, section, chunk type, token count,
  full metadata, and the chunk text.

**Findings from the last real run** (see `experiments/edge_case_report.md`):
`hybrid` passes 10/13 applicable checks, `structure_aware` 8/10, `fixed`/`recursive`
6/9 each (the rest are `N/A`, not failures, for capabilities those strategies
don't attempt by design). Two real, non-obvious bugs were found and fixed
while building this validator (not pre-existing test gaps — this framework
caught them):
- `structure_aware`'s Excel path silently **dropped every single-row block**
  entirely (e.g. a lone "Total contacts: 21" summary line) — it assumed
  every detected block has a header row plus data rows, so a block with
  only one row found zero data rows and was skipped. Fixed.
- The *same* bug existed independently in the original hybrid
  `chunkers/excel_blocks.py` (`format_record_table`): a single-row block
  had its own values misread as a fake `"Columns:"` header, discarding the
  row's actual content. Fixed there too.

One real, un-fixed limitation surfaced and reported honestly rather than
patched over: `chunkers/brochure.py`'s `fix_reading_order` correctly
reorders a clean two-column body, but breaks when a full-width element
(e.g. a page-wide title) precedes the two columns — the title's wide
bounding box gets used as its column's reference width, and later items in
*both* real columns register as overlapping it, merging what should be two
columns into one. This affects `hybrid` too (the only strategy that
attempts reading-order correction at all) — see the
`"full-width title above 2-column body"` row in the report. Left as a
reported finding since this step is evaluation only.

## End-to-end ingestion (Blob Storage -> parsing -> chunking -> processing report)

**Azure Blob Storage is the sole ingestion source** — there is no
local-directory fallback. Runs the full pipeline in one command: lists
source documents from Blob Storage, downloads each, routes PDFs (page by
page — see "PDF parsing" above) and Excel files through the existing local
Excel parser, runs **all four, unmodified** chunking strategies against
every document, and writes a processing report. If Blob Storage isn't
configured, inaccessible, or returns no files, the run fails clearly
(naming the missing `AZURE_STORAGE_*` env var) instead of silently reading
local files.

```bash
.venv/bin/python -m ticbot_chunking.scripts.run_ingestion --output-dir experiments

# Only a folder of blobs
.venv/bin/python -m ticbot_chunking.scripts.run_ingestion --output-dir experiments --prefix "FSSAI Regulation/"
```

Writes the same `experiments/<strategy>/{chunks.jsonl,stats.json}` +
`comparison_report.json` layout as `run_chunking_experiments.py` (this
script supersedes it as the full ingestion entry point — same output
shape, sourced from Blob Storage instead of a bare local directory), plus:

- `experiments/processing_report.md` / `.json` — total files, PDF/Excel
  counts, text-based vs. scanned PDF counts, which parser processed each
  PDF, Excel sheets processed, total pages, chunks by strategy/doc_type/
  parser, per-document provenance, **processing failures** (filename,
  reason, parser attempted, error, whether retry is recommended — a
  document that fails never aborts the whole run or gets a fabricated
  result), and targeted validation of FSSAI regulation tables, NABL
  scopes, a scanned NABL certificate, brochure multi-column content,
  figures, multi-page tables, and Excel blocks — each reported as
  `available` (with the real finding, whatever it is) or `not_available`
  when that document type genuinely isn't in the current source set,
  never faked as passing.

Every chunk also carries a `parser` field (`local_pdf` /
`document_intelligence` / `excel_parser`) in its metadata, alongside the
existing `strategy` field, `source_file` (the real blob path — see "a real
bug" below), `pages`/`sheet`/`cell_range`, and `doc_type`.

**A real bug this step found and fixed:** `chunk_regulation` builds a
chunk's `source_file` from the parsed `LayoutDocument`'s own internal
`source_file` field — which is the *local temp file path* used while
downloading and parsing a blob during a run — rather than from
`DocumentMetadata.source_file` (the real blob path). Left alone, this would
silently leak the ingestion run's temp directory path into citation
metadata for every regulation-document chunk. `run_ingestion.py` corrects
`source_file` (and sets `parser`) for every chunk immediately after each
strategy call, at the orchestration layer — not by modifying
`chunkers/regulation.py` or any of the four chunking strategies themselves,
per this step's "do not change the four chunking strategies" requirement.
`ingest_from_blob.py` (an earlier step) already did the same
correction for its one hybrid-only chunks.jsonl output, which is why this
had gone unnoticed until testing all four strategies together surfaced it.

## Azure AI Search index creation (schema only — no embeddings, no upload)

Creates one Azure AI Search index per chunking strategy, so the four
strategies' outputs (`experiments/<strategy>/chunks.jsonl`) can later be
compared fairly instead of mixed into a single index:

| Strategy | Index name |
|---|---|
| fixed | `ticbot-chunks-fixed` |
| recursive | `ticbot-chunks-recursive` |
| structure_aware | `ticbot-chunks-structure` |
| hybrid | `ticbot-chunks-hybrid` |

This step is schema-only: `ticbot_chunking/search/schema.py` builds a
`SearchIndex` definition, `ticbot_chunking/search/index_manager.py`
creates/checks/recreates it, and `ticbot_chunking/search/validate.py`
checks the result — none of it reads `chunks.jsonl`, generates embeddings,
uploads documents, or runs a query.

```bash
# One strategy, default index name (ticbot-chunks-<strategy>)
.venv/bin/python -m ticbot_chunking.scripts.create_search_index --strategy fixed

# All four strategies at once
.venv/bin/python -m ticbot_chunking.scripts.create_search_index --strategy all

# Build + validate the schema locally without calling Azure AI Search at all
# (works even when AZURE_SEARCH_ADMIN_KEY isn't configured)
.venv/bin/python -m ticbot_chunking.scripts.create_search_index --strategy all --dry-run

# An index that already exists is always left untouched and reported as
# such, unless --recreate is passed explicitly
.venv/bin/python -m ticbot_chunking.scripts.create_search_index --strategy fixed --recreate
```

**Fields** (`ticbot_chunking/search/schema.py`) — every field is a direct
copy of an existing `ChunkMetadata` attribute (see
`ticbot_chunking/metadata/schema.py`) except: `chunk_id` (the required key
field — synthetic, since `ChunkMetadata` has no id of its own),
`chunking_strategy` (set by the loader from which strategy's `chunks.jsonl`
a chunk came from, not `ChunkMetadata.strategy`, which only the `hybrid`
strategy populates today), `blob_path` (an explicit alias of
`source_file`), and `document_type`/`parser_used` (`doc_type`/`parser`,
renamed for the index's external API):

- **Key**: `chunk_id`.
- **Full-text searchable**: `text` (the chunk content) and `section_path`
  (the human-readable heading trail) — nothing else is searchable by
  default, so filtering and full-text search stay clearly separated.
- **Filterable + facetable + sortable** (citation/comparison metadata):
  `chunking_strategy`, `document_type`, `chunk_type`, `parser_used`,
  `authority`, `lab_location`, `discipline`, `material`, `facility`,
  `access_class`.
- **Filterable only** (exact-match citation data, not meant to facet or
  sort): `source_file`, `blob_path`, `pages`, `section_number`,
  `certificate_no`, `sheet`, `cell_range`, `contains_pii`.
- **Vector field**: `chunk_vector` — `Collection(Edm.Single)`, dimension
  from `config.OPENAI.embedding_dimensions` (see below), in a `ticbot-hnsw`
  HNSW vector-search profile, ready for vector and hybrid (keyword + vector)
  queries once embeddings exist. A semantic configuration is also defined
  (title = `section_path`, content = `text`, keywords = `section_number`),
  ready for semantic re-ranking later — retrieval itself isn't implemented
  in this step.

**Vector dimension**: from `AZURE_OPENAI_EMBEDDING_DIMENSIONS` if set, else
a known default keyed by `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
(`config.KNOWN_EMBEDDING_DIMENSIONS`; 3072 for `text-embedding-3-large`,
the currently configured deployment) — never guessed silently: an
unresolvable dimension is a hard CLI error. The existing
`retrieval/embeddings.py` (used by the older single-index
`retrieval/azure_search_index.py`, see its docstring for how that index
differs from this one) now derives its `EMBEDDING_DIMENSIONS` constant from
this same config property instead of a separate hardcoded `3072`, so the
two can't silently drift apart.

**Index manager** (`ticbot_chunking/search/index_manager.py`): creates an
index, checks whether one exists, fetches a live index for validation, and
recreates one only when `--recreate` is passed explicitly — an existing
index is never silently overwritten.

**Live status**: `AZURE_SEARCH_ADMIN_KEY` is configured, and all four
indexes (`ticbot-chunks-fixed/recursive/structure/hybrid`) have been
created and live-validated against the real Azure AI Search service.

## Embedding + indexing (`scripts/index_chunks.py`)

Reads one strategy's `chunks.jsonl`, embeds each chunk's text with the
configured `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, and uploads it (keyed by a
stable `chunk_id` — see `search/chunk_id.py` — so re-indexing the same
chunks updates in place rather than duplicating) to that strategy's index:

```bash
python -m ticbot_chunking.scripts.index_chunks --strategy hybrid --chunks-dir experiments_blob
python -m ticbot_chunking.scripts.index_chunks --all   # must be explicit — never the default
```

All four real indexes are currently populated from the real Blob-sourced
`experiments_blob/` output: fixed 1,518 / recursive 1,493 / structure_aware
1,108 / hybrid 647 documents — matching their local `chunks.jsonl` line
counts exactly.

## Retrieval + evaluation (`scripts/search_chunks.py`, `run_retrieval_eval.py`, `evaluate_retrieval.py`)

`search/retrieval_client.py` is the one retrieval interface used everywhere
downstream (including the RAG service below) — keyword, vector, or hybrid
mode against any of the four indexes, with the query embedded via the same
deployment used for documents:

```bash
python -m ticbot_chunking.scripts.search_chunks --strategy hybrid --mode hybrid --query "..."
python -m ticbot_chunking.scripts.run_retrieval_eval          # full 20-question x 4-strategy x 3-mode matrix
python -m ticbot_chunking.scripts.evaluate_retrieval --question-id Q001   # side-by-side across all 4 strategies
```

See `evaluation/final_poc_retrieval_summary.md` for the full write-up,
including the real NABL scope chunking bug this evaluation surfaced and
fixed (0% -> 100% discipline/material/lab-location coverage).

## RAG backend (`ticbot_chunking/rag/` — grounded answers, no Streamlit yet)

Sits directly on top of the existing retrieval client — no second Azure AI
Search client, no separate vector store, no duplicated query-embedding
logic:

```
question -> retrieval_client.search(strategy, mode, question, top_k)
         -> context_builder.build_context(results)   # numbered sources, full provenance
         -> prompt.build_messages(question, context)  # the 10 grounding rules
         -> chat_client.complete_chat_with_retry(...)  # Azure OpenAI chat, retried on transient errors
         -> RagResponse(answer, citations, retrieved_chunks, ...)
```

```bash
python -m ticbot_chunking.scripts.ask_rag --question "What services are provided by SGS Molecular?"
python -m ticbot_chunking.scripts.ask_rag --question "..." --strategy fixed --mode vector --top-k 10
python -m ticbot_chunking.scripts.ask_rag --question "..." --json   # full RagResponse, for debugging
```

Defaults to `strategy="hybrid"` (the document-type-aware strategy) and
`mode=config.SEARCH.retrieval_mode` — `"vector"` unless the `RETRIEVAL_MODE`
env var is set to `"hybrid"` (manual testing found keyword mode unreliable —
see "Retrieval mode" below); both are configurable per call, matching
`retrieval_client.search()`'s own parameters exactly.

**Citation safety**: the LLM is shown numbered sources (`[1]`, `[2]`, ...)
and asked to cite them inline, but the structured `citations` returned to
the caller are built entirely from the corresponding retrieved chunk's real
metadata (`chunk_id`, `source_file`, `page`, `sheet`, `cell_range`,
`section`, and — when present — `certificate_no`/`lab_location`/
`discipline`/`material`) — never parsed or trusted from the LLM's own text
beyond *which* source numbers it referenced. A citation to a source number
the model was never given (a hallucinated `[99]`) is silently dropped, not
fabricated into a citation. If the model writes no `[N]` markers at all but
still gives a substantive answer, every source it was actually given is
cited (safe default); if it explicitly declines ("not enough information"),
no citations are returned even though the retrieved sources stay available
on the response for debugging.

**No-context handling**: an empty retrieval short-circuits before any LLM
call — `RagResponse.context_used=False`, the answer is the fixed
`NO_CONTEXT_ANSWER` sentence, and no Azure OpenAI cost is incurred.
Insufficient/irrelevant (but non-empty) retrieval is handled by the prompt
itself, which explicitly instructs the model to say so rather than guess.

**Configuration required**: `AZURE_OPENAI_CHAT_DEPLOYMENT` — configured in
this environment (`gpt-4.1`). `chat_client.require_chat_client()` raises a
clear, specific `RuntimeError` naming this exact variable when it's unset,
distinct from the general "Azure OpenAI is not configured" error.
Everything else (embedding deployment, Search endpoint/key) is reused
as-is from the existing `config.OPENAI` / `config.SEARCH`. Verified live:
2 real end-to-end questions (one PDF-prose, one NABL scope) answered
correctly with accurate citations against the real `ticbot-chunks-hybrid`
index and the real `gpt-4.1` chat deployment.

## Streamlit UI (`ticbot_chunking/app.py`)

A chat UI on top of the RAG backend above — it contains no retrieval,
embedding, or Azure OpenAI logic of its own; every question goes through
the same `rag_service.answer()` used by `scripts/ask_rag.py`.

```bash
streamlit run ticbot_chunking/app.py
```

Requires the same environment variables as the RAG backend
(`AZURE_SEARCH_ENDPOINT`/`AZURE_SEARCH_ADMIN_KEY`,
`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_API_KEY`/
`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`/`AZURE_OPENAI_CHAT_DEPLOYMENT`) — no
new configuration is introduced. The sidebar shows a ✅/❌ configured status
per component (endpoint/key values themselves are never displayed) rather
than requiring you to check `.env` directly.

**UI → backend call**: the Top-K number input (default 5) is passed
through to `rag_service.answer(question, strategy="hybrid",
mode=config.SEARCH.retrieval_mode, top_k=selected_top_k)` — the same call
`ask_rag.py` makes, just from a chat widget instead of `argparse`.
`strategy` is fixed to `"hybrid"` (the document-type-aware, bug-fixed
strategy). **There is no retrieval-mode picker in the UI** — manual
testing found keyword mode unreliable (it ranked the wrong document's
chunk #1 on several regulation questions, and failed a "lead in cocoa
powder"-style lookup entirely), while vector mode ranked the correct chunk
#1-#2 on every regulation question tested. Retrieval mode is a deployment
config (`RETRIEVAL_MODE=vector|hybrid`, default `vector`), not a per-query
UI choice; the sidebar's "Index" panel shows which mode is active for
reference.

**Citation display**: for each citation, the UI shows the source filename,
document type, and whichever of page(s) / sheet / cell range / section /
certificate number / laboratory / discipline / material the underlying
`Citation` object actually has (fields that don't apply to that source —
e.g. a page number on an Excel citation — are simply omitted, never shown
as blank). Each citation is also labelled with the `[N]` source number the
answer actually cited, recovered by matching the citation's `chunk_id`
back to its rank in `retrieved_chunks` — the UI never invents this number
or re-derives it from the answer text. An expandable "Retrieved sources"
section lists every chunk retrieval returned (cited or not), each with its
score and full metadata, for inspecting what the model had available.

**Error handling**: a missing/misconfigured Azure setting (`RuntimeError`
from the existing `require_chat_client()` / retrieval client) is shown as
a distinct "Configuration error" message; any other failure is shown as a
generic service error — neither crashes the app or leaves a dangling,
unanswered question in the chat history. An empty retrieval renders the
existing `NO_CONTEXT_ANSWER` sentence with no citations, exactly as
`ask_rag.py` would show it. Chat history lives only in
`st.session_state` (a "Clear chat" button resets it) — no database, no
persistence across a page refresh or a new session.

## Retrieval / citation-accuracy eval (Azure AI Search + Azure OpenAI — not run in this step)

```bash
.venv/bin/python -m ticbot_chunking.scripts.build_index output/chunks.jsonl
.venv/bin/python -m ticbot_chunking.scripts.run_eval qa_questions.json
```

`qa_questions.json` is a list of `{question, area, expected_source_file,
expected_pages | (expected_sheet, expected_cell_range)}` records — see
`ticbot_chunking/retrieval/qa_eval.py` for the exact schema. A starter file
is at `qa_questions.example.json`.

## Verified against real sample data (2026-09-24 stabilization pass)

All 3 real Excel workbooks (`Sample docs/`) now run end-to-end locally with
no Azure dependency — 26 chunks generated and spot-checked:
- `excel_blocks.chunk_excel_charts` correctly turned the real Summary sheet
  chart into `"Contacts by Location: Ahmedabad 3; Chennai 4; …"`, matching
  section 5D/6.5's worked example exactly.
- Filename-based doc-type routing (`guess_doc_type_from_filename`) correctly
  classified all 3 real workbooks (`capability_matrix`, `contact_directory`,
  and the `reference_register` fallback for the regulatory-links register).
- Fixed against the real Key Contacts workbook: an oversized `record_table`
  block that gets split row-by-row now gives each split chunk its own exact
  `cell_range` and correct "Row N" label — previously every split piece was
  tagged with the whole block's range and repeated the same row number.
- Fixed against the real Regulatory Links Register workbook: the "Licensed
  References" sheet's explicit "Access Classification" column (values like
  "Licensed" for full ISO/AOAC/ASTM/AOCS text) is now read and applied as
  each chunk's `access_class`, per section 7's access-control rule — it was
  previously ignored and defaulted to `public`.
- `contact_directory` documents (e.g. Key Contacts) are now automatically
  tagged `access_class="internal"` / `contains_pii=True` by the pipeline
  itself, per section 7, rather than requiring every caller to set it.

**Chunking-experiments + validation frameworks**, run against all 6 real
sample files (3 PDFs + 3 Excel workbooks) end-to-end — **entirely locally,
zero Azure calls**, since all 3 real sample PDFs turned out to be
text-based and route to the local parser (see "PDF parsing" above):
`fixed` 26 chunks, `recursive` 27, `structure_aware` 42, `hybrid` 42 (see
`experiments/edge_case_report.md` for the full pass/fail table). Two real
bugs the local-parser work surfaced and fixed along the way, beyond the
parser itself:
- `structure_aware`'s narrative chunks tracked section headings internally
  (visible in the chunk header text) but never actually stored
  `section_path` in chunk metadata at all — found because the validation
  framework's "missing section hierarchy" check flagged 24/24 chunks. Fixed.
- Because `structure_aware` reuses the `recursive` strategy's row/paragraph
  packer (`_pack_units`) for its own narrative chunks, every one of its
  narrative chunks was mistagged `strategy: "recursive"` instead of
  `"structure_aware"` in metadata — `_pack_units` now takes an explicit
  `strategy` argument instead of hardcoding its own module's constant.

Also fixed while building the local parser itself (found against the real
FSSAI regulation sample, which conveys almost all of its structure through
text convention — "CHAPTER 2", "2.3.1: ..." — with zero font/size
distinction from body text): a first pass detected headings only by font
size/boldness and found none; adding a textual signal (reusing
`chunkers/section_numbering.py`'s `CHAPTER_RE`/`ANNEXURE_RE`, plus a new
conservative dotted-numbering pattern capped at 7 title words) correctly
picked up "CHAPTER 1", "CHAPTER 2", "1.1: Short title...", "2.1: METAL
CONTAMINANTS" etc., while *not* misreading numbered body clauses that share
the same "x.y.z:" numbering convention (e.g. "1.1.2: These regulations
shall come into force on or after 5th August, 2011") as headings.

## Known gaps / remaining limitations

- **Mixed text/scanned PDFs are now routed per page, not as a whole
  document.** `parsers/page_classifier.py` classifies every page
  (TEXT/SCANNED/AMBIGUOUS) and `parsers/page_router.py` sends only the
  SCANNED/AMBIGUOUS pages to Document Intelligence's page-selection API
  (e.g. `pages="41,81-82"`), never the whole document — wired into both
  `pipeline.process_pdf` and `ingestion.orchestrator.ingest_document`.
  `KNOWN_ISSUES.md` has the full detail and test references.
- **Local table detection only finds ruling-line tables.** Whitespace-
  aligned tables with no drawn lines (confirmed present in the real FSSAI
  sample) come through as plain paragraph text, not a `Table` — deliberate,
  to avoid the alternative (pdfplumber's text-alignment strategy), which
  was confirmed to badly mis-segment ordinary prose into garbled fake table
  cells on this exact document. Document Intelligence's ML layout model
  handles un-ruled tables; the local parser doesn't.
  Rowspan/colspan also isn't reconstructed locally (pdfplumber returns a
  plain grid); DI detects it natively.
  No NABL scope of accreditation PDFs are available yet to test this against
  a real ruled table, though `nabl_scope.py` supports two possible
  real-world table shapes — confirm and adjust `_group_context`/
  `COLUMN_SYNONYMS` once one is available.
- **Local heading/title detection can find little or nothing on
  heavily graphic-design-styled documents.** Confirmed against one of the
  three real brochure samples: no consistent body-text font size/style and
  no textual numbering convention meant zero headings and no title were
  detected, so the whole document came back as one large chunk with an
  empty `section_path` — the underlying text content is still fully
  preserved, just less finely segmented than Document Intelligence's
  ML-based role classification would produce.
- The 60-question QA set and the specific hit-rate numbers in section 8 of
  the strategy doc were produced by SGS's own earlier test run; this repo
  ships the harness (`run_eval.py`) to reproduce that methodology on Azure,
  not a canned copy of those results. Azure AI Search / Azure OpenAI /
  Streamlit remain explicitly out of scope through this step.
