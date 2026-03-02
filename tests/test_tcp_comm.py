"""Tests for mock TCP server and TCPReceiver.

Validates:
- MockTCPServer lifecycle (start/stop, OS-assigned port)
- MockTCPClient reads sentences over loopback
- TCPReceiver sentence reading and polling
- Multiple concurrent clients
"""

from __future__ import annotations

import pytest

from gnss_framework.protocols.tcp_mock import MockTCPClient, MockTCPServer
from gnss_framework.receivers.tcp_receiver import TCPReceiver
from tests.conftest import GPS_FIX_SENTENCES


class TestMockTCPServer:
    def test_server_starts_and_assigns_port(self):
        with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
            host, port = server.address
            assert host == "127.0.0.1"
            assert port > 0

    def test_client_receives_nmea_data(self):
        with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
            host, port = server.address
            with MockTCPClient(host, port) as client:
                line = client.readline()
        assert line.startswith("$")

    def test_client_reads_n_sentences(self):
        with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
            host, port = server.address
            with MockTCPClient(host, port) as client:
                sentences = client.read_n(5)
        assert len(sentences) == 5
        assert all(s.startswith("$") for s in sentences)

    def test_server_cycles_sentences(self):
        """Verify the server loops past the end of its sentence list."""
        with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
            host, port = server.address
            with MockTCPClient(host, port) as client:
                # Read more sentences than the corpus contains
                sentences = client.read_n(len(GPS_FIX_SENTENCES) * 3)
        assert len(sentences) == len(GPS_FIX_SENTENCES) * 3

    def test_multiple_clients_can_connect(self):
        with MockTCPServer(sentences=GPS_FIX_SENTENCES) as server:
            host, port = server.address
            results = []
            for _ in range(3):
                with MockTCPClient(host, port) as client:
                    results.append(client.readline())
        assert all(r.startswith("$") for r in results)


class TestTCPReceiver:
    def test_context_manager_connects_and_disconnects(self, tcp_server):
        host, port = tcp_server.address
        with TCPReceiver(host, port) as rx:
            assert rx._client is not None
        assert rx._client is None

    def test_read_sentence(self, tcp_receiver):
        sentence = tcp_receiver.read_sentence()
        assert sentence is not None

    def test_read_n_sentences(self, tcp_receiver):
        sentences = tcp_receiver.read_n_sentences(5)
        assert len(sentences) == 5

    def test_poll_has_fix(self, tcp_receiver):
        reading = tcp_receiver.poll()
        assert reading.has_fix is True

    def test_poll_position_within_expected_range(self, tcp_receiver):
        reading = tcp_receiver.poll()
        pos = reading.position
        assert pos is not None
        lat, lon = pos
        assert 48.0 < lat < 49.0
        assert 11.0 < lon < 12.0

    def test_poll_gga_present(self, tcp_receiver):
        reading = tcp_receiver.poll()
        assert reading.gga is not None

    def test_poll_rmc_present(self, tcp_receiver):
        reading = tcp_receiver.poll()
        assert reading.rmc is not None

    def test_read_before_connect_raises(self, tcp_server):
        host, port = tcp_server.address
        rx = TCPReceiver(host, port)
        with pytest.raises(IOError):
            rx.read_sentence()
