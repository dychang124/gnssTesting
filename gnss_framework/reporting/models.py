"""Shared data models for test result reporting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TestStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class TestResult:
    """Result for a single test case."""

    name: str
    status: TestStatus
    duration_s: float
    message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSuiteResult:
    """Aggregated results for a complete test suite run."""

    suite_name: str
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    results: list[TestResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, result: TestResult) -> None:
        self.results.append(result)

    def finish(self) -> None:
        self.finished_at = time.time()

    # ------------------------------------------------------------------
    # Computed summary stats
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.SKIPPED)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0

    @property
    def total_duration_s(self) -> float:
        if self.finished_at:
            return self.finished_at - self.started_at
        return sum(r.duration_s for r in self.results)
