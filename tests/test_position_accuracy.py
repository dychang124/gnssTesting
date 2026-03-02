"""Position accuracy and precision regression tests.

These tests represent the core of a GNSS firmware regression suite:
verifying that receiver output stays within defined accuracy thresholds.

Accuracy metrics tested:
- Horizontal position error vs. known reference
- CEP50 / CEP95 (circular error probable) over repeated readings
- DOP (HDOP / PDOP) within acceptable bounds
- Fix acquisition time (how quickly a fix appears in the sentence stream)
- RTK fix quality detection
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import pytest

from gnss_framework.protocols.nmea import FixQuality, NMEAParser
from gnss_framework.protocols.serial_mock import MockSerialPort
from gnss_framework.receivers.serial_receiver import SerialReceiver
from tests.conftest import GPS_FIX_SENTENCES


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Coordinates encoded in our test corpus (Munich area)
REFERENCE_LAT = 48.1173167  # from 4807.038,N
REFERENCE_LON = 11.5166667  # from 01131.000,E


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def cep_from_errors(errors_m: list[float], percentile: float) -> float:
    """Return horizontal error at the given percentile (e.g. 0.50 → CEP50)."""
    sorted_errors = sorted(errors_m)
    idx = int(math.ceil(percentile * len(sorted_errors))) - 1
    return sorted_errors[max(0, idx)]


@dataclass
class AccuracyThresholds:
    max_single_error_m: float = 5.0   # Per-fix horizontal error
    cep50_m: float = 2.0              # 50th-percentile CEP
    cep95_m: float = 4.0              # 95th-percentile CEP
    max_hdop: float = 2.0
    max_pdop: float = 4.0
    min_satellites: int = 4
    max_fix_acquisition_sentences: int = 20


THRESHOLDS = AccuracyThresholds()


# ---------------------------------------------------------------------------
# Single-fix accuracy tests
# ---------------------------------------------------------------------------

class TestSingleFixAccuracy:
    def test_position_within_horizontal_error_budget(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.has_fix, "Receiver must report a fix"
        pos = reading.position
        assert pos is not None

        error_m = haversine_distance_m(*pos, REFERENCE_LAT, REFERENCE_LON)
        assert error_m < THRESHOLDS.max_single_error_m, (
            f"Horizontal error {error_m:.3f} m exceeds budget of "
            f"{THRESHOLDS.max_single_error_m} m"
        )

    def test_fix_quality_is_at_least_gps(self):
        parser = NMEAParser()
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.fix_quality != FixQuality.INVALID, "Fix quality must not be INVALID"

    def test_satellite_count_meets_minimum(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.satellites_in_use >= THRESHOLDS.min_satellites, (
            f"Only {reading.gga.satellites_in_use} satellites; minimum is {THRESHOLDS.min_satellites}"
        )

    def test_hdop_within_threshold(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.hdop is not None
        assert reading.gga.hdop <= THRESHOLDS.max_hdop, (
            f"HDOP {reading.gga.hdop} exceeds threshold {THRESHOLDS.max_hdop}"
        )

    def test_rtk_fix_detected_from_quality_field(self):
        rtk_sentence = (
            "$GPGGA,123519,4807.038,N,01131.000,E,4,12,0.5,545.4,M,46.9,M,1.0,0001*XX"
        )
        parser = NMEAParser()
        s = parser.parse(rtk_sentence)
        gga = parser.as_gga(s)
        assert gga.fix_quality == FixQuality.RTK


# ---------------------------------------------------------------------------
# Statistical accuracy tests (CEP)
# ---------------------------------------------------------------------------

class TestCEPAccuracy:
    """Simulate a series of consecutive position fixes and compute CEP values."""

    def _collect_errors(self, n: int) -> list[float]:
        """Collect *n* position fixes and return their horizontal errors in metres."""
        # Build a long repeating corpus for multiple polling cycles
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        errors = []
        with SerialReceiver(port) as rx:
            for _ in range(n):
                reading = rx.poll(sentence_count=len(GPS_FIX_SENTENCES))
                if reading.position:
                    error = haversine_distance_m(*reading.position, REFERENCE_LAT, REFERENCE_LON)
                    errors.append(error)
        return errors

    def test_cep50_within_threshold(self):
        errors = self._collect_errors(20)
        assert errors, "No fixes collected"
        cep50 = cep_from_errors(errors, 0.50)
        assert cep50 <= THRESHOLDS.cep50_m, (
            f"CEP50 = {cep50:.3f} m exceeds threshold {THRESHOLDS.cep50_m} m"
        )

    def test_cep95_within_threshold(self):
        errors = self._collect_errors(20)
        assert errors, "No fixes collected"
        cep95 = cep_from_errors(errors, 0.95)
        assert cep95 <= THRESHOLDS.cep95_m, (
            f"CEP95 = {cep95:.3f} m exceeds threshold {THRESHOLDS.cep95_m} m"
        )

    def test_no_outlier_exceeds_5x_cep50(self):
        errors = self._collect_errors(20)
        assert errors, "No fixes collected"
        cep50 = cep_from_errors(errors, 0.50)
        max_error = max(errors)
        assert max_error <= 5 * cep50, (
            f"Outlier detected: max error {max_error:.3f} m > 5 × CEP50 ({5 * cep50:.3f} m)"
        )


# ---------------------------------------------------------------------------
# Fix acquisition tests
# ---------------------------------------------------------------------------

class TestFixAcquisition:
    def test_fix_acquired_within_sentence_budget(self):
        """Verify a fix appears within the first N sentences of a cold-start stream."""
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        budget = THRESHOLDS.max_fix_acquisition_sentences
        acquired = False

        parser = NMEAParser()
        with SerialReceiver(port) as rx:
            for _ in range(budget):
                sentence = rx.read_sentence()
                if sentence and sentence.sentence_type == "GGA":
                    try:
                        gga = parser.as_gga(sentence)
                        if gga.fix_quality != FixQuality.INVALID:
                            acquired = True
                            break
                    except Exception:
                        pass

        assert acquired, f"Fix not acquired within {budget} sentences"

    def test_position_stable_across_consecutive_polls(self):
        """Verify consecutive polls return identical positions (stable output)."""
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        positions = []

        with SerialReceiver(port) as rx:
            for _ in range(5):
                reading = rx.poll()
                if reading.position:
                    positions.append(reading.position)

        assert len(positions) >= 2, "Need at least 2 fixes to check stability"

        for pos in positions[1:]:
            error_m = haversine_distance_m(*positions[0], *pos)
            assert error_m < 1.0, (
                f"Position jumped {error_m:.3f} m between consecutive polls"
            )
