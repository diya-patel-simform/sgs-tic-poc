"""Retrieval-evaluation metrics for the chunking-strategy comparison.

Every metric is reported as measured, per (strategy, mode) combination —
this module never ranks combinations or declares a "winner"; that judgment
call is left to whoever reads the report.

A question only contributes to the ground-truth-based metrics (Hit@K,
source recall, citation precision) when its `ground_truth_status` is
"available" or "partial" — a `"not_available"` question (no correct
document exists in the corpus at all) is still run and its raw retrieval
behavior recorded, just excluded from metrics that would otherwise unfairly
count "no hit" against every strategy for a question no strategy could
possibly answer correctly.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class Question:
    question_id: str
    category: str
    question: str
    expected_source_file: str | None
    expected_pages: list[int] | None
    expected_sheet: str | None
    expected_cell_range: str | None
    expected_metadata: dict | None
    suggested_filter: str | None
    ground_truth_status: str  # "available" | "partial" | "not_available"
    notes: str

    @property
    def has_ground_truth(self) -> bool:
        return self.ground_truth_status != "not_available" and bool(self.expected_source_file)


def load_questions(path) -> list[Question]:
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(Question(**json.loads(line)))
    return questions


def is_relevant(result, question: Question) -> bool:
    """A retrieved result counts as relevant to `question` if it's from the
    expected source file, and (when specified) overlaps the expected
    page(s) and/or matches the expected sheet — page/sheet use overlap
    rather than exact-list equality since different chunking strategies
    split the same source content into different page/row spans."""
    if not question.expected_source_file or result.source_file != question.expected_source_file:
        return False
    if question.expected_pages:
        if not (set(result.pages or []) & set(question.expected_pages)):
            return False
    if question.expected_sheet and result.sheet != question.expected_sheet:
        return False
    return True


@dataclass
class QuestionOutcome:
    question_id: str
    category: str
    strategy: str
    mode: str
    has_ground_truth: bool
    hit_at_1: bool | None
    hit_at_3: bool | None
    hit_at_5: bool | None
    first_relevant_rank: int | None
    num_results: int
    num_relevant_in_top_k: int
    avg_score: float | None
    latency_seconds: float
    empty: bool

    def to_dict(self):
        return asdict(self)


def score_query_result(query_result, question: Question) -> QuestionOutcome:
    results = query_result.results
    relevant_ranks = sorted(r.rank for r in results if is_relevant(r, question))

    def hit_at(k: int) -> bool | None:
        return any(rank <= k for rank in relevant_ranks) if question.has_ground_truth else None

    scores = [r.score for r in results if r.score is not None]

    return QuestionOutcome(
        question_id=question.question_id, category=question.category,
        strategy=query_result.strategy, mode=query_result.mode,
        has_ground_truth=question.has_ground_truth,
        hit_at_1=hit_at(1), hit_at_3=hit_at(3), hit_at_5=hit_at(5),
        first_relevant_rank=relevant_ranks[0] if relevant_ranks else None,
        num_results=len(results), num_relevant_in_top_k=len(relevant_ranks),
        avg_score=(sum(scores) / len(scores)) if scores else None,
        latency_seconds=query_result.latency_seconds, empty=(len(results) == 0),
    )


@dataclass
class AggregateMetrics:
    strategy: str
    mode: str
    top_k: int
    num_questions: int
    num_scored_questions: int
    hit_at_1: float | None
    hit_at_3: float | None
    hit_at_5: float | None
    source_recall: float | None
    citation_precision: float | None
    avg_num_results: float
    avg_score: float | None
    empty_retrieval_count: int
    avg_latency_seconds: float
    category: str | None = None  # set only for a per-category breakdown row; None for the overall row

    def to_dict(self):
        return asdict(self)


def aggregate(outcomes: list[QuestionOutcome], strategy: str, mode: str, top_k: int,
              category: str | None = None) -> AggregateMetrics:
    scored = [o for o in outcomes if o.has_ground_truth]

    def rate(attr: str) -> float | None:
        return (sum(1 for o in scored if getattr(o, attr)) / len(scored)) if scored else None

    source_recall = (sum(1 for o in scored if o.num_relevant_in_top_k > 0) / len(scored)) if scored else None
    citation_precision = (
        sum((o.num_relevant_in_top_k / o.num_results) if o.num_results else 0.0 for o in scored) / len(scored)
    ) if scored else None

    scores = [o.avg_score for o in outcomes if o.avg_score is not None]
    latencies = [o.latency_seconds for o in outcomes]

    return AggregateMetrics(
        strategy=strategy, mode=mode, top_k=top_k,
        num_questions=len(outcomes), num_scored_questions=len(scored),
        hit_at_1=rate("hit_at_1"), hit_at_3=rate("hit_at_3"), hit_at_5=rate("hit_at_5"),
        source_recall=source_recall, citation_precision=citation_precision,
        avg_num_results=(sum(o.num_results for o in outcomes) / len(outcomes)) if outcomes else 0.0,
        avg_score=(sum(scores) / len(scores)) if scores else None,
        empty_retrieval_count=sum(1 for o in outcomes if o.empty),
        avg_latency_seconds=(sum(latencies) / len(latencies)) if latencies else 0.0,
        category=category,
    )


def aggregate_by_category(outcomes: list[QuestionOutcome], strategy: str, mode: str,
                           top_k: int) -> list[AggregateMetrics]:
    """One AggregateMetrics per question category present in `outcomes`, in
    first-seen order — the same metrics as `aggregate()`, just scoped to
    each category's own questions, so a strategy's behavior on (for example)
    NABL scope data can be compared against its behavior on Excel blocks."""
    categories: list[str] = []
    by_category: dict[str, list[QuestionOutcome]] = {}
    for outcome in outcomes:
        if outcome.category not in by_category:
            categories.append(outcome.category)
            by_category[outcome.category] = []
        by_category[outcome.category].append(outcome)

    return [aggregate(by_category[c], strategy, mode, top_k, category=c) for c in categories]
