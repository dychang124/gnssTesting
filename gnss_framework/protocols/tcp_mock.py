"""Mock TCP server for GNSS receiver testing.

Many modern GNSS receivers expose an Ethernet interface (NTRIP, raw NMEA
over TCP, or proprietary protocols). This module provides:

- ``MockTCPServer`` – a lightweight asyncio TCP server that streams NMEA data
  to connected clients.
- ``MockTCPClient`` – thin client wrapper used by test cases and receiver
  drivers to consume the stream.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import AsyncIterator


class MockTCPServer:
    """Asyncio TCP server that streams NMEA sentences to every connected client.

    Intended to be started in a background thread so synchronous test code
    can interact with it via ``MockTCPClient``.

    Args:
        sentences: NMEA sentences to emit (cycled indefinitely).
        host: Bind address.
        port: 0 lets the OS assign a free port (preferred for tests).
        inter_sentence_delay: Seconds between sentences.
    """

    def __init__(
        self,
        sentences: list[str],
        host: str = "127.0.0.1",
        port: int = 0,
        inter_sentence_delay: float = 0.0,
    ) -> None:
        self._sentences = sentences
        self._host = host
        self._port = port
        self._delay = inter_sentence_delay
        self._server: asyncio.AbstractServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def address(self) -> tuple[str, int]:
        """Return (host, port) once the server is running."""
        self._ready.wait(timeout=5)
        assert self._server is not None
        sock = self._server.sockets[0]
        return sock.getsockname()[:2]

    def start(self) -> "MockTCPServer":
        """Start the server in a background daemon thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self

    def stop(self) -> None:
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)

    def __enter__(self) -> "MockTCPServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except asyncio.CancelledError:
            pass

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        self._ready.set()
        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            for sentence in _cycle(self._sentences):
                line = (sentence if sentence.endswith("\r\n") else sentence + "\r\n")
                writer.write(line.encode("ascii"))
                await writer.drain()
                if self._delay:
                    await asyncio.sleep(self._delay)
                # Stop if the client disconnected
                if writer.is_closing():
                    break
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()


class MockTCPClient:
    """Synchronous TCP client that reads NMEA sentences line by line.

    Wraps a plain ``socket`` so it can be used in non-async test code.

    Args:
        host: Server hostname or IP.
        port: Server port.
        timeout: Socket timeout in seconds.
    """

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._file: socket.SocketIO | None = None

    def connect(self) -> "MockTCPClient":
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._file = self._sock.makefile("rb")
        return self

    def readline(self) -> str:
        """Read one NMEA sentence. Returns empty string on EOF."""
        if self._file is None:
            raise IOError("Not connected")
        line = self._file.readline()
        return line.decode("ascii", errors="replace").strip()

    def read_n(self, n: int) -> list[str]:
        """Read exactly *n* sentences."""
        return [self.readline() for _ in range(n)]

    def close(self) -> None:
        if self._file:
            self._file.close()
        if self._sock:
            self._sock.close()

    def __enter__(self) -> "MockTCPClient":
        return self.connect()

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cycle(items: list[str]):
    """Yield items in order, cycling forever."""
    while True:
        yield from items
