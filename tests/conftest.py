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
