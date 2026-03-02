"""Abstract base class for GNSS receiver drivers.

All concrete receiver implementations (serial, TCP, file replay, etc.)
must implement this interface. Tests are written against this abstraction,
making it trivial to swap transport layers without changing test logic.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from gnss_framework.protocols.nmea import (
    GGAData,
    NMEAParser,
    NMEASentence,
    RMCData,
)


@dataclass
class ReceiverReading:
    """Consolidated snapshot from a single receiver poll cycle.

    Aggregates all sentences received in one update interval so test
    assertions work with a single, coherent data object.
    """

    timestamp: float = field(default_factory=time.monotonic)
    sentences: list[NMEASentence] = field(default_factory=list)
    gga: Optional[GGAData] = None
    rmc: Optional[RMCData] = None
    raw_sentences: list[str] = field(default_factory=list)

    @property
    def has_fix(self) -> bool:
        from gnss_framework.protocols.nmea import FixQuality, FixStatus

        if self.gga and self.gga.fix_quality not in (FixQuality.INVALID,):
            return True
        if self.rmc and self.rmc.status == FixStatus.ACTIVE:
            return True
        return False

    @property
    def position(self) -> Optional[tuple[float, float]]:
        """Return (latitude, longitude) in decimal degrees or None."""
        if self.gga and self.gga.latitude is not None and self.gga.longitude is not None:
            return (self.gga.latitude, self.gga.longitude)
        if self.rmc and self.rmc.latitude is not None and self.rmc.longitude is not None:
            return (self.rmc.latitude, self.rmc.longitude)
        return None


class BaseReceiver(ABC):
    """Abstract GNSS receiver driver.

    Subclasses implement ``_read_line()`` for their transport layer.
    The base class handles NMEA parsing and reading aggregation.
    """

    def __init__(self) -> None:
        self._parser = NMEAParser()

    # ------------------------------------------------------------------
    # Abstract transport interface
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Open the transport connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the transport connection."""

    @abstractmethod
    def _read_line(self) -> str:
        """Read one raw line from the transport. Return empty string on EOF."""

    # ------------------------------------------------------------------
    # Public reading API
    # ------------------------------------------------------------------

    def read_sentence(self) -> Optional[NMEASentence]:
        """Read and parse a single NMEA sentence."""
        line = self._read_line()
        if not line:
            return None
        try:
            return self._parser.parse(line)
        except Exception:
            return None

    def read_n_sentences(self, n: int) -> list[NMEASentence]:
        """Read exactly *n* valid NMEA sentences."""
        results: list[NMEASentence] = []
        while len(results) < n:
            sentence = self.read_sentence()
            if sentence is not None:
                results.append(sentence)
        return results

    def poll(self, sentence_count: int = 10) -> ReceiverReading:
        """Collect *sentence_count* sentences and return an aggregated reading.

        This mirrors a real test harness that reads a burst of sentences
        and extracts the latest GGA/RMC fix.
        """
        reading = ReceiverReading()
        sentences = self.read_n_sentences(sentence_count)
        reading.sentences = sentences
        reading.raw_sentences = [s.raw for s in sentences]

        for sentence in reversed(sentences):
            try:
                if sentence.sentence_type == "GGA" and reading.gga is None:
                    reading.gga = self._parser.as_gga(sentence)
                elif sentence.sentence_type == "RMC" and reading.rmc is None:
                    reading.rmc = self._parser.as_rmc(sentence)
            except Exception:
                pass

        return reading

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "BaseReceiver":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
