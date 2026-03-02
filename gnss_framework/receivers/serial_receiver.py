"""Serial-transport GNSS receiver driver.

Accepts either a real ``serial.Serial`` instance or the ``MockSerialPort``
from ``gnss_framework.protocols.serial_mock``. Tests inject the mock;
production code passes in a real port.
"""

from __future__ import annotations

from typing import Union

from gnss_framework.receivers.base_receiver import BaseReceiver


class SerialReceiver(BaseReceiver):
    """GNSS receiver driver backed by a serial (RS-232/USB) transport.

    Args:
        port: An open serial port object. Must expose ``readline() -> bytes``
              and ``close()``. Compatible with both ``serial.Serial`` and
              ``MockSerialPort``.

    Example::

        from gnss_framework.protocols.serial_mock import MockSerialPort
        from gnss_framework.receivers.serial_receiver import SerialReceiver

        port = MockSerialPort(sentences=[...])
        with SerialReceiver(port) as rx:
            reading = rx.poll()
    """

    def __init__(self, port: object) -> None:
        super().__init__()
        self._port = port
        self._connected = False

    def connect(self) -> None:
        # Port is already open when passed in; just mark as connected.
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        try:
            self._port.close()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _read_line(self) -> str:
        if not self._connected:
            raise IOError("Receiver is not connected")
        raw: bytes = self._port.readline()  # type: ignore[attr-defined]
        return raw.decode("ascii", errors="replace").strip()
