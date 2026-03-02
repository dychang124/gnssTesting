# GNSS Test Framework

[![CI](https://github.com/dychang124/gnssTesting/actions/workflows/ci.yml/badge.svg)](https://github.com/dychang124/gnssTesting/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)

An automated regression test framework for GNSS receiver firmware validation. Provides hardware-independent mock transports, NMEA 0183 protocol parsing, and structured test reporting — enabling full CI/CD integration without physical receivers attached.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [Supported NMEA Sentences](#supported-nmea-sentences)
- [Test Reports](#test-reports)
- [CI/CD Pipeline](#cicd-pipeline)
- [Development](#development)

---

## Overview

GNSS firmware validation traditionally requires physical receiver hardware, making automated regression testing slow and environment-dependent. This framework decouples tests from hardware by providing:

- **Mock serial and TCP transports** that stream configurable NMEA sentence sequences in-process
- **A typed NMEA 0183 parser** with checksum validation for GGA, RMC, GSA, and GSV sentences
- **An abstract receiver driver interface** that accepts both mock and real transports — zero code changes required to run the same tests on a bench unit
- **HTML and JSON reporters** for CI artifact upload and stakeholder dashboards

---

## Architecture

The framework is organized into three independent layers:

```
┌─────────────────────────────────────────────────────┐
│                     Test Suite                      │
│              tests/test_*.py (pytest)               │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  Receivers Layer                    │
│   BaseReceiver (ABC) → SerialReceiver, TCPReceiver  │
│   Aggregates sentences into ReceiverReading objects │
└──────────┬──────────────────────────┬───────────────┘
           │                          │
┌──────────▼──────────┐  ┌────────────▼──────────────┐
│   Protocols Layer   │  │      Reporting Layer       │
│  NMEAParser         │  │  TestSuiteResult / models  │
│  MockSerialPort     │  │  JSONReporter              │
│  MockTCPServer      │  │  HTMLReporter              │
│  MockTCPClient      │  └────────────────────────────┘
└─────────────────────┘
```

**Transport substitution:** `SerialReceiver` and `TCPReceiver` accept any object implementing the expected interface. Swap `MockSerialPort` for a real `serial.Serial` instance and the entire test suite runs against live hardware unchanged.

---

## Installation

Requires Python 3.10 or later.

```bash
# Clone the repository
git clone https://github.com/dychang124/gnssTesting.git
cd gnssTesting

# Install with development dependencies
pip install -e ".[dev]"
```

---

## Running Tests

```bash
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_nmea_parsing.py

# Run with coverage report
pytest --cov=gnss_framework --cov-report=term-missing
```

---

## Project Structure

```
gnssTesting/
├── gnss_framework/
│   ├── protocols/
│   │   ├── nmea.py           # NMEA 0183 parser and typed data structures
│   │   ├── serial_mock.py    # In-process mock serial port (RS-232/USB)
│   │   └── tcp_mock.py       # Asyncio mock TCP server + synchronous client
│   ├── receivers/
│   │   ├── base_receiver.py  # Abstract driver interface + ReceiverReading
│   │   ├── serial_receiver.py
│   │   └── tcp_receiver.py
│   └── reporting/
│       ├── models.py          # TestResult, TestSuiteResult, TestStatus
│       ├── json_reporter.py   # Structured JSON output for CI dashboards
│       └── html_reporter.py   # Self-contained HTML dashboard with JS frontend
├── tests/
│   ├── conftest.py
│   ├── test_nmea_parsing.py
│   ├── test_position_accuracy.py
│   ├── test_serial_comm.py
│   ├── test_tcp_comm.py
│   └── test_reporting.py
├── .github/workflows/ci.yml   # GitHub Actions pipeline
└── pyproject.toml
```

---

## Supported NMEA Sentences

| Sentence | Full Name | Key Fields |
|----------|-----------|------------|
| `GGA` | Global Positioning System Fix Data | Position, altitude, fix quality, satellite count, HDOP |
| `RMC` | Recommended Minimum Specific GNSS Data | Position, speed (knots), heading, date, fix status |
| `GSA` | GNSS DOP and Active Satellites | Fix type (2D/3D), active satellite IDs, PDOP/HDOP/VDOP |
| `GSV` | GNSS Satellites in View | Satellite ID, elevation, azimuth, SNR (dB) |

Supported talker IDs: `GP` (GPS), `GL` (GLONASS), `GA` (Galileo), `GN` (multi-constellation).

All sentences are validated against their XOR checksum before parsing. Malformed or corrupted sentences are caught without interrupting the test run.

### Example

```python
from gnss_framework.protocols.nmea import NMEAParser

parser = NMEAParser()
sentence = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
gga = parser.as_gga(sentence)

print(gga.latitude)          # 48.1173
print(gga.altitude_m)        # 545.4
print(gga.fix_quality)       # FixQuality.GPS_FIX
print(gga.satellites_in_use) # 8
```

---

## Test Reports

After each test run, reports are written to `reports/`:

**JSON report** — machine-readable, suitable for CI dashboards and trend tracking:

```json
{
  "suite_name": "NMEA Parsing",
  "summary": {
    "total": 12,
    "passed": 12,
    "failed": 0,
    "pass_rate_pct": 100.0,
    "total_duration_s": 0.043
  },
  "results": [...]
}
```

**HTML report** — a self-contained dashboard with a filterable results table and pass/fail distribution bar. No server or external dependencies required — open directly in any browser or attach as a CI artifact.

---

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs automatically on every push to `main` or `develop` and on all pull requests targeting `main`.

**Jobs:**

| Job | What it does |
|-----|--------------|
| `test (3.10)` | Runs the full pytest suite with coverage on Python 3.10 |
| `test (3.11)` | Same on Python 3.11 |
| `test (3.12)` | Same on Python 3.12 |
| `lint` | Runs `ruff` to check code style across `gnss_framework/` and `tests/` |

Coverage reports (`coverage.xml`, `htmlcov/`) and JUnit XML results are uploaded as artifacts on every run.

---

## Development

```bash
# Install with dev tools (ruff, mypy)
pip install -e ".[dev]"

# Lint
ruff check gnss_framework tests

# Type check
mypy gnss_framework

# Run tests with full coverage report
pytest --cov=gnss_framework --cov-report=html:reports/htmlcov
```
