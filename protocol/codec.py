"""Sony headphone protocol codec — framing, escaping, checksums.

Ported from the Rust implementation in sony-headphones-client.
Packet structure:
    START | data_type | seq | payload_len(4 BE) | payload | checksum | END
All bytes between START and END are escaped.
"""

from dataclasses import dataclass

from .constants import (
    START_MARKER,
    END_MARKER,
    ESCAPE_BYTE,
    ESCAPE_MAP,
    UNESCAPE_MAP,
    DataType,
)


@dataclass
class Message:
    """A decoded protocol message."""
    data_type: int
    seq: int
    payload: bytes


def escape(data: bytes) -> bytes:
    """Escape special bytes in the payload region."""
    out = bytearray()
    for b in data:
        if b in ESCAPE_MAP:
            out.append(ESCAPE_BYTE)
            out.append(ESCAPE_MAP[b])
        else:
            out.append(b)
    return bytes(out)


def unescape(data: bytes) -> bytes:
    """Reverse escaping of special bytes."""
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == ESCAPE_BYTE and i + 1 < len(data):
            next_byte = data[i + 1]
            if next_byte in UNESCAPE_MAP:
                out.append(UNESCAPE_MAP[next_byte])
                i += 2
                continue
        out.append(data[i])
        i += 1
    return bytes(out)


def checksum(data: bytes) -> int:
    """Wrapping sum of all bytes, truncated to uint8."""
    return sum(data) & 0xFF


def pack(data_type: int, seq: int, payload: bytes) -> bytes:
    """Build a complete framed packet ready to send over RFCOMM.

    Layout (before escaping inner region):
        START | data_type | seq | len_hi | len_mid_hi | len_mid_lo | len_lo | payload | checksum | END
    """
    length = len(payload)
    # Header: data_type, seq, 4-byte big-endian length
    header = bytes([
        data_type,
        seq,
        (length >> 24) & 0xFF,
        (length >> 16) & 0xFF,
        (length >> 8) & 0xFF,
        length & 0xFF,
    ])
    inner = header + payload
    chk = checksum(inner)
    inner_with_chk = inner + bytes([chk])
    escaped = escape(inner_with_chk)
    return bytes([START_MARKER]) + escaped + bytes([END_MARKER])


def unpack(raw: bytes) -> Message | None:
    """Decode a raw framed packet into a Message.

    Expects raw to include START and END markers.
    Returns None if the packet is malformed.
    """
    if len(raw) < 2 or raw[0] != START_MARKER or raw[-1] != END_MARKER:
        return None

    inner = unescape(raw[1:-1])
    if len(inner) < 7:  # header(6) + checksum(1) minimum
        return None

    # Verify checksum
    expected_chk = inner[-1]
    actual_chk = checksum(inner[:-1])
    if expected_chk != actual_chk:
        return None

    data_type = inner[0]
    seq = inner[1]
    length = (inner[2] << 24) | (inner[3] << 16) | (inner[4] << 8) | inner[5]
    payload = inner[6:6 + length]

    if len(payload) != length:
        return None

    return Message(data_type=data_type, seq=seq, payload=payload)


def extract_message(buffer: bytes) -> tuple[Message | None, bytes]:
    """Extract the first complete packet from a byte buffer.

    Returns (message, remaining_buffer). If no complete packet is found,
    returns (None, buffer).
    """
    start = buffer.find(START_MARKER)
    if start == -1:
        return None, buffer

    end = buffer.find(END_MARKER, start + 1)
    if end == -1:
        return None, buffer[start:]  # keep from start marker onward

    raw = buffer[start:end + 1]
    remaining = buffer[end + 1:]
    msg = unpack(raw)
    if msg is None:
        # Malformed — skip this start marker and try again
        return extract_message(buffer[start + 1:])
    return msg, remaining


def build_ack(data_type: int, seq: int) -> bytes:
    """Build an ACK packet for the given data type and sequence number."""
    ack_type_map = {
        DataType.DATA: DataType.ACK,
        DataType.DATA_MDR: DataType.ACK_MDR,
        DataType.DATA_MDR_NO2: DataType.ACK_MDR_NO2,
    }
    ack_type = ack_type_map.get(data_type, DataType.ACK)
    return pack(ack_type, seq, b"")
