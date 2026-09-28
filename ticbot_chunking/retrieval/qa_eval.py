"""Retrieval and citation accuracy test harness — section 8 of
TICbot_Chunking_Strategy_Answers.md.

Runs a hybrid (keyword + vector) query per question against the Azure AI
Search index and reports hit@1/5/10 and MRR@10, grouped by area, plus a
citation-accuracy check (does the top-ranked hit's source_file and
page/sheet match what's expected).

QA file format (JSON list):
    {
      "question": "...",
      "area": "NABL scopes" | "FSSAI regulation" | "Brochures" | "Excel workbooks",
      "expected_source_file": "Contaminants_Regulations_pages_1-5.pdf",
      "expected_pages": [5, 6],        # for PDFs
      "expected_sheet": "Key Contacts",  # for Excel
      "expected_cell_range": "A5:H10"    # for Excel, optional substring match
    }

A "hit" mirrors section 8's definition: the returned chunk's source_file
matches, and either its pages overlap `expected_pages` or its sheet matches
`expected_sheet` (with `expected_cell_range` checked as a substring/overlap
when given).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ticbot_chunking.config import SEARCH
from ticbot_chunking.retrieval.embeddings import embed_query


@dataclass
class QAItem:
    question: str
    area: str
    expected_source_file: str
    expected_pages: list[int] = field(default_factory=list)
    expected_sheet: str | None = None
    expected_cell_range: str | None = None


def load_qa_file(path: str) -> list[QAItem]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [QAItem(**item) for item in raw]


def _is_citation_hit(item: QAItem, doc: dict) -> bool:
    if doc.get("source_file") != item.expected_source_file:
        return False
    if item.expected_sheet:
        if doc.get("sheet") != item.expected_sheet:
            return False
        if item.expected_cell_range and doc.get("cell_range"):
            return item.expected_cell_range in doc["cell_range"] or doc["cell_range"] in item.expected_cell_range
        return True
    if item.expected_pages:
        return bool(set(doc.get("pages") or []) & set(item.expected_pages))
    return True


def _require_search_client():
    if not SEARCH.is_configured:
        raise RuntimeError(
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY."
        )
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    return SearchClient(endpoint=SEARCH.endpoint, index_name=SEARCH.index_name,
                         credential=AzureKeyCredential(SEARCH.admin_key))


def run_query(client, question: str, top: int = 10) -> list[dict]:
    from azure.search.documents.models import VectorizedQuery

    vector_query = VectorizedQuery(vector=embed_query(question), k_nearest_neighbors=top, fields="content_vector")
    results = client.search(search_text=question, vector_queries=[vector_query], top=top)
    return list(results)


@dataclass
class AreaStats:
    n: int = 0
    hit_at_1: int = 0
    hit_at_5: int = 0
    hit_at_10: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "questions": self.n,
            "hit@1": self.hit_at_1,
            "hit@1_pct": round(100 * self.hit_at_1 / self.n, 1) if self.n else 0.0,
            "hit@5": self.hit_at_5,
            "hit@5_pct": round(100 * self.hit_at_5 / self.n, 1) if self.n else 0.0,
            "hit@10": self.hit_at_10,
            "mrr@10": round(sum(self.reciprocal_ranks) / self.n, 3) if self.n else 0.0,
        }


def run_eval(qa_path: str, top: int = 10) -> dict:
    client = _require_search_client()
    items = load_qa_file(qa_path)

    stats_by_area: dict[str, AreaStats] = {}
    details = []

    for item in items:
        docs = run_query(client, item.question, top=top)
        rank = None
        for i, doc in enumerate(docs, start=1):
            if _is_citation_hit(item, doc):
                rank = i
                break

        stats = stats_by_area.setdefault(item.area, AreaStats())
        stats.n += 1
        if rank is not None:
            if rank == 1:
                stats.hit_at_1 += 1
            if rank <= 5:
                stats.hit_at_5 += 1
            if rank <= 10:
                stats.hit_at_10 += 1
            stats.reciprocal_ranks.append(1.0 / rank)
        else:
            stats.reciprocal_ranks.append(0.0)

        details.append({"question": item.question, "area": item.area, "rank": rank})

    total = AreaStats()
    for s in stats_by_area.values():
        total.n += s.n
        total.hit_at_1 += s.hit_at_1
        total.hit_at_5 += s.hit_at_5
        total.hit_at_10 += s.hit_at_10
        total.reciprocal_ranks.extend(s.reciprocal_ranks)

    return {
        "by_area": {area: s.as_dict() for area, s in stats_by_area.items()},
        "total": total.as_dict(),
        "details": details,
    }
