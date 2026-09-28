"""Shared result type for the chunk-quality / edge-case validation
framework.

Every check (generic corpus scan or fixture-based scenario) reports one or
more `EdgeCaseResult` rows, which `report.py` renders as the
"Edge Case | Expected | Actual | Pass/Fail" table.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EdgeCaseResult:
    edge_case: str      # short name, e.g. "Missing table headers"
    strategy: str        # fixed | recursive | structure_aware | hybrid
    expected: str
    actual: str
    passed: bool | None  # None = not applicable to this strategy/corpus (not a failure)
    details: str = ""

    @property
    def status(self) -> str:
        if self.passed is None:
            return "N/A"
        return "PASS" if self.passed else "FAIL"
