"""JSON reporter – serialises TestSuiteResult to a structured JSON file.

The output is designed for consumption by CI/CD dashboards and the
HTML reporter's JavaScript frontend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from gnss_framework.reporting.models import TestSuiteResult


class JSONReporter:
    """Write a ``TestSuiteResult`` to a JSON file.

    Args:
        output_dir: Directory where the report file is written.
                    Created automatically if it does not exist.
    """

    def __init__(self, output_dir: str | Path = "reports") -> None:
        self._output_dir = Path(output_dir)

    def write(self, suite: TestSuiteResult, filename: str | None = None) -> Path:
        """Serialise *suite* and write to *filename* inside ``output_dir``.

        Returns the path of the written file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            filename = f"{suite.suite_name.replace(' ', '_')}_{ts}.json"

        payload = self._build_payload(suite)
        path = self._output_dir / filename
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(suite: TestSuiteResult) -> dict:
        return {
            "suite_name": suite.suite_name,
            "started_at": datetime.fromtimestamp(suite.started_at, tz=timezone.utc).isoformat(),
            "finished_at": (
                datetime.fromtimestamp(suite.finished_at, tz=timezone.utc).isoformat()
                if suite.finished_at
                else None
            ),
            "summary": {
                "total": suite.total,
                "passed": suite.passed,
                "failed": suite.failed,
                "errors": suite.errors,
                "skipped": suite.skipped,
                "pass_rate_pct": round(suite.pass_rate, 2),
                "total_duration_s": round(suite.total_duration_s, 4),
            },
            "metadata": suite.metadata,
            "results": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "duration_s": round(r.duration_s, 6),
                    "message": r.message,
                    "metadata": r.metadata,
                }
                for r in suite.results
            ],
        }
