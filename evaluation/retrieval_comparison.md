# Retrieval Strategy Comparison Report

Generated: 2026-09-24T20:18:24.605711+00:00
Questions: 20  |  top_k: 5  |  Strategy/mode combinations tested: 12

**No strategy is automatically ranked or declared a winner.** The table below reports measurements only, per (strategy, mode) combination, run against the identical question set and top_k.

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Citation Precision | Avg Score | Avg Results | Empty | Avg Latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed | keyword | 0.789 | 0.947 | 0.947 | 0.947 | 0.579 | 21.220 | 4.850 | 0 | 1.097 |
| fixed | vector | 0.895 | 1.000 | 1.000 | 1.000 | 0.604 | 0.701 | 4.900 | 0 | 1.687 |
| fixed | hybrid | 0.947 | 1.000 | 1.000 | 1.000 | 0.604 | 0.029 | 4.900 | 0 | 1.851 |
| recursive | keyword | 0.789 | 0.947 | 1.000 | 1.000 | 0.621 | 19.647 | 4.850 | 0 | 1.139 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.625 | 0.696 | 4.900 | 0 | 1.602 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.614 | 0.029 | 4.900 | 0 | 1.806 |
| structure_aware | keyword | 0.842 | 0.842 | 0.842 | 0.842 | 0.558 | 28.420 | 4.850 | 0 | 1.038 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.688 | 0.713 | 4.900 | 0 | 1.614 |
| structure_aware | hybrid | 0.947 | 1.000 | 1.000 | 1.000 | 0.688 | 0.028 | 4.900 | 0 | 1.763 |
| hybrid | keyword | 0.684 | 0.842 | 0.895 | 0.895 | 0.537 | 22.935 | 5.000 | 0 | 1.072 |
| hybrid | vector | 0.895 | 1.000 | 1.000 | 1.000 | 0.705 | 0.714 | 5.000 | 0 | 1.611 |
| hybrid | hybrid | 0.895 | 1.000 | 1.000 | 1.000 | 0.705 | 0.028 | 5.000 | 0 | 1.716 |

Hit@K / Source Recall / Citation Precision are computed over 19 of 20 questions that have verifiable ground truth (the rest have `ground_truth_status: not_available` and are excluded from these metrics — but were still run; see the raw per-question results under evaluation/results/).

## Questions without verifiable ground truth

| Question ID | Category | Reason |
|---|---|---|
| Q008 | E | NOT INDEXED: the real scanned certificate PDF (534MB, 2309 pages) was intentionally excluded from the real Blob ingestion run (see processing_report.md) to keep that run's duration reasonable. No certificate-type chunk exists in any of the four indexes. This question has no retrievable ground truth and is included specifically to observe how each strategy/mode behaves when no correct document exists (expected: no confident hit). |

## Document-type / category breakdown

The same measurements as above, split by question category, so a strategy's behavior on (for example) NABL scope data can be compared against its behavior on Excel blocks or page-specific PDF questions. Each category's questions are the same across every strategy/mode — only the underlying data characteristic differs. No winner is computed here either.

### Category A — Normal prose/content (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 0.500 | 0.500 | 0.500 | 0.500 | 14.005 | 1.172 |
| fixed | vector | 0.000 | 1.000 | 1.000 | 1.000 | 0.662 | 1.790 |
| fixed | hybrid | 0.500 | 1.000 | 1.000 | 1.000 | 0.031 | 1.912 |
| recursive | keyword | 0.500 | 0.500 | 1.000 | 1.000 | 13.350 | 1.182 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.660 | 1.561 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.030 | 1.959 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 18.522 | 1.057 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.681 | 1.521 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.700 |
| hybrid | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 16.335 | 1.010 |
| hybrid | vector | 0.500 | 1.000 | 1.000 | 1.000 | 0.689 | 1.446 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.030 | 1.785 |

### Category B — Headings and sections (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 26.274 | 1.017 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.737 | 1.754 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.029 | 1.805 |
| recursive | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 22.859 | 1.178 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.733 | 1.657 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.771 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 44.085 | 1.073 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.791 | 1.526 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.032 | 1.813 |
| hybrid | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 30.201 | 1.109 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.752 | 1.620 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.665 |

### Category C — Multi-page tables (1 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 0.000 | 1.000 | 1.000 | 1.000 | 22.719 | 0.993 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.712 | 1.520 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.029 | 1.784 |
| recursive | keyword | 0.000 | 1.000 | 1.000 | 1.000 | 19.170 | 1.182 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.710 | 1.684 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.026 | 1.816 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 28.789 | 1.058 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.715 | 1.802 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.876 |
| hybrid | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 35.488 | 1.183 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.725 | 1.622 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.030 | 1.934 |

