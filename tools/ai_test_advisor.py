#!/usr/bin/env python3
"""AI-powered test failure analyzer for the GNSS test framework.

Reads JSON test reports from the reports/ directory, identifies failure
patterns, and uses Claude to suggest new targeted tests for the areas
most likely to regress.

Usage:
    python tools/ai_test_advisor.py              # analyze latest report
    python tools/ai_test_advisor.py --report path/to/report.json
    python tools/ai_test_advisor.py --demo       # run with built-in sample data

Requirements:
    pip install anthropic
    export ANTHROPIC_API_KEY=your_key_here
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic


# ---------------------------------------------------------------------------
# Demo data — representative failure set for demonstration without real reports
# ---------------------------------------------------------------------------

DEMO_REPORT = {
    "suite_name": "GNSS Regression Suite",
    "started_at": "2024-03-01T08:00:00+00:00",
    "finished_at": "2024-03-01T08:01:23+00:00",
    "summary": {
        "total": 28,
        "passed": 22,
        "failed": 4,
        "errors": 2,
        "skipped": 0,
        "pass_rate_pct": 78.57,
        "total_duration_s": 83.4,
    },
    "results": [
        {
            "name": "test_hdop_within_threshold",
            "status": "failed",
            "duration_s": 0.021,
            "message": "AssertionError: HDOP 3.1 exceeds threshold 2.0 — assert 3.1 <= 2.0",
        },
        {
            "name": "test_cep50_within_threshold",
            "status": "failed",
            "duration_s": 12.3,
            "message": "AssertionError: CEP50 = 2.847 m exceeds threshold 2.0 m",
        },
        {
            "name": "test_rtk_fix_detected_from_quality_field",
            "status": "failed",
            "duration_s": 0.008,
            "message": "AssertionError: assert <FixQuality.GPS_FIX: 1> == <FixQuality.RTK: 4>",
        },
        {
            "name": "test_position_stable_across_consecutive_polls",
            "status": "failed",
            "duration_s": 3.1,
            "message": "AssertionError: Position jumped 1.34 m between polls — assert 1.34 < 1.0",
        },
        {
            "name": "test_fix_acquired_within_sentence_budget",
            "status": "error",
            "duration_s": 0.001,
            "message": "TimeoutError: No GGA sentence received within 20-sentence budget",
        },
        {
            "name": "test_satellite_count_meets_minimum",
            "status": "error",
            "duration_s": 0.002,
            "message": "AttributeError: 'NoneType' object has no attribute 'satellites_in_use'",
        },
        # Passing tests included so Claude understands what is already covered
        {"name": "test_valid_checksum_is_accepted",        "status": "passed", "duration_s": 0.003, "message": None},
        {"name": "test_wrong_checksum_flagged",            "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_latitude_north",                    "status": "passed", "duration_s": 0.004, "message": None},
        {"name": "test_longitude_east",                    "status": "passed", "duration_s": 0.003, "message": None},
        {"name": "test_south_latitude_is_negative",        "status": "passed", "duration_s": 0.003, "message": None},
        {"name": "test_fix_quality_gps",                   "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_satellites_in_use",                 "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_status_active",                     "status": "passed", "duration_s": 0.003, "message": None},
        {"name": "test_speed_knots",                       "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_mode_auto",                         "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_fix_type_3d",                       "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_pdop",                              "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_total_messages",                    "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_satellite_snr",                     "status": "passed", "duration_s": 0.002, "message": None},
        {"name": "test_poll_has_fix",                      "status": "passed", "duration_s": 0.045, "message": None},
        {"name": "test_poll_returns_position",             "status": "passed", "duration_s": 0.043, "message": None},
        {"name": "test_server_starts_and_assigns_port",   "status": "passed", "duration_s": 0.12,  "message": None},
        {"name": "test_client_receives_nmea_data",         "status": "passed", "duration_s": 0.15,  "message": None},
        {"name": "test_file_is_created",                   "status": "passed", "duration_s": 0.011, "message": None},
        {"name": "test_output_is_valid_json",              "status": "passed", "duration_s": 0.009, "message": None},
        {"name": "test_suite_name_present",                "status": "passed", "duration_s": 0.008, "message": None},
        {"name": "test_output_contains_suite_name",        "status": "passed", "duration_s": 0.012, "message": None},
    ],
}


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def load_latest_report(reports_dir: Path) -> dict:
    """Load the most recently modified JSON report from reports_dir."""
    json_files = sorted(
        reports_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        raise FileNotFoundError(f"No JSON reports found in {reports_dir}")
    path = json_files[0]
    print(f"Loaded report: {path.name}\n")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_failure_summary(report: dict) -> str:
    """Format the report into a concise text block for the prompt."""
    failures = [r for r in report["results"] if r["status"] in ("failed", "error")]
    passing  = [r for r in report["results"] if r["status"] == "passed"]
    s = report["summary"]

    lines = [
        f"Suite: {report['suite_name']}",
        f"Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
        f"Errors: {s['errors']}  Pass rate: {s['pass_rate_pct']}%",
        "",
        "=== FAILURES AND ERRORS ===",
    ]

    for r in failures:
        lines.append(f"\n[{r['status'].upper()}]  {r['name']}")
        if r.get("message"):
            lines.append(f"  Error: {r['message']}")
        lines.append(f"  Duration: {r['duration_s']:.4f}s")

    lines += [
        "",
        "=== PASSING TESTS (for coverage context) ===",
        ", ".join(r["name"] for r in passing),
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior Software Development Engineer in Test (SDET) specializing in \
GNSS (GPS/satellite navigation) receiver firmware validation. You have deep expertise \
in NMEA 0183 protocols, position accuracy metrics (CEP, HDOP, PDOP), RTK \
positioning, serial and TCP communication testing, and Python test automation \
with pytest.

When analyzing test failures you:
1. Identify the root cause pattern behind the symptom
2. Recognize which firmware subsystem or behavior is most at risk
3. Suggest targeted new tests that probe the exact boundary conditions that caused failures
4. Write production-quality pytest code that integrates seamlessly with the existing framework
"""

