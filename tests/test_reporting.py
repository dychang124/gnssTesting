"""Tests for JSON and HTML reporters.

Validates:
- JSONReporter output structure and content
- HTMLReporter output is valid HTML with correct data
- TestSuiteResult summary statistics
- Report filenames and output directory creation
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from gnss_framework.reporting.models import TestResult, TestStatus, TestSuiteResult
from gnss_framework.reporting.json_reporter import JSONReporter
from gnss_framework.reporting.html_reporter import HTMLReporter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_suite(tmp_path) -> TestSuiteResult:
    suite = TestSuiteResult(suite_name="GNSS Regression Suite")
    suite.add(TestResult(name="test_gga_parsing", status=TestStatus.PASSED, duration_s=0.012))
    suite.add(TestResult(name="test_rmc_parsing", status=TestStatus.PASSED, duration_s=0.008))
    suite.add(TestResult(name="test_hdop_threshold", status=TestStatus.FAILED, duration_s=0.015, message="HDOP 3.5 > 2.0"))
    suite.add(TestResult(name="test_fix_acquisition", status=TestStatus.ERROR, duration_s=0.001, message="TimeoutError"))
    suite.add(TestResult(name="test_satellite_count", status=TestStatus.SKIPPED, duration_s=0.0))
    suite.finish()
    return suite


@pytest.fixture
def json_reporter(tmp_path) -> JSONReporter:
    return JSONReporter(output_dir=tmp_path / "reports")


@pytest.fixture
def html_reporter(tmp_path) -> HTMLReporter:
    return HTMLReporter(output_dir=tmp_path / "reports")


# ---------------------------------------------------------------------------
# TestSuiteResult statistics
# ---------------------------------------------------------------------------

class TestSuiteResultStats:
    def test_total_count(self, sample_suite):
        assert sample_suite.total == 5

    def test_passed_count(self, sample_suite):
        assert sample_suite.passed == 2

    def test_failed_count(self, sample_suite):
        assert sample_suite.failed == 1

    def test_error_count(self, sample_suite):
        assert sample_suite.errors == 1

    def test_skipped_count(self, sample_suite):
        assert sample_suite.skipped == 1

    def test_pass_rate(self, sample_suite):
        assert sample_suite.pass_rate == pytest.approx(40.0)

    def test_total_duration_positive(self, sample_suite):
        assert sample_suite.total_duration_s > 0


# ---------------------------------------------------------------------------
# JSON reporter
# ---------------------------------------------------------------------------

class TestJSONReporter:
    def test_file_is_created(self, sample_suite, json_reporter, tmp_path):
        path = json_reporter.write(sample_suite, filename="test_output.json")
        assert path.exists()

    def test_output_is_valid_json(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_suite_name_present(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        data = json.loads(path.read_text())
        assert data["suite_name"] == "GNSS Regression Suite"

    def test_summary_totals_correct(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        data = json.loads(path.read_text())
        assert data["summary"]["total"] == 5
        assert data["summary"]["passed"] == 2
        assert data["summary"]["failed"] == 1

    def test_results_list_length(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        data = json.loads(path.read_text())
        assert len(data["results"]) == 5

    def test_failed_test_has_message(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        data = json.loads(path.read_text())
        failed = next(r for r in data["results"] if r["status"] == "failed")
        assert "HDOP" in failed["message"]

    def test_output_dir_created_if_missing(self, sample_suite, tmp_path):
        reporter = JSONReporter(output_dir=tmp_path / "nested" / "dir")
        path = reporter.write(sample_suite)
        assert path.exists()

    def test_auto_filename_contains_suite_name(self, sample_suite, json_reporter):
        path = json_reporter.write(sample_suite)
        assert "GNSS" in path.name or "Regression" in path.name


# ---------------------------------------------------------------------------
# HTML reporter
# ---------------------------------------------------------------------------

class TestHTMLReporter:
    def test_file_is_created(self, sample_suite, html_reporter):
        path = html_reporter.write(sample_suite)
        assert path.exists()
        assert path.suffix == ".html"

    def test_output_contains_doctype(self, sample_suite, html_reporter):
        path = html_reporter.write(sample_suite)
        content = path.read_text()
        assert "<!DOCTYPE html>" in content

    def test_output_contains_suite_name(self, sample_suite, html_reporter):
        path = html_reporter.write(sample_suite)
        content = path.read_text()
        assert "GNSS Regression Suite" in content

    def test_output_contains_json_data(self, sample_suite, html_reporter):
        path = html_reporter.write(sample_suite)
        content = path.read_text()
        # The embedded DATA object must include our test names
        assert "test_gga_parsing" in content
        assert "test_hdop_threshold" in content

    def test_output_contains_pass_rate(self, sample_suite, html_reporter):
        path = html_reporter.write(sample_suite)
        content = path.read_text()
        assert "40" in content  # 40% pass rate

    def test_output_is_self_contained(self, sample_suite, html_reporter):
        """No external stylesheet or script links."""
        path = html_reporter.write(sample_suite)
        content = path.read_text()
        assert "http" not in content  # no external URLs
