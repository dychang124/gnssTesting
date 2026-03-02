"""NMEA 0183 sentence parser.

Supports GGA, RMC, GSA, and GSV sentence types commonly output by GNSS receivers.
Validates checksum integrity on every sentence before parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FixQuality(Enum):
    INVALID = 0
    GPS_FIX = 1
    DGPS_FIX = 2
    PPS_FIX = 3
    RTK = 4
    FLOAT_RTK = 5
    ESTIMATED = 6
    MANUAL = 7
    SIMULATION = 8


class FixStatus(Enum):
    ACTIVE = "A"
    VOID = "V"


@dataclass
class NMEASentence:
    talker: str          # GP, GL, GA, GN, etc.
    sentence_type: str   # GGA, RMC, GSA, GSV
    raw: str
    checksum_valid: bool


@dataclass
class GGAData:
    """GGA – Global Positioning System Fix Data."""

    utc_time: str
    latitude: Optional[float]      # decimal degrees, positive = N
    longitude: Optional[float]     # decimal degrees, positive = E
    fix_quality: FixQuality
    satellites_in_use: int
    hdop: Optional[float]
    altitude_m: Optional[float]
    geoid_separation_m: Optional[float]
    dgps_age_s: Optional[float]
    dgps_station_id: Optional[str]


@dataclass
class RMCData:
    """RMC – Recommended Minimum Specific GNSS Data."""

    utc_time: str
    status: FixStatus
    latitude: Optional[float]
    longitude: Optional[float]
    speed_knots: Optional[float]
    track_degrees: Optional[float]
    date: str
    magnetic_variation: Optional[float]


@dataclass
class GSAData:
    """GSA – GNSS DOP and Active Satellites."""

    mode: str                          # A=auto, M=manual
    fix_type: int                      # 1=no fix, 2=2D, 3=3D
    satellite_ids: list[Optional[int]]
    pdop: Optional[float]
    hdop: Optional[float]
    vdop: Optional[float]


@dataclass
class GSVData:
    """GSV – GNSS Satellites in View."""

    total_messages: int
    message_number: int
    satellites_in_view: int
    satellites: list[dict]  # [{id, elevation_deg, azimuth_deg, snr_db}]


class NMEAChecksumError(ValueError):
    pass


class NMEAParseError(ValueError):
    pass


def _compute_checksum(sentence_body: str) -> str:
    """XOR all bytes between '$' and '*' (exclusive)."""
    checksum = 0
    for char in sentence_body:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def _validate_checksum(raw: str) -> bool:
    """Return True if the sentence checksum is correct."""
    match = re.match(r"^\$([^*]+)\*([0-9A-Fa-f]{2})\s*$", raw.strip())
    if not match:
        return False
    body, given = match.group(1), match.group(2).upper()
    return _compute_checksum(body) == given


def _parse_lat(value: str, direction: str) -> Optional[float]:
    if not value:
        return None
    degrees = float(value[:2])
    minutes = float(value[2:])
    decimal = degrees + minutes / 60.0
    return -decimal if direction == "S" else decimal


def _parse_lon(value: str, direction: str) -> Optional[float]:
    if not value:
        return None
    degrees = float(value[:3])
    minutes = float(value[3:])
    decimal = degrees + minutes / 60.0
    return -decimal if direction == "W" else decimal


def _opt_float(value: str) -> Optional[float]:
    return float(value) if value else None


def _opt_int(value: str) -> Optional[int]:
    return int(value) if value else None


class NMEAParser:
    """Parse NMEA 0183 sentences into typed data structures.

    Usage::

        parser = NMEAParser()
        sentence = parser.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        gga = parser.as_gga(sentence)
    """

    def parse(self, raw: str) -> NMEASentence:
        raw = raw.strip()
        if not raw.startswith("$"):
            raise NMEAParseError(f"Sentence must start with '$': {raw!r}")

        checksum_valid = _validate_checksum(raw)

        # Strip checksum for field parsing
        body = raw.lstrip("$")
        if "*" in body:
            body = body[: body.index("*")]

        parts = body.split(",")
        header = parts[0]  # e.g. "GPGGA"

        if len(header) < 3:
            raise NMEAParseError(f"Malformed sentence header: {header!r}")

        # Talker IDs are typically 2 chars; sentence type is the remainder
        talker = header[:2]
        sentence_type = header[2:]

        return NMEASentence(
            talker=talker,
            sentence_type=sentence_type,
            raw=raw,
            checksum_valid=checksum_valid,
        )

    def as_gga(self, sentence: NMEASentence) -> GGAData:
        if sentence.sentence_type != "GGA":
            raise NMEAParseError(f"Expected GGA, got {sentence.sentence_type}")
        parts = self._fields(sentence.raw)
        # parts[0] = header, [1]=time, [2]=lat, [3]=N/S, [4]=lon, [5]=E/W,
        # [6]=quality, [7]=sats, [8]=hdop, [9]=alt, [10]=M, [11]=geoid, [12]=M,
        # [13]=dgps_age, [14]=dgps_id
        return GGAData(
            utc_time=parts[1],
            latitude=_parse_lat(parts[2], parts[3]) if len(parts) > 3 else None,
            longitude=_parse_lon(parts[4], parts[5]) if len(parts) > 5 else None,
            fix_quality=FixQuality(int(parts[6])) if len(parts) > 6 and parts[6] else FixQuality.INVALID,
            satellites_in_use=int(parts[7]) if len(parts) > 7 and parts[7] else 0,
            hdop=_opt_float(parts[8]) if len(parts) > 8 else None,
            altitude_m=_opt_float(parts[9]) if len(parts) > 9 else None,
            geoid_separation_m=_opt_float(parts[11]) if len(parts) > 11 else None,
            dgps_age_s=_opt_float(parts[13]) if len(parts) > 13 else None,
            dgps_station_id=parts[14] if len(parts) > 14 and parts[14] else None,
        )

    def as_rmc(self, sentence: NMEASentence) -> RMCData:
        if sentence.sentence_type != "RMC":
            raise NMEAParseError(f"Expected RMC, got {sentence.sentence_type}")
        parts = self._fields(sentence.raw)
        return RMCData(
            utc_time=parts[1],
            status=FixStatus(parts[2]) if len(parts) > 2 and parts[2] else FixStatus.VOID,
            latitude=_parse_lat(parts[3], parts[4]) if len(parts) > 4 and parts[3] else None,
            longitude=_parse_lon(parts[5], parts[6]) if len(parts) > 6 and parts[5] else None,
            speed_knots=_opt_float(parts[7]) if len(parts) > 7 else None,
            track_degrees=_opt_float(parts[8]) if len(parts) > 8 else None,
            date=parts[9] if len(parts) > 9 else "",
            magnetic_variation=_opt_float(parts[10]) if len(parts) > 10 else None,
        )

    def as_gsa(self, sentence: NMEASentence) -> GSAData:
        if sentence.sentence_type != "GSA":
            raise NMEAParseError(f"Expected GSA, got {sentence.sentence_type}")
        parts = self._fields(sentence.raw)
        sat_ids = [_opt_int(parts[i]) for i in range(3, 15) if i < len(parts)]
        return GSAData(
            mode=parts[1] if len(parts) > 1 else "",
            fix_type=int(parts[2]) if len(parts) > 2 and parts[2] else 1,
            satellite_ids=sat_ids,
            pdop=_opt_float(parts[15]) if len(parts) > 15 else None,
            hdop=_opt_float(parts[16]) if len(parts) > 16 else None,
            vdop=_opt_float(parts[17]) if len(parts) > 17 else None,
        )

    def as_gsv(self, sentence: NMEASentence) -> GSVData:
        if sentence.sentence_type != "GSV":
            raise NMEAParseError(f"Expected GSV, got {sentence.sentence_type}")
        parts = self._fields(sentence.raw)
        satellites = []
        # Satellite data starts at index 4, groups of 4 fields
        i = 4
        while i + 3 < len(parts):
            satellites.append(
                {
                    "id": _opt_int(parts[i]),
                    "elevation_deg": _opt_float(parts[i + 1]),
                    "azimuth_deg": _opt_float(parts[i + 2]),
                    "snr_db": _opt_float(parts[i + 3]),
                }
            )
            i += 4
        return GSVData(
            total_messages=int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            message_number=int(parts[2]) if len(parts) > 2 and parts[2] else 0,
            satellites_in_view=int(parts[3]) if len(parts) > 3 and parts[3] else 0,
            satellites=satellites,
        )

    @staticmethod
    def _fields(raw: str) -> list[str]:
        """Extract comma-separated fields, stripping the checksum suffix."""
        body = raw.lstrip("$")
        if "*" in body:
            body = body[: body.index("*")]
        return body.split(",")
