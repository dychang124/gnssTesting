"""Shared pytest fixtures for the GNSS test framework test suite."""

from __future__ import annotations

import pytest

from gnss_framework.protocols.serial_mock import MockSerialPort
from gnss_framework.protocols.tcp_mock import MockTCPServer
from gnss_framework.receivers.serial_receiver import SerialReceiver
from gnss_framework.receivers.tcp_receiver import TCPReceiver


# ---------------------------------------------------------------------------
# Representative NMEA sentence corpus
# ---------------------------------------------------------------------------

GPS_FIX_SENTENCES = [
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
    # GSA: header + mode + fix_type + 12 satellite ID slots + PDOP + HDOP + VDOP = 17 fields
    "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39",
    "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75",
    "$GPGSV,2,2,08,15,14,013,42,21,38,097,41,22,18,258,34,24,57,062,45*76",
]

RTK_FIX_SENTENCES = [
    "$GPGGA,123519,4807.038,N,01131.000,E,4,12,0.5,545.4,M,46.9,M,1.0,0001*XX",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,000.0,000.0,230394,003.1,W*6A",
]

NO_FIX_SENTENCES = [
    # 4 empty fields (lat, N/S, lon, E/W) between time and quality=0
    "$GPGGA,000000,,,,,0,00,99.9,,M,,M,,*48",
    "$GPRMC,000000,V,,,,,,,010100,,,N*53",
]

MALFORMED_SENTENCES = [
    "INVALID_LINE",
    "$GPGGA,bad_data",
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*FF",  # bad checksum
]

# DGPS fix — quality=2, 10 satellites, HDOP 0.8. Tighter geometry than standard GPS.
DGPS_FIX_SENTENCES = [
    "$GPGGA,123519,4807.038,N,01131.000,E,2,10,0.8,545.4,M,46.9,M,1.0,0001*XX",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,000.0,000.0,230394,003.1,W*6A",
    "$GPGSA,A,3,04,05,06,09,12,15,24,28,,,,,1.6,0.8,1.4*XX",
    "$GPGSV,2,1,10,01,55,083,48,02,42,308,44,06,35,201,46,09,28,097,43*XX",
    "$GPGSV,2,2,10,12,22,344,41,15,14,013,39,24,57,062,47,28,33,155,44*XX",
]

# Float RTK fix — quality=5, 14 satellites, HDOP 0.5. Decimetre-level expected.
FLOAT_RTK_SENTENCES = [
    "$GPGGA,123519,4807.038,N,01131.000,E,5,14,0.5,545.4,M,46.9,M,0.8,0001*XX",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,000.0,000.0,230394,003.1,W*6A",
    "$GPGSA,A,3,04,05,06,09,12,15,19,24,28,31,33,35,1.1,0.5,0.9*XX",
]

# Non-zero speed and heading — 22.4 kn at 084.4° — for velocity accuracy tests.
MOVING_SENTENCES = [
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
    "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39",
    "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75",
    "$GPGSV,2,2,08,15,14,013,42,21,38,097,41,22,18,258,34,24,57,062,45*76",
]

# Southern hemisphere — Cape Town area (33°S, 18°E). Geoid separation is negative.
SOUTHERN_HEMISPHERE_SENTENCES = [
    "$GPGGA,123519,3355.123,S,01830.456,E,1,08,1.1,12.3,M,-27.2,M,,*XX",
    "$GPRMC,123519,A,3355.123,S,01830.456,E,000.0,000.0,230394,003.1,W*XX",
    "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.8,1.4,2.4*XX",
    "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*XX",
    "$GPGSV,2,2,08,15,14,013,42,21,38,097,41,22,18,258,34,24,57,062,45*XX",
]

# Reacquisition stream — 8 no-fix sentences followed by a valid GPS fix stream.
REACQUISITION_SENTENCES = NO_FIX_SENTENCES * 4 + GPS_FIX_SENTENCES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gps_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=GPS_FIX_SENTENCES, loop=True)


@pytest.fixture
def rtk_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=RTK_FIX_SENTENCES, loop=True)


@pytest.fixture
def no_fix_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=NO_FIX_SENTENCES, loop=True)


@pytest.fixture
def gps_serial_receiver(gps_serial_port: MockSerialPort) -> SerialReceiver:
    rx = SerialReceiver(gps_serial_port)
    rx.connect()
    yield rx
    rx.disconnect()


@pytest.fixture
def tcp_server() -> MockTCPServer:
    with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
        yield server


@pytest.fixture
def tcp_receiver(tcp_server: MockTCPServer) -> TCPReceiver:
    host, port = tcp_server.address
    with TCPReceiver(host, port) as rx:
        yield rx


@pytest.fixture
def dgps_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=DGPS_FIX_SENTENCES, loop=True)


@pytest.fixture
def float_rtk_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=FLOAT_RTK_SENTENCES, loop=True)


@pytest.fixture
def moving_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=MOVING_SENTENCES, loop=True)


@pytest.fixture
def southern_hemisphere_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=SOUTHERN_HEMISPHERE_SENTENCES, loop=True)


@pytest.fixture
def reacquisition_serial_port() -> MockSerialPort:
    return MockSerialPort(sentences=REACQUISITION_SENTENCES, loop=True)
