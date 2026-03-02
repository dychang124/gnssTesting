"""TCP-transport GNSS receiver driver.

Works with any TCP source that streams NMEA sentences: production NTRIP
casters, proprietary Ethernet GNSS interfaces, or the ``MockTCPServer``
for tests.
"""

from __future__ import annotations

from gnss_framework.protocols.tcp_mock import MockTCPClient
from gnss_framework.receivers.base_receiver import BaseReceiver


class TCPReceiver(BaseReceiver):
    """GNSS receiver driver backed by a TCP transport.

    Args:
        host: Hostname or IP address of the GNSS data source.
        port: TCP port number.
        timeout: Socket read timeout in seconds.

    Example::

        from gnss_framework.protocols.tcp_mock import MockTCPServer
        from gnss_framework.receivers.tcp_receiver import TCPReceiver

        with MockTCPServer(sentences=[...]) as server:
            host, port = server.address
            with TCPReceiver(host, port) as rx:
                reading = rx.poll()
    """

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._timeout = timeout
        self._client: MockTCPClient | None = None

    def connect(self) -> None:
        self._client = MockTCPClient(self._host, self._port, timeout=self._timeout)
        self._client.connect()

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _read_line(self) -> str:
        if self._client is None:
            raise IOError("Receiver is not connected")
        return self._client.readline()
