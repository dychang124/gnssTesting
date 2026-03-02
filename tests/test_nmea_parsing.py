"""Tests for the NMEA 0183 parser.

Covers:
- Checksum validation (correct, incorrect, missing)
- GGA sentence parsing (position, fix quality, HDOP, altitude)
- RMC sentence parsing (position, speed, date)
- GSA sentence parsing (DOP values, fix type)
- GSV sentence parsing (satellite count, SNR values)
- Malformed / edge-case input handling
"""

from __future__ import annotations

import pytest

from gnss_framework.protocols.nmea import (
    FixQuality,
    FixStatus,
    NMEAParseError,
    NMEAParser,
)


@pytest.fixture
def parser() -> NMEAParser:
    return NMEAParser()


# ---------------------------------------------------------------------------
# Checksum validation
# ---------------------------------------------------------------------------

class TestChecksumValidation:
    def test_valid_checksum_is_accepted(self, parser):
        sentence = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        assert sentence.checksum_valid is True

    def test_wrong_checksum_flagged(self, parser):
        sentence = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*FF")
        assert sentence.checksum_valid is False

    def test_sentence_without_checksum_flagged(self, parser):
        sentence = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
        assert sentence.checksum_valid is False

    def test_sentence_missing_dollar_raises(self, parser):
        with pytest.raises(NMEAParseError):
            parser.parse("GPGGA,123519")


# ---------------------------------------------------------------------------
# Talker and sentence type extraction
# ---------------------------------------------------------------------------

class TestSentenceMetadata:
    def test_gp_talker_extracted(self, parser):
        s = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        assert s.talker == "GP"
        assert s.sentence_type == "GGA"

    def test_gn_talker_extracted(self, parser):
        s = parser.parse("$GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        assert s.talker == "GN"

    def test_rmc_type_extracted(self, parser):
        s = parser.parse("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
        assert s.sentence_type == "RMC"


# ---------------------------------------------------------------------------
# GGA parsing
# ---------------------------------------------------------------------------

class TestGGAParsing:
    GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"

    def test_utc_time(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.utc_time == "123519"

    def test_latitude_north(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.latitude is not None
        assert gga.latitude == pytest.approx(48.1173, abs=1e-4)

    def test_longitude_east(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.longitude is not None
        assert gga.longitude == pytest.approx(11.5167, abs=1e-4)

    def test_south_latitude_is_negative(self, parser):
        s = parser.parse("$GPGGA,123519,3351.234,S,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*XX")
        gga = parser.as_gga(s)
        assert gga.latitude is not None
        assert gga.latitude < 0

    def test_west_longitude_is_negative(self, parser):
        s = parser.parse("$GPGGA,123519,4807.038,N,11807.345,W,1,08,0.9,545.4,M,46.9,M,,*XX")
        gga = parser.as_gga(s)
        assert gga.longitude is not None
        assert gga.longitude < 0

    def test_fix_quality_gps(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.fix_quality == FixQuality.GPS_FIX

    def test_fix_quality_rtk(self, parser):
        s = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,4,12,0.5,545.4,M,46.9,M,,*XX")
        gga = parser.as_gga(s)
        assert gga.fix_quality == FixQuality.RTK

    def test_satellites_in_use(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.satellites_in_use == 8

    def test_hdop(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.hdop == pytest.approx(0.9)

    def test_altitude(self, parser):
        s = parser.parse(self.GGA)
        gga = parser.as_gga(s)
        assert gga.altitude_m == pytest.approx(545.4)

    def test_no_fix_returns_invalid_quality(self, parser):
        # 4 empty fields (lat, N/S, lon, E/W) before quality=0
        s = parser.parse("$GPGGA,000000,,,,,0,00,99.9,,M,,M,,*48")
        gga = parser.as_gga(s)
        assert gga.fix_quality == FixQuality.INVALID
        assert gga.latitude is None

    def test_wrong_type_raises(self, parser):
        s = parser.parse("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
        with pytest.raises(NMEAParseError):
            parser.as_gga(s)


# ---------------------------------------------------------------------------
# RMC parsing
# ---------------------------------------------------------------------------

class TestRMCParsing:
    RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"

    def test_status_active(self, parser):
        s = parser.parse(self.RMC)
        rmc = parser.as_rmc(s)
        assert rmc.status == FixStatus.ACTIVE

    def test_status_void(self, parser):
        s = parser.parse("$GPRMC,000000,V,,,,,,,010100,,,N*53")
        rmc = parser.as_rmc(s)
        assert rmc.status == FixStatus.VOID

    def test_speed_knots(self, parser):
        s = parser.parse(self.RMC)
        rmc = parser.as_rmc(s)
        assert rmc.speed_knots == pytest.approx(22.4)

    def test_track_degrees(self, parser):
        s = parser.parse(self.RMC)
        rmc = parser.as_rmc(s)
        assert rmc.track_degrees == pytest.approx(84.4)

    def test_date(self, parser):
        s = parser.parse(self.RMC)
        rmc = parser.as_rmc(s)
        assert rmc.date == "230394"

    def test_latitude_matches_gga(self, parser):
        gga_s = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        rmc_s = parser.parse(self.RMC)
        gga = parser.as_gga(gga_s)
        rmc = parser.as_rmc(rmc_s)
        assert gga.latitude == pytest.approx(rmc.latitude, abs=1e-4)
        assert gga.longitude == pytest.approx(rmc.longitude, abs=1e-4)


# ---------------------------------------------------------------------------
# GSA parsing
# ---------------------------------------------------------------------------

class TestGSAParsing:
    # 12 satellite ID slots (indices 3-14) then PDOP/HDOP/VDOP at 15/16/17
    GSA = "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39"

    def test_mode_auto(self, parser):
        s = parser.parse(self.GSA)
        gsa = parser.as_gsa(s)
        assert gsa.mode == "A"

    def test_fix_type_3d(self, parser):
        s = parser.parse(self.GSA)
        gsa = parser.as_gsa(s)
        assert gsa.fix_type == 3

    def test_pdop(self, parser):
        s = parser.parse(self.GSA)
        gsa = parser.as_gsa(s)
        assert gsa.pdop == pytest.approx(2.5)

    def test_hdop(self, parser):
        s = parser.parse(self.GSA)
        gsa = parser.as_gsa(s)
        assert gsa.hdop == pytest.approx(1.3)

    def test_vdop(self, parser):
        s = parser.parse(self.GSA)
        gsa = parser.as_gsa(s)
        assert gsa.vdop == pytest.approx(2.1)


# ---------------------------------------------------------------------------
# GSV parsing
# ---------------------------------------------------------------------------

class TestGSVParsing:
    GSV = "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"

    def test_total_messages(self, parser):
        s = parser.parse(self.GSV)
        gsv = parser.as_gsv(s)
        assert gsv.total_messages == 2

    def test_satellites_in_view(self, parser):
        s = parser.parse(self.GSV)
        gsv = parser.as_gsv(s)
        assert gsv.satellites_in_view == 8

    def test_satellite_count_in_message(self, parser):
        s = parser.parse(self.GSV)
        gsv = parser.as_gsv(s)
        assert len(gsv.satellites) == 4

    def test_satellite_snr(self, parser):
        s = parser.parse(self.GSV)
        gsv = parser.as_gsv(s)
        # First satellite should have SNR 46
        assert gsv.satellites[0]["snr_db"] == pytest.approx(46.0)

    def test_satellite_elevation(self, parser):
        s = parser.parse(self.GSV)
        gsv = parser.as_gsv(s)
        assert gsv.satellites[0]["elevation_deg"] == pytest.approx(40.0)
