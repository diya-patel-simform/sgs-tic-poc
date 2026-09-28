"""Generic edge-case checks that scan an already-generated
`experiments/<strategy>/chunks.jsonl` corpus directly (as opposed to
`fixture_checks.py`, which builds known synthetic scenarios). These check
properties that hold — or should hold — across any real chunk corpus
regardless of what document produced it.
"""
from __future__ import annotations

from collections import Counter

from ticbot_chunking.validation.edge_cases import EdgeCaseResult

TABLE_LIKE_CHUNK_TYPES = {"table", "scope_records", "sheet_table"}
EMPTY_TINY_TOKEN_THRESHOLD = 5  # matches MIN_CONTENT_TOKENS used across the chunkers


def _na(edge_case: str, strategy: str, reason: str) -> EdgeCaseResult:
    return EdgeCaseResult(edge_case=edge_case, strategy=strategy, expected="(not applicable to this corpus)",
                           actual=reason, passed=None)


def check_missing_source_page_metadata(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Missing source/page metadata"
    if not rows:
        return _na(edge_case, strategy, "no chunks produced")
    missing = [i for i, r in enumerate(rows) if not r["metadata"].get("source_file")
               or not (r["metadata"].get("pages") or r["metadata"].get("sheet"))]
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="Every chunk has source_file and either pages or sheet",
        actual=f"{len(missing)}/{len(rows)} chunk(s) missing citation metadata",
        passed=len(missing) == 0,
        details=f"indices: {missing[:10]}" if missing else "",
    )


def check_empty_tiny_chunks(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Empty/tiny chunks"
    if not rows:
        return _na(edge_case, strategy, "no chunks produced")
    tiny = [i for i, r in enumerate(rows)
            if r["metadata"].get("tokens", 0) < EMPTY_TINY_TOKEN_THRESHOLD or not r["text"].strip()]
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected=f"No chunk under {EMPTY_TINY_TOKEN_THRESHOLD} tokens or with empty text",
        actual=f"{len(tiny)}/{len(rows)} chunk(s) empty or near-empty",
        passed=len(tiny) == 0,
        details=f"indices: {tiny[:10]}" if tiny else "",
    )


def check_excessive_duplication(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Excessive duplication"
    if not rows:
        return _na(edge_case, strategy, "no chunks produced")
    counts = Counter(r["text"] for r in rows)
    dupes = {t: c for t, c in counts.items() if c > 1}
    total_dupe_chunks = sum(dupes.values())
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="No exact-duplicate chunk text",
        actual=f"{len(dupes)} distinct text(s) duplicated across {total_dupe_chunks} chunk(s)",
        passed=len(dupes) == 0,
    )


def check_token_limit_violations(rows: list[dict], strategy: str, limit_fn) -> EdgeCaseResult:
    edge_case = "Token-limit violations"
    if not rows:
        return _na(edge_case, strategy, "no chunks produced")
    violations = []
    for i, r in enumerate(rows):
        limit = limit_fn(r["metadata"].get("chunk_type"))
        tokens = r["metadata"].get("tokens", 0)
        if limit and tokens > limit:
            violations.append((i, tokens, limit))
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="No chunk exceeds its configured token limit",
        actual=f"{len(violations)}/{len(rows)} chunk(s) exceed their limit",
        passed=len(violations) == 0,
        details=str(violations[:10]) if violations else "",
    )


def check_missing_table_headers(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Missing table headers"
    table_rows = [r for r in rows if r["metadata"].get("chunk_type") in TABLE_LIKE_CHUNK_TYPES]
    if not table_rows:
        return _na(edge_case, strategy, "no table-type chunks in this corpus")

    def has_header(row: dict) -> bool:
        meta = row["metadata"]
        if meta.get("row_count") == 1:
            # A single isolated row (e.g. a lone "Total contacts: 21"
            # summary line) has no separate header row to repeat — this is
            # expected, not a defect.
            return True
        text = row["text"]
        if meta.get("chunk_type") == "scope_records":
            return "Accredited tests:" in text
        return "| --- |" in text or "|---|" in text.replace(" ", "") or "Columns:" in text

    missing = [i for i, r in enumerate(table_rows) if not has_header(r)]
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="Every table-type chunk repeats a recognizable header/intro line (except a lone single-row chunk, which has none to repeat)",
        actual=f"{len(missing)}/{len(table_rows)} table chunk(s) missing a header",
        passed=len(missing) == 0,
        details=f"indices: {missing[:10]}" if missing else "",
    )


def check_missing_section_hierarchy(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Missing section hierarchy"
    if strategy in ("fixed", "recursive"):
        return EdgeCaseResult(
            edge_case=edge_case, strategy=strategy,
            expected="N/A — this strategy has no structural awareness by design",
            actual="section_path is always empty, as expected",
            passed=None,
        )
    relevant = [r for r in rows if r["metadata"].get("chunk_type") in ("text", "table")
                and r["metadata"].get("source_file", "").lower().endswith(".pdf")]
    if not relevant:
        return _na(edge_case, strategy, "no PDF text/table chunks in this corpus")
    missing = [i for i, r in enumerate(relevant) if not r["metadata"].get("section_path")]
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="Every PDF text/table chunk has a non-empty section_path",
        actual=f"{len(missing)}/{len(relevant)} chunk(s) missing section_path",
        passed=len(missing) == 0,
        details=f"indices: {missing[:10]}" if missing else "",
    )


def check_multi_page_table_continuity(rows: list[dict], strategy: str) -> EdgeCaseResult:
    edge_case = "Multi-page table continuity"
    multi_page = [r for r in rows if len(r["metadata"].get("pages") or []) > 1]
    if not multi_page:
        return _na(edge_case, strategy, "no multi-page chunks in this corpus")
    bad = []
    for i, r in enumerate(multi_page):
        meta = r["metadata"]
        malformed = meta.get("tokens", 0) <= 0 or not r["text"].strip()
        if meta.get("chunk_type") in TABLE_LIKE_CHUNK_TYPES and not meta.get("row_count"):
            malformed = True
        if malformed:
            bad.append(i)
    return EdgeCaseResult(
        edge_case=edge_case, strategy=strategy,
        expected="Chunks spanning multiple pages stay well-formed (non-empty; row_count set for table types)",
        actual=f"{len(bad)}/{len(multi_page)} multi-page chunk(s) malformed",
        passed=len(bad) == 0,
        details=f"indices: {bad[:10]}" if bad else "",
    )


def run_all_generic_checks(rows: list[dict], strategy: str, limit_fn) -> list[EdgeCaseResult]:
    return [
        check_missing_source_page_metadata(rows, strategy),
        check_empty_tiny_chunks(rows, strategy),
        check_excessive_duplication(rows, strategy),
        check_token_limit_violations(rows, strategy, limit_fn),
        check_missing_table_headers(rows, strategy),
        check_missing_section_hierarchy(rows, strategy),
        check_multi_page_table_continuity(rows, strategy),
    ]