### Category D — NABL scope information (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 8.799 | 1.057 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.699 | 1.693 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.022 | 1.814 |
| recursive | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 8.539 | 1.199 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.693 | 1.551 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.023 | 1.786 |
| structure_aware | keyword | 0.000 | 0.000 | 0.000 | 0.000 | 13.270 | 1.033 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.707 | 1.635 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.020 | 1.824 |
| hybrid | keyword | 0.000 | 0.000 | 0.000 | 0.000 | 16.006 | 1.178 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.704 | 1.662 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.019 | 1.664 |

### Category E — Certificate/lab information (1 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | n/a | n/a | n/a | n/a | 17.633 | 0.982 |
| fixed | vector | n/a | n/a | n/a | n/a | 0.728 | 1.748 |
| fixed | hybrid | n/a | n/a | n/a | n/a | 0.023 | 2.214 |
| recursive | keyword | n/a | n/a | n/a | n/a | 18.216 | 1.264 |
| recursive | vector | n/a | n/a | n/a | n/a | 0.718 | 1.714 |
| recursive | hybrid | n/a | n/a | n/a | n/a | 0.024 | 1.744 |
| structure_aware | keyword | n/a | n/a | n/a | n/a | 17.216 | 1.041 |
| structure_aware | vector | n/a | n/a | n/a | n/a | 0.742 | 1.675 |
| structure_aware | hybrid | n/a | n/a | n/a | n/a | 0.021 | 1.805 |
| hybrid | keyword | n/a | n/a | n/a | n/a | 21.423 | 1.023 |
| hybrid | vector | n/a | n/a | n/a | n/a | 0.718 | 1.789 |
| hybrid | hybrid | n/a | n/a | n/a | n/a | 0.019 | 1.529 |

### Category F — Excel contact information (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 28.253 | 1.111 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.673 | 1.704 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.032 | 1.935 |
| recursive | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 27.562 | 1.314 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.668 | 1.545 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.032 | 1.860 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 24.251 | 1.056 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.681 | 1.592 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.028 | 1.702 |
| hybrid | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 24.080 | 1.023 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.704 | 1.723 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.887 |

### Category G — Excel structured blocks (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 21.110 | 1.058 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.708 | 1.649 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.029 | 1.707 |
| recursive | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 19.308 | 1.086 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.700 | 1.523 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.029 | 1.909 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 20.982 | 1.038 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.704 | 1.656 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.030 | 1.799 |
| hybrid | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 22.681 | 1.030 |
| hybrid | vector | 0.500 | 1.000 | 1.000 | 1.000 | 0.738 | 1.729 |
| hybrid | hybrid | 0.500 | 1.000 | 1.000 | 1.000 | 0.032 | 1.609 |

### Category H — Page-specific questions (3 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 25.728 | 1.157 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.721 | 1.712 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.030 | 1.953 |
| recursive | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 25.043 | 1.088 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.719 | 1.599 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.831 |
| structure_aware | keyword | 0.667 | 0.667 | 0.667 | 0.667 | 48.081 | 1.019 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.735 | 1.512 |
| structure_aware | hybrid | 0.667 | 1.000 | 1.000 | 1.000 | 0.031 | 1.746 |
| hybrid | keyword | 0.667 | 0.667 | 1.000 | 1.000 | 26.202 | 1.036 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.728 | 1.546 |
| hybrid | hybrid | 0.667 | 1.000 | 1.000 | 1.000 | 0.030 | 1.626 |

### Category I — Metadata-filter questions (3 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 22.380 | 1.156 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.674 | 1.562 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.027 | 1.720 |
| recursive | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 20.025 | 1.022 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.666 | 1.617 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.028 | 1.592 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 21.981 | 1.001 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.676 | 1.723 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.026 | 1.697 |
| hybrid | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 16.917 | 1.138 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.675 | 1.602 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.028 | 1.589 |

### Category J — Long-context questions (2 question(s))

| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |
|---|---|---|---|---|---|---|---|
| fixed | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 21.422 | 1.101 |
| fixed | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.714 | 1.739 |
| fixed | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.833 |
| recursive | keyword | 0.500 | 1.000 | 1.000 | 1.000 | 18.551 | 1.047 |
| recursive | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.715 | 1.663 |
| recursive | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.861 |
| structure_aware | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 34.988 | 1.047 |
| structure_aware | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.723 | 1.618 |
| structure_aware | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.029 | 1.785 |
| hybrid | keyword | 1.000 | 1.000 | 1.000 | 1.000 | 26.912 | 1.005 |
| hybrid | vector | 1.000 | 1.000 | 1.000 | 1.000 | 0.729 | 1.505 |
| hybrid | hybrid | 1.000 | 1.000 | 1.000 | 1.000 | 0.031 | 1.993 |