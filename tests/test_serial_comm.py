"""Tests for mock serial port and SerialReceiver.

Validates:
- MockSerialPort loopback and lifecycle
- SerialReceiver sentence reading via serial transport
- ReceiverReading aggregation (has_fix, position)
- Closed-port error handling
"""

from __future__ import annotations

import pytest

from gnss_framework.protocols.serial_mock import MockSerialPort
from gnss_framework.receivers.serial_receiver import SerialReceiver
from tests.conftest import GPS_FIX_SENTENCES, NO_FIX_SENTENCES


class TestMockSerialPort:
    def test_readline_returns_bytes(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        line = port.readline()
        assert isinstance(line, bytes)

    def test_readline_contains_nmea_dollar(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        line = port.readline().decode("ascii").strip()
        assert line.startswith("$")

    def test_loop_cycles_sentences(self):
        port = MockSerialPort(sentences=["$TEST,1*00"], loop=True)
        lines = [port.readline() for _ in range(5)]
        assert all(b"$TEST" in l for l in lines)

    def test_no_loop_exhausts_buffer(self):
        port = MockSerialPort(sentences=["$TEST,1*00"], loop=False)
        # Read the one sentence
        port.readline()
        # Buffer now empty – should return empty bytes
        assert port.readline() == b""

    def test_close_marks_port_closed(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        port.close()
        assert not port.is_open

    def test_read_after_close_raises(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        port.close()
        with pytest.raises(IOError):
            port.readline()

    def test_context_manager_closes_port(self):
        with MockSerialPort(sentences=GPS_FIX_SENTENCES) as port:
            port.readline()
        assert not port.is_open

    def test_inject_prepends_sentence(self):
        port = MockSerialPort(sentences=["$GPGGA,normal*00"])
        port.inject("$INJECTED,emergency*00")
        first = port.readline().decode("ascii").strip()
        assert "INJECTED" in first

    def test_write_accepts_bytes(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        written = port.write(b"$PTNL,CMD*XX\r\n")
        assert written == 14


class TestSerialReceiver:
    def test_connect_and_disconnect(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        rx = SerialReceiver(port)
        rx.connect()
        assert rx._connected is True
        rx.disconnect()
        assert rx._connected is False

    def test_context_manager(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        with SerialReceiver(port) as rx:
            assert rx._connected is True
        assert rx._connected is False

    def test_read_sentence_returns_nmea_sentence(self, gps_serial_receiver):
        sentence = gps_serial_receiver.read_sentence()
        assert sentence is not None
        assert sentence.sentence_type in ("GGA", "RMC", "GSA", "GSV")

    def test_read_n_sentences(self, gps_serial_receiver):
        sentences = gps_serial_receiver.read_n_sentences(5)
        assert len(sentences) == 5

    def test_poll_has_fix(self, gps_serial_receiver):
        reading = gps_serial_receiver.poll()
        assert reading.has_fix is True

    def test_poll_returns_position(self, gps_serial_receiver):
        reading = gps_serial_receiver.poll()
        pos = reading.position
        assert pos is not None
        lat, lon = pos
        # Munich-area coordinates from our test corpus
        assert 48.0 < lat < 49.0
        assert 11.0 < lon < 12.0

    def test_poll_no_fix(self):
        port = MockSerialPort(sentences=NO_FIX_SENTENCES, loop=True)
        with SerialReceiver(port) as rx:
            reading = rx.poll()
        assert reading.has_fix is False
        assert reading.position is None

    def test_read_before_connect_raises(self):
        port = MockSerialPort(sentences=GPS_FIX_SENTENCES)
        rx = SerialReceiver(port)
        with pytest.raises(IOError):
            rx.read_sentence()
