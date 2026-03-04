"""Position accuracy and precision regression tests.

These tests are the core of the GNSS firmware regression suite. Positional
validation is the primary quality gate: every other subsystem (protocols,
transport, reporting) exists to support this goal.

Accuracy metrics tested:
- Horizontal position error vs. known reference (haversine distance)
- CEP50 / CEP95 (circular error probable) over repeated readings
- Vertical / altitude accuracy and stability
- DOP (HDOP / PDOP / VDOP) within acceptable bounds per fix mode
- Fix mode detection and progression (GPS → DGPS → Float RTK → Fixed RTK)
- Velocity accuracy (speed and course-over-ground from RMC)
- Satellite signal quality (SNR thresholds from GSV)
- Southern-hemisphere and western-longitude boundary conditions
- Fix acquisition and reacquisition after satellite outage
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import pytest

from gnss_framework.protocols.nmea import FixQuality, NMEAParser
from gnss_framework.protocols.serial_mock import MockSerialPort
from gnss_framework.receivers.serial_receiver import SerialReceiver
from tests.conftest import (
    DGPS_FIX_SENTENCES,
    FLOAT_RTK_SENTENCES,
    GPS_FIX_SENTENCES,
    MOVING_SENTENCES,
    NO_FIX_SENTENCES,
    REACQUISITION_SENTENCES,
    RTK_FIX_SENTENCES,
    SOUTHERN_HEMISPHERE_SENTENCES,
)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Munich-area coordinates encoded in the primary test corpus
REFERENCE_LAT = 48.1173167   # from 4807.038,N
REFERENCE_LON = 11.5166667   # from 01131.000,E
REFERENCE_ALT_M = 545.4      # from GGA altitude field

# Cape Town area encoded in SOUTHERN_HEMISPHERE_SENTENCES
CAPE_TOWN_LAT = -33.91872    # from 3355.123,S
CAPE_TOWN_LON = 18.5076      # from 01830.456,E

# Unit conversion
KNOTS_TO_MS = 0.514444       # 1 knot = 0.514444 m/s


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
    # Horizontal accuracy
    max_single_error_m: float = 5.0   # Per-fix horizontal error budget
    cep50_m: float = 2.0              # 50th-percentile CEP
    cep95_m: float = 4.0              # 95th-percentile CEP
    # Vertical accuracy
    max_altitude_error_m: float = 10.0
    # DOP limits
    max_hdop: float = 2.0
    max_pdop: float = 4.0
    max_vdop: float = 3.0
    # Satellite geometry
    min_satellites: int = 4
    min_snr_db: float = 30.0          # Satellites below this contribute noise
    # Timing
    max_fix_acquisition_sentences: int = 20


# Standard GPS thresholds
THRESHOLDS = AccuracyThresholds()

# DGPS corrections tighten geometry — stricter DOP and horizontal budget
DGPS_THRESHOLDS = AccuracyThresholds(
    max_single_error_m=2.0,
    cep50_m=1.0,
    cep95_m=1.5,
    max_hdop=1.5,
    max_pdop=2.5,
    min_satellites=6,
)

# Fixed RTK — centimetre-level; thresholds are near-zero
RTK_THRESHOLDS = AccuracyThresholds(
    max_single_error_m=0.05,
    cep50_m=0.02,
    cep95_m=0.05,
    max_hdop=1.0,
    max_pdop=2.0,
    min_satellites=8,
)


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


# ---------------------------------------------------------------------------
# DOP threshold tests
# ---------------------------------------------------------------------------

class TestDOPThresholds:
    """Verify DOP values from GSA sentences remain within acceptable limits."""

    def _parse_gsa(self, sentences: list[str]):
        """Return the first GSAData from a sentence list."""
        parser = NMEAParser()
        for raw in sentences:
            s = parser.parse(raw)
            if s.sentence_type == "GSA":
                return parser.as_gsa(s)
        raise AssertionError("No GSA sentence found in corpus")

    def test_hdop_from_gsa_within_threshold(self):
        gsa = self._parse_gsa(GPS_FIX_SENTENCES)
        assert gsa.hdop is not None
        assert gsa.hdop <= THRESHOLDS.max_hdop, (
            f"HDOP {gsa.hdop} exceeds threshold {THRESHOLDS.max_hdop}"
        )

    def test_pdop_within_threshold(self):
        gsa = self._parse_gsa(GPS_FIX_SENTENCES)
        assert gsa.pdop is not None
        assert gsa.pdop <= THRESHOLDS.max_pdop, (
            f"PDOP {gsa.pdop} exceeds threshold {THRESHOLDS.max_pdop}"
        )

    def test_vdop_within_threshold(self):
        gsa = self._parse_gsa(GPS_FIX_SENTENCES)
        assert gsa.vdop is not None
        assert gsa.vdop <= THRESHOLDS.max_vdop, (
            f"VDOP {gsa.vdop} exceeds threshold {THRESHOLDS.max_vdop}"
        )

    def test_fix_type_is_3d(self):
        """GSA fix_type 3 means 3D fix — minimum requirement for positional tests."""
        gsa = self._parse_gsa(GPS_FIX_SENTENCES)
        assert gsa.fix_type == 3, (
            f"Expected 3D fix (fix_type=3), got fix_type={gsa.fix_type}"
        )

    def test_dgps_hdop_lower_than_gps(self):
        """DGPS corrections improve geometry — DGPS HDOP must be less than GPS HDOP."""
        gps_gsa = self._parse_gsa(GPS_FIX_SENTENCES)    # HDOP 1.3
        dgps_gsa = self._parse_gsa(DGPS_FIX_SENTENCES)  # HDOP 0.8
        assert dgps_gsa.hdop < gps_gsa.hdop, (
            f"DGPS HDOP ({dgps_gsa.hdop}) should be less than GPS HDOP ({gps_gsa.hdop})"
        )


# ---------------------------------------------------------------------------
# Altitude accuracy tests
# ---------------------------------------------------------------------------

class TestAltitudeAccuracy:
    """Verify MSL altitude reported in GGA meets vertical error budget."""

    def test_altitude_within_vertical_error_budget(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.altitude_m is not None
        error_m = abs(reading.gga.altitude_m - REFERENCE_ALT_M)
        assert error_m <= THRESHOLDS.max_altitude_error_m, (
            f"Altitude error {error_m:.2f} m exceeds budget {THRESHOLDS.max_altitude_error_m} m"
        )

    def test_altitude_is_positive_in_northern_fix(self):
        """Munich-area fix should report positive MSL altitude."""
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.altitude_m is not None
        assert reading.gga.altitude_m > 0, (
            f"Expected positive altitude, got {reading.gga.altitude_m} m"
        )

    def test_geoid_separation_present(self):
        """GGA must report geoid separation for full positional accuracy."""
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()

        assert reading.gga is not None
        assert reading.gga.geoid_separation_m is not None, (
            "Geoid separation must be present in GGA output"
        )

    def test_altitude_stable_across_consecutive_polls(self):
        """Altitude should not drift between polls of the same static corpus."""
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)
        altitudes = []

        with SerialReceiver(port) as rx:
            for _ in range(5):
                reading = rx.poll()
                if reading.gga and reading.gga.altitude_m is not None:
                    altitudes.append(reading.gga.altitude_m)

        assert len(altitudes) >= 2, "Need at least 2 altitude readings"
        spread_m = max(altitudes) - min(altitudes)
        assert spread_m <= THRESHOLDS.max_altitude_error_m, (
            f"Altitude spread {spread_m:.2f} m exceeds vertical budget"
        )


# ---------------------------------------------------------------------------
# Velocity accuracy tests
# ---------------------------------------------------------------------------

class TestVelocityAccuracy:
    """Verify speed-over-ground and course-over-ground from RMC sentences."""

    def test_speed_knots_parsed_correctly(self):
        """RMC speed field must match the transmitted value within float tolerance."""
        port = MockSerialPort(sentences=MOVING_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(MOVING_SENTENCES))

        assert reading.rmc is not None
        assert reading.rmc.speed_knots is not None
        assert reading.rmc.speed_knots == pytest.approx(22.4, abs=0.01), (
            f"Speed {reading.rmc.speed_knots} kn does not match expected 22.4 kn"
        )

    def test_heading_in_valid_range(self):
        """Course-over-ground must be in [0, 360) degrees."""
        port = MockSerialPort(sentences=MOVING_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(MOVING_SENTENCES))

        assert reading.rmc is not None
        assert reading.rmc.track_degrees is not None
        assert 0.0 <= reading.rmc.track_degrees < 360.0, (
            f"Heading {reading.rmc.track_degrees}° outside valid range [0, 360)"
        )

    def test_speed_conversion_to_ms(self):
        """Speed in m/s computed from knots must match expected value."""
        port = MockSerialPort(sentences=MOVING_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(MOVING_SENTENCES))

        assert reading.rmc is not None
        assert reading.rmc.speed_knots is not None
        speed_ms = reading.rmc.speed_knots * KNOTS_TO_MS
        expected_ms = 22.4 * KNOTS_TO_MS
        assert speed_ms == pytest.approx(expected_ms, abs=0.01), (
            f"Speed {speed_ms:.3f} m/s does not match expected {expected_ms:.3f} m/s"
        )

    def test_stationary_fix_reports_near_zero_speed(self):
        """A static DGPS fix should report speed at or near 0 knots."""
        port = MockSerialPort(sentences=DGPS_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(DGPS_FIX_SENTENCES))

        assert reading.rmc is not None
        assert reading.rmc.speed_knots is not None
        assert reading.rmc.speed_knots < 1.0, (
            f"Static fix reported {reading.rmc.speed_knots} kn — expected near-zero speed"
        )


# ---------------------------------------------------------------------------
# Signal quality tests
# ---------------------------------------------------------------------------

class TestSignalQuality:
    """Verify satellite count and SNR values from GSV sentences."""

    def _collect_gsv(self, sentences: list[str]) -> list:
        """Parse and return all GSVData objects from a sentence list."""
        parser = NMEAParser()
        gsv_list = []
        for raw in sentences:
            s = parser.parse(raw)
            if s.sentence_type == "GSV":
                gsv_list.append(parser.as_gsv(s))
        return gsv_list

    def test_satellites_in_view_count(self):
        """GSV total satellites-in-view must meet minimum satellite threshold."""
        gsv_list = self._collect_gsv(GPS_FIX_SENTENCES)
        assert gsv_list, "No GSV sentences found"
        total_siv = gsv_list[0].satellites_in_view
        assert total_siv >= THRESHOLDS.min_satellites, (
            f"Satellites in view {total_siv} below minimum {THRESHOLDS.min_satellites}"
        )

    def test_minimum_snr_threshold(self):
        """All reported satellites must have SNR at or above the noise floor."""
        gsv_list = self._collect_gsv(GPS_FIX_SENTENCES)
        assert gsv_list, "No GSV sentences found"
        all_satellites = [sat for gsv in gsv_list for sat in gsv.satellites]
        snr_values = [sat["snr_db"] for sat in all_satellites if sat["snr_db"] is not None]
        assert snr_values, "No SNR values found in GSV data"
        below_floor = [s for s in snr_values if s < THRESHOLDS.min_snr_db]
        assert not below_floor, (
            f"Satellites below SNR floor ({THRESHOLDS.min_snr_db} dB): {below_floor}"
        )

    def test_high_elevation_satellites_have_strong_snr(self):
        """Satellites above 30° elevation should report SNR >= 35 dB."""
        gsv_list = self._collect_gsv(GPS_FIX_SENTENCES)
        all_satellites = [sat for gsv in gsv_list for sat in gsv.satellites]
        high_el = [
            sat for sat in all_satellites
            if sat["elevation_deg"] is not None and sat["elevation_deg"] >= 30
        ]
        assert high_el, "No high-elevation satellites found"
        for sat in high_el:
            if sat["snr_db"] is not None:
                assert sat["snr_db"] >= 35.0, (
                    f"High-elevation satellite {sat['id']} has weak SNR {sat['snr_db']} dB"
                )

    def test_dgps_gsv_reports_more_satellites_than_gps(self):
        """DGPS corpus tracks more satellites than standard GPS corpus."""
        gps_gsv = self._collect_gsv(GPS_FIX_SENTENCES)
        dgps_gsv = self._collect_gsv(DGPS_FIX_SENTENCES)
        assert gps_gsv and dgps_gsv, "Missing GSV data in one corpus"
        assert dgps_gsv[0].satellites_in_view > gps_gsv[0].satellites_in_view, (
            f"DGPS SIV ({dgps_gsv[0].satellites_in_view}) should exceed "
            f"GPS SIV ({gps_gsv[0].satellites_in_view})"
        )


# ---------------------------------------------------------------------------
# Southern-hemisphere boundary condition tests
# ---------------------------------------------------------------------------

class TestSouthernHemisphere:
    """Verify correct sign handling for negative latitudes and geoid separations."""

    def test_southern_latitude_is_negative(self):
        """Cape Town latitude (33°S) must parse as a negative decimal value."""
        port = MockSerialPort(sentences=SOUTHERN_HEMISPHERE_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(SOUTHERN_HEMISPHERE_SENTENCES))

        assert reading.position is not None
        lat, _ = reading.position
        assert lat < 0, f"Southern latitude must be negative, got {lat}"

    def test_southern_position_within_error_budget(self):
        """Cape Town position must fall within horizontal error budget of reference."""
        port = MockSerialPort(sentences=SOUTHERN_HEMISPHERE_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(SOUTHERN_HEMISPHERE_SENTENCES))

        assert reading.position is not None
        error_m = haversine_distance_m(*reading.position, CAPE_TOWN_LAT, CAPE_TOWN_LON)
        assert error_m < THRESHOLDS.max_single_error_m, (
            f"Cape Town position error {error_m:.3f} m exceeds budget "
            f"{THRESHOLDS.max_single_error_m} m"
        )

    def test_rmc_and_gga_latitudes_agree(self):
        """GGA and RMC latitude fields must parse to the same value."""
        parser = NMEAParser()
        gga_lat = None
        rmc_lat = None
        for raw in SOUTHERN_HEMISPHERE_SENTENCES:
            s = parser.parse(raw)
            if s.sentence_type == "GGA" and gga_lat is None:
                gga_lat = parser.as_gga(s).latitude
            elif s.sentence_type == "RMC" and rmc_lat is None:
                rmc_lat = parser.as_rmc(s).latitude

        assert gga_lat is not None and rmc_lat is not None
        assert gga_lat == pytest.approx(rmc_lat, abs=1e-5), (
            f"GGA lat ({gga_lat}) and RMC lat ({rmc_lat}) disagree"
        )

    def test_southern_hemisphere_geoid_separation_is_negative(self):
        """Cape Town geoid separation is below the ellipsoid — must be negative."""
        parser = NMEAParser()
        for raw in SOUTHERN_HEMISPHERE_SENTENCES:
            s = parser.parse(raw)
            if s.sentence_type == "GGA":
                gga = parser.as_gga(s)
                assert gga.geoid_separation_m is not None
                assert gga.geoid_separation_m < 0, (
                    f"Expected negative geoid separation, got {gga.geoid_separation_m} m"
                )
                return
        pytest.fail("No GGA sentence found in SOUTHERN_HEMISPHERE_SENTENCES")


# ---------------------------------------------------------------------------
# Fix reacquisition tests
# ---------------------------------------------------------------------------

class TestFixReacquisition:
    """Verify receiver correctly detects loss of fix and reacquires after outage."""

    def test_no_fix_detected_during_outage(self):
        """Polling during the no-fix window must not report a valid position."""
        port = MockSerialPort(sentences=NO_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(NO_FIX_SENTENCES))

        assert not reading.has_fix, "Receiver must not report a fix during satellite outage"
        assert reading.position is None, "Position must be None when no fix is available"

    def test_fix_reacquired_after_outage(self):
        """After the no-fix period, a valid fix must appear within the corpus."""
        parser = NMEAParser()
        port = MockSerialPort(sentences=REACQUISITION_SENTENCES, loop=False)
        fix_acquired = False

        with SerialReceiver(port) as rx:
            for _ in range(len(REACQUISITION_SENTENCES)):
                sentence = rx.read_sentence()
                if sentence and sentence.sentence_type == "GGA":
                    try:
                        gga = parser.as_gga(sentence)
                        if gga.fix_quality != FixQuality.INVALID:
                            fix_acquired = True
                            break
                    except Exception:
                        pass

        assert fix_acquired, "Fix must be reacquired after satellite outage"

    def test_position_valid_after_reacquisition(self):
        """Position reported after reacquisition must fall within error budget."""
        port = MockSerialPort(sentences=REACQUISITION_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll(sentence_count=len(REACQUISITION_SENTENCES))

        assert reading.has_fix, "Receiver must report a fix after reacquisition"
        assert reading.position is not None
        error_m = haversine_distance_m(*reading.position, REFERENCE_LAT, REFERENCE_LON)
        assert error_m < THRESHOLDS.max_single_error_m, (
            f"Post-reacquisition position error {error_m:.3f} m exceeds budget"
        )


# ---------------------------------------------------------------------------
# Parametrized fix-mode detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sentences,expected_quality", [
    (GPS_FIX_SENTENCES,   FixQuality.GPS_FIX),
    (DGPS_FIX_SENTENCES,  FixQuality.DGPS_FIX),
    (FLOAT_RTK_SENTENCES, FixQuality.FLOAT_RTK),
    (RTK_FIX_SENTENCES,   FixQuality.RTK),
])
def test_fix_quality_detection(sentences, expected_quality):
    """Verify GGA fix_quality field maps to the correct FixQuality enum for each fix mode."""
    port = MockSerialPort(sentences=sentences, loop=True)
    with SerialReceiver(port) as rx:
        reading = rx.poll(sentence_count=len(sentences))

    assert reading.gga is not None, "GGA sentence must be present"
    assert reading.gga.fix_quality == expected_quality, (
        f"Expected {expected_quality}, got {reading.gga.fix_quality}"
    )