_USER_PROMPT_TEMPLATE = """\
Below are the results from the latest GNSS regression test run. Analyze the \
failures, identify patterns, and suggest new test cases that would catch these \
regressions earlier or probe the surrounding boundary conditions more thoroughly.

--- TEST RESULTS ---
{failure_summary}
--- END RESULTS ---

Please provide four sections:

## 1. Failure Pattern Analysis
What do the failures have in common? What firmware subsystem or behavior is \
most at risk? Are these independent failures or symptoms of a single underlying issue?

## 2. Risk Assessment
Based on what is failing, which areas of the codebase have the least test coverage \
and are most likely to regress next?

## 3. Suggested New Tests
Write 3–5 new pytest test cases (actual Python code, ready to paste into the \
test suite) that specifically target the failure patterns identified. Each test should:
- Follow the existing `test_<behavior>` naming convention
- Include a brief comment explaining which regression it guards against
- Use fixtures and helpers from conftest.py where possible
- Be more specific than the tests that already failed

## 4. Threshold Recommendations
If any acceptance thresholds (HDOP, CEP, position error budget) appear \
too tight for the hardware under test, suggest better values and explain the reasoning.
"""


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def run_analysis(report: dict) -> None:
    """Send the report to Claude and stream the analysis back to stdout."""
    client = anthropic.Anthropic()

    failure_summary = _build_failure_summary(report)
    user_message = _USER_PROMPT_TEMPLATE.format(failure_summary=failure_summary)

    print("=" * 70)
    print("  GNSS AI TEST ADVISOR")
    print(f"  {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    print()

    # Stream with adaptive thinking — Claude decides how much reasoning to apply
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)

    print("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze GNSS test failures with Claude and suggest new tests.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--report",
        type=Path,
        metavar="FILE",
        help="Path to a specific JSON report (default: most recent in reports/)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with built-in sample failure data — no real report needed",
    )
    args = parser.parse_args()

    if args.demo:
        print("Running in demo mode with sample failure data.\n")
        report = DEMO_REPORT
    elif args.report:
        if not args.report.exists():
            print(f"Error: report file not found: {args.report}", file=sys.stderr)
            sys.exit(1)
        report = json.loads(args.report.read_text(encoding="utf-8"))
        print(f"Loaded report: {args.report.name}\n")
    else:
        reports_dir = Path(__file__).parent.parent / "reports"
        try:
            report = load_latest_report(reports_dir)
        except FileNotFoundError:
            print(
                "No JSON reports found in reports/.\n"
                "Run pytest first to generate reports, or use --demo for sample data.",
                file=sys.stderr,
            )
            sys.exit(1)

    run_analysis(report)


if __name__ == "__main__":
    main()
