"""Mock serial port for GNSS receiver testing.

Replaces a physical RS-232/USB serial connection with an in-process
loopback that emits configurable NMEA sentence streams. This allows
test suites to run without hardware attached.
"""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Iterator
from typing import Optional


class MockSerialPort:
    """Simulate a serial port that streams NMEA sentences.

    Mimics the subset of the ``serial.Serial`` API used in receiver drivers
    (``read``, ``readline``, ``write``, ``close``, context manager).

    Args:
        sentences: Ordered list of NMEA sentences to emit. The port cycles
            through them indefinitely unless ``loop`` is False.
        baud_rate: Stored for interface compatibility; has no effect in-process.
        inter_sentence_delay: Seconds to sleep between sentences, simulating
            a real receiver's output rate (e.g. 1.0 s for 1 Hz output).
        loop: Whether to loop back to the start after the last sentence.
    """

    def __init__(
        self,
        sentences: list[str],
        baud_rate: int = 9600,
        inter_sentence_delay: float = 0.0,
        loop: bool = True,
    ) -> None:
        self.baud_rate = baud_rate
        self.inter_sentence_delay = inter_sentence_delay
        self._sentences = [s if s.endswith("\r\n") else s + "\r\n" for s in sentences]
        self._loop = loop
        self._buffer = io.BytesIO()
        self._lock = threading.Lock()
        self._closed = False
        self._fill_buffer()

    # ------------------------------------------------------------------
    # Public API (mirrors serial.Serial)
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return not self._closed

    def readline(self) -> bytes:
        """Read one NMEA sentence (terminated by \\r\\n)."""
        self._ensure_open()
        with self._lock:
            line = self._buffer.readline()
            if not line:
                if self._loop:
                    self._fill_buffer()
                    line = self._buffer.readline()
            if self.inter_sentence_delay:
                time.sleep(self.inter_sentence_delay)
            return line

    def read(self, size: int = 1) -> bytes:
        """Read up to *size* bytes."""
        self._ensure_open()
        with self._lock:
            return self._buffer.read(size)

    def write(self, data: bytes) -> int:
        """Accept bytes written to the port (command injection, etc.)."""
        self._ensure_open()
        return len(data)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "MockSerialPort":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Iterator protocol – yields one decoded sentence at a time
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[str]:
        while not self._closed:
            line = self.readline()
            if not line:
                break
            yield line.decode("ascii", errors="replace").strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_buffer(self) -> None:
        content = "".join(self._sentences).encode("ascii")
        self._buffer = io.BytesIO(content)

    def _ensure_open(self) -> None:
        if self._closed:
            raise IOError("Serial port is closed")

    def inject(self, sentence: str) -> None:
        """Prepend an out-of-band sentence (e.g. to simulate error conditions)."""
        self._ensure_open()
        with self._lock:
            remaining = self._buffer.read()
            self._buffer = io.BytesIO(
                (sentence + "\r\n").encode("ascii") + remaining
            )
            self._buffer.seek(0)
